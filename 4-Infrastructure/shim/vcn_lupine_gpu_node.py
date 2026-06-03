#!/usr/bin/env python3
"""VCN-LUPINE GPU node receiver — runs on qfox-1 (GPU node).

Receives MKV stream from VPS, dispatches to:
  - LUPINE server (TAG_LUPINE) → NVIDIA GPU via local libcuda.so.1
  - VCN compute path (TAG_STRAND/CROSSING/PIST) → AMD VCN hardware decode

Listens on:
  - tcp:14834  (MKV stream from VPS)

Schema: vcn_lupine_gpu_node_v1
"""

import argparse
import json
import logging
import os
import select
import socket
import struct
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from vcn_lupine_bridge import (
    TAG_STRAND, TAG_CROSSING, TAG_PIST, TAG_LUPINE,
    FLAG_REPLY, FRAME_HDR_SIZE, pack_frame, unpack_frame,
    pack_reply, unpack_reply, tag_name, decode_lupine_reply,
    encode_lupine_reply, encode_lupine_request,
    decode_lupine_request, FrameDispatcher, CUDABackend,
    bridge_receipt,
)
from vcn_lupine_opcodes import OPCODE_NAMES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("vcn-lupine-gpu-node")


GPU_NODE_HOST = "0.0.0.0"
GPU_NODE_PORT = 14834

LUPINE_SERVER_HOST = os.environ.get("LUPINE_SERVER_HOST", "127.0.0.1")
LUPINE_SERVER_PORT = int(os.environ.get("LUPINE_SERVER_PORT", "14833"))

RS_NSYM = 32
CHACHA_KEY_SIZE = 32


# ── H.264 / MKV decode ─────────────────────────────────────────────────────────

def decode_mkv_frame(mkv_data: bytes) -> list[tuple[int, bytes]]:
    """Decode H.264/MKV to raw frames. Returns list of (seq, frame_bytes).

    Uses FFmpeg to demux and hardware-decode.
    """
    if not mkv_data or len(mkv_data) < 8:
        return []

    tmp_in = tempfile.NamedTemporaryFile(suffix=".mkv", delete=False)
    tmp_in.write(mkv_data)
    tmp_in.close()
    tmp_out_dir = tempfile.mkdtemp(prefix="vcn_lupine_dec_")
    tmp_out = os.path.join(tmp_out_dir, "frame.bin")
    os.mkfifo(tmp_out)

    cmd = [
        "ffmpeg", "-y",
        "-i", tmp_in.name,
        "-c:v", "h264_qsv",      # AMD VCN hardware decode
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-pix_fmt", "yuv420p",
        tmp_out,
    ]

    writer_done = threading.Event()
    result_holder = []

    def _write_frames():
        pipe = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        _, stderr = pipe.communicate()
        if pipe.returncode != 0:
            log.error("FFmpeg decode error: %s", stderr[-500:])
        writer_done.set()

    writer = threading.Thread(target=_write_frames, daemon=True)
    writer.start()

    try:
        writer_done.wait(timeout=10)
    except Exception:
        pass

    frames = []
    try:
        with open(tmp_out, "rb") as f:
            data = f.read()
        offset = 0
        while offset + 12 <= len(data):
            seq_read = struct.unpack("<I", data[offset:offset + 4])[0]
            payload_len = struct.unpack("<I", data[offset + 4:offset + 8])[0]
            offset += 8
            if offset + payload_len <= len(data):
                payload = data[offset:offset + payload_len]
                frames.append((seq_read, payload))
                offset += payload_len
            else:
                break
    except FileNotFoundError:
        pass
    finally:
        try:
            os.unlink(tmp_in.name)
            os.rmdir(tmp_out_dir)
        except OSError:
            pass

    return frames


def encode_frame_to_raw(frame_bytes: bytes, seq: int) -> bytes:
    """Encode frame bytes as raw YUV420p for transmission.

    Used for reply path: encode result → raw YUV → send back.
    """
    w, h = 1920, 1080
    pipe_dir = tempfile.mkdtemp(prefix="vcn_lupine_enc_")
    in_fifo = os.path.join(pipe_dir, "in.fifo")
    out_raw = os.path.join(pipe_dir, "out.raw")
    os.mkfifo(in_fifo)

    def _write():
        with open(in_fifo, "wb") as fifo:
            header = struct.pack("<II", seq, len(frame_bytes))
            fifo.write(header + frame_bytes)
            fifo.write(b"\x00" * (w * h * 3 // 2 - 8 - len(frame_bytes)))

    t = threading.Thread(target=_write, daemon=True)
    t.start()

    result = b""
    try:
        with open(out_raw, "rb") as f:
            result = f.read()
    except FileNotFoundError:
        pass
    finally:
        try:
            os.unlink(in_fifo)
            os.unlink(out_raw)
            os.rmdir(pipe_dir)
        except OSError:
            pass
        t.join(timeout=2)

    return result


# ── LUPINE local backend (GPU node calls NVIDIA GPU) ───────────────────────────

class LocalCUDABackend(CUDABackend):
    """CUDA backend that calls the local LUPINE server.

    The GPU node already has LUPINE server running on localhost:14833.
    This backend forwards decoded LUPINE requests to that server.
    """

    def __init__(self, server_host: str = LUPINE_SERVER_HOST,
                 server_port: int = LUPINE_SERVER_PORT):
        self.server_host = server_host
        self.server_port = server_port

    def call(self, opcode: int, args: dict) -> dict:
        import urllib.request, urllib.error

        payload = json.dumps({"opcode": opcode, "args": args}).encode("utf-8")
        req = urllib.request.Request(
            f"http://{self.server_host}:{self.server_port}/cuda",
            data=payload,
            headers={"Content-Type": "application/json",
                     "X-LUPINE-Request": "1"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as e:
            raise RuntimeError(f"LUPINE server call failed: {e}")


# ── VCN braid compute backend ─────────────────────────────────────────────────

class VCNBraidBackend:
    """VCN braid compute backend — calls into vcn_compute_substrate."""

    def compute(self, tag: int, payload: bytes) -> bytes:
        if tag == TAG_STRAND:
            return self._compute_strand(payload)
        elif tag == TAG_CROSSING:
            return self._compute_crossing(payload)
        elif tag == TAG_PIST:
            return self._compute_pist(payload)
        else:
            raise ValueError(f"Unknown braid tag: {tag:#04x}")

    def _compute_strand(self, payload: bytes) -> bytes:
        import vcn_compute_substrate as vcn
        strand = vcn.deserialize_braid_strand(payload)
        result = vcn.compute_strand_phase(strand)
        return vcn.serialize_phase_result(result)

    def _compute_crossing(self, payload: bytes) -> bytes:
        import vcn_compute_substrate as vcn
        bracket_a = vcn.deserialize_braid_bracket(payload[:21])
        bracket_b = vcn.deserialize_braid_bracket(payload[21:42])
        result = vcn.compute_crossing_residual(bracket_a, bracket_b)
        return vcn.serialize_crossing_result(result)

    def _compute_pist(self, payload: bytes) -> bytes:
        import vcn_compute_substrate as vcn
        spectral_data = vcn.deserialize_pist_data(payload)
        result = vcn.compute_pist_spectral(spectral_data)
        return vcn.serialize_pist_result(result)


# ── Reply encoder ─────────────────────────────────────────────────────────────

def encode_reply_frame(tag: int, seq: int, payload: bytes) -> bytes:
    return pack_reply(tag, seq, payload)


# ── GPU node receiver ─────────────────────────────────────────────────────────

class GPUNodeReceiver:
    def __init__(self, port: int = GPU_NODE_PORT,
                 cuda_backend: CUDABackend = None,
                 braid_backend = None):
        self.port = port
        self.dispatcher = FrameDispatcher(cuda_backend, braid_backend)
        self._running = False
        self._thread: threading.Thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        log.info("GPU node receiver listening on port %d", self.port)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _serve(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.port))
        srv.listen(8)
        srv.settimeout(5)

        while self._running:
            try:
                conn, addr = srv.accept()
                log.info("Connection from %s", addr)
                thread = threading.Thread(target=self._handle_conn,
                                       args=(conn,), daemon=True)
                thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                log.error("Accept error: %s", e)
                break

        srv.close()

    def _handle_conn(self, conn: socket.socket):
        conn.settimeout(30)
        buf = b""
        while self._running:
            try:
                size_buf = b""
                while len(size_buf) < 4:
                    chunk = conn.recv(4 - len(size_buf))
                    if not chunk:
                        return
                    size_buf += chunk
                size = struct.unpack("<I", size_buf)[0]

                data = b""
                while len(data) < size:
                    chunk = conn.recv(min(65536, size - len(data)))
                    if not chunk:
                        return
                    data += chunk

                frames = decode_mkv_frame(data)
                for seq, frame_bytes in frames:
                    self._dispatch_frame(conn, seq, frame_bytes)

            except socket.timeout:
                break
            except Exception as e:
                log.error("Connection error: %s", e)
                break

        conn.close()

    def _dispatch_frame(self, conn: socket.socket, seq: int, frame_bytes: bytes):
        try:
            tag, flags, frame_seq, payload = unpack_frame(frame_bytes)
        except ValueError as e:
            log.error("Bad frame seq=%d: %s", seq, e)
            return

        receipt = bridge_receipt(tag, flags, frame_seq, len(payload), True)

        try:
            reply_frame = self.dispatcher.dispatch(tag, flags, frame_seq, payload)
        except Exception as e:
            log.error("Dispatch error tag=%s seq=%d: %s", tag_name(tag), seq, e)
            reply_frame = b""

        if reply_frame:
            reply_mkv = encode_reply_frame_to_mkv(reply_frame, frame_seq)
            conn.sendall(struct.pack("<I", len(reply_mkv)))
            conn.sendall(reply_mkv)


def encode_reply_frame_to_mkv(frame: bytes, seq: int) -> bytes:
    w, h = 1920, 1080
    tmp_dir = tempfile.mkdtemp(prefix="vcn_reply_")
    in_fifo = os.path.join(tmp_dir, "in.fifo")
    out_mkv = os.path.join(tmp_dir, "out.mkv")
    os.mkfifo(in_fifo)

    def _writer():
        with open(in_fifo, "wb") as fifo:
            header = struct.pack("<II", seq, len(frame))
            padded = header + frame + b"\x00" * (w * h * 3 // 2 - 8 - len(frame))
            fifo.write(padded)

    t = threading.Thread(target=_writer, daemon=True)
    t.start()

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-pix_fmt", "yuv420p", "-s", f"{w}x{h}", "-r", "30",
        "-i", in_fifo,
        "-c:v", "libx264", "-preset", "ultrafast",
        "-tune", "zerolatency", "-pix_fmt", "yuv420p",
        out_mkv,
    ]

    try:
        subprocess.run(cmd, capture_output=True, timeout=10, check=True)
        with open(out_mkv, "rb") as f:
            result = f.read()
    except Exception as e:
        log.error("Reply encode failed: %s", e)
        result = b""
    finally:
        try:
            os.unlink(in_fifo)
            os.unlink(out_mkv)
            os.rmdir(tmp_dir)
        except OSError:
            pass
        t.join(timeout=2)

    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="VCN-LUPINE GPU node receiver")
    parser.add_argument("--port", type=int, default=GPU_NODE_PORT,
                        help="Listen port (default: 14834)")
    parser.add_argument("--lupine-server", default=f"{LUPINE_SERVER_HOST}:{LUPINE_SERVER_PORT}",
                        help="LUPINE server address (default: 127.0.0.1:14833)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    host, port = args.lupine_server.split(":")
    port = int(port)

    cuda = LocalCUDABackend(server_host=host, server_port=port)
    braid = VCNBraidBackend()
    receiver = GPUNodeReceiver(port=args.port, cuda_backend=cuda,
                               braid_backend=braid)

    print(f"VCN-LUPINE GPU node listening on port {args.port}")
    print(f"Forwarding TAG_LUPINE → LUPINE server at {host}:{port}")
    print(f"Forwarding TAG_STRAND/CROSSING/PIST → VCN compute")

    receiver.start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        receiver.stop()


if __name__ == "__main__":
    main()
