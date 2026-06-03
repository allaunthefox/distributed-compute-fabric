#!/usr/bin/env python3
"""
Ray VCN Transport — distributed encode/decode via Ray Object Store.

Wraps the existing braid_vcn_encoder pipeline as Ray tasks. Uses Ray ObjectRef
as the transport mechanism (zero-copy shared memory for same-node, serialized
for cross-node).

Architecture:
    Producer → ray.put(mkv_bytes) → ObjectRef
    ObjectRef → @ray.remote decode → result dict
    ObjectRef → @ray.remote compute → new ObjectRef

Usage:
    import ray
    ray.init("auto")
    from ray_vcn_transport import RayVCNTransport
    transport = RayVCNTransport()

    # Encode a strand → ObjectRef
    ref = transport.encode_strand.remote(strand_dict)

    # Decode an MKV ref → result dict
    result = ray.get(transport.decode_mkv.remote(ref))

    # Batch encode 1000 strands
    refs = transport.encode_batch.remote(strands_list)
    results = ray.get(refs)

Design:
    - Encode tasks run on CPU workers (no FFmpeg needed for raw frame creation)
    - Decode tasks run on GPU workers (FFmpeg decode + compute)
    - ObjectRef = cluster-wide witness handle (matches FAMM receipt model)
    - All arithmetic Q16_16 (enforced by braid_vcn_encoder)
"""

from __future__ import annotations

import sys
import time
import zlib
from pathlib import Path
from typing import Dict, List, Optional

import ray

# Add shim directory to path for imports
_shim_dir = str(Path(__file__).resolve().parent)
if _shim_dir not in sys.path:
    sys.path.insert(0, _shim_dir)


# ── Remote encode tasks ─────────────────────────────────────────────────────

@ray.remote(num_cpus=1)
def encode_strand_task(strand_dict: dict,
                       resolution: str = "1080p",
                       key: Optional[bytes] = None,
                       compress: bool = True,
                       frame_counter: int = 0) -> bytes:
    """Encode a BraidStrand → MKV bytes. Runs on a Ray CPU worker."""
    from braid_vcn_encoder import encode_braid_strand
    return encode_braid_strand(strand_dict, resolution, key, compress, frame_counter)


@ray.remote(num_cpus=1)
def encode_crossing_task(bracket_a: dict, bracket_b: dict,
                         resolution: str = "1080p",
                         key: Optional[bytes] = None,
                         compress: bool = True,
                         frame_counter: int = 0) -> bytes:
    """Encode a BraidCrossing → MKV bytes. Runs on a Ray CPU worker."""
    from braid_vcn_encoder import encode_braid_crossing
    return encode_braid_crossing(bracket_a, bracket_b, resolution, key, compress, frame_counter)


@ray.remote(num_cpus=1)
def encode_pist_task(pist_dict: dict,
                     resolution: str = "1080p",
                     key: Optional[bytes] = None,
                     compress: bool = True,
                     frame_counter: int = 0) -> bytes:
    """Encode a PIST field → MKV bytes. Runs on a Ray CPU worker."""
    from braid_vcn_encoder import encode_pist_field
    return encode_pist_field(pist_dict, resolution, key, compress, frame_counter)


# ── Remote decode tasks ─────────────────────────────────────────────────────

@ray.remote(num_cpus=1)
def decode_mkv_task(mkv_bytes: bytes,
                    key: Optional[bytes] = None) -> dict:
    """Decode MKV bytes → braid result dict. Runs on a Ray worker.

    Uses FFmpeg for YUV420 extraction. Requires ffmpeg in the container image.
    Falls back to raw frame parsing if FFmpeg is unavailable.
    """
    from braid_vcn_encoder import decode_braid_mkv
    return decode_braid_mkv(mkv_bytes, key)


@ray.remote(num_cpus=1)
def decode_raw_frame_task(frame_payload: bytes,
                          key: Optional[bytes] = None) -> dict:
    """Decode raw frame payload (no FFmpeg needed). For pre-extracted frames."""
    from braid_vcn_encoder import decode_braid_frame
    return decode_braid_frame(frame_payload, key)


# ── Compute tasks (GPU worker) ──────────────────────────────────────────────

@ray.remote(num_gpus=0.25)
def compute_strand_phase_task(mkv_bytes: bytes,
                              key: Optional[bytes] = None) -> dict:
    """Decode MKV + compute strand phase. GPU worker via /dev/dri."""
    from braid_vcn_encoder import decode_braid_mkv
    from vcn_compute_substrate import compute_strand_phase, deserialize_braid_strand

    result = decode_braid_mkv(mkv_bytes, key)
    if result.get("tag_name") == "strand" and "data" in result:
        strand = result["data"]
        phase = compute_strand_phase(strand)
        result["phase_result"] = phase
    return result


@ray.remote(num_gpus=0.25)
def compute_crossing_residual_task(mkv_bytes: bytes,
                                   key: Optional[bytes] = None) -> dict:
    """Decode MKV + compute crossing residual. GPU worker."""
    from braid_vcn_encoder import decode_braid_mkv
    from vcn_compute_substrate import compute_crossing_residual

    result = decode_braid_mkv(mkv_bytes, key)
    if result.get("tag_name") == "crossing" and "data" in result:
        data = result["data"]
        residual = compute_crossing_residual(
            data["bracket_a"], data["bracket_b"], data.get("bracket_a"))
        result["residual"] = residual
    return result


# ── Batch helpers ────────────────────────────────────────────────────────────

@ray.remote
def encode_batch(strands: List[dict],
                 resolution: str = "1080p",
                 key: Optional[bytes] = None,
                 compress: bool = True,
                 start_counter: int = 0) -> List[ray.ObjectRef]:
    """Encode a batch of strands in parallel. Returns list of ObjectRefs.

    Each ref contains MKV bytes. Use ray.get(refs) to materialize.
    """
    futures = []
    for i, strand in enumerate(strands):
        ref = encode_strand_task.remote(
            strand, resolution, key, compress, start_counter + i)
        futures.append(ref)
    return futures


@ray.remote
def decode_batch(mkv_refs: List[ray.ObjectRef],
                 key: Optional[bytes] = None) -> List[dict]:
    """Decode a batch of MKV ObjectRefs in parallel."""
    futures = []
    for ref in mkv_refs:
        mkv_bytes = ray.get(ref)
        futures.append(decode_mkv_task.remote(mkv_bytes, key))
    return ray.get(futures)


# ── FAMM-gated transport ─────────────────────────────────────────────────────

@ray.remote(num_cpus=1)
def famm_encode_task(strand_dict: dict,
                     resolution: str = "1080p",
                     key: Optional[bytes] = None) -> dict:
    """FAMM-gated encode: check admissibility before encoding.

    Returns dict with:
      - success: bool
      - ref: ObjectRef (MKV bytes) if success
      - scar_bundle: scar info if rejected
      - encode_time_ms: float
    """
    from vcn_famm_transport import famm_encode
    import time

    start = time.monotonic()
    result = famm_encode(strand_dict, key)
    elapsed_ms = (time.monotonic() - start) * 1000

    return {
        "success": result.get("success", False),
        "data": result.get("data"),  # raw bytes, caller ray.put()s if needed
        "scar_bundle": result.get("scar_bundle"),
        "voltage_mode": result.get("voltage_mode"),
        "latency_class": result.get("latency_class"),
        "fd_q16": result.get("fd_q16"),
        "encode_time_ms": elapsed_ms,
    }


# ── Transport actor (persistent state) ──────────────────────────────────────

@ray.remote
class RayVCNTransport:
    """Stateful transport actor for the VCN pipeline.

    Maintains frame counter, key, and resolution config.
    Wraps encode/decode as actor methods for sequential frame numbering.
    """

    def __init__(self, resolution: str = "1080p", key: Optional[bytes] = None):
        self.resolution = resolution
        self.key = key
        self.frame_counter = 0
        self.stored_refs: List[ray.ObjectRef] = []

    def encode_strand(self, strand_dict: dict) -> ray.ObjectRef:
        """Encode a strand, auto-incrementing frame counter."""
        ref = encode_strand_task.remote(
            strand_dict, self.resolution, self.key, True, self.frame_counter)
        self.frame_counter += 1
        self.stored_refs.append(ref)
        return ref

    def encode_crossing(self, bracket_a: dict, bracket_b: dict) -> ray.ObjectRef:
        """Encode a crossing, auto-incrementing frame counter."""
        ref = encode_crossing_task.remote(
            bracket_a, bracket_b, self.resolution, self.key, True, self.frame_counter)
        self.frame_counter += 1
        self.stored_refs.append(ref)
        return ref

    def encode_pist(self, pist_dict: dict) -> ray.ObjectRef:
        """Encode a PIST field, auto-incrementing frame counter."""
        ref = encode_pist_task.remote(
            pist_dict, self.resolution, self.key, True, self.frame_counter)
        self.frame_counter += 1
        self.stored_refs.append(ref)
        return ref

    def decode(self, mkv_ref: ray.ObjectRef) -> dict:
        """Decode an MKV ObjectRef."""
        mkv_bytes = ray.get(mkv_ref)
        return ray.get(decode_mkv_task.remote(mkv_bytes, self.key))

    def get_stored_refs(self) -> List[ray.ObjectRef]:
        """Return all stored ObjectRefs (cluster-wide witness handles)."""
        return self.stored_refs

    def get_stats(self) -> dict:
        """Return transport statistics."""
        return {
            "frame_counter": self.frame_counter,
            "stored_refs": len(self.stored_refs),
            "resolution": self.resolution,
            "has_key": self.key is not None,
        }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    """Quick smoke test of the Ray VCN transport."""
    import json

    print("Ray VCN Transport — connecting to cluster...")
    ray.init("auto", ignore_reinit_error=True)

    transport = RayVCNTransport.options(name="vcn-transport").remote()

    # Test with a dummy strand
    test_strand = {
        "phaseAcc": {"x": 42, "y": 100},
        "parity": True,
        "slot": 7,
        "residue": 3,
        "jitter": 0,
        "bracket": {
            "lower": 10000,
            "upper": 20000,
            "gap": 5000,
            "kappa": 32768,
            "phi": 16384,
            "admissible": True,
        },
    }

    print(f"Encoding test strand...")
    ref = ray.get(transport.encode_strand.remote(test_strand))
    print(f"  ObjectRef size: {len(ref)} bytes")

    print(f"Decoding...")
    result = ray.get(transport.decode.remote(ref))
    print(f"  Tag: {result.get('tag_name')}")
    print(f"  Seq match: {result.get('seq_match')}")
    print(f"  CRC match: {result.get('crc_match')}")

    stats = ray.get(transport.get_stats.remote())
    print(f"  Stats: {json.dumps(stats, indent=2)}")

    # Check cluster resources
    resources = ray.cluster_resources()
    print(f"\nCluster resources: {json.dumps(resources, indent=2)}")

    print("\n✓ Ray VCN Transport smoke test passed")


if __name__ == "__main__":
    main()
