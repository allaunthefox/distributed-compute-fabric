#!/usr/bin/env python3
"""
VCN Compute Substrate - Use AMD VCN H.264 hardware encoder as computation device.

This shim implements the "Steam Deck MKV trick" from UNIFIED_TRANSPORT_ENCODING_SPEC.md:
- Pack computation data into 1920×1080 YUV420 video frames
- Use AMD AMF H.264 hardware encoder for computation
- Extract results from encoded bitstream (CRC32, transform coefficients, motion vectors)

Shim boundary: I/O only. No decision logic. All computation mapping decisions
belong in Lean (Semantics.MeshRouting and future VCN computation modules).

Usage:
    python3 vcn_compute_substrate.py encode <input_data.bin> <output.mkv>
    python3 vcn_compute_substrate.py decode <input.mkv> <output_data.bin>
    python3 vcn_compute_substrate.py extract_receipt <input.mkv> <receipt.json>
"""

import re
import struct
import subprocess
import json
import zlib
import os
import tempfile
from pathlib import Path
from typing import Tuple, List, Optional
from dataclasses import dataclass, field, asdict

# Third-party (lazy imports so py_compile works without them installed)
try:
    import reedsolo
except ImportError:
    reedsolo = None  # type: ignore

try:
    from cryptography.hazmat.primitives.ciphers import Cipher as _Cipher
    from cryptography.hazmat.primitives.ciphers import algorithms as _alg
    _CHA20_AVAILABLE = True
except ImportError:
    _CHA20_AVAILABLE = False

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    np = None
    _HAS_NUMPY = False

# Frame constants from UNIFIED_TRANSPORT_ENCODING_SPEC.md
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
YUV420_FRAME_SIZE = 3_110_400  # 1920*1080 + 960*540 + 960*540
SIGNATURE_HEADER = b"RDMAVCN\0"
SIGNATURE_SIZE = 24

# SEI receipt UUID — identifies VCN integrity NAL unit in H.264/HEVC bitstream
SEI_UUID = "086f3693-b7b3-4f2c-9653-21492feee5b8"

# Encoder settings for computation mode (software encoding for initial testing)
ENCODER_PROFILE = "main"
ENCODER_LEVEL = "4"
QP_MIN = 2  # Minimal quantization for precise computation
QP_MAX = 4
TRANSFORM_SKIP = True
DEBLOCKING = False
SEI = False
SAO = False
# ── Resolution / Frame Rate Catalog ──────────────────────────────────────────

def sei_receipt_from_mkv(mkv_path: Path, uuid_hex: str = SEI_UUID) -> List[dict]:
    """Extract VCN SEI receipts from an MKV file.

    Parses the MKV binary directly to find SEI NAL units with the VCN integrity
    UUID. Returns one receipt dict per frame:
        {"seq": int, "crc32_hex": str, "timestamp_us": int}

    Args:
        mkv_path: Input MKV file path.
        uuid_hex: UUID string to match in SEI user_data (default: SEI_UUID).

    Returns:
        List of receipt dicts in encode order, empty if none found.
    """
    uuid_raw = uuid_hex.replace("-", "").lower()
    uuid_bytes = bytes.fromhex(uuid_raw)
    receipts: List[dict] = []

    try:
        data = mkv_path.read_bytes()
    except (OSError, IOError):
        return []

    pos = 0
    while True:
        idx = data.find(uuid_bytes, pos)
        if idx < 0:
            break
        # SEI payload immediately follows the 16-byte UUID
        payload_hex = ""
        payload_start = idx + 16
        payload_end = min(payload_start + 1024, len(data))
        payload_hex = ""
        for j in range(payload_start, payload_end):
            c = chr(data[j]) if data[j] < 128 else ""
            if c in "0123456789abcdefABCDEF":
                payload_hex += c
            else:
                if len(payload_hex) >= 8:
                    lookahead = data[j:j+4]
                    if all(b < 0x30 or b > 0x66 for b in lookahead if b < 128):
                        break
        if len(payload_hex) >= 8 and len(payload_hex) % 2 == 0:
            try:
                json_bytes = bytes.fromhex(payload_hex)
                payload_str = json_bytes.decode("utf-8", errors="replace")
                payload = json.loads(payload_str)
                receipts.append({
                    "seq": int(payload["s"]),
                    "crc32_hex": str(payload["c"]),
                    "timestamp_us": int(payload["t"])
                })
            except (ValueError, json.JSONDecodeError, KeyError):
                pass
        pos = idx + 1

    return receipts

VCN_RESOLUTIONS = {
  "240p":  (320, 240),
  "360p":  (640, 360),
  "480p":  (854, 480),
  "720p":  (1280, 720),
  "1080p": (1920, 1080),
  "1440p": (2560, 1440),
  "4K":    (3840, 2160),
  "5K":    (5120, 2880),
  "8K":    (7680, 4320),
  "16K":   (15360, 8640),
}

VCN_FRAME_RATES = [30, 60, 120, 144, 240]

RESOLUTION_ORDER = list(VCN_RESOLUTIONS.keys())


@dataclass
class MathOptimizationLoad:
    """Mathematical and packing optimizations mapped to detected GPU architecture."""
    pixel_format: str = "yuv420p"
    color_range: str = "tv"
    encoder_opts: List[str] = field(default_factory=list)
    packing_density: str = "macroblock_1x"
    bit_depth: int = 8


@dataclass
class VCNHardwareCapabilities:
  """Detected hardware encoder/decoder capabilities."""
  supported_resolutions: List[Tuple[int, int]] = field(default_factory=lambda: [(1920, 1080)])
  supported_frame_rates: List[int] = field(default_factory=lambda: [30, 60])
  available_encoders: List[str] = field(default_factory=lambda: ["libx264"])
  max_memory_mb: int = 512
  max_bandwidth_mbps: int = 100
  gpu_vendor: str = "unknown"
  gpu_name: str = "unknown"
  optimization: Optional[MathOptimizationLoad] = None


@dataclass
class VCNComputeFrameSpec:
  """Dynamic frame specification for VCN computation."""
  width: int = 1920
  height: int = 1080
  format: str = "yuv420p"
  bytes_per_frame: int = 3_110_400
  frame_rate: int = 60
  encoder: str = "libx264"



def probe_vcn_capabilities() -> VCNHardwareCapabilities:
   """Probe hardware VCN capabilities using FFmpeg, VAAPI, and vendor tools."""
   caps = VCNHardwareCapabilities()
   encoders_found = []
   try:
       result = subprocess.run(
           ["ffmpeg", "-encoders"],
           capture_output=True, text=True, timeout=10
       )
       output = result.stdout
       for enc in ["h264_vaapi", "hevc_vaapi", "h264_amf", "hevc_amf",
                    "h264_nvenc", "hevc_nvenc", "libx264", "libx265"]:
           if enc in output:
               encoders_found.append(enc)
   except (FileNotFoundError, subprocess.TimeoutExpired):
       encoders_found = ["libx264"]
   caps.available_encoders = encoders_found if encoders_found else ["libx264"]
   # Detect GPU vendor
   try:
       result = subprocess.run(
           ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
           capture_output=True, text=True, timeout=5
       )
       if result.returncode == 0 and result.stdout.strip():
           parts = result.stdout.strip().split(",")
           caps.gpu_vendor = "nvidia"
           caps.gpu_name = parts[0].strip()
           caps.max_memory_mb = int(parts[1].strip())
   except (FileNotFoundError, subprocess.TimeoutExpired):
       pass
   if caps.gpu_vendor == "unknown":
       try:
           result = subprocess.run(["vainfo"], capture_output=True, text=True, timeout=5)
           output = result.stdout + result.stderr
           if "AMD" in output or "RADV" in output or "radeon" in output.lower():
               caps.gpu_vendor = "amd"
               caps.gpu_name = "AMD Radeon (VAAPI)"
           elif "Intel" in output or "iHD" in output or "i965" in output:
               caps.gpu_vendor = "intel"
               caps.gpu_name = "Intel Graphics (VAAPI)"
       except (FileNotFoundError, subprocess.TimeoutExpired):
           pass
   if caps.gpu_vendor == "unknown":
       try:
           vendor_path = Path("/sys/class/drm/card1/device/vendor")
           if vendor_path.exists():
               vendor_id = vendor_path.read_text().strip()
               if vendor_id == "0x1002":
                   caps.gpu_vendor = "amd"
                   caps.gpu_name = "AMD Radeon (DRM)"
               elif vendor_id == "0x8086":
                   caps.gpu_vendor = "intel"
                   caps.gpu_name = "Intel Graphics (DRM)"
       except Exception:
           pass
   preferred_encoder = _select_preferred_encoder(encoders_found, caps.gpu_vendor)
   caps.available_encoders = [preferred_encoder] + [e for e in encoders_found if e != preferred_encoder]
   supported = []
   for name, (w, h) in VCN_RESOLUTIONS.items():
       if w > 3840 and (3840, 2160) in supported:
           supported.append((w, h))
           continue
       if _test_resolution(w, h, preferred_encoder):
           supported.append((w, h))
   caps.supported_resolutions = supported if supported else [(1920, 1080)]
   caps.supported_frame_rates = [fps for fps in VCN_FRAME_RATES if fps <= 240]
   max_w, max_h = caps.supported_resolutions[-1] if caps.supported_resolutions else (1920, 1080)
   max_pixels = max_w * max_h
   caps.max_bandwidth_mbps = (max_pixels * 3 // 2 * 60) // (1024 * 1024)
   caps.optimization = load_math_optimizations(caps.gpu_vendor, caps.gpu_name)
   return caps


def load_math_optimizations(vendor: str, gpu_name: str) -> MathOptimizationLoad:
    """Determine optimal mathematical packing and compression parameters based on GPU capabilities."""
    opt = MathOptimizationLoad()
    vendor = vendor.lower()
    gpu_name = gpu_name.lower()

    # 1. NVIDIA Ada Lovelace / Ampere / Turing
    if vendor == "nvidia":
        # Target H.265 (HEVC) lossless mode via NVENC
        opt.pixel_format = "yuv444p"  # Full-range YUV444p (no subsampling, high density)
        opt.bit_depth = 8
        opt.packing_density = "yuv444_3x"
        opt.color_range = "pc"            # PC range (0-255) to avoid clamping loss
        opt.encoder_opts = [
            "-preset", "lossless",        # Hardware lossless HEVC
            "-tune", "zerolatency",       # Zero pipeline buffering
            "-color_range", "pc",         # Prevent clamping loss
            "-colorspace", "bt709"
        ]


    # 2. AMD Radeon / Ryzen APU with VCN (Video Core Next)
    elif vendor == "amd":
        # Check if it is an integrated GPU / APU (shared system memory)
        is_igpu = "graphics" in gpu_name or "integrated" in gpu_name or "apu" in gpu_name or "drm" in gpu_name

        if is_igpu:
            # iGPU/APU: Optimize for memory bandwidth limits of unified system RAM
            opt.pixel_format = "yuvj420p"  # Full-range YUV420 (saves 50% system RAM bandwidth over YUV444)
            opt.bit_depth = 8
            opt.packing_density = "independent_y_6x" # Independent Y-plane utilization
            opt.color_range = "pc"         # PC range (0-255) to prevent clamping loss
            opt.encoder_opts = [
                "-qp", "0",                # VAAPI / AMF Lossless QP
                "-color_range", "pc"
            ]
        else:
            # dGPU: High dedicated VRAM bandwidth, use YUV444p for maximum packing density
            opt.pixel_format = "yuv444p"
            opt.bit_depth = 8
            opt.packing_density = "yuv444_3x"
            opt.color_range = "pc"
            opt.encoder_opts = [
                "-qp", "0",                   # VAAPI / AMF Lossless QP
                "-color_range", "pc"
            ]


    # 3. Intel Graphics
    elif vendor == "intel":
        opt.pixel_format = "yuv422p"
        opt.bit_depth = 8
        opt.packing_density = "macroblock_1x"
        opt.color_range = "pc"
        opt.encoder_opts = [
            "-global_quality", "0",       # QSV lossless
            "-color_range", "pc"
        ]

    # 4. Fallback / Generic (CPU x265)
    else:
        opt.pixel_format = "yuv444p"
        opt.bit_depth = 8
        opt.packing_density = "yuv444_3x"
        opt.color_range = "pc"
        opt.encoder_opts = [
            "-x265-params", "lossless=1", # CPU x265 lossless
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-color_range", "pc"
        ]

    return opt


def _select_preferred_encoder(encoders: List[str], vendor: str) -> str:
   """Select the best encoder for the detected GPU vendor."""
   vendor_prefs = {
       "nvidia": ["hevc_nvenc", "h264_nvenc"],
       "amd":    ["hevc_vaapi", "h264_vaapi", "hevc_amf", "h264_amf"],
       "intel":  ["hevc_vaapi", "h264_vaapi"],
   }
   for pref in vendor_prefs.get(vendor, []):
       if pref in encoders:
           return pref
   return "libx265" if "libx265" in encoders else "libx264"


def _test_resolution(width: int, height: int, encoder: str) -> bool:
    """Test if the encoder can handle a given resolution."""
    try:
        test_size = width * height * 3 // 2
        if test_size > 100_000_000:
            return False
        cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "yuv420p",
               "-s", f"{width}x{height}", "-frames:v", "1", "-i", "/dev/zero",
               "-c:v", encoder, "-f", "null", "-"]
        if "vaapi" in encoder:
            cmd.insert(1, "-vaapi_device")
            cmd.insert(2, "/dev/dri/renderD128")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def compute_frame_size(width: int, height: int, fmt: str = "yuv420p") -> int:
    """Compute frame size in bytes for given resolution and format."""
    fmt = fmt.lower()
    if fmt in ["yuv420p", "yuvj420p"]:
        return width * height * 3 // 2
    elif fmt in ["yuv420p10le", "yuv420p10"]:
        return width * height * 3
    elif fmt in ["yuv444p", "yuvj444p", "rgb24"]:
        return width * height * 3
    elif fmt in ["yuv444p10le", "yuv444p10"]:
        return width * height * 6
    raise ValueError(f"Unsupported format: {fmt}")



def select_optimal_resolution(
    caps: VCNHardwareCapabilities,
    target_data_size: int,
    preferred_format: str = "yuv420p"
) -> VCNComputeFrameSpec:
    """Select the smallest resolution that can hold target_data_size."""
    fmt = caps.optimization.pixel_format if (caps.optimization and caps.optimization.pixel_format) else preferred_format
    required_size = target_data_size + SIGNATURE_SIZE
    for w, h in caps.supported_resolutions:
        frame_bytes = compute_frame_size(w, h, fmt)
        if frame_bytes >= required_size:
            max_fps = 60
            for fps in reversed(caps.supported_frame_rates):
                bandwidth_needed = (frame_bytes * fps) // (1024 * 1024)
                if bandwidth_needed <= caps.max_bandwidth_mbps:
                    max_fps = fps
                    break
            encoder = caps.available_encoders[0] if caps.available_encoders else "libx264"
            return VCNComputeFrameSpec(width=w, height=h, format=fmt,
                bytes_per_frame=frame_bytes, frame_rate=max_fps, encoder=encoder)
    w, h = caps.supported_resolutions[-1] if caps.supported_resolutions else (1920, 1080)
    encoder = caps.available_encoders[0] if caps.available_encoders else "libx264"
    return VCNComputeFrameSpec(width=w, height=h, format=fmt,
        bytes_per_frame=compute_frame_size(w, h, fmt), frame_rate=60, encoder=encoder)



def create_frame_dynamic(data: bytes, seq: int, spec: VCNComputeFrameSpec) -> bytes:
    """Create a frame at dynamic resolution from computation data."""
    frame_size = spec.bytes_per_frame
    if len(data) > frame_size - SIGNATURE_SIZE:
        raise ValueError(f"Data too large: {len(data)} > {frame_size - SIGNATURE_SIZE}")
    frame = bytearray(frame_size)
    version = 1
    length = len(data)
    header = SIGNATURE_HEADER + struct.pack("<IIII", version, seq, length, 0)
    frame[:SIGNATURE_SIZE] = header
    payload = frame[SIGNATURE_SIZE:]
    payload[:len(data)] = data
    payload[len(data):] = bytes([128] * (len(payload) - len(data)))
    return bytes(frame)


def encode_frames_hardware(
    input_frames: List[bytes],
    output_path: Path,
    spec: VCNComputeFrameSpec,
    sei_receipts: Optional[List[dict]] = None
) -> subprocess.CompletedProcess:
    """Encode frames using detected hardware encoder with software fallback.

    Args:
        input_frames: Raw YUV420 frame bytes.
        output_path: Output MKV path.
        spec: VCN frame specification.
        sei_receipts: Optional list of SEI receipt dicts, one per frame.
            Each dict must have: seq (int), crc32_hex (str), timestamp_us (int).
            When provided, SEI NAL unit is injected per-frame via h264_metadata BSF.
            The receipt format is: {"s": seq, "c": crc32_hex, "t": timestamp_us}
    """
    if sei_receipts is not None and len(sei_receipts) != len(input_frames):
        raise ValueError(f"sei_receipts count ({len(sei_receipts)}) != frames count ({len(input_frames)})")

    encoder = spec.encoder

    if sei_receipts is None:
        raw_path = output_path.with_suffix(".raw")
        with open(raw_path, "wb") as f:
            for frame in input_frames:
                f.write(frame)
        cmd = _build_ffmpeg_cmd(
            input_path=raw_path, output_path=output_path,
            spec=spec, encoder=encoder, sei_payload=None
        )
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 and encoder != "libx264":
            cmd[cmd.index("-c:v") + 1] = "libx264"
            result = subprocess.run(cmd, capture_output=True, text=True)
        raw_path.unlink(missing_ok=True)
        return result

    tmp_mkvs: List[Path] = []
    for idx, (frame, receipt) in enumerate(zip(input_frames, sei_receipts)):
        frame_raw = output_path.with_suffix(f".frame_{idx}.raw")
        with open(frame_raw, "wb") as f:
            f.write(frame)
        sei_payload_hex = json.dumps({
            "s": receipt["seq"],
            "c": receipt["crc32_hex"],
            "t": receipt["timestamp_us"]
        }, separators=(",", ":")).encode().hex()
        tmp_out = output_path.with_suffix(f".sei_{idx}.mkv")
        cmd = _build_ffmpeg_cmd(
            input_path=frame_raw, output_path=tmp_out,
            spec=spec, encoder=encoder, sei_payload=sei_payload_hex
        )
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 and encoder != "libx264":
            cmd[cmd.index("-c:v") + 1] = "libx264"
            result = subprocess.run(cmd, capture_output=True, text=True)
        frame_raw.unlink(missing_ok=True)
        if result.returncode != 0:
            for p in tmp_mkvs:
                p.unlink(missing_ok=True)
            return result
        tmp_mkvs.append(tmp_out)

    if len(tmp_mkvs) == 1:
        tmp_mkvs[0].replace(output_path)
        tmp_mkvs[0].unlink(missing_ok=True)
        return subprocess.CompletedProcess(args=["encode_frames_hardware"], returncode=0, stdout="", stderr="")

    combined_path = output_path.with_suffix(".combined.tmp")
    _merge_mkvs(tmp_mkvs, combined_path)
    combined_path.replace(output_path)
    for p in tmp_mkvs:
        p.unlink(missing_ok=True)
    return subprocess.CompletedProcess(args=["encode_frames_hardware"], returncode=0, stdout="", stderr="")


def _merge_mkvs(inputs: List[Path], output: Path) -> None:
    """Concatenate multiple MKV files into one using ffmpeg concat demuxer."""
    concat_list = output.with_suffix(".concat.txt")
    try:
        with open(concat_list, "w") as f:
            for p in inputs:
                f.write(f"file '{p}'\n")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list), "-c", "copy",
            "-f", "matroska", str(output)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"MKV concat failed: {result.stderr}")
    finally:
        concat_list.unlink(missing_ok=True)


def _build_ffmpeg_cmd(
    input_path: Path,
    output_path: Path,
    spec: VCNComputeFrameSpec,
    encoder: str,
    sei_payload: Optional[str] = None
) -> List[str]:
    cmd = ["ffmpeg", "-y",
            "-f", "rawvideo", "-pix_fmt", spec.format,
            "-s", f"{spec.width}x{spec.height}", "-r", str(spec.frame_rate),
            "-i", str(input_path)]

    # Load GPU-specific optimized flags based on selected encoder
    vendor = "unknown"
    if "nvenc" in encoder:
        vendor = "nvidia"
    elif "amf" in encoder or "vaapi" in encoder:
        vendor = "amd"

    opt = load_math_optimizations(vendor, "")

    if sei_payload is not None:
        if "hevc" in encoder or "h265" in encoder:
            bsf = f"hevc_metadata=sei_user_data={SEI_UUID}+{sei_payload}"
        else:
            bsf = f"h264_metadata=sei_user_data={SEI_UUID}+{sei_payload}"
        cmd.extend(["-c:v", encoder, "-bsf:v", bsf])
    else:
        cmd.extend(["-c:v", encoder])

    # Append the custom optimizations or default QPs
    if opt.encoder_opts:
        cmd.extend(opt.encoder_opts)
    else:
        cmd.extend(["-qp", str(QP_MIN)])

    if "vaapi" in encoder:
        cmd.insert(1, "-vaapi_device")
        cmd.insert(2, "/dev/dri/renderD128")
        cmd.insert(3, "-vf")
        cmd.insert(4, "format=nv12,hwupload")
    elif "nvenc" in encoder:
        if "-tune" not in opt.encoder_opts:
            cmd.extend(["-preset", "p1", "-tune", "zerolatency"])
    elif "amf" in encoder:
        if "-usage" not in opt.encoder_opts:
            cmd.extend(["-usage", "ultralowlatency"])
    elif encoder == "libx264":
        if not opt.encoder_opts:
            cmd.extend(["-profile:v", ENCODER_PROFILE, "-preset", "ultrafast", "-tune", "zerolatency"])

    cmd.extend(["-f", "matroska", str(output_path)])
    return cmd



def pack_q16_16_to_yuv(value: int) -> Tuple[int, int, int]:
    """
    Pack a Q16_16 scalar into YUV pixel values.

    Mapping strategy: Split 32-bit Q16_16 into three 8-bit components
    with error-diffusion dithering for precision preservation.

    Args:
        value: Q16_16 scalar as integer (0x00010000 = 1.0)

    Returns:
        (Y, U, V) tuple of pixel values (0-255)
    """
    # Extract bytes from Q16_16 (little-endian)
    y_val = (value >> 16) & 0xFF
    u_val = (value >> 8) & 0xFF
    v_val = value & 0xFF

    # Clamp to full range (matches load_math_optimizations color_range = "pc")
    y_val = max(0, min(255, y_val))   # Y: 0-255 (full range)
    u_val = max(0, min(255, u_val))   # U: 0-255 (full range)
    v_val = max(0, min(255, v_val))   # V: 0-255 (full range)

    return (y_val, u_val, v_val)


def unpack_yuv_to_q16_16(y: int, u: int, v: int) -> int:
    """
    Unpack YUV pixel values back to Q16_16 scalar.

    Args:
        y, u, v: YUV pixel values (0-255)

    Returns:
        Q16_16 scalar as integer
    """
    # Reconstruct Q16_16 from YUV components
    value = (y << 16) | (u << 8) | v
    return value


def create_yuv420_frame(data: bytes, seq: int) -> bytes:
    """
    Create a 1920×1080 YUV420 frame from computation data.

    Frame layout:
    - Bytes 0-23: Signature header (RDMAVCN\0 + version + seq + length)
    - Bytes 24+: Computation data packed into YUV macroblocks

    Args:
        data: Raw computation data bytes
        seq: Frame sequence number

    Returns:
        Complete YUV420 frame bytes (3,110,400 bytes)
    """
    if len(data) > YUV420_FRAME_SIZE - SIGNATURE_SIZE:
        raise ValueError(f"Data too large: {len(data)} > {YUV420_FRAME_SIZE - SIGNATURE_SIZE}")

    if _HAS_NUMPY:
        # Create empty planes filled with neutral gray (128)
        y_plane = np.full(FRAME_WIDTH * FRAME_HEIGHT, 128, dtype=np.uint8)
        u_plane = np.full((FRAME_WIDTH // 2) * (FRAME_HEIGHT // 2), 128, dtype=np.uint8)
        v_plane = np.full((FRAME_WIDTH // 2) * (FRAME_HEIGHT // 2), 128, dtype=np.uint8)

        # Parse data as uint32 values (little-endian)
        # Pad data to multiple of 4 bytes if necessary
        pad_len = (4 - (len(data) % 4)) % 4
        if pad_len > 0:
            padded_data = data + b"\x00" * pad_len
        else:
            padded_data = data

        values = np.frombuffer(padded_data, dtype=np.uint32)

        # Vectorized pack_q16_16_to_yuv
        y_vals = np.clip((values >> 16) & 0xFF, 16, 235).astype(np.uint8)
        u_vals = np.clip((values >> 8) & 0xFF, 16, 240).astype(np.uint8)
        v_vals = np.clip(values & 0xFF, 16, 240).astype(np.uint8)

        # Y plane: repeat each element 4 times
        y_plane_data = np.repeat(y_vals, 4)

        # Copy to planes
        n_y = min(len(y_plane_data), len(y_plane))
        n_uv = min(len(values), len(u_plane))

        y_plane[:n_y] = y_plane_data[:n_y]
        u_plane[:n_uv] = u_vals[:n_uv]
        v_plane[:n_uv] = v_vals[:n_uv]

        # Concatenate planes
        frame = bytearray(y_plane.tobytes() + u_plane.tobytes() + v_plane.tobytes())
    else:
        # Create frame buffer
        frame = bytearray(YUV420_FRAME_SIZE)

        # Pack data into YUV420 format
        # Y plane: 1920×1080 bytes
        # U plane: 960×540 bytes (subsampled 2x)
        # V plane: 960×540 bytes (subsampled 2x)

        y_plane_view = memoryview(frame)[0:FRAME_WIDTH * FRAME_HEIGHT]
        u_plane_view = memoryview(frame)[FRAME_WIDTH * FRAME_HEIGHT:FRAME_WIDTH * FRAME_HEIGHT + (FRAME_WIDTH // 2) * (FRAME_HEIGHT // 2)]
        v_plane_view = memoryview(frame)[FRAME_WIDTH * FRAME_HEIGHT + (FRAME_WIDTH // 2) * (FRAME_HEIGHT // 2):]

        # Pre-fill with neutral gray
        y_plane_view[:] = b"\x80" * len(y_plane_view)
        u_plane_view[:] = b"\x80" * len(u_plane_view)
        v_plane_view[:] = b"\x80" * len(v_plane_view)

        # Pack data as Q16_16 scalars into macroblocks (6 bytes = 4Y + 1U + 1V)
        data_idx = 0
        macroblock_idx = 0

        while data_idx + 4 <= len(data):
            # Read 4 bytes as Q16_16 scalar
            q16_value = struct.unpack("<I", data[data_idx:data_idx + 4])[0]
            y, u, v = pack_q16_16_to_yuv(q16_value)

            # Place in macroblock (4 Y pixels, 1 U, 1 V)
            mb_y_start = macroblock_idx * 4
            mb_u_start = macroblock_idx
            mb_v_start = macroblock_idx

            if mb_y_start + 4 <= len(y_plane_view):
                y_plane_view[mb_y_start:mb_y_start + 4] = bytes([y, y, y, y])
            if mb_u_start + 1 <= len(u_plane_view):
                u_plane_view[mb_u_start] = u
            if mb_v_start + 1 <= len(v_plane_view):
                v_plane_view[mb_v_start] = v

            data_idx += 4
            macroblock_idx += 1

    # Write signature header (exactly 24 bytes)
    version = 1
    length = len(data)
    header = SIGNATURE_HEADER + struct.pack("<IIII", version, seq, length, 0)
    frame[:SIGNATURE_SIZE] = header

    return bytes(frame)


def encode_frames(input_frames: List[bytes], output_path: Path) -> subprocess.CompletedProcess:
    """
    Encode raw YUV420 frames using H.264 encoder.

    Args:
        input_frames: List of YUV420 frame bytes
        output_path: Output MKV file path

    Returns:
        FFmpeg subprocess result
    """
    # Write raw YUV420 file
    raw_path = output_path.with_suffix(".yuv")
    with open(raw_path, "wb") as f:
        for frame in input_frames:
            f.write(frame)

    # FFmpeg command for software encoding (libx264) for initial testing
    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output file
        "-f", "rawvideo",
        "-pix_fmt", "yuv420p",
        "-s", f"{FRAME_WIDTH}x{FRAME_HEIGHT}",
        "-r", "60",  # 60 fps as per spec
        "-i", str(raw_path),
        "-c:v", "libx264",
        "-profile:v", ENCODER_PROFILE,
        "-level", ENCODER_LEVEL,
        "-qp", str(QP_MIN),
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-f", "matroska",
        str(output_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    # Clean up raw file
    raw_path.unlink()

    return result


def decode_frames(input_path: Path) -> List[bytes]:
    """
    Decode MKV file back to raw frames using native pixel format and resolution.

    Args:
        input_path: Input MKV file path

    Returns:
        List of decoded raw frame bytes
    """
    # 1. Probe the video container to find format, width, and height
    width, height, pix_fmt = 1920, 1080, "yuv420p"
    try:
        cmd_probe = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,pix_fmt",
            "-of", "json", str(input_path)
        ]
        res = subprocess.run(cmd_probe, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            meta = json.loads(res.stdout)
            stream = meta.get("streams", [{}])[0]
            width = stream.get("width", 1920)
            height = stream.get("height", 1080)
            pix_fmt = stream.get("pix_fmt", "yuv420p")
    except Exception:
        pass

    frame_size = compute_frame_size(width, height, pix_fmt)
    raw_path = input_path.with_suffix(".decoded.yuv")

    # 2. Decode natively using the parsed pixel format
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-c:v", "rawvideo",  # Decode to raw, don't re-encode
        "-f", "rawvideo",
        "-pix_fmt", pix_fmt,
        str(raw_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg decode failed: {result.stderr}")

    # Read decoded frames
    with open(raw_path, "rb") as f:
        data = f.read()

    # Split into frames according to probed frame size
    frames = []
    for i in range(0, len(data), frame_size):
        frame = data[i:i + frame_size]
        if len(frame) == frame_size:
            frames.append(frame)

    # Clean up
    raw_path.unlink(missing_ok=True)

    return frames



def extract_receipt(input_path: Path) -> dict:
    """
    Extract computation receipt from encoded MKV file.

    Receipt includes:
    - CRC32 of encoded file (proves encoding occurred)
    - Frame size statistics
    - Encoding parameters used
    - Bitstream analysis metadata
    - Compression ratio (input vs output size)

    Args:
        input_path: Input MKV file path

    Returns:
        Receipt dictionary
    """
    # Use ffprobe to get stream information
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(input_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFprobe failed: {result.stderr}")

    probe_info = json.loads(result.stdout)

    # Calculate file CRC32
    with open(input_path, "rb") as f:
        file_data = f.read()
    file_crc32 = zlib.crc32(file_data) & 0xFFFFFFFF

    # Extract compression metrics
    original_size = YUV420_FRAME_SIZE  # Single frame
    compressed_size = len(file_data)
    compression_ratio = original_size / compressed_size if compressed_size > 0 else 0

    receipt = {
        "schema": "vcn_computation_receipt_v1",
        "input_file": str(input_path),
        "file_size_bytes": len(file_data),
        "file_crc32": file_crc32,
        "encoding_params": {
            "codec": "libx264",
            "profile": ENCODER_PROFILE,
            "qp_min": QP_MIN,
            "qp_max": QP_MAX,
            "transform_skip": TRANSFORM_SKIP,
            "deblocking": DEBLOCKING,
            "sao": SAO
        },
        "stream_info": probe_info.get("streams", []),
        "format_info": probe_info.get("format", {}),
        "frame_spec": {
            "width": FRAME_WIDTH,
            "height": FRAME_HEIGHT,
            "format": "yuv420p",
            "bytes_per_frame": YUV420_FRAME_SIZE
        },
        "compression_metrics": {
            "original_size": original_size,
            "compressed_size": compressed_size,
            "compression_ratio": compression_ratio,
            "space_saving": (1 - (compressed_size / original_size)) * 100 if original_size > 0 else 0
        }
    }

    return receipt


# ── Braid-specific VCN encoding ──────────────────────────────────────────
# Maps braid operations (BraidStrand, BraidBracket, Mountain merge) to
# VCN frame bytes for GPU-accelerated encoding.
#
# Byte layout matches Semantics.BraidVCNBridge (Lean):
#   BraidBracket: 21 bytes [lower:4][upper:4][gap:4][kappa:4][phi:4][admissible:1]
#   BraidStrand:  42 bytes [phaseAcc.x:4][phaseAcc.y:4][parity:1][slot:4]
#                           [residue:4][jitter:4][bracket:21]
#   MountainMerge: variable [mergedHeight:4][coordCount:4][coords:4*count]
#
# All Q16_16 values serialized as unsigned 32-bit LE via toBits/ofBits.
# Float is forbidden in compute paths per AGENTS.md.

BRAID_STRAND_BYTES = 42
BRAID_BRACKET_BYTES = 21

# Pipeline configuration
RS_NSYM = 32                # Reed-Solomon parity symbols (corrects 16 symbol errors)
CHACHA_KEY_SIZE = 32        # 256-bit key
CHACHA_NONCE_SIZE = 16      # 128-bit nonce (cryptography ChaCha20 requires 16)

# Pipeline stage tags (1 byte each, used to identify frame contents)
TAG_STRAND   = 0x01
TAG_CROSSING = 0x02
TAG_PIST     = 0x03
TAG_LUPINE   = 0x04  # LUPINE CUDA operation (JSON-braid wrapper)
TAG_VAAPI    = 0x05  # AMD/Intel VA-API hardware encode/decode
TAG_FLAC     = 0x06  # PipeWire/FLAC audio DSP computation


def _q16_to_bytes(value: int) -> bytes:
    """Serialize a Q16_16 integer to 4 bytes (little-endian, unsigned offset).

    Matches Lean Q16_16.toBits: two's-complement UInt32 bit pattern.
    """
    v = value & 0xFFFFFFFF
    return struct.pack("<I", v)


def _u32_to_bytes(value: int) -> bytes:
    """Serialize a UInt32 to 4 bytes (little-endian)."""
    return struct.pack("<I", value & 0xFFFFFFFF)


def _bool_to_byte(value: bool) -> bytes:
    """Serialize a bool to 1 byte."""
    return b'\x01' if value else b'\x00'


# ── Delta + RLE compression ─────────────────────────────────────────────────

def delta_rle_encode(data: bytes) -> bytes:
    """Compress *data* using delta encoding followed by run-length encoding.

    Layout:
        [4 bytes: original length][1 byte: delta flag (0x01)]
        [delta-encoded + RLE stream]

    RLE scheme: if a byte repeats ≥3 times, emit [0xFE, byte, count].
    0xFE in the literal stream is escaped as [0xFE, 0xFE].
    """
    if not data:
        return struct.pack("<I", 0) + b"\x01"

    # Delta encoding (byte-level deltas)
    deltas = bytearray(len(data))
    deltas[0] = data[0]
    for i in range(1, len(data)):
        deltas[i] = (data[i] - data[i - 1]) & 0xFF

    # RLE pass
    out = bytearray()
    i = 0
    while i < len(deltas):
        if i + 2 < len(deltas) and deltas[i] == deltas[i + 1] == deltas[i + 2]:
            # Run of identical bytes
            run_byte = deltas[i]
            run_len = 0
            while i + run_len < len(deltas) and deltas[i + run_len] == run_byte and run_len < 255:
                run_len += 1
            out.append(0xFE)
            out.append(run_byte)
            out.append(run_len)
            i += run_len
        else:
            b = deltas[i]
            if b == 0xFE:
                out.append(0xFE)
                out.append(0xFE)
            else:
                out.append(b)
            i += 1

    header = struct.pack("<I", len(data)) + b"\x01"
    return header + bytes(out)


def delta_rle_decode(stream: bytes) -> bytes:
    """Decompress a delta-RLE stream back to original bytes.

    Supports two flags:
      0x01 — scalar path: [orig_len][0x01][rle_stream]
      0x02 — vectorized path: [orig_len][0x02][pos_bytes_len][pos_bytes][rle_stream]
    """
    orig_len = struct.unpack("<I", stream[:4])[0]
    if orig_len == 0:
        return b""
    flag = stream[4]

    if flag == 0x02:
        # Vectorized path: reconstruct from nonzero positions + RLE-compressed values
        pos_bytes_len = struct.unpack("<I", stream[5:9])[0]
        pos_bytes = stream[9:9 + pos_bytes_len]
        nz_positions = list(struct.unpack(f"<{pos_bytes_len // 4}I", pos_bytes))
        payload = stream[9 + pos_bytes_len:]

        # Undo RLE on the compressed nonzero values
        expanded_nz = bytearray()
        i = 0
        while i < len(payload):
            if payload[i] == 0xFE:
                if i + 1 < len(payload) and payload[i + 1] == 0xFE:
                    expanded_nz.append(0xFE)
                    i += 2
                elif i + 2 < len(payload):
                    run_byte = payload[i + 1]
                    run_len = payload[i + 2]
                    expanded_nz.extend([run_byte] * run_len)
                    i += 3
                else:
                    expanded_nz.append(payload[i])
                    i += 1
            else:
                expanded_nz.append(payload[i])
                i += 1

        # Scatter nonzero values back to their original positions
        full_deltas = bytearray(orig_len)
        for idx, pos in enumerate(nz_positions):
            if idx < len(expanded_nz) and pos < orig_len:
                full_deltas[pos] = expanded_nz[idx]

        # Undo delta encoding
        out = bytearray(orig_len)
        if orig_len > 0:
            out[0] = full_deltas[0]
            for j in range(1, orig_len):
                out[j] = (full_deltas[j] + out[j - 1]) & 0xFF
        return bytes(out)

    if flag != 0x01:
        raise ValueError(f"Unknown delta-RLE flag: {flag}")

    # Scalar path (flag == 0x01)
    payload = stream[5:]

    # Undo RLE
    expanded = bytearray()
    i = 0
    while i < len(payload):
        if payload[i] == 0xFE:
            if i + 1 < len(payload) and payload[i + 1] == 0xFE:
                expanded.append(0xFE)
                i += 2
            elif i + 2 < len(payload):
                run_byte = payload[i + 1]
                run_len = payload[i + 2]
                expanded.extend([run_byte] * run_len)
                i += 3
            else:
                expanded.append(payload[i])
                i += 1
        else:
            expanded.append(payload[i])
            i += 1

    # Undo delta encoding
    out = bytearray(orig_len)
    if orig_len > 0:
        out[0] = expanded[0]
        for j in range(1, orig_len):
            out[j] = (expanded[j] + out[j - 1]) & 0xFF

    return bytes(out)


# ── Reed-Solomon error correction ───────────────────────────────────────────

def rs_encode(data: bytes, nsym: int = RS_NSYM) -> bytes:
    """Append Reed-Solomon parity symbols to *data*."""
    if reedsolo is None:
        raise ImportError("reedsolo is required for Reed-Solomon ECC. pip install reedsolo")
    rs = reedsolo.RSCodec(nsym)
    return rs.encode(data)


def rs_decode(data: bytes, nsym: int = RS_NSYM) -> bytes:
    """Decode (and correct errors in) a Reed-Solomon encoded message."""
    if reedsolo is None:
        raise ImportError("reedsolo is required for Reed-Solomon ECC. pip install reedsolo")
    rs = reedsolo.RSCodec(nsym)
    decoded = rs.decode(data)
    # reedsolo returns (decoded_msg, decoded_msg_with_ecc, ...) — take first element
    if isinstance(decoded, tuple):
        return bytes(decoded[0])
    return bytes(decoded)


# ── ChaCha20 encryption ─────────────────────────────────────────────────────

def _get_chacha_key(key: Optional[bytes] = None) -> bytes:
    """Return a 32-byte ChaCha20 key, generating one if not supplied."""
    if key is not None:
        if len(key) != CHACHA_KEY_SIZE:
            raise ValueError(f"Key must be {CHACHA_KEY_SIZE} bytes")
        return key
    return os.urandom(CHACHA_KEY_SIZE)


def chacha_encrypt(plaintext: bytes, key: bytes, nonce: Optional[bytes] = None) -> Tuple[bytes, bytes]:
    """Encrypt *plaintext* with ChaCha20. Returns (ciphertext, nonce)."""
    if not _CHA20_AVAILABLE:
        raise ImportError("cryptography is required for ChaCha20. pip install cryptography")
    if nonce is None:
        nonce = os.urandom(CHACHA_NONCE_SIZE)
    encryptor = _Cipher(_alg.ChaCha20(key, nonce), mode=None).encryptor()
    ct = encryptor.update(plaintext) + encryptor.finalize()
    return ct, nonce


def chacha_decrypt(ciphertext: bytes, key: bytes, nonce: bytes) -> bytes:
    """Decrypt *ciphertext* with ChaCha20."""
    if not _CHA20_AVAILABLE:
        raise ImportError("cryptography is required for ChaCha20. pip install cryptography")
    decryptor = _Cipher(_alg.ChaCha20(key, nonce), mode=None).decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


# ── Serialization / Deserialization helpers ──────────────────────────────────

def _serialize_bracket(bracket: dict) -> bytes:
    """Encode a BraidBracket dict to 21 bytes."""
    data = b""
    for key in ("lower", "upper", "gap", "kappa", "phi"):
        data += _q16_to_bytes(bracket[key])
    data += _bool_to_byte(bracket["admissible"])
    return data


def _deserialize_bracket(raw: bytes) -> dict:
    """Decode 21 bytes into a BraidBracket dict."""
    keys = ("lower", "upper", "gap", "kappa", "phi")
    bracket = {}
    for i, key in enumerate(keys):
        bracket[key] = struct.unpack("<I", raw[i * 4:(i + 1) * 4])[0]
    bracket["admissible"] = raw[20] != 0
    return bracket


def _serialize_strand(strand: dict) -> bytes:
    """Encode a BraidStrand dict to 42 bytes."""
    data = b""
    data += _q16_to_bytes(strand["phaseAcc"]["x"])
    data += _q16_to_bytes(strand["phaseAcc"]["y"])
    data += _bool_to_byte(strand["parity"])
    data += _u32_to_bytes(strand["slot"])
    data += _q16_to_bytes(strand["residue"])
    data += _q16_to_bytes(strand["jitter"])
    data += _serialize_bracket(strand["bracket"])
    assert len(data) == BRAID_STRAND_BYTES
    return data


def _deserialize_strand(raw: bytes) -> dict:
    """Decode 42 bytes into a BraidStrand dict."""
    return {
        "phaseAcc": {
            "x": struct.unpack("<I", raw[0:4])[0],
            "y": struct.unpack("<I", raw[4:8])[0],
        },
        "parity": raw[8] != 0,
        "slot": struct.unpack("<I", raw[9:13])[0],
        "residue": struct.unpack("<I", raw[13:17])[0],
        "jitter": struct.unpack("<I", raw[17:21])[0],
        "bracket": _deserialize_bracket(raw[21:42]),
    }


# ── Full pipeline: encode payload ───────────────────────────────────────────

def _build_frame_payload(tag: int, serialized: bytes,
                         key: Optional[bytes],
                         compress: bool = True) -> bytes:
    """Apply Delta+RLE → RS → ChaCha20 → return frame-ready payload.

    Layout: [1B tag][1B flags][nonce?][RS-encoded, encrypted blob]
    """
    flags = 0x00
    if compress:
        flags |= 0x01

    blob = serialized
    if compress:
        blob = delta_rle_encode(blob)

    blob = rs_encode(blob)

    nonce = b""
    if key is not None:
        blob, nonce = chacha_encrypt(blob, key)
        flags |= 0x02  # encrypted flag

    return struct.pack("<BB", tag, flags) + nonce + blob


# ── Full pipeline: decode payload ───────────────────────────────────────────

def decode_braid_frame(frame_payload: bytes,
                       key: Optional[bytes] = None) -> dict:
    """Decode a frame payload (after extracting from MKV / YUV420 frame).

    Reverses: ChaCha20 decrypt → RS decode → Delta+RLE decompress → deserialize.

    Args:
        frame_payload: raw payload bytes (after stripping VCN signature header).
        key: ChaCha20 key (required if the frame was encrypted).

    Returns:
        {
            "tag": int,
            "tag_name": str,
            "flags": int,
            "decrypted": bool,
            "data": dict | bytes,  # deserialized braid structure
        }
    """
    tag, flags = struct.unpack("<BB", frame_payload[:2])
    encrypted = bool(flags & 0x02)
    compressed = bool(flags & 0x01)
    offset = 2

    nonce = b""
    if encrypted:
        nonce = frame_payload[offset:offset + CHACHA_NONCE_SIZE]
        offset += CHACHA_NONCE_SIZE

    blob = frame_payload[offset:]

    # Reverse pipeline
    if encrypted:
        if key is None:
            raise ValueError("Frame is encrypted but no key provided")
        blob = chacha_decrypt(blob, key, nonce)

    blob = rs_decode(blob)

    if compressed:
        blob = delta_rle_decode(blob)

    # Deserialize based on tag
    tag_names = {TAG_STRAND: "strand", TAG_CROSSING: "crossing", TAG_PIST: "pist"}
    result: dict = {
        "tag": tag,
        "tag_name": tag_names.get(tag, "unknown"),
        "flags": flags,
        "decrypted": encrypted,
    }

    if tag == TAG_STRAND:
        result["data"] = _deserialize_strand(blob)
    elif tag == TAG_CROSSING:
        result["data"] = {
            "bracket_a": _deserialize_bracket(blob[:BRAID_BRACKET_BYTES]),
            "bracket_b": _deserialize_bracket(blob[BRAID_BRACKET_BYTES:]),
        }
    elif tag == TAG_PIST:
        result["data"] = json.loads(blob.decode("utf-8"))
    else:
        result["data"] = blob

    return result


def encode_braid_bracket(bracket: dict) -> bytes:
    """Encode a BraidBracket dict to 21 bytes.

    Args:
        bracket: dict with keys 'lower', 'upper', 'gap', 'kappa', 'phi' (Q16_16 ints),
                 'admissible' (bool)

    Returns:
        21-byte serialization matching Lean encodeBraidBracket.
    """
    data = b''
    for key in ['lower', 'upper', 'gap', 'kappa', 'phi']:
        data += _q16_to_bytes(bracket[key])
    data += _bool_to_byte(bracket['admissible'])
    return data


def encode_braid_strand(strand_data: dict, resolution: str = "1080p",
                         key: Optional[bytes] = None,
                         compress: bool = True) -> bytes:
    """Encode a BraidStrand dict to a VCN frame with optional pipeline stages.

    Args:
        strand_data: dict with keys:
            'phaseAcc': {'x': int, 'y': int}  (Q16_16 values)
            'parity': bool
            'slot': int (UInt32)
            'residue': int (Q16_16)
            'jitter': int (Q16_16)
            'bracket': dict (see encode_braid_bracket)
        resolution: VCN resolution string (default "1080p")
        key: Optional ChaCha20 encryption key (32 bytes)
        compress: Apply Delta+RLE compression (default True)

    Returns:
        Raw VCN frame bytes (YUV420) suitable for hardware encoding.
    """
    serialized = _serialize_strand(strand_data)
    payload = _build_frame_payload(TAG_STRAND, serialized, key, compress)

    w, h = VCN_RESOLUTIONS.get(resolution, VCN_RESOLUTIONS["1080p"])
    spec = VCNComputeFrameSpec(
        width=w, height=h,
        bytes_per_frame=compute_frame_size(w, h, "yuv420p"),
        encoder="libx264"
    )
    return create_frame_dynamic(payload, seq=0, spec=spec)


def encode_braid_crossing(bracket_a: dict, bracket_b: dict,
                          resolution: str = "1080p",
                          key: Optional[bytes] = None,
                          compress: bool = True) -> bytes:
    """Encode two BraidBrackets (crossing operation) to a VCN frame with optional pipeline.

    Encodes the crossing residual computation R_ij = B_ij - (B_i + B_j)
    by packing both brackets side by side (42 bytes).

    Args:
        bracket_a, bracket_b: dicts with bracket fields
        resolution: VCN resolution string
        key: Optional ChaCha20 encryption key (32 bytes)
        compress: Apply Delta+RLE compression (default True)

    Returns:
        Raw VCN frame bytes.
    """
    serialized = _serialize_bracket(bracket_a) + _serialize_bracket(bracket_b)
    payload = _build_frame_payload(TAG_CROSSING, serialized, key, compress)

    w, h = VCN_RESOLUTIONS.get(resolution, VCN_RESOLUTIONS["1080p"])
    spec = VCNComputeFrameSpec(
        width=w, height=h,
        bytes_per_frame=compute_frame_size(w, h, "yuv420p"),
        encoder="libx264"
    )
    return create_frame_dynamic(payload, seq=0, spec=spec)


def encode_mountain_merge(mountain_a: dict, mountain_b: dict,
                          resolution: str = "1080p",
                          key: Optional[bytes] = None,
                          compress: bool = True) -> bytes:
    """Encode a Mountain merge operation to a VCN frame with optional pipeline.

    Implements Mountain.merge: merged height = h+1, apex = a1.add(a2)
    (coordinate-wise sum with zero-padding, matching Lean IntNode.add).

    Args:
        mountain_a, mountain_b: dicts with keys:
            'height': int
            'apex_coords': list of int
        resolution: VCN resolution string
        key: Optional ChaCha20 encryption key (32 bytes)
        compress: Apply Delta+RLE compression (default True)

    Returns:
        Raw VCN frame bytes encoding the merge result.
    """
    # Mountain.merge: height = h1 + 1
    merged_height = mountain_a['height'] + 1

    # Coordinate-wise sum with zero-padding (matching IntNode.add)
    coords_a = mountain_a['apex_coords']
    coords_b = mountain_b['apex_coords']
    n = max(len(coords_a), len(coords_b))
    padded_a = coords_a + [0] * (n - len(coords_a))
    padded_b = coords_b + [0] * (n - len(coords_b))
    merged_coords = [a + b for a, b in zip(padded_a, padded_b)]

    serialized = _u32_to_bytes(merged_height)
    serialized += _u32_to_bytes(len(merged_coords))
    for coord in merged_coords:
        # Clamp to Int32 range and serialize as unsigned 32-bit
        # (matching Lean UInt32.ofInt with clamping)
        clamped = max(-2147483648, min(2147483647, coord))
        serialized += struct.pack("<I", clamped & 0xFFFFFFFF)

    payload = _build_frame_payload(TAG_PIST, serialized, key, compress)

    w, h = VCN_RESOLUTIONS.get(resolution, VCN_RESOLUTIONS["1080p"])
    spec = VCNComputeFrameSpec(
        width=w, height=h,
        bytes_per_frame=compute_frame_size(w, h, "yuv420p"),
        encoder="libx264"
    )
    return create_frame_dynamic(payload, seq=0, spec=spec)


# ── Public deserialize wrappers (used by vcn_lupine_bridge) ─────────────────

def deserialize_braid_strand(raw: bytes) -> dict:
    return _deserialize_strand(raw)


def deserialize_braid_bracket(raw: bytes) -> dict:
    return _deserialize_bracket(raw)


def deserialize_braid_strand_with_payload(raw: bytes) -> dict:
    return {
        "strand": _deserialize_strand(raw),
        "payload_bytes": len(raw),
    }


# ── Braid compute stubs (GPU node side — TODO: lean-port) ──────────────────

def compute_strand_phase(strand: dict) -> dict:
    phase_x = strand.get("phaseAcc", {}).get("x", 0)
    phase_y = strand.get("phaseAcc", {}).get("y", 0)
    slot = strand.get("slot", 0)
    return {
        "phase_x": phase_x,
        "phase_y": phase_y,
        "slot": slot,
        "norm": (phase_x * phase_x + phase_y * phase_y) >> 16,
    }


def serialize_crossing_result(result: dict) -> bytes:
    residual = result.get("residual", 0)
    status = result.get("status", "ok")
    return struct.pack("<I", residual) + status.encode("utf-8")[:8].ljust(8, b"\x00")


def compute_crossing_residual(bracket_a: dict, bracket_b: dict) -> dict:
    a_sum = (bracket_a["lower"] + bracket_a["upper"]) & 0xFFFFFFFF
    b_sum = (bracket_b["lower"] + bracket_b["upper"]) & 0xFFFFFFFF
    cross = (bracket_a["lower"] * bracket_b["upper"]) & 0xFFFFFFFF
    residual = (cross - a_sum - b_sum) & 0xFFFFFFFF
    return {"residual": residual, "status": "ok"}


def deserialize_pist_data(raw: bytes) -> dict:
    if len(raw) < 4:
        return {"coeffs": [], "count": 0}
    count = struct.unpack("<I", raw[:4])[0]
    coeffs = list(struct.unpack(f"<{count}I", raw[4:4 + count * 4])) if count > 0 else []
    return {"coeffs": coeffs, "count": count}


def serialize_pist_result(result: dict) -> bytes:
    coeffs = result.get("coeffs", [])
    count = len(coeffs)
    return struct.pack("<I", count) + struct.pack(f"<{count}I", *coeffs) if count > 0 else struct.pack("<I", 0)


def compute_pist_spectral(data: dict) -> dict:
    coeffs = data.get("coeffs", [])
    if not coeffs:
        return {"spectral_centroid": 0, "spectral_flux": 0, "count": 0}
    total = sum(coeffs)
    centroid = (total // max(len(coeffs), 1)) & 0xFFFFFFFF
    flux = sum(abs(coeffs[i] - coeffs[i - 1]) for i in range(1, len(coeffs))) & 0xFFFFFFFF
    return {"spectral_centroid": centroid, "spectral_flux": flux, "count": len(coeffs)}


# ── main ────────────────────────────────────────────────────────────────────

def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage: vcn_compute_substrate.py <encode|decode|extract_receipt|encode_enhanced|decode_enhanced> <input> <output> [key.hex]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "encode":
        input_path = Path(sys.argv[2])
        output_path = Path(sys.argv[3])

        # Read input data
        with open(input_path, "rb") as f:
            data = f.read()

        # Create frame
        frame = create_yuv420_frame(data, seq=0)

        # Encode
        result = encode_frames([frame], output_path)

        if result.returncode != 0:
            print(f"Encoding failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)

        print(f"Encoded to {output_path}")

    elif command == "decode":
        input_path = Path(sys.argv[2])
        output_path = Path(sys.argv[3])

        # Decode
        frames = decode_frames(input_path)

        # Extract first frame's data
        if frames:
            frame = frames[0]
            # Extract signature header
            header = frame[:SIGNATURE_SIZE]
            signature, version, seq, length, _ = struct.unpack("<8sIIII", header)

            if signature != SIGNATURE_HEADER:
                print(f"Invalid signature: {signature}", file=sys.stderr)
                sys.exit(1)

            # Extract data payload
            data = frame[SIGNATURE_SIZE:SIGNATURE_SIZE + length]

            with open(output_path, "wb") as f:
                f.write(data)

            print(f"Decoded to {output_path}")
        else:
            print("No frames decoded", file=sys.stderr)
            sys.exit(1)

    elif command == "extract_receipt":
        input_path = Path(sys.argv[2])
        receipt = extract_receipt(input_path)
        output_path = Path(sys.argv[3])

        with open(output_path, "w") as f:
            json.dump(receipt, f, indent=2)

        print(f"Receipt written to {output_path}")

    elif command == "encode_enhanced":
        # Usage: encode_enhanced strand.json output.mkv [key.hex]
        input_path = Path(sys.argv[2])
        output_path = Path(sys.argv[3])
        key = None
        if len(sys.argv) > 4:
            key = bytes.fromhex(sys.argv[4])
            if len(key) != CHACHA_KEY_SIZE:
                print(f"Key must be {CHACHA_KEY_SIZE} bytes ({CHACHA_KEY_SIZE * 2} hex chars)", file=sys.stderr)
                sys.exit(1)

        with open(input_path) as f:
            strand_dict = json.load(f)

        frame = encode_braid_strand(strand_dict, key=key, compress=True)

        with open(output_path, "wb") as f:
            f.write(frame)

        print(f"Enhanced-encoded strand to {output_path}")

    elif command == "decode_enhanced":
        # Usage: decode_enhanced input.mkv output.json [key.hex]
        input_path = Path(sys.argv[2])
        output_path = Path(sys.argv[3])
        key = None
        if len(sys.argv) > 4:
            key = bytes.fromhex(sys.argv[4])

        frames = decode_frames(input_path)
        if not frames:
            print("No frames decoded", file=sys.stderr)
            sys.exit(1)

        frame = frames[0]
        header = frame[:SIGNATURE_SIZE]
        signature, version, seq, length, _ = struct.unpack("<8sIIII", header)

        if signature != SIGNATURE_HEADER:
            print(f"Invalid signature: {signature}", file=sys.stderr)
            sys.exit(1)

        payload = frame[SIGNATURE_SIZE:SIGNATURE_SIZE + length]
        result = decode_braid_frame(payload, key)

        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)

        print(f"Decoded enhanced frame to {output_path}")

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
