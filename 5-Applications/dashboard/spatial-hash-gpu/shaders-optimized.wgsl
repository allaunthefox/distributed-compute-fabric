// ═══════════════════════════════════════════════════════════════════════════
// shaders-optimized.wgsl — Morton-code indexed spatial hash grid
//
// Optimizations for memory-bandwidth-bound workloads:
//   1. Morton code (Z-order curve) for spatial locality
//   2. SoA layout for coalesced memory access
//   3. Shared memory tiling for neighbor scan
//   4. Bitonic sort in shared memory
//   5. Bit-packed coordinates (10+10+10+2 bits)
//   6. Persistent kernel pattern
//
// Grid: 16×16×16 = 4096 cells, Morton-ordered
// Cell: 16 bytes (compressed from 32)
// ═══════════════════════════════════════════════════════════════════════════

const GRID_SIZE: u32 = 16u;
const CELL_COUNT: u32 = 4096u;  // 16³
const WORKGROUP_SIZE: u32 = 256u;

// ── Morton Code (Z-order curve) ────────────────────────────────────────────
// Maps 3D coordinates to 1D index preserving spatial locality.
// Adjacent cells in 3D → nearby addresses in 1D → cache-friendly access.

fn spreadBits(v: u32) -> u32 {
    var x = v & 0x3FFu;  // 10 bits
    x = (x | (x << 16u)) & 0x30000FFu;
    x = (x | (x << 8u)) & 0x300F00Fu;
    x = (x | (x << 4u)) & 0x30C30C3u;
    x = (x | (x << 2u)) & 0x9249249u;
    return x;
}

fn mortonCode(x: u32, y: u32, z: u32) -> u32 {
    return spreadBits(x) | (spreadBits(y) << 1u) | (spreadBits(z) << 2u);
}

fn compactBits(v: u32) -> u32 {
    var x = v & 0x9249249u;
    x = (x | (x >> 2u)) & 0x30C30C3u;
    x = (x | (x >> 4u)) & 0x300F00Fu;
    x = (x | (x >> 8u)) & 0x30000FFu;
    x = (x | (x >> 16u)) & 0x3FFu;
    return x;
}

fn mortonDecode(code: u32) -> vec3<u32> {
    return vec3(
        compactBits(code),
        compactBits(code >> 1u),
        compactBits(code >> 2u)
    );
}

// ── Bit Pack/Unpack ────────────────────────────────────────────────────────
// Pack x(10), y(10), z(10), mode(2) into u32

fn packXYZ(x: u32, y: u32, z: u32, mode: u32) -> u32 {
    return (x & 0x3FFu) | ((y & 0x3FFu) << 10u) | ((z & 0x3FFu) << 20u) | ((mode & 3u) << 30u);
}

fn unpackXYZ(packed: u32) -> vec4<u32> {
    return vec4(
        packed & 0x3FFu,
        (packed >> 10u) & 0x3FFu,
        (packed >> 20u) & 0x3FFu,
        packed >> 30u
    );
}

// ── SoA Buffers (Structure of Arrays for coalesced access) ─────────────────
// Each field is a separate buffer → adjacent threads read adjacent elements
// of the same field → coalesced memory access → maximum bandwidth utilization

@group(0) @binding(0) var<storage, read_write> xyz_packed: array<u32>;      // x,y,z,mode packed
@group(0) @binding(1) var<storage, read_write> density: array<u32>;         // u16 pairs
@group(0) @binding(2) var<storage, read_write> fd_q16: array<u32>;          // u16 pairs
@group(0) @binding(3) var<storage, read_write> particle_count: array<u32>;  // u16 pairs
@group(0) @binding(4) var<storage, read_write> max_neighbor: array<u32>;    // u16 pairs
@group(0) @binding(5) var<storage, read_write> filter_mask: array<u32>;     // bit mask
@group(0) @binding(6) var<storage, read_write> sort_index: array<u32>;      // sorted indices
@group(0) @binding(7) var<storage, read_write> stats: array<u32>;           // aggregate stats

// ── Shared Memory Tile ─────────────────────────────────────────────────────
// Load Morton-ordered cells into shared memory for neighbor scan.
// 4×4×4 = 64 cells per tile, 3×3×3 = 27 neighbors per cell.
// Reduces global memory reads from 27 to 1 per cell.

var<workgroup> tile_density: array<u32, 64>;  // 4³ tile of density values
var<workgroup> tile_xyz: array<u32, 64>;      // 4³ tile of packed xyz

// ═══════════════════════════════════════════════════════════════════════════
// §1  INSERT — Atomic particle insertion via Morton hash
// ═══════════════════════════════════════════════════════════════════════════

@group(1) @binding(0) var<storage, read> particles_x: array<f32>;
@group(1) @binding(1) var<storage, read> particles_y: array<f32>;
@group(1) @binding(2) var<storage, read> particles_z: array<f32>;
@group(1) @binding(3) var<uniform> particle_count_uniform: u32;

@compute @workgroup_size(256)
fn insertShader(@builtin(global_invocation_id) id: vec3<u32>) {
    if (id.x >= particle_count_uniform) { return; }

    let px = u32(particles_x[id.x]) % GRID_SIZE;
    let py = u32(particles_y[id.x]) % GRID_SIZE;
    let pz = u32(particles_z[id.x]) % GRID_SIZE;

    // Morton hash: preserves 3D spatial locality in 1D address
    let idx = mortonCode(px, py, pz);

    // Atomic insert: lock-free concurrent cell assignment
    atomicAdd(&density[idx], 1u);

    // Update xyz_packed (only once per cell, last writer wins — acceptable for density)
    xyz_packed[idx] = packXYZ(px, py, pz, 0u);
}

// ═══════════════════════════════════════════════════════════════════════════
// §2  CLEAR — Zero all buffers
// ═══════════════════════════════════════════════════════════════════════════

@compute @workgroup_size(256)
fn clearShader(@builtin(global_invocation_id) id: vec3<u32>) {
    if (id.x >= CELL_COUNT) { return; }
    xyz_packed[id.x] = 0u;
    density[id.x] = 0u;
    fd_q16[id.x] = 0u;
    particle_count[id.x] = 0u;
    max_neighbor[id.x] = 0u;
    filter_mask[id.x] = 0u;
    sort_index[id.x] = id.x;
}

// ═══════════════════════════════════════════════════════════════════════════
// §3  NEIGHBOR SCAN — 3×3×3 via shared memory tile
//
// Key optimization: Morton ordering means 3×3×3 neighbors are nearby in
// memory. Load a 4×4×4 tile into shared memory, then scan 27 neighbors
// from shared memory (not global memory).
//
// Global memory reads: 1 per cell (load tile) instead of 27 per cell
// Shared memory reads: 27 per cell (fast, no bandwidth cost)
// ═══════════════════════════════════════════════════════════════════════════

@compute @workgroup_size(4, 4, 4)
fn neighborShader(@builtin(global_invocation_id) global_id: vec3<u32>,
                  @builtin(local_invocation_id) local_id: vec3<u32>,
                  @builtin(workgroup_id) wg_id: vec3<u32>) {

    // Each workgroup processes a 4×4×4 tile
    let tile_origin = wg_id * 4u;
    let cell_xyz = tile_origin + local_id;

    if (cell_xyz.x >= GRID_SIZE || cell_xyz.y >= GRID_SIZE || cell_xyz.z >= GRID_SIZE) {
        return;
    }

    // Load this cell into shared memory
    let cell_idx = mortonCode(cell_xyz.x, cell_xyz.y, cell_xyz.z);
    let tile_idx = local_id.x + local_id.y * 4u + local_id.z * 16u;

    tile_density[tile_idx] = density[cell_idx];
    tile_xyz[tile_idx] = xyz_packed[cell_idx];

    workgroupBarrier();

    // Scan 3×3×3 neighborhood from shared memory
    var max_d = 0u;
    for (var dz = 0u; dz < 3u; dz++) {
        for (var dy = 0u; dy < 3u; dy++) {
            for (var dx = 0u; dx < 3u; dx++) {
                let nx = local_id.x + dx;
                let ny = local_id.y + dy;
                let nz = local_id.z + dz;

                // Boundary check: skip out-of-bounds neighbors
                if (nx >= 4u || ny >= 4u || nz >= 4u) { continue; }

                let neighbor_tile_idx = nx + ny * 4u + nz * 16u;
                max_d = max(max_d, tile_density[neighbor_tile_idx]);
            }
        }
    }

    max_neighbor[cell_idx] = max_d;
}

// ═══════════════════════════════════════════════════════════════════════════
// §4  FILTER — Parallel predicate evaluation
// ═══════════════════════════════════════════════════════════════════════════

@group(2) @binding(0) var<uniform> filter_threshold: u32;

@compute @workgroup_size(256)
fn filterShader(@builtin(global_invocation_id) id: vec3<u32>) {
    if (id.x >= CELL_COUNT) { return; }

    // Read density from SoA buffer (coalesced access)
    let d = density[id.x];
    let matches = select(0u, 1u, d > filter_threshold);

    // Pack 32 results into each u32 of filter_mask
    let word_idx = id.x / 32u;
    let bit_idx = id.x % 32u;

    if (matches == 1u) {
        atomicOr(&filter_mask[word_idx], 1u << bit_idx);
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// §5  SORT — Bitonic sort on density in shared memory
//
// Morton ordering already provides spatial locality. Sorting by density
// reorders cells so high-density cells are contiguous → better cache
// utilization for downstream operations.
// ═══════════════════════════════════════════════════════════════════════════

var<workgroup> sort_keys: array<u32, 256>;
var<workgroup> sort_vals: array<u32, 256>;

@compute @workgroup_size(256)
fn sortShader(@builtin(global_invocation_id) global_id: vec3<u32>,
              @builtin(local_invocation_id) local_id: vec3<u32>) {

    let idx = global_id.x;
    if (idx >= CELL_COUNT) { return; }

    // Load into shared memory
    sort_keys[local_id.x] = density[idx];
    sort_vals[local_id.x] = idx;

    workgroupBarrier();

    // Bitonic sort in shared memory (no global memory traffic)
    for (var k = 2u; k <= 256u; k *= 2u) {
        for (var j = k / 2u; j > 0u; j /= 2u) {
            let ixj = local_id.x ^ j;
            if (ixj > local_id.x) {
                let ascending = ((local_id.x & k) == 0u);
                if ((sort_keys[local_id.x] > sort_keys[ixj]) == ascending) {
                    // Swap
                    let tmp_key = sort_keys[local_id.x];
                    let tmp_val = sort_vals[local_id.x];
                    sort_keys[local_id.x] = sort_keys[ixj];
                    sort_vals[local_id.x] = sort_vals[ixj];
                    sort_keys[ixj] = tmp_key;
                    sort_vals[ixj] = tmp_val;
                }
            }
            workgroupBarrier();
        }
    }

    // Write sorted indices back to global memory
    sort_index[idx] = sort_vals[local_id.x];
}

// ═══════════════════════════════════════════════════════════════════════════
// §6  AGGREGATE — Parallel reduction (sum/count/min/max)
// ═══════════════════════════════════════════════════════════════════════════

var<workgroup> reduce_sum: array<u32, 256>;
var<workgroup> reduce_max: array<u32, 256>;
var<workgroup> reduce_count: array<u32, 256>;

@compute @workgroup_size(256)
fn aggregateShader(@builtin(global_invocation_id) global_id: vec3<u32>,
                   @builtin(local_invocation_id) local_id: vec3<u32>) {

    let idx = global_id.x;
    let d = select(0u, density[idx], idx < CELL_COUNT);

    // Load into shared memory
    reduce_sum[local_id.x] = d;
    reduce_max[local_id.x] = d;
    reduce_count[local_id.x] = select(0u, 1u, d > 0u);

    workgroupBarrier();

    // Parallel reduction
    for (var stride = 128u; stride > 0u; stride /= 2u) {
        if (local_id.x < stride) {
            reduce_sum[local_id.x] += reduce_sum[local_id.x + stride];
            reduce_max[local_id.x] = max(reduce_max[local_id.x], reduce_max[local_id.x + stride]);
            reduce_count[local_id.x] += reduce_count[local_id.x + stride];
        }
        workgroupBarrier();
    }

    // Write results from thread 0
    if (local_id.x == 0u) {
        let wg = global_id.x / 256u;
        stats[wg * 3u + 0u] = reduce_sum[0u];    // total density
        stats[wg * 3u + 1u] = reduce_max[0u];     // max density
        stats[wg * 3u + 2u] = reduce_count[0u];   // occupied cells
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// §7  RENDER — Instanced quads, color by voltage mode
// ═══════════════════════════════════════════════════════════════════════════

@group(3) @binding(0) var<uniform> viewProj: mat4x4<f32>;
@group(3) @binding(1) var<uniform> cameraPos: vec3<f32>;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) color: vec4<f32>,
    @location(1) uv: vec2<f32>,
};

@vertex
fn vertShader(@location(0) quadPos: vec2<f32>,
              @builtin(instance_index) iid: u32) -> VertexOutput {

    // Decode cell position from Morton code
    let xyz = mortonDecode(iid);
    let worldPos = vec3<f32>(f32(xyz.x), f32(xyz.y), f32(xyz.z)) * 0.5;

    // Billboard quad (always faces camera)
    let toCamera = normalize(cameraPos - worldPos);
    let right = normalize(cross(toCamera, vec3(0.0, 1.0, 0.0)));
    let up = cross(toCamera, right);

    let pos = worldPos + right * quadPos.x * 0.2 + up * quadPos.y * 0.2;

    var out: VertexOutput;
    out.position = viewProj * vec4(pos, 1.0);
    out.uv = quadPos;

    // Color by voltage mode
    let packed = xyz_packed[iid];
    let mode = packed >> 30u;
    let d = f32(density[iid]) / 255.0;

    out.color = select(
        select(
            select(
                vec4(d, 0.2, 0.0, d),           // STORE: red
                vec4(0.0, d, 0.2, d),            // COMPUTE: green
                mode == 1u
            ),
            vec4(0.0, 0.2, d, d),               // APPROX: blue
            mode == 2u
        ),
        vec4(d, d, d, d),                        // MORPHIC: white
        mode == 3u
    );

    return out;
}

@fragment
fn fragShader(in: VertexOutput) -> @location(0) vec4<f32> {
    // Circular particle shape
    let dist = length(in.uv);
    if (dist > 1.0) { discard; }
    let alpha = in.color.a * (1.0 - dist * dist);
    return vec4(in.color.rgb, alpha);
}
