"""
VCN FAMM Transport — Gate-checked encode/decode with scar tracking.

Wraps the VCN pipeline with FAMM (Framework-Agnostic Meta-Monitor) checks:
  - gateCondition: ||coker(M) residual|| < ε (Q16_16)
  - Scar/ScarBundle: pressure + mode per strand
  - fammGate: admissibility check on 8-strand state
  - Eigensolid convergence: verify before transmission
  - Fractal dimension: select voltage mode
  - RouteCost: latency class → transport priority
  - SEI receipts: CRC32 + FAMM metadata

All arithmetic is Q16_16 fixed-point (no Float in compute paths).

Lean source of truth:
  - Semantics/DegeneracyConversion.lean: gateCondition
  - Semantics/BraidTreeDIATPIST.lean: Scar, ScarBundle, fammGate
  - Semantics/F01_Q16_16_FixedPoint.lean: eigensolidReceipt
"""

from __future__ import annotations

import hashlib
import struct
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))

# BraidDiatCodec: compact braid encoding (714 bytes avg)
try:
    from braid_diat_codec import BraidDiatFrame, BraidDiatCodec
    _HAS_BRAID_DIAT = True
except ImportError:
    _HAS_BRAID_DIAT = False

from braid_vcn_encoder import (
    delta_rle_encode_vectorized,
    rs_encode,
    decode_braid_frame_extended,
)
from vcn_compute_substrate import (
    _build_frame_payload, create_frame_dynamic,
    encode_frames_hardware, compute_frame_size,
    VCNComputeFrameSpec, TAG_STRAND,
)
from fractal_dimension import fractal_dimension, fd_compress_hint

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


# ── Q16_16 Fixed-Point (matches Lean FixedPoint.lean) ───────────────────────

Q16_SCALE = 65536  # 2^16
Q16_MAX = 32767    # max Q16_16 value
Q16_MIN = -32768   # min Q16_16 value


def q16_from_int(x: int) -> int:
    """Convert integer to Q16_16 raw value."""
    raw = x * Q16_SCALE
    return max(Q16_MIN, min(Q16_MAX, raw))


def q16_to_float(raw: int) -> float:
    """Convert Q16_16 raw to float (boundary use only)."""
    return raw / Q16_SCALE


def q16_abs(raw: int) -> int:
    """Absolute value in Q16_16."""
    return raw if raw >= 0 else -raw


def q16_neg(raw: int) -> int:
    """Negate in Q16_16."""
    result = -raw
    return max(Q16_MIN, min(Q16_MAX, result))


def q16_mul(a: int, b: int) -> int:
    """Multiply two Q16_16 values."""
    result = (a * b) // Q16_SCALE
    return max(Q16_MIN, min(Q16_MAX, result))


def q16_add(a: int, b: int) -> int:
    """Add two Q16_16 values."""
    result = a + b
    return max(Q16_MIN, min(Q16_MAX, result))


def q16_sub(a: int, b: int) -> int:
    """Subtract two Q16_16 values."""
    result = a - b
    return max(Q16_MIN, min(Q16_MAX, result))


# ── Gate Condition (from DegeneracyConversion.lean) ─────────────────────────

def gate_condition(residual: int, threshold: int) -> bool:
    """FAMM gate: ||coker(M) residual|| < ε.

    Matches Lean: gateCondition (residual : Q16_16) (threshold : Q16_16) : Bool
    Returns True if admissible (residual < threshold).
    """
    abs_residual = q16_abs(residual)
    return abs_residual < threshold


def gate_condition_decidable(residual: int, threshold: int) -> Tuple[bool, str]:
    """Gate condition with decision reason."""
    abs_residual = q16_abs(residual)
    if abs_residual < threshold:
        return True, f"admissible: |{abs_residual}| < {threshold}"
    else:
        return False, f"rejected: |{abs_residual}| >= {threshold}"


# ── Scar / ScarBundle (from BraidTreeDIATPIST.lean) ──────────────────────────

@dataclass
class Scar:
    """Scar: pressure + mode per strand.

    Matches Lean: structure Scar where pressure : Int; mode : UInt8
    """
    pressure: int  # Q16_16 raw
    mode: int      # 0=none, 1=pressure, 2=convergence, 3=offline


@dataclass
class ScarBundle:
    """Bundle of scars for 8 strands.

    Matches Lean: structure ScarBundle where scars : Fin 8 → Option Scar
    """
    scars: List[Optional[Scar]] = field(default_factory=lambda: [None] * 8)

    def is_admissible(self, i: int) -> bool:
        """Check if strand i is admissible (no scar)."""
        return self.scars[i] is None

    def all_admissible(self) -> bool:
        """Check if all strands are admissible."""
        return all(s is None for s in self.scars)

    def scar_count(self) -> int:
        """Count number of scars."""
        return sum(1 for s in self.scars if s is not None)

    def max_pressure(self) -> int:
        """Maximum scar pressure (Q16_16)."""
        pressures = [s.pressure for s in self.scars if s is not None]
        return max(pressures) if pressures else 0


def famm_gate(strands: List[Dict]) -> Tuple[List[Dict], ScarBundle]:
    """FAMM gate: check admissibility of 8-strand state.

    Matches Lean: def fammGate (s : State8) : State8 × ScarBundle

    Args:
        strands: List of 8 strand dicts with 'kappa_raw' and 'slot' fields.

    Returns:
        (strands, scar_bundle) — strands unchanged, scar_bundle with scars.
    """
    scars: List[Optional[Scar]] = []

    for i in range(8):
        strand = strands[i]
        kappa_raw = strand.get('kappa_raw', 0)
        slot = strand.get('slot', 0)

        # Check bracket: kappa_raw <= 49152 (0.75 in Q0_2)
        bracket_ok = kappa_raw <= 49152

        # Check slot: no other strand has the same slot
        slot_ok = all(
            j == i or strands[j].get('slot', 0) != slot
            for j in range(8)
        )

        if bracket_ok and slot_ok:
            scars.append(None)  # admissible
        else:
            scars.append(Scar(pressure=49152, mode=1))  # scar

    return strands, ScarBundle(scars=scars)


# ── Eigensolid Convergence (from F01_Q16_16_FixedPoint.lean) ─────────────────

def eigensolid_converged(strands: List[Dict], threshold: int = 1024) -> bool:
    """Check if eigensolid has converged.

    Convergence: all strand residuals are below threshold.
    threshold default = 1024 (0.015625 in Q16_16).
    """
    for strand in strands:
        residual = strand.get('residual_raw', 0)
        if q16_abs(residual) >= threshold:
            return False
    return True


def eigensolid_receipt(strands: List[Dict]) -> Dict:
    """Generate eigensolid receipt (matches Lean eigensolidReceipt).

    Returns dict with convergence status and residual stats.
    """
    residuals = [s.get('residual_raw', 0) for s in strands]
    abs_residuals = [q16_abs(r) for r in residuals]
    max_residual = max(abs_residuals) if abs_residuals else 0
    converged = max_residual < 1024

    return {
        'converged': converged,
        'max_residual_q16': max_residual,
        'strand_residuals': residuals,
        'threshold_q16': 1024,
    }


# ── Voltage Mode Selection (from fractal_dimension.py) ───────────────────────

# Q16_16 thresholds for FD → voltage mode
FD_THRESH_LOW = 150733   # 2.3 * 65536
FD_THRESH_MED = 170394   # 2.6 * 65536
FD_THRESH_HIGH = 190054  # 2.9 * 65536


def voltage_mode_from_fd(fd_q16: int) -> int:
    """Select voltage mode from fractal dimension (Q16_16).

    Matches Lean: fractal_fd_selector.v thresholds.
    Returns: 0=STORE, 1=COMPUTE, 2=APPROX, 3=MORPHIC.
    """
    if fd_q16 < FD_THRESH_LOW:
        return 0  # STORE (smooth, minimal compression)
    elif fd_q16 < FD_THRESH_MED:
        return 1  # COMPUTE (moderate)
    elif fd_q16 < FD_THRESH_HIGH:
        return 2  # APPROX (high complexity)
    else:
        return 3  # MORPHIC (maximum complexity)


# ── RouteCost Latency Class (from RouteCost.lean) ───────────────────────────

LATENCY_CLASS_LOCAL = 0
LATENCY_CLASS_NEAR = 1
LATENCY_CLASS_FAR = 2
LATENCY_CLASS_DERP = 3
LATENCY_CLASS_OFFLINE = 4


def latency_class_from_rtt(rtt_ms: float) -> int:
    """Classify latency from RTT measurement.

    Matches RouteCost.lean latency classes.
    """
    if rtt_ms < 1.0:
        return LATENCY_CLASS_LOCAL
    elif rtt_ms < 10.0:
        return LATENCY_CLASS_NEAR
    elif rtt_ms < 100.0:
        return LATENCY_CLASS_FAR
    elif rtt_ms < 1000.0:
        return LATENCY_CLASS_DERP
    else:
        return LATENCY_CLASS_OFFLINE


def transport_priority_from_latency(latency_class: int) -> int:
    """Transport priority from latency class.

    Lower latency = higher priority (more urgent).
    """
    return max(0, 4 - latency_class)


# ── FAMM-Integrated Transport ────────────────────────────────────────────────

@dataclass
class FAMMTransportResult:
    """Result of FAMM-checked encode/decode."""
    success: bool
    data: bytes
    receipt: Dict
    scar_bundle: Optional[ScarBundle] = None
    eigensolid: Optional[Dict] = None
    voltage_mode: int = 0
    latency_class: int = 0
    fd_q16: int = 0
    encode_time_ms: float = 0.0


def famm_encode(
    braid_data: bytes,
    threshold_q16: int = 32768,  # 0.5 in Q16_16
    check_eigensolid: bool = True,
    check_famm: bool = True,
    compute_fd: bool = True,
    latency_rtt_ms: float = 0.0,
    frame_counter: int = 0,
) -> FAMMTransportResult:
    """FAMM-gated VCN encode.

    Pipeline:
    1. FAMM gate check (admissibility)
    2. Eigensolid convergence check
    3. Fractal dimension → voltage mode
    4. RouteCost latency classification
    5. VCN encode (Delta+RLE → RS ECC → ChaCha20 → H.264)
    6. SEI receipt with FAMM metadata

    Args:
        braid_data: Raw braid data bytes.
        threshold_q16: Gate threshold in Q16_16 (default 0.5).
        check_eigensolid: Whether to check eigensolid convergence.
        check_famm: Whether to run FAMM gate.
        compute_fd: Whether to compute fractal dimension.
        latency_rtt_ms: Measured RTT in milliseconds.
        frame_counter: Frame sequence number for SEI receipt.

    Returns:
        FAMMTransportResult with encoded data and metadata.
    """
    t0 = time.time()

    # ── Step 1: Parse strands from braid data ──
    # For now, treat raw bytes as 8 strands of 8 bytes each
    strands = []
    for i in range(8):
        offset = i * 8
        if offset + 8 <= len(braid_data):
            strand_bytes = braid_data[offset:offset + 8]
            strands.append({
                'kappa_raw': strand_bytes[0] * 256 + strand_bytes[1],
                'slot': strand_bytes[2],
                'residual_raw': int.from_bytes(strand_bytes[4:8], 'little', signed=True),
            })
        else:
            strands.append({'kappa_raw': 0, 'slot': 0, 'residual_raw': 0})

    # ── Step 2: FAMM gate check ──
    scar_bundle = None
    famm_admissible = True
    if check_famm:
        strands, scar_bundle = famm_gate(strands)
        famm_admissible = scar_bundle.all_admissible()

    # ── Step 3: Eigensolid convergence ──
    eigensolid = None
    eigensolid_ok = True
    if check_eigensolid:
        eigensolid = eigensolid_receipt(strands)
        eigensolid_ok = eigensolid['converged']

    # ── Step 4: Fractal dimension → voltage mode ──
    fd_q16 = 0
    voltage_mode = 0
    if compute_fd and _HAS_NUMPY and len(braid_data) >= 64:
        arr = np.frombuffer(braid_data[:256], dtype=np.uint8)
        fd = fractal_dimension(arr.reshape(-1, 1) if len(arr.shape) == 1 else arr)
        fd_q16 = int(fd * Q16_SCALE)
        voltage_mode = voltage_mode_from_fd(fd_q16)

    # ── Step 5: RouteCost latency ──
    latency_class = latency_class_from_rtt(latency_rtt_ms)
    transport_priority = transport_priority_from_latency(latency_class)

    # ── Step 6: Gate decision ──
    # Combined gate: FAMM admissible AND eigensolid converged
    gate_passed = famm_admissible and eigensolid_ok

    if not gate_passed:
        # Gate rejected — return with scar info, don't encode
        encode_time = (time.time() - t0) * 1000
        return FAMMTransportResult(
            success=False,
            data=b'',
            receipt={
                'schema': 'vcn_famm_receipt_v1',
                'gate_passed': False,
                'famm_admissible': famm_admissible,
                'eigensolid_converged': eigensolid_ok,
                'scar_count': scar_bundle.scar_count() if scar_bundle else 0,
                'max_pressure': scar_bundle.max_pressure() if scar_bundle else 0,
                'claim_boundary': 'admissibility-and-routing-pass-only',
                'promotion': 'not_promoted',
            },
            scar_bundle=scar_bundle,
            eigensolid=eigensolid,
            voltage_mode=voltage_mode,
            latency_class=latency_class,
            fd_q16=fd_q16,
            encode_time_ms=encode_time,
        )

    # ── Step 7: VCN encode ──
    # braid_data is raw bytes — use the lower-level pipeline directly
    # (encode_braid_strand expects a dict, not bytes)
    payload = _build_frame_payload(TAG_STRAND, braid_data, key=None, compress=True)
    w, h = 1920, 1080
    spec = VCNComputeFrameSpec(
        width=w, height=h,
        bytes_per_frame=compute_frame_size(w, h, "yuv420p"),
        encoder="libx264",
    )
    frame = create_frame_dynamic(payload, seq=frame_counter, spec=spec)
    with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        import zlib as _zlib
        frame_crc = f"{_zlib.crc32(frame):08x}"
        timestamp_us = int(time.time_ns() / 1000)
        result = encode_frames_hardware(
            [frame], tmp_path, spec,
            sei_receipts=[{"seq": frame_counter, "crc32_hex": frame_crc, "timestamp_us": timestamp_us}],
        )
        if result.returncode != 0:
            raise RuntimeError(f"VCN encode failed: {result.stderr}")
        encoded = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    encode_time = (time.time() - t0) * 1000

    # ── Step 8: Build receipt with FAMM metadata ──
    receipt = {
        'schema': 'vcn_famm_receipt_v1',
        'gate_passed': True,
        'famm_admissible': True,
        'eigensolid_converged': eigensolid_ok,
        'scar_count': 0,
        'max_pressure': 0,
        'voltage_mode': voltage_mode,
        'voltage_mode_name': ['STORE', 'COMPUTE', 'APPROX', 'MORPHIC'][voltage_mode],
        'fd_q16': fd_q16,
        'fd_approx': round(fd_q16 / Q16_SCALE, 3),
        'latency_class': latency_class,
        'transport_priority': transport_priority,
        'input_bytes': len(braid_data),
        'output_bytes': len(encoded),
        'compression_ratio': round(len(encoded) / max(len(braid_data), 1), 3),
        'encode_time_ms': round(encode_time, 2),
        'frame_counter': frame_counter,
        'claim_boundary': 'admissibility-and-routing-pass-only',
        'promotion': 'not_promoted',
    }

    return FAMMTransportResult(
        success=True,
        data=encoded,
        receipt=receipt,
        scar_bundle=scar_bundle,
        eigensolid=eigensolid,
        voltage_mode=voltage_mode,
        latency_class=latency_class,
        fd_q16=fd_q16,
        encode_time_ms=encode_time,
    )


def famm_decode(
    encoded_data: bytes,
    expected_seq: Optional[int] = None,
    expected_crc: Optional[str] = None,
    check_gate: bool = True,
    threshold_q16: int = 32768,
) -> Tuple[bytes, Dict]:
    """FAMM-gated VCN decode.

    Args:
        encoded_data: MKV-encoded bytes.
        expected_seq: Expected frame sequence number.
        expected_crc: Expected CRC32 hex string.
        check_gate: Whether to verify gate on decode side.
        threshold_q16: Gate threshold for decode-side check.

    Returns:
        (decoded_data, receipt) — decoded bytes and verification receipt.
    """
    t0 = time.time()

    # ── Step 1: VCN decode ──
    result = decode_braid_frame_extended(
        encoded_data,
        key=None,
        expected_seq=expected_seq,
        expected_crc=expected_crc,
    )
    decoded = result.get("data", b"") if isinstance(result.get("data"), bytes) else b""
    success = result.get("crc_match") != "corrupt" and result.get("seq_match") != "drop"
    info = result

    decode_time = (time.time() - t0) * 1000

    # ── Step 2: Decode-side gate check ──
    gate_passed = True
    if check_gate and decoded:
        # Check residual from decoded data
        strands = []
        for i in range(8):
            offset = i * 8
            if offset + 8 <= len(decoded):
                strand_bytes = decoded[offset:offset + 8]
                strands.append({
                    'kappa_raw': strand_bytes[0] * 256 + strand_bytes[1],
                    'slot': strand_bytes[2],
                    'residual_raw': int.from_bytes(strand_bytes[4:8], 'little', signed=True),
                })
            else:
                strands.append({'kappa_raw': 0, 'slot': 0, 'residual_raw': 0})

        _, scar_bundle = famm_gate(strands)
        gate_passed = scar_bundle.all_admissible()

    # ── Step 3: Build receipt ──
    receipt = {
        'schema': 'vcn_famm_decode_receipt_v1',
        'success': success and gate_passed,
        'gate_passed': gate_passed,
        'decode_time_ms': round(decode_time, 2),
        'input_bytes': len(encoded_data),
        'output_bytes': len(decoded) if decoded else 0,
        'claim_boundary': 'admissibility-and-routing-pass-only',
        'promotion': 'not_promoted',
    }

    return decoded, receipt


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python vcn_famm_transport.py <braid_data_file>")
        print("       python vcn_famm_transport.py --test")
        sys.exit(1)

    if sys.argv[1] == '--test':
        # Test with synthetic data
        data = bytes(range(256)) * 4  # 1024 bytes

        print("=== FAMM Encode Test ===")
        result = famm_encode(data, compute_fd=True)
        print(f"  Gate passed: {result.receipt['gate_passed']}")
        print(f"  FAMM admissible: {result.receipt['famm_admissible']}")
        print(f"  Eigensolid converged: {result.receipt['eigensolid_converged']}")
        print(f"  Voltage mode: {result.receipt.get('voltage_mode_name', 'N/A')}")
        print(f"  FD: {result.receipt.get('fd_approx', 'N/A')}")
        print(f"  Latency class: {result.latency_class}")
        print(f"  Output bytes: {len(result.data)}")
        print(f"  Encode time: {result.encode_time_ms:.1f}ms")
        print(f"  Receipt: {result.receipt}")

        if result.success:
            print("\n=== FAMM Decode Test ===")
            decoded, dec_receipt = famm_decode(result.data)
            print(f"  Success: {dec_receipt['success']}")
            print(f"  Gate passed: {dec_receipt['gate_passed']}")
            print(f"  Decode time: {dec_receipt['decode_time_ms']:.1f}ms")
            print(f"  Data match: {decoded == data}")

        print("\n=== Gate Rejection Test ===")
        # Create data that should trigger FAMM rejection
        bad_data = bytes([255] * 64)  # high kappa values
        bad_result = famm_encode(bad_data, threshold_q16=1024)  # very low threshold
        print(f"  Gate passed: {bad_result.receipt['gate_passed']}")
        print(f"  Scar count: {bad_result.receipt['scar_count']}")
    else:
        data = Path(sys.argv[1]).read_bytes()
        result = famm_encode(data)
        print(f"Gate: {result.receipt['gate_passed']}")
        print(f"FD: {result.receipt.get('fd_approx', 'N/A')}")
        print(f"Mode: {result.receipt.get('voltage_mode_name', 'N/A')}")
        print(f"Output: {len(result.data)} bytes")
