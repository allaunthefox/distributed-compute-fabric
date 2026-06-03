#!/usr/bin/env python3
"""vectorless_morton_hash_backend.py — Locality-preserving Morton code spatial hash.

Replaces SipHash with Morton code (Z-order curve) to preserve spatial locality.
Nearby rows remain nearby in the 16×16×16 grid, making neighbor queries semantically meaningful.

Corresponds to Lean formalization: Semantics.SpatialHashCodec.MortonHash
"""

import dataclasses
import time
from dataclasses import dataclass
from typing import List, Tuple, Optional
import numpy as np


# ============================================================
# §1  SPATIAL COORDINATE (16×16×16)
# ============================================================

@dataclass
class SpatialCoord:
    """16×16×16 spatial coordinate. Each axis is 4 bits (0-15)."""
    x: int  # 0-15 (4 bits)
    y: int  # 0-15 (4 bits)
    z: int  # 0-15 (4 bits)
    
    def to_linear(self) -> int:
        """Convert to linear index using Morton code (Z-order)."""
        # Interleave bits: z2 y2 x2 z1 y1 x1 z0 y0 x0 (9 bits for 3D Morton)
        morton = 0
        for i in range(4):  # 4 bits per coordinate
            morton |= ((self.x >> i) & 1) << (3 * i + 0)      # x bits at positions 0,3,6,9
            morton |= ((self.y >> i) & 1) << (3 * i + 1)      # y bits at positions 1,4,7,10
            morton |= ((self.z >> i) & 1) << (3 * i + 2)      # z bits at positions 2,5,8,11
        return morton
    
    @staticmethod
    def from_linear(idx: int) -> 'SpatialCoord':
        """Convert from linear index using Morton code decoding."""
        # Decode interleaved bits
        x, y, z = 0, 0, 0
        for i in range(4):
            x |= ((idx >> (3 * i + 0)) & 1) << i
            y |= ((idx >> (3 * i + 1)) & 1) << i
            z |= ((idx >> (3 * i + 2)) & 1) << i
        return SpatialCoord(x, y, z)
    
    def __hash__(self) -> int:
        return self.to_linear()
    
    def __eq__(self, other) -> bool:
        if not isinstance(other, SpatialCoord):
            return False
        return self.x == other.x and self.y == other.y and self.z == other.z


# ============================================================
# §2  MORTON CODE HASHING
# ============================================================

def morton_encode_3d(x: int, y: int, z: int) -> int:
    """Encode 3D coordinates to Morton code (Z-order curve).
    
    This preserves locality: nearby coordinates remain nearby in Morton space.
    
    Args:
        x: X coordinate (0-15)
        y: Y coordinate (0-15)
        z: Z coordinate (0-15)
    
    Returns:
        Morton code (0-4095 for 4-bit coordinates)
    """
    morton = 0
    for i in range(4):
        morton |= ((x >> i) & 1) << (3 * i + 0)
        morton |= ((y >> i) & 1) << (3 * i + 1)
        morton |= ((z >> i) & 1) << (3 * i + 2)
    return morton


def morton_decode_3d(morton: int) -> Tuple[int, int, int]:
    """Decode Morton code to 3D coordinates.
    
    Args:
        morton: Morton code (0-4095)
    
    Returns:
        (x, y, z) coordinates (0-15 each)
    """
    x, y, z = 0, 0, 0
    for i in range(4):
        x |= ((morton >> (3 * i + 0)) & 1) << i
        y |= ((morton >> (3 * i + 1)) & 1) << i
        z |= ((morton >> (3 * i + 2)) & 1) << i
    return x, y, z


def table_row_to_morton_coord(table_name: str, row_id: int) -> SpatialCoord:
    """Map (table_name, row_id) to spatial coordinate using Morton code.
    
    Uses a locality-preserving approach:
    1. Extract sequential bits from row_id
    2. Use table_name hash for spatial rotation
    3. Preserve locality: row_id N and N+1 are nearby in Morton space
    
    Args:
        table_name: Source table name
        row_id: Row identifier
    
    Returns:
        Spatial coordinate preserving locality
    """
    # Use lower 12 bits of row_id (preserves locality for sequential IDs)
    row_bits = row_id & 0xFFF
    
    # Use table_name hash for spatial rotation (prevents clustering)
    import hashlib
    table_hash = int(hashlib.md5(table_name.encode()).hexdigest()[:8], 16)
    
    # XOR with table hash for spatial distribution while preserving locality
    morton = row_bits ^ (table_hash & 0xFFF)
    
    # Decode to coordinates
    x, y, z = morton_decode_3d(morton)
    
    return SpatialCoord(x, y, z)


# ============================================================
# §3  VOLTAGE MODE CLASSIFICATION (2-bit)
# ============================================================

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
    """Classify cell into voltage mode based on access pattern.
    
    Matches Lean formalization: Semantics.SpatialHashCodec.classifyVoltageMode
    Fixed: uses (write_count + 1) to match Lean semantics.
    
    Args:
        write_count: Number of write operations
        read_count: Number of read operations
        delta_variance: Variance of delta values
        threshold: Stability threshold for APPROX mode
    
    Returns:
        Voltage mode (0=STORE, 1=COMPUTE, 2=APPROX, 3=MORPHIC)
    """
    if write_count == 0:
        return 0  # STORE: never written → I-frame
    elif read_count / (write_count + 1) > 10:  # FIXED: matches Lean
        return 1  # COMPUTE: read-heavy → P-frame
    elif delta_variance < threshold:
        return 2  # APPROX: stable → quantized
    else:
        return 3  # MORPHIC: volatile → B-frame


# ============================================================
# §4  SPATIAL CELL
# ============================================================

@dataclass
class SpatialCell:
    """Single cell in 16×16×16 spatial hash grid.
    
    Corresponds to Semantics.SpatialHashCodec.SpatialCell in Lean.
    """
    coord: SpatialCoord
    voltage_mode: int  # 2 bits: 0=STORE, 1=COMPUTE, 2=APPROX, 3=MORPHIC
    density: int  # 0-255 (Q0_16 range)
    row_ids: List[int]  # Multiple rows can hash to same cell
    table_name: str  # Source table name
    write_count: int = 0
    read_count: int = 0
    delta_variance: float = 0.0
    mean_delta: float = 0.0
    m2: float = 0.0  # For online variance computation
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


# ============================================================
# §5  OCTREE-STYLE SPATIAL REFINEMENT
# ============================================================

class OctreeSpatialBackend:
    """Octree-style spatial refinement backend.
    
    Instead of fixed 16×16×16 grid, uses hierarchical refinement:
    - Level 0: 16×16×16 (4096 cells) - L1 cache
    - Level 1: 32×32×32 (32768 cells) - L2 cache  
    - Level 2: 64×64×64 (262144 cells) - Main memory
    
    This preserves O(1)-ish navigation while allowing expansion.
    """
    
    def __init__(self, max_levels: int = 3):
        self.max_levels = max_levels
        self.levels = []
        
        # Initialize level 0 (16×16×16)
        self.levels.append(np.empty((16, 16, 16), dtype=object))
        self._init_level(0, 16)
        
        # Initialize higher levels on demand
        for level in range(1, max_levels):
            size = 16 * (2 ** level)
            self.levels.append(np.empty((size, size, size), dtype=object))
            self._init_level(level, size)
    
    def _init_level(self, level: int, size: int):
        """Initialize a level with empty cells."""
        for x in range(size):
            for y in range(size):
                for z in range(size):
                    self.levels[level][x, y, z] = SpatialCell(
                        coord=SpatialCoord(x % 16, y % 16, z % 16),  # Keep base coord
                        voltage_mode=0,
                        density=0,
                        row_ids=[],
                        table_name=""
                    )
    
    def _get_level_for_row_count(self, row_count: int) -> int:
        """Determine which level to use based on row count.
        
        Aim for ~10 rows per cell to maintain graph structure.
        """
        if row_count < 40000:  # < 10 rows/cell at level 0
            return 0
        elif row_count < 320000:  # < 10 rows/cell at level 1
            return 1
        else:
            return 2
    
    def table_to_spatial_coord(self, table_name: str, row_id: int) -> SpatialCoord:
        """Map (table_name, row_id) to spatial coordinate using Morton code."""
        return table_row_to_morton_coord(table_name, row_id)
    
    def add_row(self, table_name: str, row_id: int, density: int = 0):
        """Add a row to the appropriate level of the octree."""
        coord = self.table_to_spatial_coord(table_name, row_id)
        
        # Determine which level to use
        total_rows = sum(len(self.levels[l][coord.x % (16 * (2**l)), 
                                           coord.y % (16 * (2**l)), 
                                           coord.z % (16 * (2**l))].row_ids) 
                        for l in range(len(self.levels)))
        level = self._get_level_for_row_count(total_rows)
        
        size = 16 * (2 ** level)
        level_coord = (coord.x % size, coord.y % size, coord.z % size)
        cell = self.levels[level][level_coord]
        
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
    
    def get_cell(self, table_name: str, row_id: int, level: int = 0) -> SpatialCell:
        """Get cell at specific level."""
        coord = self.table_to_spatial_coord(table_name, row_id)
        size = 16 * (2 ** level)
        level_coord = (coord.x % size, coord.y % size, coord.z % size)
        cell = self.levels[level][level_coord]
        cell.read_count += 1
        cell.last_access_ts = time.time()
        
        # Reclassify mode on access
        cell.voltage_mode = classify_voltage_mode(
            cell.write_count,
            cell.read_count,
            cell.delta_variance
        )
        
        return cell


# ============================================================
# §6  TOPOLOGICAL DELTAS (renamed from motion vectors)
# ============================================================

@dataclass
class TopologicalDelta:
    """Topological delta between spatial cells.
    
    Renamed from "motion vector" to avoid confusion with H.264 temporal motion.
    These represent static spatial relationships, not temporal displacement.
    """
    dx: int  # X-axis difference
    dy: int  # Y-axis difference
    dz: int  # Z-axis difference
    weight: float  # Correlation weight (0-1)


def compute_topological_deltas(cell: SpatialCell, neighbors: List[SpatialCell]) -> List[TopologicalDelta]:
    """Compute topological deltas between cell and its neighbors.
    
    Args:
        cell: Source cell
        neighbors: Neighbor cells
    
    Returns:
        List of topological deltas
    """
    deltas = []
    for neighbor in neighbors:
        dx = neighbor.coord.x - cell.coord.x
        dy = neighbor.coord.y - cell.coord.y
        dz = neighbor.coord.z - cell.coord.z
        
        # Weight based on density correlation
        if cell.density > 0 and neighbor.density > 0:
            weight = 1.0 - abs(cell.density - neighbor.density) / 255.0
        else:
            weight = 0.0
        
        deltas.append(TopologicalDelta(dx, dy, dz, weight))
    
    return deltas


# ============================================================
# §7  EXAMPLE USAGE
# ============================================================

if __name__ == '__main__':
    # Test Morton code locality preservation
    print("Testing Morton code locality preservation:")
    for row_id in range(100, 105):
        coord = table_row_to_morton_coord("users", row_id)
        morton = coord.to_linear()
        print(f"Row {row_id}: coord=({coord.x},{coord.y},{coord.z}), morton={morton}")
    
    # Test octree backend
    print("\nTesting OctreeSpatialBackend:")
    backend = OctreeSpatialBackend(max_levels=2)
    
    # Add rows to test level selection
    for i in range(50000):
        backend.add_row("users", i, density=128)
    
    stats_0 = backend.levels[0].size
    stats_1 = backend.levels[1].size if len(backend.levels) > 1 else 0
    print(f"Level 0 size: {stats_0}, Level 1 size: {stats_1}")
    
    # Test topological deltas
    cell = backend.get_cell("users", 100)
    print(f"\nCell (100): coord=({cell.coord.x},{cell.coord.y},{cell.coord.z}), mode={VOLTAGE_MODES[cell.voltage_mode]}")
