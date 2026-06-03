// ============================================================
// shaders.wgsl — WebGPU compute + render shaders for spatial hash grid
// Hash: cellIdx = x + y*16 + z*256  (16×16×16 = 4096 cells)
// Density stored as integer counts (Q16_16 convention: no floats in compute)
// ============================================================

const GRID_DIM : u32 = 16u;
const GRID_SIZE : u32 = 4096u;  // 16*16*16

// Voltage modes (matching Python spatial_hash_grid.py)
const MODE_STORE    : u32 = 0u;
const MODE_COMPUTE  : u32 = 1u;
const MODE_APPROX   : u32 = 2u;
const MODE_MORPHIC  : u32 = 3u;

// Cell struct — 8 × u32 = 32 bytes per cell
struct Cell {
    x : u32,
    y : u32,
    z : u32,
    density : atomic<u32>,  // particle count (integer, not float) — atomic for race-free concurrent inserts
    fd : u32,               // free density field (Q16_16 fixed-point raw bits)
    voltage_mode : u32,     // 0=STORE, 1=COMPUTE, 2=APPROX, 3=MORPHIC
    particle_count : atomic<u32>, // explicit particle count — atomic for race-free concurrent inserts
    max_neighbor : u32,     // max neighbor density (Q16_16 raw bits)
}

struct Params {
    threshold : u32,        // filter threshold (integer density)
    count : u32,            // number of elements
    pad0 : u32,
    pad1 : u32,
};

@group(0) @binding(0) var<storage, read_write> grid : array<Cell, 4096>;
@group(0) @binding(1) var<storage, read_write> filterMask : array<u32, 4096>;
@group(0) @binding(2) var<storage, read_write> sortIndex : array<u32, 4096>;
@group(0) @binding(3) var<uniform> params : Params;

// ============================================================
// Insert shader — atomicAdd particle into cell
// Dispatch with 1 thread per particle batch
// ============================================================

struct ParticleEntry {
    cell_idx : u32,   // pre-computed hash = x + y*16 + z*256
    count : u32,
};

@group(0) @binding(4) var<storage, read> particles : array<ParticleEntry>;

@compute @workgroup_size(64)
fn insertShader(@builtin(global_invocation_id) gid : vec3<u32>) {
    let idx = gid.x;
    if (idx >= params.count) { return; }
    let pe = particles[idx];
    let ci = pe.cell_idx % GRID_SIZE;
    // Decode cell coordinates from hash
    let cx = ci % GRID_DIM;
    let cy = (ci / GRID_DIM) % GRID_DIM;
    let cz = ci / (GRID_DIM * GRID_DIM);
    // Set coordinates on first insert
    if (atomicLoad(&grid[ci].particle_count) == 0u) {
        grid[ci].x = cx;
        grid[ci].y = cy;
        grid[ci].z = cz;
    }
    // FIX: atomicAdd prevents data race when multiple threads insert into the same cell
    atomicAdd(&grid[ci].particle_count, pe.count);
    atomicAdd(&grid[ci].density, pe.count);
}

// ============================================================
// Clear shader — zero all cells
// ============================================================

@compute @workgroup_size(64)
fn clearShader(@builtin(global_invocation_id) gid : vec3<u32>) {
    let idx = gid.x;
    if (idx >= GRID_SIZE) { return; }
    grid[idx].x = idx % GRID_DIM;
    grid[idx].y = (idx / GRID_DIM) % GRID_DIM;
    grid[idx].z = idx / (GRID_DIM * GRID_DIM);
    atomicStore(&grid[idx].density, 0u);
    grid[idx].fd = 0u;
    grid[idx].voltage_mode = 0u;
    atomicStore(&grid[idx].particle_count, 0u);
    grid[idx].max_neighbor = 0u;
    filterMask[idx] = 0u;
    sortIndex[idx] = idx;
}

// ============================================================
// Neighbor shader — 3×3×3 scan, compute max_neighbor
// ============================================================

@compute @workgroup_size(64)
fn neighborShader(@builtin(global_invocation_id) gid : vec3<u32>) {
    let idx = gid.x;
    if (idx >= GRID_SIZE) { return; }
    let cx = idx % GRID_DIM;
    let cy = (idx / GRID_DIM) % GRID_DIM;
    let cz = idx / (GRID_DIM * GRID_DIM);
    var maxD : u32 = 0u;
    for (var dz : i32 = -1; dz <= 1; dz++) {
        for (var dy : i32 = -1; dy <= 1; dy++) {
            for (var dx : i32 = -1; dx <= 1; dx++) {
                let nx = (cx + u32(dx + 16)) % GRID_DIM;
                let ny = (cy + u32(dy + 16)) % GRID_DIM;
                let nz = (cz + u32(dz + 16)) % GRID_DIM;
                let ni = nx + ny * GRID_DIM + nz * GRID_DIM * GRID_DIM;
                let d = atomicLoad(&grid[ni].density);
                if (d > maxD) {
                    maxD = d;
                }
            }
        }
    }
    grid[idx].max_neighbor = maxD;
}

// ============================================================
// Filter shader — predicate: density > threshold → mask = 1
// ============================================================

@compute @workgroup_size(64)
fn filterShader(@builtin(global_invocation_id) gid : vec3<u32>) {
    let idx = gid.x;
    if (idx >= GRID_SIZE) { return; }
    filterMask[idx] = select(0u, 1u, atomicLoad(&grid[idx].density) > params.threshold);
}

// ============================================================
// Sort shader — parallel bitonic sort on density column
// sortIndex stores indices, sorted by grid[idx].density descending
// ============================================================

@compute @workgroup_size(256)
fn sortShader(@builtin(local_invocation_id) lid : vec3<u32>,
              @builtin(global_invocation_id) gid : vec3<u32>) {
    // Bitonic sort stages — dispatched in multiple passes from JS
    // Each invocation handles one compare-and-swap
    let idx = gid.x;
    if (idx >= GRID_SIZE) { return; }

    // Read stage/step from params (packed into threshold/count)
    let stage = params.threshold;   // repurposed for sort params
    let step  = params.count;

    let blockSize = 1u << (stage + 1u);
    let halfBlock = 1u << step;

    let blockOffset = idx & ~(halfBlock - 1u);
    let elemIdx = idx;
    let partner = elemIdx ^ (halfBlock);

    if (partner >= GRID_SIZE) { return; }
    if (elemIdx >= partner) { return; }

    // Determine sort direction
    let ascending = ((elemIdx / blockSize) % 2u) == 0u;

    let a = sortIndex[elemIdx];
    let b = sortIndex[partner];
    let da = atomicLoad(&grid[a].density);
    let db = atomicLoad(&grid[b].density);

    if (ascending && da < db) || (!ascending && da > db) {
        sortIndex[elemIdx] = b;
        sortIndex[partner] = a;
    }
}

// ============================================================
// Aggregate shader — parallel reduction (sum, count, min, max)
// First pass: per-block reduction into partial results
// ============================================================

struct AggregateResult {
    sum : atomic<u32>,  // FIX: atomic to prevent race when multiple workgroups accumulate
    count : u32,
    min_val : u32,
    max_val : u32,
};

@group(0) @binding(5) var<storage, read_write> aggResult : AggregateResult;
@group(0) @binding(6) var<storage, read_write> scratch : array<u32, 4096>;

@compute @workgroup_size(64)
fn aggregateShader(@builtin(global_invocation_id) gid : vec3<u32>,
                   @builtin(local_invocation_id) lid : vec3<u32>,
                   @builtin(workgroup_id) wid : vec3<u32>) {
    let idx = gid.x;
    var val : u32 = 0u;
    if (idx < GRID_SIZE && filterMask[idx] != 0u) {
        val = atomicLoad(&grid[idx].density);
    }
    scratch[idx] = val;

    // Workgroup barrier
    workgroupBarrier();

    // Simple reduction within workgroup
    for (var stride : u32 = 32u; stride > 0u; stride >>= 1u) {
        if (lid.x < stride && (idx + stride) < GRID_SIZE) {
            scratch[idx] += scratch[idx + stride];
        }
        workgroupBarrier();
    }

    // First thread in each workgroup writes block sum
    if (lid.x == 0u) {
        // FIX: atomicAdd prevents race when multiple workgroups accumulate into aggResult.sum
        atomicAdd(&aggResult.sum, scratch[idx]);
    }
}

// ============================================================
// Render shaders — instanced quads positioned by cell x/y/z
// ============================================================

struct Uniforms {
    mvp : mat4x4<f32>,
    cameraPos : vec3<f32>,
    time : f32,
};

struct VertexOutput {
    @builtin(position) position : vec4<f32>,
    @location(0) color : vec4<f32>,
    @location(1) uv : vec2<f32>,
};

@group(0) @binding(10) var<uniform> uniforms : Uniforms;

// Voltage mode color mapping
fn modeColor(mode : u32) -> vec3<f32> {
    switch mode {
        case 0u: { return vec3<f32>(1.0, 0.2, 0.2); }   // STORE = red
        case 1u: { return vec3<f32>(0.2, 1.0, 0.2); }   // COMPUTE = green
        case 2u: { return vec3<f32>(0.2, 0.2, 1.0); }   // APPROX = blue
        case 3u: { return vec3<f32>(1.0, 1.0, 1.0); }   // MORPHIC = white
        default: { return vec3<f32>(0.5, 0.5, 0.5); }
    }
}

@vertex
fn vertexMain(@location(0) quadPos : vec2<f32>,       // quad vertex [-0.5, 0.5]
              @location(1) instancePos : vec3<f32>,    // cell world position
              @location(2) instanceMode : u32,         // voltage_mode
              @location(3) instanceDensity : f32) -> VertexOutput {
    var out : VertexOutput;

    // Billboard quad offset (screen-facing)
    let scale = 0.4;
    let offset = quadPos * scale;

    // Position in world space
    let worldPos = instancePos + vec3<f32>(offset.x, offset.y, 0.0);

    out.position = uniforms.mvp * vec4<f32>(worldPos, 1.0);
    let alpha = clamp(instanceDensity / 100.0, 0.05, 1.0);
    out.color = vec4<f32>(modeColor(instanceMode), alpha);
    out.uv = quadPos + 0.5;

    return out;
}

@fragment
fn fragmentMain(in : VertexOutput) -> @location(0) vec4<f32> {
    // Discard transparent pixels
    if (in.color.a < 0.01) {
        discard;
    }
    // Rounded quad with soft edge
    let d = length(in.uv - 0.5) * 2.0;
    let alpha = in.color.a * smoothstep(1.0, 0.8, d);
    return vec4<f32>(in.color.rgb, alpha);
}
