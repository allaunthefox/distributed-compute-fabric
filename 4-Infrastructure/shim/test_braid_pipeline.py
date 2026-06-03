#!/usr/bin/env python3
"""
Test suite for the Braid VCN Encoder Pipeline.

Tests:
  1. Q16_16 LUT generation and frame encoding/decoding round-trip
  2. Delta+RLE compression round-trip
  3. Reed-Solomon error correction round-trip
  4. ChaCha20 encryption round-trip
  5. Full braid strand encode → decode pipeline (without VCN hardware encoding)
  6. Sidon slot assignment and verification
  7. Soliton search convergence
  8. QUBO optimization
"""

from __future__ import annotations

import sys
import struct
import hashlib
from pathlib import Path

# Ensure shim directory is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import q16_lut_vcn
import braid_vcn_encoder as bve
import braid_search as bs

Q16_ONE = 0x00010000

passed = 0
failed = 0


def report(name: str, ok: bool, detail: str = ""):
    global passed, failed
    status = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        failed += 1
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{status}] {name}{suffix}")


# ── 1. Q16_16 LUT generation ────────────────────────────────────────────────

def test_lut_generation():
    print("\n── Q16_16 LUT Generation ──")

    for op in q16_lut_vcn.SUPPORTED_OPS:
        table = q16_lut_vcn.generate_lut(op)
        report(f"generate_lut('{op}') returns 65536 entries",
               len(table) == 65536, f"got {len(table)}")

    # Spot-check add: 1.0 + 1.0 = 2.0
    # In the 256×256 grid, index for 1.0 is at position 256 (stride=256, so 1.0 = 256*256=65536)
    # Actually stride = Q16_ONE // 256 = 256.  So value 1.0 (65536) is at index 65536/256 = 256.
    add_lut = q16_lut_vcn.generate_lut("add")
    # add(1.0, 1.0) → entry[256*256 + 256] = entry[65792] — but that's > 65535
    # Grid is 256×256, so index i*256+j where a=i*256, b=j*256
    # For a=1.0 (65536): i = 65536/256 = 256 → out of grid range (0..255)
    # So 1.0 is not sampled; let's check a simpler case.
    # add(0, 0) → entry[0] should be 0
    report("add(0, 0) = 0", add_lut[0] == 0)
    # add(stride, 0) should equal stride
    report("add(stride, 0) = stride",
           add_lut[1] == q16_lut_vcn.SAMPLE_STRIDE)

    # neg(0) should be 0
    neg_lut = q16_lut_vcn.generate_lut("neg")
    report("neg(0) = 0", neg_lut[0] == 0)

    # abs of a negative value should be positive
    abs_lut = q16_lut_vcn.generate_lut("abs")
    report("abs LUT generated", len(abs_lut) == 65536)


def test_lut_serialization():
    print("\n── LUT Serialization ──")
    table = q16_lut_vcn.generate_lut("sub")
    data = q16_lut_vcn.serialize_lut(table)
    report("serialize_lut size = 256 KiB", len(data) == 65536 * 4)
    recovered = q16_lut_vcn.deserialize_lut(data)
    report("deserialize_lut round-trip", recovered == table)


def test_lut_checksum():
    print("\n── LUT Checksum ──")
    table = q16_lut_vcn.generate_lut("mul")
    c1 = q16_lut_vcn.lut_checksum(table)
    c2 = q16_lut_vcn.lut_checksum(table)
    report("checksum is deterministic", c1 == c2)
    report("checksum is 64 hex chars", len(c1) == 64)

    table2 = q16_lut_vcn.generate_lut("div")
    report("different ops have different checksums",
           q16_lut_vcn.lut_checksum(table) != q16_lut_vcn.lut_checksum(table2))


# ── 2. Delta+RLE compression ────────────────────────────────────────────────

def test_delta_rle():
    print("\n── Delta+RLE Compression ──")

    # Simple data
    data = bytes(range(256))
    compressed = bve.delta_rle_encode(data)
    decompressed = bve.delta_rle_decode(compressed)
    report("delta+RLE round-trip (range 0-255)", decompressed == data)

    # Repetitive data (should compress well)
    data2 = bytes([42] * 1000)
    c2 = bve.delta_rle_encode(data2)
    d2 = bve.delta_rle_decode(c2)
    report("delta+RLE round-trip (repetitive)", d2 == data2)
    report("RLE compression ratio > 10x", len(c2) < len(data2) // 10,
           f"{len(data2)}→{len(c2)}")

    # Empty data
    empty = b""
    ce = bve.delta_rle_encode(empty)
    de = bve.delta_rle_decode(ce)
    report("delta+RLE round-trip (empty)", de == empty)

    # Random-ish data
    data3 = bytes(hashlib.sha256(i.to_bytes(4, "little")).digest()[0]
                  for i in range(500))
    c3 = bve.delta_rle_encode(data3)
    d3 = bve.delta_rle_decode(c3)
    report("delta+RLE round-trip (hash-derived)", d3 == data3)


# ── 3. Reed-Solomon error correction ────────────────────────────────────────

def test_reed_solomon():
    print("\n── Reed-Solomon ECC ──")
    try:
        import reedsolo
    except ImportError:
        print("  [SKIP] reedsolo not installed")
        return

    data = b"Hello, Braid VCN Encoder! This is a test payload."
    encoded = bve.rs_encode(data)
    report("RS encode appends parity", len(encoded) > len(data))
    report("RS parity size = 32 bytes", len(encoded) - len(data) == 32)

    # No errors
    decoded = bve.rs_decode(encoded)
    report("RS round-trip (no errors)", decoded == data)

    # Introduce up to 16 symbol errors (RS can correct n/2 = 16)
    corrupted = bytearray(encoded)
    for i in range(16):
        corrupted[i] ^= 0xFF
    decoded2 = bve.rs_decode(bytes(corrupted))
    report("RS corrects 16 symbol errors", decoded2 == data)

    # RS encode/decode on larger data
    import os as _os
    big_data = _os.urandom(1024)
    big_encoded = bve.rs_encode(big_data)
    big_decoded = bve.rs_decode(big_encoded)
    report("RS round-trip (1 KiB)", big_decoded == big_data)


# ── 4. ChaCha20 encryption ──────────────────────────────────────────────────

def test_chacha20():
    print("\n── ChaCha20 Encryption ──")
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    except ImportError:
        print("  [SKIP] cryptography not installed")
        return

    import os as _os
    key = _os.urandom(32)
    plaintext = b"Secret braid crossing data: Q16_16 payload"
    ct, nonce = bve.chacha_encrypt(plaintext, key)
    report("ChaCha20 encrypt produces ciphertext", ct != plaintext)
    report("ChaCha20 nonce is 16 bytes", len(nonce) == 16)

    pt = bve.chacha_decrypt(ct, key, nonce)
    report("ChaCha20 round-trip", pt == plaintext)

    # Wrong key should fail
    wrong_key = _os.urandom(32)
    try:
        bad_pt = bve.chacha_decrypt(ct, wrong_key, nonce)
        report("ChaCha20 wrong key produces different plaintext", bad_pt != plaintext)
    except Exception:
        report("ChaCha20 wrong key raises exception", True)


# ── 5. Braid strand serialization round-trip ─────────────────────────────────

def test_braid_strand_roundtrip():
    print("\n── Braid Strand Serialization ──")

    strand = {
        "phaseAcc": {"x": 0x00030000, "y": 0x00040000},  # 3.0, 4.0
        "parity": True,
        "slot": 42,
        "residue": 0x00018000,  # 1.5
        "jitter": 0x00004000,   # 0.25
        "bracket": {
            "lower": 0x00000000,  # 0.0
            "upper": 0x000A0000,  # 10.0
            "gap": 0x000A0000,
            "kappa": 0x00010000,  # 1.0
            "phi": 0x00008000,    # 0.5
            "admissible": True,
        },
    }

    # Test serialization
    raw = bve._serialize_strand(strand)
    report("strand serialization = 42 bytes", len(raw) == 42)

    recovered = bve._deserialize_strand(raw)
    report("strand round-trip: phaseAcc.x",
           recovered["phaseAcc"]["x"] == strand["phaseAcc"]["x"])
    report("strand round-trip: parity",
           recovered["parity"] == strand["parity"])
    report("strand round-trip: slot",
           recovered["slot"] == strand["slot"])
    report("strand round-trip: bracket.admissible",
           recovered["bracket"]["admissible"] == strand["bracket"]["admissible"])


def test_braid_crossing_serialization():
    print("\n── Braid Crossing Serialization ──")

    bracket_a = {
        "lower": 0, "upper": 0x00050000, "gap": 0x00050000,
        "kappa": 0x00010000, "phi": 0, "admissible": True,
    }
    bracket_b = {
        "lower": 0x00030000, "upper": 0x00080000, "gap": 0x00050000,
        "kappa": 0x00020000, "phi": 0x00010000, "admissible": True,
    }

    raw_a = bve._serialize_bracket(bracket_a)
    raw_b = bve._serialize_bracket(bracket_b)
    report("bracket serialization = 21 bytes each",
           len(raw_a) == 21 and len(raw_b) == 21)

    rec_a = bve._deserialize_bracket(raw_a)
    rec_b = bve._deserialize_bracket(raw_b)
    report("bracket A round-trip", rec_a == bracket_a)
    report("bracket B round-trip", rec_b == bracket_b)


# ── 6. Pipeline encode/decode (without hardware encoding) ───────────────────

def test_pipeline_payload():
    """Test the payload construction and parsing without FFmpeg."""
    print("\n── Pipeline Payload (no FFmpeg) ──")

    import os as _os2
    key = _os2.urandom(32)

    strand = {
        "phaseAcc": {"x": 100, "y": 200},
        "parity": False,
        "slot": 7,
        "residue": 50,
        "jitter": 25,
        "bracket": {
            "lower": 0, "upper": 1000, "gap": 1000,
            "kappa": 100, "phi": 50, "admissible": True,
        },
    }

    serialized = bve._serialize_strand(strand)

    # Build payload with encryption
    payload_enc = bve._build_frame_payload(bve.TAG_STRAND, serialized, key, compress=True)
    report("encrypted payload has nonce prefix",
           len(payload_enc) > len(serialized))

    # Build payload without encryption
    payload_plain = bve._build_frame_payload(bve.TAG_STRAND, serialized, None, compress=True)
    report("plaintext payload is smaller than encrypted",
           len(payload_plain) < len(payload_enc))

    # Decode the encrypted payload
    result = bve.decode_braid_frame(payload_enc, key)
    report("decode encrypted strand: tag = strand",
           result["tag"] == bve.TAG_STRAND)
    report("decode encrypted strand: data matches",
           result["data"]["phaseAcc"]["x"] == 100)
    report("decode encrypted strand: slot matches",
           result["data"]["slot"] == 7)

    # Decode the plaintext payload
    result2 = bve.decode_braid_frame(payload_plain, None)
    report("decode plaintext strand: data matches",
           result2["data"]["parity"] == False)

    # Test PIST field
    import os as _os
    import json as _json
    pist = {"energy": 0x10000, "phase": 0x8000, "label": "test"}

    pist_data = _json.dumps(pist, separators=(",", ":")).encode("utf-8")
    pist_payload = bve._build_frame_payload(bve.TAG_PIST, pist_data, None, compress=True)
    pist_result = bve.decode_braid_frame(pist_payload, None)
    report("PIST field round-trip", pist_result["data"]["label"] == "test")


# ── 7. Sidon Slot Assignment ────────────────────────────────────────────────

def test_sidon():
    print("\n── Sidon Slot Assignment ──")

    slots = bs.assign_sidon_slots(10)
    report("assign_sidon_slots(10) returns 10 slots", len(slots) == 10)
    report("sidon slots are sorted", slots == sorted(slots))
    report("sidon slots are unique", len(set(slots)) == 10)
    report("sidon set is valid", bs.verify_sidon(slots))

    slots20 = bs.assign_sidon_slots(20)
    report("assign_sidon_slots(20) is valid Sidon set", bs.verify_sidon(slots20))

    # Edge cases
    report("assign_sidon_slots(0) = []", bs.assign_sidon_slots(0) == [])
    report("assign_sidon_slots(1) = [1]", bs.assign_sidon_slots(1) == [1])

    # Reproducibility (deterministic — no seed needed for Mian-Chowla)
    s1 = bs.assign_sidon_slots(15)
    s2 = bs.assign_sidon_slots(15)
    report("sidon is deterministic", s1 == s2)

    # Method comparison
    p2 = bs.assign_sidon_slots(8, 'powers_of_2')
    mc = bs.assign_sidon_slots(8, 'greedy_optimal')
    report("Mian-Chowla denser than powers_of_2", max(mc) < max(p2))


# ── 8. Soliton Search ────────────────────────────────────────────────────────

def test_soliton_search():
    print("\n── Soliton Search ──")

    candidates = [
        {"brackets": [{"admissible": True, "gap": 0x50000}, {"admissible": True, "gap": 0x30000}], "admissible": True},
        {"brackets": [{"admissible": False, "gap": 0x10000}, {"admissible": False, "gap": 0x10000}], "admissible": False},
        {"brackets": [{"admissible": True, "gap": 0xA0000}, {"admissible": True, "gap": 0x80000}], "admissible": True},
        {"brackets": [{"admissible": True, "gap": 0x20000}, {"admissible": False, "gap": 0x10000}], "admissible": False},
    ]

    result = bs.soliton_search(target_energy=100.0, candidates=candidates,
                                max_iterations=500, seed=42)
    report("soliton_search returns dict", isinstance(result, dict))
    report("soliton finds best candidate", result["best"] is not None)
    report("soliton best_energy > 0", result["best_energy"] > 0)
    report("soliton iterations > 0", result["iterations"] > 0)
    report("soliton converged or exhausted",
           result["converged"] or result["iterations"] == 500)


# ── 9. QUBO Optimization ────────────────────────────────────────────────────

def test_qubo():
    print("\n── QUBO Optimization ──")

    pairs = [
        ({"admissible": True, "gap": 0x50000, "lower": 0, "upper": 0x50000},
         {"admissible": True, "gap": 0x30000, "lower": 0, "upper": 0x30000}),
        ({"admissible": True, "gap": 0x80000, "lower": 0x10000, "upper": 0x90000},
         {"admissible": True, "gap": 0x40000, "lower": 0, "upper": 0x40000}),
        ({"admissible": False, "gap": 0x10000, "lower": 0, "upper": 0x10000},
         {"admissible": False, "gap": 0x10000, "lower": 0, "upper": 0x10000}),
    ]

    result = bs.qubo_optimize(pairs, max_iterations=2000, seed=42)
    report("qubo_optimize returns dict", isinstance(result, dict))
    report("qubo selection length = 3", len(result["selection"]) == 3)
    report("qubo selection is binary",
           all(b in (0, 1) for b in result["selection"]))
    report("qubo has energy", isinstance(result["energy"], float))


def test_find_optimal_crossing():
    print("\n── find_optimal_crossing ──")

    brackets = [
        {"lower": 0, "upper": 0x50000, "gap": 0x50000, "kappa": 0x10000,
         "phi": 0x8000, "admissible": True},
        {"lower": 0x20000, "upper": 0x70000, "gap": 0x50000, "kappa": 0x10000,
         "phi": 0x8000, "admissible": True},
        {"lower": 0x60000, "upper": 0xB0000, "gap": 0x50000, "kappa": 0x20000,
         "phi": 0x10000, "admissible": False},
    ]

    result = bs.find_optimal_crossing(brackets, max_iterations=200)
    report("find_optimal_crossing returns dict", isinstance(result, dict))
    report("has qubo_result", "qubo_result" in result)
    report("has soliton_result", "soliton_result" in result)
    report("has optimal_pairs", "optimal_pairs" in result)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    import os as _os_main  # noqa: F811 — needed for RS/ChaCha tests

    print("=" * 60)
    print("Braid VCN Encoder Pipeline — Test Suite")
    print("=" * 60)

    test_lut_generation()
    test_lut_serialization()
    test_lut_checksum()
    test_delta_rle()
    test_reed_solomon()
    test_chacha20()
    test_braid_strand_roundtrip()
    test_braid_crossing_serialization()
    test_pipeline_payload()
    test_sidon()
    test_soliton_search()
    test_qubo()
    test_find_optimal_crossing()

    print("\n" + "=" * 60)
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
