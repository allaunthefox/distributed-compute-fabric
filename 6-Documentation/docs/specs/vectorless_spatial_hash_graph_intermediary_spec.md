# Vectorless Spatial Hash Graph Intermediary Specification

**Purpose:** Implement a hardware-native graph intermediary layer for H.264-style database compression using vectorless spatial hash indexing (LyteNyte architecture).

**Date:** 2026-06-02
**Status:** Implementation Draft
**Dependencies:**

- `Semantics.PIST.Spectral` (spectral analysis)
- `Semantics.BraidDiatCodec` (codec bit-packing)
- `virtio_net_compute_fabric_spec.md` (hardware acceleration)
- LyteNyte spatial hash dashboard (reference implementation)

---

## 1. Architecture Overview

### 1.1 Design Principles

1. **Vectorless**: No embedding models, no vector similarity search
2. **O(1) Access**: Spatial hash provides constant-time cell lookup
3. **Hardware-Native**: 2-bit voltage modes fit in ASIC registers
4. **Graph-Native**: Preserves sparsity and topological relationships
5. **H.264 Compatible**: Maps directly to I/P/B frames, DCT, quantization

### 1.2 Data Flow Pipeline

```text
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: Relational Input                                       │
│ ┌──────────────────┐                                          │
│ │ users table      │                                          │
│ │ (1M rows, 50 cols)│  ───────┐                                │
│ └──────────────────┘         │                                │
│                              ▼                                │
│ Layer 2: Spatial Hash Intermediary (O(1))                      │
│ ┌──────────────────────────────────────────────────────────┐  │
│ │ 16×16×16 = 4096 cells                                    │  │
│ │ Each cell: (coord, voltage_mode, density, row_ids)      │  │
│ │ Voltage modes: STORE(00), COMPUTE(01), APPROX(10), MORPHIC(11)│  │
│ └──────────────────────────────────────────────────────────┘  │
│                              │                                │
│                              ▼                                │
│ Layer 3: Graph Construction (from spatial neighbors)          │
│ ┌──────────────────────────────────────────────────────────┐  │
│ │ Adjacency graph from 26-neighbor connectivity           │  │
│ │ Edge weights = spatial similarity (density correlation)  │  │
│ └──────────────────────────────────────────────────────────┘  │
│                              │                                │
│                              ▼                                │
│ Layer 4: Spectral Transform (PIST)                             │
│ ┌──────────────────────────────────────────────────────────┐  │
│ │ Graph → Adjacency Matrix → Laplacian → Eigenvalues       │  │
│ │ Low freq = I-frame, High freq = P-frame residuals        │  │
│ └──────────────────────────────────────────────────────────┘  │
│                              │                                │
│                              ▼                                │
│ Layer 5: H.264 Codec Encoding                                 │
│ ┌──────────────────────────────────────────────────────────┐  │
│ │ Macroblocks = spatial cells                              │  │
│ │ Quantization = voltage mode class                        │  │
│ │ DCT coefficients = density values                         │  │
│ │ Motion vectors = neighbor deltas                         │  │
│ └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Data Structures

### 2.1 Spatial Hash Cell

```python
# 4-Infrastructure/shim/vectorless_spatial_hash_backend.py

from dataclasses import dataclass
from typing import List, Tuple, Optional
import numpy as np

@dataclass
class SpatialCoord:
    """16×16×16 spatial coordinate (4 bits per axis)."""
    x: int  # 0-15 (4 bits)
    y: int  # 0-15 (4 bits)  
    z: int  # 0-15 (4 bits)
    
    def to_linear(self) -> int:
        """Convert to linear index (0-4095)."""
        return self.x + 16 * (self.y + 16 * self.z)
    
    @staticmethod
    def from_linear(idx: int) -> 'SpatialCoord':
        """Convert from linear index (0-4095)."""
        z = idx // 256
        y = (idx % 256) // 16
        x = idx % 16
        return SpatialCoord(x, y, z)

@dataclass
class SpatialCell:
    """Single cell in 16×16×16 spatial hash grid."""
    coord: SpatialCoord
    voltage_mode: int  # 2 bits: 0=STORE, 1=COMPUTE, 2=APPROX, 3=MORPHIC
    density: int  # 0-255 (Q0_16 range)
    row_ids: List[int]  # Multiple rows can hash to same cell
    table_name: str  # Source table name
    write_count: int = 0
    read_count: int = 0
    delta_variance: float = 0.0
    last_access_ts: float = 0.0
    
    def to_packed(self) -> int:
        """Pack to 64-bit integer for hardware transmission."""
        packed = 0
        packed |= (self.coord.x & 0xF) << 0
        packed |= (self.coord.y & 0xF) << 4
        packed |= (self.coord.z & 0xF) << 8
        packed |= (self.voltage_mode & 0x3) << 12
        packed |= (self.density & 0xFF) << 16
        return packed
    
    @staticmethod
    def from_packed(packed: int) -> 'SpatialCell':
        """Unpack from 64-bit integer."""
        x = (packed >> 0) & 0xF
        y = (packed >> 4) & 0xF
        z = (packed >> 8) & 0xF
        mode = (packed >> 12) & 0x3
        density = (packed >> 16) & 0xFF
        return SpatialCell(
            coord=SpatialCoord(x, y, z),
            voltage_mode=mode,
            density=density,
            row_ids=[],
            table_name=""
        )
```

### 2.2 Voltage Mode Classification

```python
VOLTAGE_MODES = {
    0: "STORE",    # I-frame: exact storage, no quantization
    1: "COMPUTE",  # P-frame: motion vectors + residuals  
    2: "APPROX",   # Quantized: lossy approximation
    3: "MORPHIC"   # B-frame: bidirectional prediction
}

def classify_voltage_mode(
    write_count: int,
    read_count: int,
    delta_variance: float,
    threshold: float = 0.1
) -> int:
    """JIT-classify cell into voltage mode based on access pattern.
    
    This is a pure function suitable for JIT compilation (numba).
    """
    if write_count == 0:
        return 0  # STORE: never written → I-frame
    elif read_count / max(1, write_count) > 10:
        return 1  # COMPUTE: read-heavy → P-frame
    elif delta_variance < threshold:
        return 2  # APPROX: stable → quantized
    else:
        return 3  # MORPHIC: volatile → B-frame
```

### 2.3 Spatial Hash Backend

```python
class VectorlessSpatialHashBackend:
    """O(1) spatial hash backend replacing traditional graph databases."""
    
    def __init__(self):
        # 16×16×16 = 4096 cells
        self.hash_grid: np.ndarray = np.empty((16, 16, 16), dtype=object)
        for x in range(16):
            for y in range(16):
                for z in range(16):
                    self.hash_grid[x, y, z] = SpatialCell(
                        coord=SpatialCoord(x, y, z),
                        voltage_mode=0,
                        density=0,
                        row_ids=[],
                        table_name=""
                    )
        
        # SipHash24 key for deterministic hashing
        self.hash_key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    
    def _siphash24(self, data: bytes) -> int:
        """SipHash24 for deterministic spatial coordinate mapping.
        
        Collision-resistant for 4096-cell space.
        """
        # Simplified SipHash24 (production: use cryptography library)
        k0 = int.from_bytes(self.hash_key[0:8], 'little')
        k1 = int.from_bytes(self.hash_key[8:16], 'little')
        
        # Initialization
        v0 = 0x736f6d6570736575 ^ k0
        v1 = 0x646f72616e646f6d ^ k1
        v2 = 0x6c7967656e657261 ^ k0
        v3 = 0x7465646279746575 ^ k1
        
        # Compression (simplified)
        for i in range(0, len(data), 8):
            m = int.from_bytes(data[i:i+8].ljust(8, b'\x00'), 'little')
            v3 ^= m
            # ... full SipHash24 round omitted for brevity
        
        # Finalization
        v2 ^= 0xff
        # ... finalization rounds omitted
        
        return (v0 ^ v1 ^ v2 ^ v3) & 0xFFFFFFFFFFFFFFFF
    
    def table_to_spatial_coord(self, table_name: str, row_id: int) -> SpatialCoord:
        """Map (table_name, row_id) to deterministic spatial coordinate."""
        hash_input = f"{table_name}:{row_id}".encode()
        hash_val = self._siphash24(hash_input)
        
        x = hash_val & 0xF
        y = (hash_val >> 4) & 0xF
        z = (hash_val >> 8) & 0xF
        
        return SpatialCoord(x, y, z)
    
    def add_row(self, table_name: str, row_id: int, density: int = 0):
        """Add a row to the spatial hash grid."""
        coord = self.table_to_spatial_coord(table_name, row_id)
        cell = self.hash_grid[coord.x, coord.y, coord.z]
        
        cell.row_ids.append(row_id)
        cell.table_name = table_name
        cell.density = density
        cell.write_count += 1
        cell.last_access_ts = time.time()
        
        # JIT-classify voltage mode
        cell.voltage_mode = classify_voltage_mode(
            cell.write_count,
            cell.read_count,
            cell.delta_variance
        )
    
    def get_cell(self, table_name: str, row_id: int) -> SpatialCell:
        """O(1) cell lookup."""
        coord = self.table_to_spatial_coord(table_name, row_id)
        cell = self.hash_grid[coord.x, coord.y, coord.z]
        cell.read_count += 1
        cell.last_access_ts = time.time()
        
        # Reclassify mode on access
        cell.voltage_mode = classify_voltage_mode(
            cell.write_count,
            cell.read_count,
            cell.delta_variance
        )
        
        return cell
    
    def get_neighbors(self, table_name: str, row_id: int) -> List[SpatialCell]:
        """Get 26 neighboring cells (3D Moore neighborhood)."""
        coord = self.table_to_spatial_coord(table_name, row_id)
        neighbors = []
        
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                for dz in [-1, 0, 1]:
                    if dx == 0 and dy == 0 and dz == 0:
                        continue
                    
                    nx, ny, nz = coord.x + dx, coord.y + dy, coord.z + dz
                    if 0 <= nx < 16 and 0 <= ny < 16 and 0 <= nz < 16:
                        neighbors.append(self.hash_grid[nx, ny, nz])
        
        return neighbors
    
    def compute_density(self, table_name: str, row_id: int, value: float) -> int:
        """Compute density (0-255) from value using Q0_16 scaling.
        
        Maps value range to 0-255 for DCT coefficient proxy.
        """
        # Clamp to 0-255 range
        scaled = max(0, min(255, int(value * 255)))
        return scaled
    
    def update_delta_variance(self, table_name: str, row_id: int, delta: float):
        """Update running variance of deltas for mode classification."""
        coord = self.table_to_spatial_coord(table_name, row_id)
        cell = self.hash_grid[coord.x, coord.y, coord.z]
        
        # Online variance update (Welford's algorithm)
        n = cell.write_count
        if n == 1:
            cell.mean_delta = delta
            cell.m2 = 0.0
        else:
            delta_n = delta - cell.mean_delta
            cell.mean_delta += delta_n / n
            delta_n2 = delta - cell.mean_delta
            cell.m2 += delta_n * delta_n2
        
        if n > 1:
            cell.delta_variance = cell.m2 / (n - 1)
```

---

## 3. Graph Construction Layer

### 3.1 Spatial Hash to Adjacency Graph

```python
class SpatialGraphBuilder:
    """Build adjacency graph from spatial hash connectivity."""
    
    def __init__(self, backend: VectorlessSpatialHashBackend):
        self.backend = backend
    
    def compute_spatial_similarity(self, cell_a: SpatialCell, cell_b: SpatialCell) -> float:
        """Compute similarity between two cells based on density and mode.
        
        Higher similarity = stronger edge weight.
        """
        # Density correlation (0-1 range)
        density_sim = 1.0 - abs(cell_a.density - cell_b.density) / 255.0
        
        # Voltage mode similarity (same mode = 1.0, different = 0.0)
        mode_sim = 1.0 if cell_a.voltage_mode == cell_b.voltage_mode else 0.0
        
        # Combined similarity
        return 0.7 * density_sim + 0.3 * mode_sim
    
    def build_adjacency_matrix(self) -> np.ndarray:
        """Build full adjacency matrix from spatial hash (4096×4096).
        
        Returns sparse representation (CSR format for efficiency).
        """
        from scipy.sparse import csr_matrix
        
        rows = []
        cols = []
        data = []
        
        for x in range(16):
            for y in range(16):
                for z in range(16):
                    cell = self.backend.hash_grid[x, y, z]
                    idx = cell.coord.to_linear()
                    
                    # Connect to 26 neighbors
                    for dx in [-1, 0, 1]:
                        for dy in [-1, 0, 1]:
                            for dz in [-1, 0, 1]:
                                if dx == 0 and dy == 0 and dz == 0:
                                    continue
                                
                                nx, ny, nz = x + dx, y + dy, z + dz
                                if 0 <= nx < 16 and 0 <= ny < 16 and 0 <= nz < 16:
                                    neighbor = self.backend.hash_grid[nx, ny, nz]
                                    nidx = neighbor.coord.to_linear()
                                    
                                    weight = self.compute_spatial_similarity(cell, neighbor)
                                    rows.append(idx)
                                    cols.append(nidx)
                                    data.append(weight)
        
        return csr_matrix((data, (rows, cols)), shape=(4096, 4096))
```

---

## 4. Spectral Transform Layer (PIST Integration)

### 4.1 Graph to Spectral Profile

```python
# 4-Infrastructure/shim/vectorless_spectral_transform.py

import sys
sys.path.append('/home/researcher/stack/4-Infrastructure/shim')

# Reuse existing PIST spectral analysis
from pist_trace_classify_mcp import compute_spectral

class SpatialSpectralTransform:
    """Convert spatial hash graph to spectral profile for H.264 encoding."""
    
    def __init__(self, graph_builder: SpatialGraphBuilder):
        self.graph_builder = graph_builder
    
    def transform(self) -> dict:
        """Convert spatial graph to spectral profile.
        
        Returns spectral features mapping to H.264 codec parameters:
        - spectral_gap → quantization parameter
        - laplacian_eigenvalue_max → DCT coefficient energy
        - density → macroblock complexity
        """
        adj_matrix = self.graph_builder.build_adjacency_matrix()
        
        # Convert CSR to dense for PIST spectral analysis
        adj_dense = adj_matrix.toarray()
        
        # Reuse PIST spectral computation
        spectral_profile = compute_spectral(adj_dense.tolist())
        
        return spectral_profile
    
    def spectral_to_h264_params(self, spectral: dict) -> dict:
        """Map spectral profile to H.264 codec parameters."""
        # Spectral gap → quantization parameter (0-51)
        qp = int(51 * (1.0 - spectral.get('spectral_gap', 0.0)))
        qp = max(0, min(51, qp))
        
        # Laplacian max eigenvalue → DCT coefficient scaling
        dct_scale = spectral.get('laplacian_eigenvalue_max', 1.0)
        
        # Density → macroblock mode decision
        density = spectral.get('density', 0.0)
        if density > 0.8:
            mb_mode = "I_FRAME"  # Intra-coded
        elif density > 0.4:
            mb_mode = "P_FRAME"  # Predictive
        else:
            mb_mode = "B_FRAME"  # Bidirectional
        
        return {
            'quantization_parameter': qp,
            'dct_coefficient_scale': dct_scale,
            'macroblock_mode': mb_mode,
            'spectral_gap': spectral.get('spectral_gap', 0.0),
            'density': density
        }
```

---

## 5. H.264 Codec Encoding Layer

### 5.1 Spatial Hash to H.264 Macroblock

```python
# 4-Infrastructure/shim/vectorless_h264_encoder.py

@dataclass
class H264Macroblock:
    """H.264 macroblock encoded from spatial hash cell."""
    coord: SpatialCoord
    voltage_mode: int  # Maps to frame type (I/P/B)
    density: int  # DCT coefficient proxy (0-255)
    quantization_param: int  # 0-51
    motion_vectors: List[Tuple[int, int, int]]  # (dx, dy, dz) neighbor deltas
    residual: List[int]  # Residual coefficients
    
    def to_nal_unit(self) -> bytes:
        """Encode to H.264 NAL unit format."""
        # Simplified NAL unit encoding
        header = bytes([0x00, 0x00, 0x00, 0x01])  # NAL start code
        nal_type = self.voltage_mode & 0x1F  # NAL unit type
        
        # Pack macroblock data
        coord_packed = (self.coord.x << 0) | (self.coord.y << 4) | (self.coord.z << 8)
        mb_data = bytes([
            nal_type,
            (coord_packed >> 0) & 0xFF,
            (coord_packed >> 8) & 0xFF,
            self.density & 0xFF,
            self.quantization_param & 0xFF,
        ])
        
        # Add motion vectors (max 4 vectors per macroblock)
        for i, (dx, dy, dz) in enumerate(self.motion_vectors[:4]):
            if i >= 4:
                break
            mv_data = bytes([
                (dx + 1) & 0xFF,  # Bias to avoid sign issues
                (dy + 1) & 0xFF,
                (dz + 1) & 0xFF,
            ])
            mb_data += mv_data
        
        return header + mb_data

class SpatialH264Encoder:
    """Encode spatial hash grid to H.264 macroblock stream."""
    
    def __init__(self, backend: VectorlessSpatialHashBackend):
        self.backend = backend
    
    def encode_cell_to_macroblock(self, cell: SpatialCell, spectral_params: dict) -> H264Macroblock:
        """Encode single spatial cell to H.264 macroblock."""
        # Map voltage mode to frame type
        frame_type_map = {
            0: "I_FRAME",  # STORE → Intra-coded
            1: "P_FRAME",  # COMPUTE → Predictive
            2: "P_FRAME",  # APPROX → Predictive (quantized)
            3: "B_FRAME"   # MORPHIC → Bidirectional
        }
        
        # Compute motion vectors from neighbor deltas
        neighbors = self.backend.get_neighbors(cell.table_name, cell.row_ids[0] if cell.row_ids else 0)
        motion_vectors = []
        for neighbor in neighbors:
            dx = neighbor.coord.x - cell.coord.x
            dy = neighbor.coord.y - cell.coord.y
            dz = neighbor.coord.z - cell.coord.z
            motion_vectors.append((dx, dy, dz))
        
        # Compute residual (density difference from mean)
        mean_density = sum(n.density for n in neighbors) / max(1, len(neighbors))
        residual = [cell.density - int(mean_density)]
        
        return H264Macroblock(
            coord=cell.coord,
            voltage_mode=cell.voltage_mode,
            density=cell.density,
            quantization_param=spectral_params['quantization_parameter'],
            motion_vectors=motion_vectors,
            residual=residual
        )
    
    def encode_grid_to_bitstream(self, spectral_params: dict) -> bytes:
        """Encode entire spatial hash grid to H.264 bitstream."""
        bitstream = b''
        
        for x in range(16):
            for y in range(16):
                for z in range(16):
                    cell = self.backend.hash_grid[x, y, z]
                    if not cell.row_ids:
                        continue  # Skip empty cells
                    
                    mb = self.encode_cell_to_macroblock(cell, spectral_params)
                    bitstream += mb.to_nal_unit()
        
        return bitstream
```

---

## 6. Lean Formalization

### 6.1 Spatial Hash Types

```lean
-- 0-Core-Formalism/lean/Semantics/Semantics/SpatialHashCodec.lean

import Semantics.FixedPoint

namespace Semantics.SpatialHashCodec

open Semantics.Q16_16

-- ============================================================
-- §1  SPATIAL COORDINATE (16×16×16)
-- ============================================================

/-- 16×16×16 spatial coordinate. Each axis is 4 bits (0-15). -/
structure SpatialCoord where
  x : Fin 16
  y : Fin 16
  z : Fin 16
  deriving Repr, DecidableEq, BEq

namespace SpatialCoord

/-- Convert to linear index (0-4095). -/
def toLinear (c : SpatialCoord) : Nat :=
  c.x.val + 16 * (c.y.val + 16 * c.z.val)

/-- Convert from linear index (0-4095). -/
def fromLinear (idx : Nat) : SpatialCoord :=
  let z := idx / 256
  let y := (idx % 256) / 16
  let x := idx % 16
  { x := ⟨x, by decide⟩, y := ⟨y, by decide⟩, z := ⟨z, by decide⟩ }

/-- Roundtrip: fromLinear (toLinear c) = c. -/
theorem linearRoundtrip (c : SpatialCoord) :
  fromLinear (toLinear c) = c := by
  simp [toLinear, fromLinear]
  have : c.z.val = (c.x.val + 16 * (c.y.val + 16 * c.z.val)) / 256 := by
    -- Proof requires modular arithmetic
    sorry  -- TODO(lean-port): requires div_mod lemma
  sorry

end SpatialCoord

-- ============================================================
-- §2  VOLTAGE MODE (2-bit classification)
-- ============================================================

/-- Voltage mode: 2-bit classification (4 states). -/
inductive VoltageMode where
  | store    -- 00: I-frame (exact storage)
  | compute  -- 01: P-frame (motion vectors + residuals)
  | approx   -- 10: Quantized (lossy approximation)
  | morphic  -- 11: B-frame (bidirectional prediction)
  deriving Repr, DecidableEq, BEq

namespace VoltageMode

/-- Convert to 2-bit value. -/
def toBits (m : VoltageMode) : Fin 4 :=
  match m with
  | store => ⟨0, by decide⟩
  | compute => ⟨1, by decide⟩
  | approx => ⟨2, by decide⟩
  | morphic => ⟨3, by decide⟩

/-- Convert from 2-bit value. -/
def fromBits (b : Fin 4) : VoltageMode :=
  match b.val with
  | 0 => store
  | 1 => compute
  | 2 => approx
  | _ => morphic

/-- Roundtrip: fromBits (toBits m) = m. -/
theorem bitsRoundtrip (m : VoltageMode) :
  fromBits (toBits m) = m := by
  cases m <;> simp [toBits, fromBits]

end VoltageMode

-- ============================================================
-- §3  SPATIAL CELL
-- ============================================================

/-- Single cell in 16×16×16 spatial hash grid. -/
structure SpatialCell where
  coord : SpatialCoord
  voltage_mode : VoltageMode
  density : Q0_16  -- 0-255 as Q0_16
  row_ids : List Nat
  table_name : String
  write_count : Nat
  read_count : Nat
  delta_variance : Q16_16
  last_access_ts : Q16_16  -- UInt64 timestamp as Q16_16
  deriving Repr

namespace SpatialCell

/-- Pack to 64-bit integer for hardware transmission. -/
def toPacked (c : SpatialCell) : UInt64 :=
  let packed : UInt64 := 0
  let packed := packed ||| (UInt64.ofNat c.coord.x.val)
  let packed := packed ||| (UInt64.ofNat c.coord.y.val <<< 4)
  let packed := packed ||| (UInt64.ofNat c.coord.z.val <<< 8)
  let packed := packed ||| (UInt64.ofNat (VoltageMode.toBits c.voltage_mode).val <<< 12)
  let packed := packed ||| (UInt64.ofNat c.density.toNat <<< 16)
  packed

/-- Unpack from 64-bit integer. -/
def fromPacked (packed : UInt64) : SpatialCell :=
  let x := (packed &&& 0xF).toNat
  let y := ((packed >>> 4) &&& 0xF).toNat
  let z := ((packed >>> 8) &&& 0xF).toNat
  let mode := ((packed >>> 12) &&& 0x3).toNat
  let density := ((packed >>> 16) &&& 0xFF).toNat
  {
    coord := { x := ⟨x, by decide⟩, y := ⟨y, by decide⟩, z := ⟨z, by decide⟩ },
    voltage_mode := VoltageMode.fromBits ⟨mode, by decide⟩,
    density := Q0_16.ofNat density,
    row_ids := [],
    table_name := "",
    write_count := 0,
    read_count := 0,
    delta_variance := zero,
    last_access_ts := zero
  }

/-- Roundtrip: fromPacked (toPacked c) = c (excluding volatile fields). -/
theorem packedRoundtrip (c : SpatialCell) :
  (fromPacked (toPacked c)).coord = c.coord ∧
  (fromPacked (toPacked c)).voltage_mode = c.voltage_mode ∧
  (fromPacked (toPacked c)).density = c.density := by
  simp [toPacked, fromPacked, VoltageMode.toBits, VoltageMode.fromBits]
  constructor <;> sorry  -- TODO(lean-port): bit manipulation lemmas

end SpatialCell

-- ============================================================
-- §4  VOLTAGE MODE CLASSIFICATION
-- ============================================================

/-- Classify voltage mode from access pattern (JIT-compatible signature). -/
def classifyVoltageMode 
    (write_count read_count : Nat)
    (delta_variance : Q16_16)
    (threshold : Q16_16) : VoltageMode :=
  if write_count = 0 then
    .store
  else if read_count / (write_count + 1) > 10 then
    .compute
  else if delta_variance < threshold then
    .approx
  else
    .morphic

/-- Classification is monotonic: more writes → lower mode. -/
theorem classificationMonotone
    (w1 w2 r1 r2 : Nat)
    (dv : Q16_16)
    (th : Q16_16)
    (h : w1 ≤ w2) :
    classifyVoltageMode w1 r1 dv th ≤ classifyVoltageMode w2 r2 dv th := by
      -- TODO(lean-port): requires VoltageMode ordering lemma
      sorry

-- ============================================================
-- §5  SPATIAL HASH BACKEND
-- ============================================================

/-- Spatial hash backend: 16×16×16 = 4096 cells. -/
structure SpatialHashBackend where
  grid : Fin 4096 → SpatialCell  -- Linear indexing
  deriving Repr

namespace SpatialHashBackend

/-- Empty backend (all cells zeroed). -/
def empty : SpatialHashBackend :=
  { grid := fun _ => {
      coord := fromLinear 0,
      voltage_mode := .store,
      density := Q0_16.zero,
      row_ids := [],
      table_name := "",
      write_count := 0,
      read_count := 0,
      delta_variance := Q16_16.zero,
      last_access_ts := Q16_16.zero
    }
  }

/-- Get cell at spatial coordinate. -/
def getCell (b : SpatialHashBackend) (coord : SpatialCoord) : SpatialCell :=
  b.grid coord.toLinear

/-- Set cell at spatial coordinate. -/
def setCell (b : SpatialHashBackend) (coord : SpatialCoord) (cell : SpatialCell) : SpatialHashBackend :=
  { b with grid := fun idx => if idx = coord.toLinear then cell else b.grid idx }

/-- Add row to spatial hash. -/
def addRow 
    (b : SpatialHashBackend)
    (table_name : String)
    (row_id : Nat)
    (density : Q0_16) 
    : SpatialHashBackend := by
      -- TODO(lean-port): requires hash function formalization
      sorry

end SpatialHashBackend

end Semantics.SpatialHashCodec
```

---

## 7. Hardware Acceleration Path

### 7.1 Virtio-Net ASIC Mapping

```python
# 4-Infrastructure/shim/vectorless_virtio_accelerator.py

class SpatialVirtioAccelerator:
    """Map spatial hash operations to virtio-net ASIC offloads."""
    
    def __init__(self, backend: VectorlessSpatialHashBackend):
        self.backend = backend
    
    def rss_spatial_hash(self, table_name: str, row_id: int) -> int:
        """Use RSS (Toeplitz) for spatial coordinate hashing.
        
        Maps to: RSS Toeplitz Matrix Multiplication
        ASIC operation: Toeplitz hash at 100 Gbps line rate
        """
        # Convert (table, row_id) to RSS key
        rss_key = self._generate_rss_key(table_name, row_id)
        
        # Toeplitz hash (hardware-accelerated)
        spatial_hash = self._toeplitz_hash(rss_key)
        
        # Extract spatial coordinates
        x = spatial_hash & 0xF
        y = (spatial_hash >> 4) & 0xF
        z = (spatial_hash >> 8) & 0xF
        
        return x, y, z
    
    def tso_macroblock_segmentation(self, bitstream: bytes) -> List[bytes]:
        """Use TSO (TCP Segmentation) for macroblock segmentation.
        
        Maps to: TSO Tensor Slicing
        ASIC operation: Automatic recursive tiling
        """
        # TSO automatically segments large payloads
        # Each segment becomes a macroblock
        segment_size = 256  # 256 bytes per macroblock
        segments = [bitstream[i:i+segment_size] 
                    for i in range(0, len(bitstream), segment_size)]
        return segments
    
    def crc_spatial_witness(self, cell: SpatialCell) -> int:
        """Use CRC32 for spatial cell witness signature.
        
        Maps to: CRC32 Galois Field polynomial division
        ASIC operation: Instant graph connection validation
        """
        import zlib
        packed = cell.to_packed()
        crc = zlib.crc32(packed.to_bytes(8, 'little'))
        return crc
```

---

## 8. Integration Points

### 8.1 End-to-End Pipeline

```python
# 4-Infrastructure/shim/vectorless_pipeline.py

class VectorlessSpatialPipeline:
    """End-to-end pipeline: Table → Spatial Hash → Graph → Spectral → H.264."""
    
    def __init__(self):
        self.backend = VectorlessSpatialHashBackend()
        self.graph_builder = SpatialGraphBuilder(self.backend)
        self.spectral_transform = SpatialSpectralTransform(self.graph_builder)
        self.h264_encoder = SpatialH264Encoder(self.backend)
        self.virtio_accel = SpatialVirtioAccelerator(self.backend)
    
    def ingest_table(self, table_name: str, rows: List[dict]):
        """Ingest relational table into spatial hash."""
        for row in rows:
            row_id = row['id']
            # Compute density from row values
            density = self.backend.compute_density(table_name, row_id, row.get('value', 0.0))
            self.backend.add_row(table_name, row_id, density)
    
    def transform_to_spectral(self) -> dict:
        """Transform spatial hash to spectral profile."""
        return self.spectral_transform.transform()
    
    def encode_to_h264(self) -> bytes:
        """Encode to H.264 bitstream."""
        spectral = self.transform_to_spectral()
        h264_params = self.spectral_transform.spectral_to_h264_params(spectral)
        return self.h264_encoder.encode_grid_to_bitstream(h264_params)
    
    def accelerate_with_virtio(self, bitstream: bytes) -> List[bytes]:
        """Accelerate encoding with virtio-net ASIC offloads."""
        # RSS for spatial hashing
        # TSO for macroblock segmentation
        # CRC for witness validation
        return self.virtio_accel.tso_macroblock_segmentation(bitstream)
```

---

## 9. Verification & Testing

### 9.1 Unit Tests

```python
# 4-Infrastructure/shim/test_vectorless_spatial_hash.py

import pytest
from vectorless_spatial_hash_backend import VectorlessSpatialHashBackend, SpatialCoord, classify_voltage_mode

def test_spatial_coord_roundtrip():
    coord = SpatialCoord(7, 11, 3)
    linear = coord.to_linear()
    recovered = SpatialCoord.from_linear(linear)
    assert recovered.x == coord.x
    assert recovered.y == coord.y
    assert recovered.z == coord.z

def test_voltage_mode_classification():
    # STORE: never written
    assert classify_voltage_mode(0, 10, 0.05) == 0
    
    # COMPUTE: read-heavy
    assert classify_voltage_mode(5, 100, 0.05) == 1
    
    # APPROX: stable variance
    assert classify_voltage_mode(10, 50, 0.05) == 2
    
    # MORPHIC: volatile
    assert classify_voltage_mode(10, 50, 0.5) == 3

def test_spatial_hash_backend():
    backend = VectorlessSpatialHashBackend()
    backend.add_row("users", 12345, density=128)
    
    cell = backend.get_cell("users", 12345)
    assert cell.density == 128
    assert len(cell.row_ids) == 1
    assert cell.row_ids[0] == 12345

def test_neighbor_lookup():
    backend = VectorlessSpatialHashBackend()
    backend.add_row("users", 12345, density=128)
    
    neighbors = backend.get_neighbors("users", 12345)
    assert len(neighbors) == 26  # 3^3 - 1 (exclude self)
```

### 9.2 Lean Theorems

```lean
-- Test theorems for SpatialHashCodec

#eval Semantics.SpatialHashCodec.SpatialCoord.toLinear { x := ⟨7, by decide⟩, y := ⟨11, by decide⟩, z := ⟨3, by decide⟩ }
-- Expected: 7 + 16 * (11 + 16 * 3) = 7 + 16 * (11 + 48) = 7 + 16 * 59 = 7 + 944 = 951

#eval Semantics.SpatialHashCodec.VoltageMode.toBits .compute
-- Expected: 1

#eval Semantics.SpatialHashCodec.VoltageMode.fromBits ⟨1, by decide⟩
-- Expected: .compute
```

---

## 10. Performance Targets

| Metric | Target | Measurement |
| --- | --- | --- |
| Cell lookup | O(1) < 100ns | Benchmark `get_cell()` |
| Neighbor query | O(1) < 500ns | Benchmark `get_neighbors()` |
| Voltage mode classify | O(1) < 50ns | JIT-compiled `classify_voltage_mode()` |
| Spectral transform | O(N log N) < 10ms (4096 cells) | Benchmark `transform()` |
| H.264 encode | O(N) < 5ms (4096 cells) | Benchmark `encode_grid_to_bitstream()` |
| Memory per cell | 64 bytes | `sizeof(SpatialCell)` |
| Total memory | 256 KB (4096 cells) | `sizeof(SpatialHashBackend)` |

---

## 11. Next Steps

1. **Implement spatial hash backend** (`vectorless_spatial_hash_backend.py`)
2. **Add voltage mode JIT compilation** (numba)
3. **Integrate with PIST spectral analysis**
4. **Lean formalization** (`SpatialHashCodec.lean`)
5. **Hardware acceleration tests** (virtio-net offloads)
6. **End-to-end benchmark** (vs traditional graph database)
7. **LyteNyte dashboard integration** (real-time visualization)

---

## 12. References

- LyteNyte dashboard: `5-Applications/dashboard/lytenyte-storage/`
- PIST spectral analysis: `4-Infrastructure/shim/pist_trace_classify_mcp.py`
- BraidDiatCodec: `0-Core-Formalism/lean/Semantics/Semantics/BraidDiatCodec.lean`
- Virtio-net compute fabric: `6-Documentation/docs/specs/virtio_net_compute_fabric_spec.md`
- Venice conversation: `5-Applications/scripts/ingest_venice_research_stack_conversation.py`
