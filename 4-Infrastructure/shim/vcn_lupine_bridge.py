"""VCN-LUPINE unified compute bridge.

Encodes both VCN braid operations and LUPINE CUDA calls as H.264 video frames
over the same transport, then dispatches to the appropriate compute backend.

Schema: vcn_lupine_bridge_v1

Tag byte (matches vcn_compute_substrate):
  0x01 = TAG_STRAND    (braid strand state)
  0x02 = TAG_CROSSING  (braid crossing operation)
  0x03 = TAG_PIST      (PIST spectral data)
  0x04 = TAG_LUPINE    (LUPINE CUDA operation, JSON-encoded args)

Reply flag: 0x80 ORed with tag for replies.
"""

import json
import struct
import sys
from pathlib import Path
from typing import Any, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from vcn_compute_substrate import (
    TAG_STRAND, TAG_CROSSING, TAG_PIST, TAG_LUPINE, TAG_VAAPI, TAG_FLAC,
    BRAID_STRAND_BYTES, BRAID_BRACKET_BYTES,
)
from vcn_lupine_opcodes import (
    OPCODE_NAMES,
    LUPINE_OPCODES,
)


FLAG_REPLY   = 0x80

MAX_PAYLOAD = 4 * 1024 * 1024  # 4 MB per frame


_TAG_NAMES = {TAG_STRAND: "STRAND", TAG_CROSSING: "CROSSING", TAG_PIST: "PIST",
              TAG_LUPINE: "LUPINE", TAG_VAAPI: "VAAPI", TAG_FLAC: "FLAC"}


def tag_name(tag: int) -> str:
    flag, base = tag & FLAG_REPLY, tag & 0x7F
    prefix = "REPLY_" if flag else ""
    return prefix + _TAG_NAMES.get(base, f"UNKNOWN({base})")


# ── Unified frame header ───────────────────────────────────────────────────────

FRAME_HDR = "<BBII"  # tag(1) flags(1) seq(4) payload_len(4)
FRAME_HDR_SIZE = 10


def pack_frame(tag: int, seq: int, payload: bytes) -> bytes:
    """Pack a unified frame: tag + flags + seq + payload_len + payload."""
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"Payload {len(payload)} exceeds MAX_PAYLOAD {MAX_PAYLOAD}")
    return struct.pack(FRAME_HDR, tag, 0, seq, len(payload)) + payload


def unpack_frame(frame: bytes) -> Tuple[int, int, int, bytes]:
    """Unpack a unified frame. Returns (tag, flags, seq, payload)."""
    if len(frame) < FRAME_HDR_SIZE:
        raise ValueError(f"Frame too short: {len(frame)} < {FRAME_HDR_SIZE}")
    tag, flags, seq, payload_len = struct.unpack(FRAME_HDR, frame[:FRAME_HDR_SIZE])
    payload = frame[FRAME_HDR_SIZE:FRAME_HDR_SIZE + payload_len]
    if len(payload) < payload_len:
        raise ValueError(f"Payload truncated: {len(payload)} < {payload_len}")
    return tag, flags, seq, payload


def pack_reply(tag: int, seq: int, payload: bytes) -> bytes:
    """Pack a reply frame (same tag, FLAG_REPLY set)."""
    return struct.pack(FRAME_HDR, tag | FLAG_REPLY, FLAG_REPLY, seq, len(payload)) + payload


def unpack_reply(frame: bytes) -> Tuple[int, int, int, bytes]:
    """Unpack a reply frame. Asserts FLAG_REPLY is set."""
    tag, flags, seq, payload_len = struct.unpack(FRAME_HDR, frame[:FRAME_HDR_SIZE])
    if not (flags & FLAG_REPLY):
        raise ValueError(f"Not a reply frame: flags={flags:#04x}")
    return tag & 0x7F, flags, seq, frame[FRAME_HDR_SIZE:FRAME_HDR_SIZE + payload_len]


# ── LUPINE JSON-braid codec ───────────────────────────────────────────────────

def encode_lupine_request(request_id: int, opcode: int, args: dict) -> bytes:
    """Encode a LUPINE CUDA request as a JSON-braid frame payload.

    Layout: [4:request_id][4:opcode][4:args_len][N:JSON args]
    All integers are UInt32LE.
    """
    args_json = json.dumps(args, separators=(",", ":")).encode("utf-8")
    args_len = len(args_json)
    header = struct.pack("<III", request_id, opcode, args_len)
    return header + args_json


def decode_lupine_request(payload: bytes) -> Tuple[int, int, dict]:
    """Decode a LUPINE CUDA request payload. Returns (request_id, opcode, args_dict)."""
    if len(payload) < 12:
        raise ValueError(f"LUPINE payload too short: {len(payload)} < 12")
    request_id, opcode, args_len = struct.unpack("<III", payload[:12])
    if opcode not in LUPINE_OPCODES:
        raise ValueError(f"Unknown LUPINE opcode: {opcode}")
    args_json = payload[12:12 + args_len].decode("utf-8")
    args = json.loads(args_json)
    return request_id, opcode, args


def encode_lupine_reply(request_id: int, status: int, result: Any) -> bytes:
    """Encode a LUPINE CUDA reply as a JSON-braid frame payload.

    Layout: [4:request_id][4:status][4:result_len][N:JSON result]
    status: 0 = OK, -1 = error
    """
    result_json = json.dumps(result, separators=(",", ":")).encode("utf-8")
    result_len = len(result_json)
    return struct.pack("<III", request_id, status, result_len) + result_json


def decode_lupine_reply(payload: bytes) -> Tuple[int, int, Any]:
    """Decode a LUPINE CUDA reply payload. Returns (request_id, status, result)."""
    if len(payload) < 12:
        raise ValueError(f"LUPINE reply too short: {len(payload)} < 12")
    request_id, status, result_len = struct.unpack("<III", payload[:12])
    result_json = payload[12:12 + result_len].decode("utf-8")
    result = json.loads(result_json)
    return request_id, status, result


def lupine_opcode_name(opcode: int) -> str:
    return OPCODE_NAMES.get(opcode, f"UNKNOWN({opcode})")


# ── Frame dispatch ─────────────────────────────────────────────────────────────

class FrameDispatcher:
    """Routes TAG_LUPINE frames to CUDA backend, braid frames to VCN compute."""
    def __init__(self, cuda_backend: Optional["CUDABackend"] = None,
                 braid_backend: Optional["BraidBackend"] = None,
                 vaapi_backend: Optional["VAAPIBackend"] = None,
                 flac_backend: Optional["FLACBackend"] = None):
        self.cuda = cuda_backend
        self.braid = braid_backend
        self.vaapi = vaapi_backend
        self.flac = flac_backend
    def dispatch(self, tag: int, flags: int, seq: int,
                 payload: bytes) -> Optional[bytes]:
        """Dispatch a received frame to the appropriate backend.

        Returns reply frame bytes, or None if the tag is not handled.
        Raises ValueError on protocol errors.
        """
        is_reply = bool(flags & FLAG_REPLY)

        if tag == TAG_LUPINE:
            if is_reply:
                return self._dispatch_lupine_reply(seq, payload)
            else:
                return self._dispatch_lupine_request(seq, payload)

        elif tag in (TAG_STRAND, TAG_CROSSING, TAG_PIST):
            if is_reply:
                return self._dispatch_braid_reply(tag, seq, payload)
            else:
                return self._dispatch_braid_request(tag, seq, payload)

        else:
            raise ValueError(f"Unknown tag: {tag:#04x}")

    def _dispatch_lupine_request(self, seq: int, payload: bytes) -> bytes:
        """Handle TAG_LUPINE request: forward to CUDA backend."""
        if self.cuda is None:
            return self._lupine_error(seq, -1, "CUDA backend not available")
        try:
            request_id, opcode, args = decode_lupine_request(payload)
            result = self.cuda.call(opcode, args)
            return pack_reply(TAG_LUPINE, seq,
                              encode_lupine_reply(request_id, 0, result))
        except Exception as e:
            request_id, _, _ = decode_lupine_request(payload) if len(payload) >= 12 else (0, 0, {})
            return pack_reply(TAG_LUPINE, seq,
                              encode_lupine_reply(request_id, -1, str(e)))

    def _dispatch_lupine_reply(self, seq: int, payload: bytes) -> bytes:
        """Handle TAG_LUPINE reply: pass through (called by daemon)."""
        return pack_frame(TAG_LUPINE | FLAG_REPLY, seq, payload)

    def _dispatch_braid_request(self, tag: int, seq: int, payload: bytes) -> bytes:
        """Handle braid compute request: forward to VCN braid backend."""
        if self.braid is None:
            raise ValueError("Braid backend not available")
        result = self.braid.compute(tag, payload)
        return pack_reply(tag, seq, result)

    def _dispatch_braid_reply(self, tag: int, seq: int, payload: bytes) -> bytes:
        """Handle braid compute reply: pass through."""
        return pack_frame(tag | FLAG_REPLY, seq, payload)

    def _lupine_error(self, seq: int, status: int, msg: str) -> bytes:
        return pack_reply(TAG_LUPINE, seq, encode_lupine_reply(0, status, msg))

    def _dispatch_vaapi_request(self, seq: int, payload: bytes) -> bytes:
        if self.vaapi is None:
            raise ValueError("VA-API backend not available")
        op = payload[0] if payload else 0
        if op == 0:
            result = self.vaapi.encode(payload[1:])
        else:
            result = self.vaapi.decode(payload[1:])
        return pack_reply(TAG_VAAPI, seq, result)

    def _dispatch_vaapi_reply(self, seq: int, payload: bytes) -> bytes:
        return pack_frame(TAG_VAAPI | FLAG_REPLY, seq, payload)


# ── CUDABackend interface ──────────────────────────────────────────────────────

class CUDABackend:
    """Interface for CUDA compute backends (LUPINE, local, etc.)."""

    def call(self, opcode: int, args: dict) -> Any:
        raise NotImplementedError


class LUPINEBackend(CUDABackend):
    """LUPINE CUDA backend — sends requests to remote NVIDIA GPU over HTTP/2.

    This is the client-side shim that the GPU node runs. The VPS sends
    TAG_LUPINE frames to this backend via the MKV transport.
    """

    def __init__(self, server: str = "localhost:14833"):
        self.server = server
        self._session = None

    def call(self, opcode: int, args: dict) -> Any:
        """Forward a CUDA API call to the LUPINE server via HTTP POST."""
        import urllib.request

        api_name = lupine_opcode_name(opcode)
        payload = json.dumps({"opcode": opcode, "api": api_name, "args": args}).encode("utf-8")
        req = urllib.request.Request(
            f"http://{self.server}/cuda",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"LUPINE call to {self.server} failed: {e}")


# ── FLACBackend interface ──────────────────────────────────────────────────────

class FLACBackend:
    """Interface for PipeWire/FLAC audio DSP backends."""

    def process_chunk(self, chunk_data: bytes, sample_rate: int = 48000) -> dict:
        raise NotImplementedError


class LocalFLACBackend(FLACBackend):
    """Local FLAC DSP backend using numpy FFT."""

    def process_chunk(self, chunk_data: bytes, sample_rate: int = 48000) -> dict:
        import struct
        import json

        try:
            import numpy as np
            # chunk_data is raw PCM samples (float32 LE)
            n = len(chunk_data) // 4
            data = np.frombuffer(chunk_data[:n*4], dtype=np.float32)

            if data.ndim > 1:
                data = data.mean(axis=1)

            n_fft = min(4096, len(data))
            window = np.hanning(n_fft)
            frame = data[:n_fft] * window
            spectrum = np.abs(np.fft.rfft(frame))
            freqs = np.fft.rfftfreq(n_fft, 1.0 / sample_rate)

            peak_indices = np.argsort(spectrum)[-8:]
            peaks = [{"freq_hz": float(freqs[i]), "magnitude": float(spectrum[i])}
                     for i in sorted(peak_indices)]

            spectral_sum = np.sum(spectrum)
            centroid = float(np.sum(freqs * spectrum) / spectral_sum) if spectral_sum > 0 else 0.0
            rms = float(np.sqrt(np.mean(data ** 2)))
            rms_db = float(20 * np.log10(rms + 1e-12))

            return {
                "status": "ok",
                "fft_peaks": peaks,
                "spectral_centroid_hz": centroid,
                "rms_level_db": rms_db,
                "sample_rate": sample_rate,
                "samples": len(data),
            }
        except ImportError:
            return {"status": "missing_libs", "error": "numpy not available"}
        except Exception as e:
            return {"status": "error", "error": str(e)}


# ── BraidBackend interface ─────────────────────────────────────────────────────

class BraidBackend:
    """Interface for braid compute backends (VCN compute path)."""

    def compute(self, tag: int, payload: bytes) -> bytes:
        raise NotImplementedError


# ── Receipt ───────────────────────────────────────────────────────────────────

def bridge_receipt(tag: int, flags: int, seq: int,
                   payload_len: int, handled: bool) -> dict:
    return {
        "schema": "vcn_lupine_bridge_receipt_v1",
        "tag": tag,
        "tag_name": tag_name(tag),
        "flags": flags,
        "seq": seq,
        "payload_bytes": payload_len,
        "handled": handled,
    }
