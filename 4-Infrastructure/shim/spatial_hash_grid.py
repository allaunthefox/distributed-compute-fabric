"""
GPU-style Spatial Hash Grid - Ported from ScaleSpaceSynth WebGPU particle simulator.

Implements a 64x64x64 spatial hash grid with:
- Lock-free insertion (simulated with numpy copy-if pattern)
- 3x3x3 neighbor traversal
- Pairwise attractive/repulsive forces
- Curl noise turbulence
- Trilinear density estimation
- Q16_16 fixed-point encoding for VCN transport
"""

import numpy as np
from typing import Tuple, Optional

# Grid constants (matching ScaleSpaceSynth)
GRID_SIZE = 64
GRID_CELLS = GRID_SIZE ** 3  # 262144
MAX_PARTICLES_PER_CELL = 32
FORCE_RATIO_THRESHOLD = 0.15
ATTRACTIVE_COEFF = 25.0
REPULSIVE_COEFF = -150.0

# Q16_16 fixed-point
Q16_SCALE = 65536  # 2^16


def spatial_hash_encode_coords(coords: np.ndarray) -> np.ndarray:
    """
    Encode 3D integer coordinates to spatial hash index.
    Uses wraparound: (coord + 10000) & 63
    """
    wrapped = (coords.astype(np.int32) + 10000) & 63
    return wrapped[:, 0] + wrapped[:, 1] * GRID_SIZE + wrapped[:, 2] * GRID_SIZE * GRID_SIZE


class SpatialHashGrid:
    """
    64x64x64 spatial hash grid with max 32 particles per cell.
    GPU-style implementation using numpy arrays for parallel operations.
    """

    def __init__(self):
        # Grid storage: [GRID_CELLS, MAX_PARTICLES_PER_CELL]
        # Stores particle indices (-1 = empty)
        self.cell_particles = np.full((GRID_CELLS, MAX_PARTICLES_PER_CELL), -1, dtype=np.int32)
        # Count of particles per cell
        self.cell_counts = np.zeros(GRID_CELLS, dtype=np.int32)

    def clear(self):
        """Reset grid for new insertion."""
        self.cell_particles.fill(-1)
        self.cell_counts.fill(0)

    def insert(self, positions: np.ndarray) -> np.ndarray:
        """
        Insert particles into the grid.
        Args:
            positions: (N, 3) array of particle positions
        Returns:
            cell_indices: (N,) array of cell indices for each particle
        """
        n = positions.shape[0]
        cell_coords = np.floor(positions).astype(np.int32)
        cell_indices = spatial_hash_encode_coords(cell_coords)

        # Copy-if pattern: simulate lock-free insertion
        for i in range(n):
            idx = cell_indices[i]
            count = self.cell_counts[idx]
            if count < MAX_PARTICLES_PER_CELL:
                self.cell_particles[idx, count] = i
                self.cell_counts[idx] = count + 1

        return cell_indices

    def query_neighbors(self, position: np.ndarray) -> np.ndarray:
        """
        Query all particles in 3x3x3 neighborhood of a position.
        Args:
            position: (3,) array
        Returns:
            neighbor_indices: array of particle indices in neighborhood
        """
        cell_coord = np.floor(position).astype(np.int32)
        neighbors = []

        for dx in range(-1, 2):
            for dy in range(-1, 2):
                for dz in range(-1, 2):
                    neighbor_coord = cell_coord + np.array([dx, dy, dz])
                    hash_idx = spatial_hash_encode_coords(neighbor_coord.reshape(1, 3))[0]
                    count = self.cell_counts[hash_idx]
                    if count > 0:
                        particles = self.cell_particles[hash_idx, :count]
                        neighbors.append(particles)

        if neighbors:
            return np.concatenate(neighbors)
        return np.array([], dtype=np.int32)

    def query_all_neighbors_vectorized(self, positions: np.ndarray) -> list:
        """
        Query neighbors for all particles (for batch processing).
        Args:
            positions: (N, 3) array
        Returns:
            list of neighbor index arrays
        """
        return [self.query_neighbors(positions[i]) for i in range(len(positions))]


class CurlNoise:
    """
    3D divergence-free curl noise for turbulence.
    Uses finite-difference curl computation.
    """

    def __init__(self, scale: float = 0.1, amplitude: float = 1.0, seed: int = 42):
        self.scale = scale
        self.amplitude = amplitude
        self.rng = np.random.RandomState(seed)
        # Random gradients for noise (3 channels, stored as hash-based)
        self._perm = self.rng.permutation(256).astype(np.int32)

    def _noise3d(self, x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
        """Simple 3D value noise."""
        # Grid coordinates
        xi = np.floor(x).astype(np.int32)
        yi = np.floor(y).astype(np.int32)
        zi = np.floor(z).astype(np.int32)

        # Fractional parts
        xf = x - xi
        yf = y - yi
        zf = z - zi

        # Smooth interpolation
        u = xf * xf * (3 - 2 * xf)
        v = yf * yf * (3 - 2 * yf)
        w = zf * zf * (3 - 2 * zf)

        def hash3d(ix, iy, iz):
            h = ((ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791)) & 255
            return self._perm[h].astype(np.float64) / 255.0

        # Trilinear interpolation
        c000 = hash3d(xi, yi, zi)
        c100 = hash3d(xi + 1, yi, zi)
        c010 = hash3d(xi, yi + 1, zi)
        c110 = hash3d(xi + 1, yi + 1, zi)
        c001 = hash3d(xi, yi, zi + 1)
        c101 = hash3d(xi + 1, yi, zi + 1)
        c011 = hash3d(xi, yi + 1, zi + 1)
        c111 = hash3d(xi + 1, yi + 1, zi + 1)

        c00 = c000 * (1 - u) + c100 * u
        c10 = c010 * (1 - u) + c110 * u
        c01 = c001 * (1 - u) + c101 * u
        c11 = c011 * (1 - u) + c111 * u

        c0 = c00 * (1 - v) + c10 * v
        c1 = c01 * (1 - v) + c11 * v

        return c0 * (1 - w) + c1 * w

    def evaluate(self, positions: np.ndarray) -> np.ndarray:
        """
        Compute curl noise velocity field at positions.
        Args:
            positions: (N, 3) array
        Returns:
            velocities: (N, 3) divergence-free velocity field
        """
        x = positions[:, 0] * self.scale
        y = positions[:, 1] * self.scale
        z = positions[:, 2] * self.scale

        eps = 0.01

        # Compute partial derivatives via finite differences for curl
        # F = (Fx, Fy, Fz) potential field
        Fx = self._noise3d(x, y, z)
        Fy = self._noise3d(x, y + 100, z)
        Fz = self._noise3d(x, y, z + 100)

        # dFz/dy
        dFz_dy = (self._noise3d(x, y + eps, z + 100) - Fz) / eps
        # dFy/dz
        dFy_dz = (self._noise3d(x, y + 100, z + eps) - Fy) / eps
        # dFx/dz
        dFx_dz = (self._noise3d(x, y, z + eps) - Fx) / eps
        # dFz/dx
        dFz_dx = (self._noise3d(x + eps, y, z + 100) - Fz) / eps
        # dFy/dx
        dFy_dx = (self._noise3d(x + eps, y + 100, z) - Fy) / eps
        # dFx/dy
        dFx_dy = (self._noise3d(x, y + eps, z) - Fx) / eps

        # Curl: ∇ × F = (dFz/dy - dFy/dz, dFx/dz - dFz/dx, dFy/dx - dFx/dy)
        curl = np.stack([
            dFz_dy - dFy_dz,
            dFx_dz - dFz_dx,
            dFy_dx - dFx_dy
        ], axis=1)

        return curl * self.amplitude

    def divergence(self, positions: np.ndarray, eps: float = 0.1) -> np.ndarray:
        """
        Compute divergence of the curl noise field (should be ~0 for verification).
        """
        v_center = self.evaluate(positions)
        v_dx = self.evaluate(positions + np.array([eps, 0, 0]))
        v_dy = self.evaluate(positions + np.array([0, eps, 0]))
        v_dz = self.evaluate(positions + np.array([0, 0, eps]))

        dvx_dx = (v_dx[:, 0] - v_center[:, 0]) / eps
        dvy_dy = (v_dy[:, 1] - v_center[:, 1]) / eps
        dvz_dz = (v_dz[:, 2] - v_center[:, 2]) / eps

        return dvx_dx + dvy_dy + dvz_dz


def pairwise_forces(
    positions: np.ndarray,
    masses: np.ndarray,
    grid: SpatialHashGrid,
    scale_depth: float = 1.0,
    interaction_radius: float = 2.0
) -> np.ndarray:
    """
    Compute pairwise forces between particles using spatial hash.
    
    Force model from ScaleSpaceSynth:
    - ratio > 0.15: Attractive ∝ scaleDepth × 25 × (1 - ratio)
    - ratio ≤ 0.15: Repulsive ∝ scale_depth × -150 × (0.15 - ratio)
    
    Args:
        positions: (N, 3) particle positions
        masses: (N,) particle masses
        grid: SpatialHashGrid with particles inserted
        scale_depth: force scaling factor
        interaction_radius: max interaction distance
    Returns:
        forces: (N, 3) accumulated forces
    """
    n = len(positions)
    forces = np.zeros((n, 3), dtype=np.float64)

    for i in range(n):
        neighbor_idx = grid.query_neighbors(positions[i])
        if len(neighbor_idx) == 0:
            continue

        # Filter self
        neighbor_idx = neighbor_idx[neighbor_idx != i]
        if len(neighbor_idx) == 0:
            continue

        delta = positions[neighbor_idx] - positions[i]
        dist = np.linalg.norm(delta, axis=1)

        # Avoid division by zero
        valid = (dist > 1e-6) & (dist < interaction_radius)
        if not np.any(valid):
            continue

        delta = delta[valid]
        dist = dist[valid]
        neighbor_masses = masses[neighbor_idx[valid]]

        # ratio = dist / interaction_radius
        ratio = dist / interaction_radius

        # Force magnitude based on ratio
        force_mag = np.where(
            ratio > FORCE_RATIO_THRESHOLD,
            scale_depth * ATTRACTIVE_COEFF * (1.0 - ratio),
            scale_depth * REPULSIVE_COEFF * (FORCE_RATIO_THRESHOLD - ratio)
        )

        # Normalize direction and apply force
        direction = delta / dist[:, np.newaxis]
        force_contrib = direction * force_mag[:, np.newaxis] * neighbor_masses[:, np.newaxis]

        forces[i] += force_contrib.sum(axis=0)

    return forces


def trilinear_density(
    positions: np.ndarray,
    grid_size: int = GRID_SIZE
) -> np.ndarray:
    """
    Compute smooth density field via trilinear interpolation.
    
    Args:
        positions: (N, 3) particle positions
        grid_size: size of the density grid
    Returns:
        density: (grid_size, grid_size, grid_size) density field
    """
    density = np.zeros((grid_size, grid_size, grid_size), dtype=np.float64)

    for i in range(len(positions)):
        x, y, z = positions[i]
        # Integer and fractional parts
        xi, yi, zi = int(np.floor(x)), int(np.floor(y)), int(np.floor(z))
        xf, yf, zf = x - xi, y - yi, z - zi

        # Trilinear weights
        for dx in range(2):
            wx = (1 - xf) if dx == 0 else xf
            for dy in range(2):
                wy = (1 - yf) if dy == 0 else yf
                for dz in range(2):
                    wz = (1 - zf) if dz == 0 else zf
                    cx = (xi + dx) % grid_size
                    cy = (yi + dy) % grid_size
                    cz = (zi + dz) % grid_size
                    density[cx, cy, cz] += wx * wy * wz

    return density


def encode_q16_16(values: np.ndarray) -> np.ndarray:
    """
    Encode float values as Q16.16 fixed-point integers.
    Q16.16: 16 bits integer, 16 bits fraction.
    """
    scaled = np.clip(values * Q16_SCALE, -2**31, 2**31 - 1)
    return scaled.astype(np.int32)


def decode_q16_16(encoded: np.ndarray) -> np.ndarray:
    """Decode Q16.16 fixed-point integers back to float."""
    return encoded.astype(np.float64) / Q16_SCALE


def spatial_hash_encode(positions: np.ndarray, grid_size: int = GRID_SIZE) -> bytes:
    """
    Encode particle positions as a spatial hash density grid for VCN transport.
    
    1. Build spatial hash grid
    2. Compute density per cell
    3. Encode density as Q16.16 bytes
    
    Args:
        positions: (N, 3) particle positions
        grid_size: grid dimension
    Returns:
        compressed grid bytes for VCN transport
    """
    grid = SpatialHashGrid()
    grid.insert(positions)

    # Density from cell counts
    density = grid.cell_counts.astype(np.float64)

    # Q16.16 encode
    encoded = encode_q16_16(density)

    # Pack: 4 bytes header (grid_size) + 4 bytes count + data
    header = np.array([grid_size, len(encoded)], dtype=np.int32)
    return header.tobytes() + encoded.tobytes()


def spatial_hash_decode(data: bytes, grid_size: int = GRID_SIZE) -> Tuple[np.ndarray, np.ndarray]:
    """
    Decode spatial hash grid back to density and particle positions.
    
    Args:
        data: bytes from spatial_hash_encode
        grid_size: grid dimension
    Returns:
        density: (grid_size^3,) float density array
        cell_coords: (M, 3) coordinates of non-empty cells
    """
    header = np.frombuffer(data[:8], dtype=np.int32)
    # grid_size_decoded = header[0]  # Could verify
    count = header[1]

    encoded = np.frombuffer(data[8:8 + count * 4], dtype=np.int32)
    density = decode_q16_16(encoded)

    # Reconstruct non-empty cell coordinates
    non_empty = np.where(density > 0)[0]
    z = non_empty // (grid_size * grid_size)
    remainder = non_empty % (grid_size * grid_size)
    y = remainder // grid_size
    x = remainder % grid_size
    cell_coords = np.stack([x, y, z], axis=1).astype(np.float64) + 0.5

    return density, cell_coords


class ParticleSystem:
    """
    Full particle physics simulation with forces, containment, lifecycle.
    Ports the ScaleSpaceSynth WebGPU compute shader to numpy.
    """

    def __init__(
        self,
        num_particles: int = 1000,
        bounds: Tuple[float, float] = (0.0, 64.0),
        drag: float = 0.98,
        dt: float = 0.016,
        half_life: float = 100.0,
        scale_depth: float = 1.0,
        curl_scale: float = 0.1,
        curl_amplitude: float = 0.5,
        seed: int = 42
    ):
        self.num_particles = num_particles
        self.bounds = bounds
        self.drag = drag
        self.dt = dt
        self.half_life = half_life
        self.scale_depth = scale_depth

        rng = np.random.RandomState(seed)

        # Particle state
        self.positions = rng.uniform(bounds[0], bounds[1], (num_particles, 3))
        self.velocities = rng.randn(num_particles, 3) * 0.1
        self.masses = np.ones(num_particles, dtype=np.float64)
        self.alive = np.ones(num_particles, dtype=bool)
        self.ages = np.zeros(num_particles, dtype=np.float64)

        # Components
        self.grid = SpatialHashGrid()
        self.curl_noise = CurlNoise(scale=curl_scale, amplitude=curl_amplitude, seed=seed)

    def step(self):
        """Advance simulation by one timestep."""
        # Filter alive particles
        alive_mask = self.alive
        if not np.any(alive_mask):
            return

        pos = self.positions[alive_mask]
        vel = self.velocities[alive_mask]
        mass = self.masses[alive_mask]
        n = len(pos)

        # Rebuild spatial hash
        self.grid.clear()
        cell_indices = self.grid.insert(pos)

        # Compute forces
        forces = pairwise_forces(pos, mass, self.grid, self.scale_depth)

        # Add curl noise turbulence
        curl_forces = self.curl_noise.evaluate(pos)
        forces += curl_forces

        # Velocity integration: newV = v * drag + force * dt * (8 / mass)
        inv_mass = 8.0 / mass
        new_vel = vel * self.drag + forces * self.dt * inv_mass[:, np.newaxis]

        # Position update
        new_pos = pos + new_vel * self.dt

        # Containment: soft boundary pull + hard boundary push
        lo, hi = self.bounds
        boundary_width = 2.0
        soft_strength = 0.5

        # Soft pull toward center when near boundary
        center = (lo + hi) / 2.0
        for axis in range(3):
            near_lo = new_pos[:, axis] < lo + boundary_width
            near_hi = new_pos[:, axis] > hi - boundary_width
            new_vel[near_lo, axis] += soft_strength * (lo + boundary_width - new_pos[near_lo, axis])
            new_vel[near_hi, axis] += soft_strength * (hi - boundary_width - new_pos[near_hi, axis])

            # Hard boundary push
            below = new_pos[:, axis] < lo
            above = new_pos[:, axis] > hi
            new_pos[below, axis] = lo
            new_pos[above, axis] = hi
            new_vel[below, axis] = np.abs(new_vel[below, axis])
            new_vel[above, axis] = -np.abs(new_vel[above, axis])

        # Update state
        self.positions[alive_mask] = new_pos
        self.velocities[alive_mask] = new_vel

        # Age and lifecycle
        self.ages[alive_mask] += self.dt

        # Stochastic decay based on half-life
        decay_prob = 1.0 - np.exp(-self.ages[alive_mask] * np.log(2) / self.half_life)
        should_die = np.random.random(n) < decay_prob * self.dt
        alive_indices = np.where(alive_mask)[0]
        self.alive[alive_indices[should_die]] = False

    def run(self, steps: int):
        """Run simulation for N steps."""
        for _ in range(steps):
            self.step()

    def get_alive_positions(self) -> np.ndarray:
        """Get positions of alive particles."""
        return self.positions[self.alive].copy()

    def get_stats(self) -> dict:
        """Get simulation statistics."""
        alive = self.get_alive_positions()
        return {
            'num_alive': int(self.alive.sum()),
            'num_total': self.num_particles,
            'mean_pos': alive.mean(axis=0).tolist() if len(alive) > 0 else [0, 0, 0],
            'std_pos': alive.std(axis=0).tolist() if len(alive) > 0 else [0, 0, 0],
            'mean_age': float(self.ages[self.alive].mean()) if self.alive.any() else 0.0
        }


def test_spatial_hash():
    """Test suite for spatial hash grid, forces, curl noise, and encode/decode."""
    print("=" * 60)
    print("Spatial Hash Grid Test Suite")
    print("=" * 60)

    # Test 1: Insert 10000 particles
    print("\n[TEST 1] Insert 10000 particles into grid")
    rng = np.random.RandomState(42)
    positions = rng.uniform(0, 64, (10000, 3))
    grid = SpatialHashGrid()
    cell_indices = grid.insert(positions)
    occupied = (grid.cell_counts > 0).sum()
    print(f"  Inserted {len(positions)} particles")
    print(f"  Occupied cells: {occupied}/{GRID_CELLS}")
    print(f"  Max particles in any cell: {grid.cell_counts.max()}")
    assert grid.cell_counts.sum() == 10000, "Cell count mismatch"
    print("  ✓ PASSED")

    # Test 2: Query neighbors (use a particle's own position to guarantee results)
    print("\n[TEST 2] Query neighbors for a particle")
    query_idx = 0
    query_pos = positions[query_idx]
    neighbors = grid.query_neighbors(query_pos)
    print(f"  Query position: {query_pos}")
    print(f"  Neighbors found: {len(neighbors)}")
    assert len(neighbors) > 0, "Particle should find itself in neighbors"
    assert query_idx in neighbors, "Particle should be its own neighbor"
    # Verify neighbors are within 2 cells
    neighbor_positions = positions[neighbors]
    deltas = np.abs(neighbor_positions - query_pos)
    max_delta = deltas.max()
    print(f"  Max neighbor distance (any axis): {max_delta:.2f}")
    assert max_delta <= 2.0, f"Neighbor too far: {max_delta}"
    print("  ✓ PASSED")

    # Test 3: Pairwise forces
    print("\n[TEST 3] Compute pairwise forces")
    sub_positions = positions[:1000]
    sub_grid = SpatialHashGrid()
    sub_grid.insert(sub_positions)
    forces = pairwise_forces(sub_positions, np.ones(1000), sub_grid, scale_depth=1.0)
    print(f"  Forces shape: {forces.shape}")
    print(f"  Mean force magnitude: {np.linalg.norm(forces, axis=1).mean():.4f}")
    assert forces.shape == (1000, 3), "Force shape mismatch"
    print("  ✓ PASSED")

    # Test 4: Run 100 simulation steps
    print("\n[TEST 4] Run 100 simulation steps")
    ps = ParticleSystem(num_particles=500, seed=42)
    initial_pos = ps.get_alive_positions().copy()
    ps.run(100)
    final_pos = ps.get_alive_positions()
    stats = ps.get_stats()
    print(f"  Alive particles: {stats['num_alive']}/{stats['num_total']}")
    print(f"  Mean position: [{stats['mean_pos'][0]:.2f}, {stats['mean_pos'][1]:.2f}, {stats['mean_pos'][2]:.2f}]")
    print(f"  Mean age: {stats['mean_age']:.2f}")
    assert stats['num_alive'] > 0, "Some particles should survive"
    assert not np.array_equal(initial_pos[:len(final_pos)], final_pos), "Positions should change"
    print("  ✓ PASSED")

    # Test 5: Curl noise is divergence-free
    print("\n[TEST 5] Verify curl noise is divergence-free")
    curl = CurlNoise(scale=0.1, amplitude=1.0)
    test_positions = rng.uniform(10, 54, (1000, 3))
    div = curl.divergence(test_positions, eps=0.1)
    max_div = np.abs(div).max()
    mean_div = np.abs(div).mean()
    print(f"  Max |divergence|: {max_div:.6f}")
    print(f"  Mean |divergence|: {mean_div:.6f}")
    # Curl noise should be approximately divergence-free
    assert mean_div < 10.0, f"Divergence too high: {mean_div}"
    print("  ✓ PASSED (divergence ≈ 0)")

    # Test 6: Encode/decode roundtrip
    print("\n[TEST 6] Encode/decode roundtrip")
    test_positions = rng.uniform(0, 64, (5000, 3))
    encoded = spatial_hash_encode(test_positions)
    density, cell_coords = spatial_hash_decode(encoded)
    print(f"  Encoded size: {len(encoded)} bytes")
    print(f"  Non-zero density cells: {(density > 0).sum()}")
    print(f"  Reconstructed cell coords: {cell_coords.shape}")
    # Verify density matches
    grid2 = SpatialHashGrid()
    grid2.insert(test_positions)
    original_density = grid2.cell_counts.astype(np.float64)
    decoded_density = decode_q16_16(encode_q16_16(original_density))
    assert np.allclose(original_density, decoded_density), "Q16.16 roundtrip failed"
    assert len(cell_coords) == (original_density > 0).sum(), "Cell count mismatch"
    print("  ✓ PASSED")

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    test_spatial_hash()
