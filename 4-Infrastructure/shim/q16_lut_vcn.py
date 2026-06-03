#!/usr/bin/env python3
"""
Q16_16 Lookup Table VCN Encoder

Generates Q16_16 lookup tables for arithmetic operations (add/sub/mul/div/
max/min/neg/abs), encodes each LUT as a VCN YUV420 frame via the existing
vcn_compute_substrate infrastructure, and provides round-trip decode.

The full Q16_16 range is 2^32 values, but we discretize into 65536 entries
per operation (sampling every 65536-th input or using a 256×256 grid for
two-operand ops) so the LUT fits a single VCN frame.

Usage:
    python3 q16_lut_vcn.py gen_add 1080p   -> writes add_lut.mkv
"""

from __future__ import annotations

import struct
import math
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Local imports – same directory
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from vcn_compute_substrate import (
    VCNComputeFrameSpec, VCN_RESOLUTIONS, SIGNATURE_HEADER, SIGNATURE_SIZE,
    compute_frame_size, create_frame_dynamic, encode_frames_hardware,
)

# ── Constants ────────────────────────────────────────────────────────────────

Q16_ONE = 0x00010000          # 1.0 in Q16_16
Q16_MASK = 0xFFFFFFFF
LUT_ENTRIES = 65536           # 256 × 256 grid for two-operand ops
GRID_SIDE = 256               # sample every 256-th value along each axis
SAMPLE_STRIDE = Q16_ONE // GRID_SIDE  # 256

SUPPORTED_OPS = ("add", "sub", "mul", "div", "max", "min", "neg", "abs")


# ── Q16_16 arithmetic (integer-only, no float in compute paths) ─────────────

def _q16_add(a: int, b: int) -> int:
    return (a + b) & Q16_MASK

def _q16_sub(a: int, b: int) -> int:
    return (a - b) & Q16_MASK

def _q16_mul(a: int, b: int) -> int:
    """Saturating Q16_16 multiply."""
    sa = a if a < 0x80000000 else a - 0x100000000
    sb = b if b < 0x80000000 else b - 0x100000000
    result = (sa * sb) >> 16
    # Clamp to Q16_16 range
    if result > 0x7FFFFFFF:
        return 0x7FFFFFFF
    if result < -0x80000000:
        return 0x80000000
    return result & Q16_MASK

def _q16_div(a: int, b: int) -> int:
    """Saturating Q16_16 divide."""
    if b == 0:
        return 0x7FFFFFFF  # saturate
    sa = a if a < 0x80000000 else a - 0x100000000
    sb = b if b < 0x80000000 else b - 0x100000000
    result = (sa << 16) // sb
    if result > 0x7FFFFFFF:
        return 0x7FFFFFFF
    if result < -0x80000000:
        return 0x80000000
    return result & Q16_MASK

def _q16_max(a: int, b: int) -> int:
    sa = a if a < 0x80000000 else a - 0x100000000
    sb = b if b < 0x80000000 else b - 0x100000000
    return (sa if sa >= sb else sb) & Q16_MASK

def _q16_min(a: int, b: int) -> int:
    sa = a if a < 0x80000000 else a - 0x100000000
    sb = b if b < 0x80000000 else b - 0x100000000
    return (sa if sa <= sb else sb) & Q16_MASK

def _q16_neg(a: int) -> int:
    return (-a) & Q16_MASK

def _q16_abs(a: int) -> int:
    sa = a if a < 0x80000000 else a - 0x100000000
    return (sa if sa >= 0 else -sa) & Q16_MASK


# Two-operand dispatch table
_TWO_OP = {
    "add": _q16_add,
    "sub": _q16_sub,
    "mul": _q16_mul,
    "div": _q16_div,
    "max": _q16_max,
    "min": _q16_min,
}

# Single-operand dispatch table
_ONE_OP = {
    "neg": _q16_neg,
    "abs": _q16_abs,
}


# ── LUT generation ───────────────────────────────────────────────────────────

def generate_lut(operation: str) -> List[int]:
    """Generate 65536-entry LUT for *operation*.

    For two-operand ops we build a 256×256 grid:  entry[i*256+j] = op(i*stride, j*stride).
    For single-operand ops we store op(i*stride) for i in 0..65535.

    Returns a list of 65536 unsigned 32-bit Q16_16 results.
    """
    if operation not in SUPPORTED_OPS:
        raise ValueError(f"Unsupported operation '{operation}'. Choose from {SUPPORTED_OPS}")

    table: List[int] = [0] * LUT_ENTRIES

    if operation in _TWO_OP:
        fn = _TWO_OP[operation]
        for i in range(GRID_SIDE):
            a = (i * SAMPLE_STRIDE) & Q16_MASK
            for j in range(GRID_SIDE):
                b = (j * SAMPLE_STRIDE) & Q16_MASK
                table[i * GRID_SIDE + j] = fn(a, b)
    else:
        fn = _ONE_OP[operation]
        for i in range(LUT_ENTRIES):
            val = (i * (Q16_ONE // LUT_ENTRIES * LUT_ENTRIES if LUT_ENTRIES < Q16_ONE else 1)) & Q16_MASK
            # For single-operand, map index to Q16 value
            val = (i * (Q16_MASK // LUT_ENTRIES + 1)) & Q16_MASK
            table[i] = fn(val)

    return table


def serialize_lut(table: List[int]) -> bytes:
    """Serialize LUT to bytes (65536 × 4 = 256 KiB)."""
    return struct.pack(f"<{LUT_ENTRIES}I", *table)


def deserialize_lut(data: bytes) -> List[int]:
    """Deserialize bytes back to LUT."""
    return list(struct.unpack(f"<{LUT_ENTRIES}I", data[:LUT_ENTRIES * 4]))


def lut_checksum(table: List[int]) -> str:
    """SHA-256 hex digest of the serialized LUT."""
    return hashlib.sha256(serialize_lut(table)).hexdigest()


# ── VCN frame encode / decode ───────────────────────────────────────────────

def encode_q16_lut_frame(operation: str, resolution: str = "1080p") -> bytes:
    """Generate a Q16_16 LUT for *operation* and encode it as a VCN YUV420 frame.

    The frame payload is:  [4-byte op tag][32-byte SHA-256][256 KiB LUT data]

    Returns raw YUV420 frame bytes.
    """
    table = generate_lut(operation)
    payload = serialize_lut(table)

    # Prepend operation tag + checksum for validation on decode
    op_tag = operation.encode("ascii").ljust(4, b"\x00")[:4]
    checksum = hashlib.sha256(payload).digest()  # 32 bytes
    frame_data = op_tag + checksum + payload  # 4 + 32 + 262144 = 262180 bytes

    w, h = VCN_RESOLUTIONS.get(resolution, VCN_RESOLUTIONS["1080p"])
    spec = VCNComputeFrameSpec(
        width=w, height=h,
        bytes_per_frame=compute_frame_size(w, h, "yuv420p"),
        encoder="libx264",
    )
    return create_frame_dynamic(frame_data, seq=0, spec=spec)


def decode_q16_lut_frame(frame_bytes: bytes, operation: str) -> Dict:
    """Decode a VCN YUV420 frame back to a Q16_16 LUT.

    Parses the frame payload, validates the SHA-256 checksum, and returns:
        {
            "operation": str,
            "entries": List[int],   # 65536 Q16_16 values
            "checksum_valid": bool,
            "checksum": str,        # hex
        }
    """
    # Strip signature header (first SIGNATURE_SIZE bytes)
    payload = frame_bytes[SIGNATURE_SIZE:]

    # Parse header
    op_tag = payload[:4].rstrip(b"\x00").decode("ascii")
    stored_checksum = payload[4:36]  # 32 bytes
    lut_data = payload[36:36 + LUT_ENTRIES * 4]

    table = deserialize_lut(lut_data)
    computed_checksum = hashlib.sha256(lut_data).digest()
    valid = computed_checksum == stored_checksum

    return {
        "operation": op_tag if op_tag else operation,
        "entries": table,
        "checksum_valid": valid,
        "checksum": computed_checksum.hex(),
    }


def encode_q16_lut_to_mkv(operation: str, output_path: str | Path,
                           resolution: str = "1080p") -> Path:
    """Full pipeline: generate LUT → VCN frame → hardware encode to MKV."""
    output_path = Path(output_path)
    frame = encode_q16_lut_frame(operation, resolution)
    w, h = VCN_RESOLUTIONS.get(resolution, VCN_RESOLUTIONS["1080p"])
    spec = VCNComputeFrameSpec(
        width=w, height=h,
        bytes_per_frame=compute_frame_size(w, h, "yuv420p"),
        encoder="libx264",
    )
    result = encode_frames_hardware([frame], output_path, spec)
    if result.returncode != 0:
        raise RuntimeError(f"VCN encode failed: {result.stderr}")
    return output_path


# ── CLI entry-point ──────────────────────────────────────────────────────────

def main():
    import sys
    if len(sys.argv) < 3:
        print("Usage: q16_lut_vcn.py <operation> <resolution>")
        print(f"  operations: {SUPPORTED_OPS}")
        print("  resolution: 240p .. 16K")
        sys.exit(1)

    op = sys.argv[1]
    res = sys.argv[2] if len(sys.argv) > 2 else "1080p"

    print(f"Generating Q16_16 LUT for '{op}' ...")
    table = generate_lut(op)
    print(f"  LUT size: {len(table)} entries, checksum: {lut_checksum(table)}")

    out = encode_q16_lut_to_mkv(op, Path(f"{op}_lut.mkv"), res)
    print(f"  Written to {out}")


if __name__ == "__main__":
    main()
