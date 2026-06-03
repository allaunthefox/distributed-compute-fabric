// ═══════════════════════════════════════════════════════════════════════════
// grid-storage-optimized.js — Morton-code indexed spatial hash grid driver
//
// Optimizations over grid-storage.js:
//   1. Morton code hash (Z-order curve) for spatial locality
//   2. SoA layout (separate buffer per field) for coalesced access
//   3. Persistent kernel (grid stays in GPU memory across frames)
//   4. Memory bandwidth monitoring
//   5. Arrow/Parquet-compatible export (SoA is already columnar)
//   6. Benchmark mode (p50/p99 latency)
// ═══════════════════════════════════════════════════════════════════════════

const GRID_SIZE = 16;
const CELL_COUNT = GRID_SIZE * GRID_SIZE * GRID_SIZE;  // 4096
const WORKGROUP_SIZE = 256;

// ── Morton Code (Z-order curve) ────────────────────────────────────────────

function spreadBits(v) {
    v = v & 0x3FF;
    v = (v | (v << 16)) & 0x30000FF;
    v = (v | (v << 8)) & 0x300F00F;
    v = (v | (v << 4)) & 0x30C30C3;
    v = (v | (v << 2)) & 0x9249249;
    return v;
}

function mortonCode(x, y, z) {
    return spreadBits(x) | (spreadBits(y) << 1) | (spreadBits(z) << 2);
}

function compactBits(v) {
    v = v & 0x9249249;
    v = (v | (v >> 2)) & 0x30C30C3;
    v = (v | (v >> 4)) & 0x300F00F;
    v = (v | (v >> 8)) & 0x30000FF;
    v = (v | (v >> 16)) & 0x3FF;
    return v;
}

function mortonDecode(code) {
    return [
        compactBits(code),
        compactBits(code >> 1),
        compactBits(code >> 2),
    ];
}

// ── Bit Pack/Unpack ────────────────────────────────────────────────────────

function packXYZ(x, y, z, mode) {
    return (x & 0x3FF) | ((y & 0x3FF) << 10) | ((z & 0x3FF) << 20) | ((mode & 3) << 30);
}

function unpackXYZ(packed) {
    return {
        x: packed & 0x3FF,
        y: (packed >> 10) & 0x3FF,
        z: (packed >> 20) & 0x3FF,
        mode: packed >>> 30,
    };
}

// ── GridStorage Class ──────────────────────────────────────────────────────

export class GridStorage {
    constructor(device) {
        this.device = device;
        this.initialized = false;
        this.stats = {
            totalInserts: 0,
            totalFilters: 0,
            totalSorts: 0,
            totalNeighbors: 0,
            frameTimes: [],
        };
    }

    async init(shaderModule) {
        this.shaderModule = shaderModule;

        // ── SoA Buffers (one per field for coalesced access) ────────────
        this.xyzBuffer = this.device.createBuffer({
            size: CELL_COUNT * 4,
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST,
        });

        this.densityBuffer = this.device.createBuffer({
            size: CELL_COUNT * 4,
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST,
        });

        this.fdBuffer = this.device.createBuffer({
            size: CELL_COUNT * 4,
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST,
        });

        this.particleCountBuffer = this.device.createBuffer({
            size: CELL_COUNT * 4,
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST,
        });

        this.maxNeighborBuffer = this.device.createBuffer({
            size: CELL_COUNT * 4,
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST,
        });

        this.filterMaskBuffer = this.device.createBuffer({
            size: Math.ceil(CELL_COUNT / 32) * 4,
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST,
        });

        this.sortIndexBuffer = this.device.createBuffer({
            size: CELL_COUNT * 4,
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST,
        });

        this.statsBuffer = this.device.createBuffer({
            size: 16 * 3 * 4,  // 16 workgroups × 3 stats
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC,
        });

        // ── Staging buffers for readback ────────────────────────────────
        this.stagingDensity = this.device.createBuffer({
            size: CELL_COUNT * 4,
            usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST,
        });

        this.stagingXYZ = this.device.createBuffer({
            size: CELL_COUNT * 4,
            usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST,
        });

        this.stagingStats = this.device.createBuffer({
            size: 16 * 3 * 4,
            usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST,
        });

        // ── Uniform buffers ─────────────────────────────────────────────
        this.particleCountUniform = this.device.createBuffer({
            size: 4,
            usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
        });

        this.filterThresholdUniform = this.device.createBuffer({
            size: 4,
            usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
        });

        // ── Bind group layouts ──────────────────────────────────────────
        this.storageBindGroupLayout = this.device.createBindGroupLayout({
            entries: [
                { binding: 0, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
                { binding: 1, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
                { binding: 2, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
                { binding: 3, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
                { binding: 4, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
                { binding: 5, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
                { binding: 6, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
                { binding: 7, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
            ],
        });

        this.storageBindGroup = this.device.createBindGroup({
            layout: this.storageBindGroupLayout,
            entries: [
                { binding: 0, resource: { buffer: this.xyzBuffer } },
                { binding: 1, resource: { buffer: this.densityBuffer } },
                { binding: 2, resource: { buffer: this.fdBuffer } },
                { binding: 3, resource: { buffer: this.particleCountBuffer } },
                { binding: 4, resource: { buffer: this.maxNeighborBuffer } },
                { binding: 5, resource: { buffer: this.filterMaskBuffer } },
                { binding: 6, resource: { buffer: this.sortIndexBuffer } },
                { binding: 7, resource: { buffer: this.statsBuffer } },
            ],
        });

        // ── Compute pipelines ───────────────────────────────────────────
        const pipelineLayout = this.device.createPipelineLayout({
            bindGroupLayouts: [this.storageBindGroupLayout],
        });

        this.clearPipeline = this.device.createComputePipeline({
            layout: pipelineLayout,
            compute: { module: shaderModule, entryPoint: 'clearShader' },
        });

        this.neighborPipeline = this.device.createComputePipeline({
            layout: pipelineLayout,
            compute: { module: shaderModule, entryPoint: 'neighborShader' },
        });

        this.sortPipeline = this.device.createComputePipeline({
            layout: pipelineLayout,
            compute: { module: shaderModule, entryPoint: 'sortShader' },
        });

        this.aggregatePipeline = this.device.createComputePipeline({
            layout: pipelineLayout,
            compute: { module: shaderModule, entryPoint: 'aggregateShader' },
        });

        this.initialized = true;
    }

    // ── Operations ──────────────────────────────────────────────────────

    clear() {
        const encoder = this.device.createCommandEncoder();
        const pass = encoder.beginComputePass();
        pass.setPipeline(this.clearPipeline);
        pass.setBindGroup(0, this.storageBindGroup);
        pass.dispatchWorkgroups(Math.ceil(CELL_COUNT / WORKGROUP_SIZE));
        pass.end();
        this.device.queue.submit([encoder.finish()]);
    }

    async insert(particles) {
        const t0 = performance.now();

        // Upload particle positions
        const xArr = new Float32Array(particles.length);
        const yArr = new Float32Array(particles.length);
        const zArr = new Float32Array(particles.length);
        for (let i = 0; i < particles.length; i++) {
            xArr[i] = particles[i][0];
            yArr[i] = particles[i][1];
            zArr[i] = particles[i][2];
        }

        const xBuf = this.device.createBuffer({
            size: xArr.byteLength,
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
        });
        const yBuf = this.device.createBuffer({ size: yArr.byteLength, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST });
        const zBuf = this.device.createBuffer({ size: zArr.byteLength, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST });

        this.device.queue.writeBuffer(xBuf, 0, xArr);
        this.device.queue.writeBuffer(yBuf, 0, yArr);
        this.device.queue.writeBuffer(zBuf, 0, zArr);
        this.device.queue.writeBuffer(this.particleCountUniform, 0, new Uint32Array([particles.length]));

        // Create insert bind group
        const insertBindGroup = this.device.createBindGroup({
            layout: this.device.createBindGroupLayout({
                entries: [
                    { binding: 0, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
                    { binding: 1, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
                    { binding: 2, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
                    { binding: 3, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'uniform' } },
                ],
            }),
            entries: [
                { binding: 0, resource: { buffer: xBuf } },
                { binding: 1, resource: { buffer: yBuf } },
                { binding: 2, resource: { buffer: zBuf } },
                { binding: 3, resource: { buffer: this.particleCountUniform } },
            ],
        });

        const encoder = this.device.createCommandEncoder();
        const pass = encoder.beginComputePass();
        pass.setPipeline(this.device.createComputePipeline({
            layout: this.device.createPipelineLayout({
                bindGroupLayouts: [this.storageBindGroupLayout,
                    this.device.createBindGroupLayout({
                        entries: [
                            { binding: 0, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
                            { binding: 1, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
                            { binding: 2, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
                            { binding: 3, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'uniform' } },
                        ],
                    })],
            }),
            compute: { module: this.shaderModule, entryPoint: 'insertShader' },
        }));
        pass.setBindGroup(0, this.storageBindGroup);
        pass.setBindGroup(1, insertBindGroup);
        pass.dispatchWorkgroups(Math.ceil(particles.length / WORKGROUP_SIZE));
        pass.end();
        this.device.queue.submit([encoder.finish()]);

        await this.device.queue.onSubmittedWorkDone();

        xBuf.destroy();
        yBuf.destroy();
        zBuf.destroy();

        this.stats.totalInserts += particles.length;
        this.stats.frameTimes.push(performance.now() - t0);
    }

    neighbor() {
        const t0 = performance.now();
        const encoder = this.device.createCommandEncoder();
        const pass = encoder.beginComputePass();
        pass.setPipeline(this.neighborPipeline);
        pass.setBindGroup(0, this.storageBindGroup);
        // 4×4×4 workgroups of 4×4×4 threads = 16×16×16 cells
        pass.dispatchWorkgroups(4, 4, 4);
        pass.end();
        this.device.queue.submit([encoder.finish()]);
        this.stats.totalNeighbors++;
        this.stats.frameTimes.push(performance.now() - t0);
    }

    sort() {
        const t0 = performance.now();
        const encoder = this.device.createCommandEncoder();
        const pass = encoder.beginComputePass();
        pass.setPipeline(this.sortPipeline);
        pass.setBindGroup(0, this.storageBindGroup);
        pass.dispatchWorkgroups(Math.ceil(CELL_COUNT / WORKGROUP_SIZE));
        pass.end();
        this.device.queue.submit([encoder.finish()]);
        this.stats.totalSorts++;
        this.stats.frameTimes.push(performance.now() - t0);
    }

    async aggregate() {
        const encoder = this.device.createCommandEncoder();
        const pass = encoder.beginComputePass();
        pass.setPipeline(this.aggregatePipeline);
        pass.setBindGroup(0, this.storageBindGroup);
        pass.dispatchWorkgroups(Math.ceil(CELL_COUNT / WORKGROUP_SIZE));
        pass.end();

        // Copy stats to staging buffer
        encoder.copyBufferToBuffer(this.statsBuffer, 0, this.stagingStats, 0, 16 * 3 * 4);

        this.device.queue.submit([encoder.finish()]);
        await this.device.queue.onSubmittedWorkDone();

        // Read back stats
        await this.stagingStats.mapAsync(GPUMapMode.READ);
        const data = new Uint32Array(this.stagingStats.getMappedRange());
        let totalDensity = 0, maxDensity = 0, occupiedCells = 0;
        for (let i = 0; i < 16; i++) {
            totalDensity += data[i * 3 + 0];
            maxDensity = Math.max(maxDensity, data[i * 3 + 1]);
            occupiedCells += data[i * 3 + 2];
        }
        this.stagingStats.unmap();

        return { totalDensity, maxDensity, occupiedCells };
    }

    // ── Readback ────────────────────────────────────────────────────────

    async readGrid() {
        const encoder = this.device.createCommandEncoder();
        encoder.copyBufferToBuffer(this.densityBuffer, 0, this.stagingDensity, 0, CELL_COUNT * 4);
        encoder.copyBufferToBuffer(this.xyzBuffer, 0, this.stagingXYZ, 0, CELL_COUNT * 4);
        this.device.queue.submit([encoder.finish()]);
        await this.device.queue.onSubmittedWorkDone();

        await this.stagingDensity.mapAsync(GPUMapMode.READ);
        const densityData = new Uint32Array(this.stagingDensity.getMappedRange()).slice();
        this.stagingDensity.unmap();

        await this.stagingXYZ.mapAsync(GPUMapMode.READ);
        const xyzData = new Uint32Array(this.stagingXYZ.getMappedRange()).slice();
        this.stagingXYZ.unmap();

        const grid = [];
        for (let i = 0; i < CELL_COUNT; i++) {
            const { x, y, z, mode } = unpackXYZ(xyzData[i]);
            grid.push({
                index: i,
                morton: i,
                x, y, z,
                density: densityData[i],
                voltage_mode: mode,
            });
        }
        return grid;
    }

    // ── Export (SoA is already columnar — zero copy) ─────────────────────

    exportParquetCompatible() {
        return {
            schema: 'spatial_hash_soa_v1',
            grid_size: GRID_SIZE,
            cell_count: CELL_COUNT,
            layout: 'morton_ordered',
            columns: {
                xyz_packed: { type: 'u32', buffer: 'xyzBuffer' },
                density: { type: 'u32', buffer: 'densityBuffer' },
                fd_q16: { type: 'u32', buffer: 'fdBuffer' },
                particle_count: { type: 'u32', buffer: 'particleCountBuffer' },
                max_neighbor: { type: 'u32', buffer: 'maxNeighborBuffer' },
            },
            note: 'SoA layout is Arrow/Parquet compatible — reference buffers directly',
        };
    }

    // ── Performance Monitoring ───────────────────────────────────────────

    getStats() {
        const times = this.stats.frameTimes;
        const sorted = [...times].sort((a, b) => a - b);
        return {
            totalInserts: this.stats.totalInserts,
            totalFilters: this.stats.totalFilters,
            totalSorts: this.stats.totalSorts,
            totalNeighbors: this.stats.totalNeighbors,
            frameCount: times.length,
            p50: sorted[Math.floor(sorted.length * 0.5)] || 0,
            p99: sorted[Math.floor(sorted.length * 0.99)] || 0,
            mean: times.reduce((a, b) => a + b, 0) / times.length || 0,
            // Memory bandwidth estimate:
            // Each cell is 16 bytes (compressed), read+write = 32 bytes
            // Neighbor scan: 4096 cells × 32 bytes = 128 KB
            bandwidthPerOp: (CELL_COUNT * 32) / 1024,  // KB
        };
    }

    destroy() {
        this.xyzBuffer?.destroy();
        this.densityBuffer?.destroy();
        this.fdBuffer?.destroy();
        this.particleCountBuffer?.destroy();
        this.maxNeighborBuffer?.destroy();
        this.filterMaskBuffer?.destroy();
        this.sortIndexBuffer?.destroy();
        this.statsBuffer?.destroy();
        this.stagingDensity?.destroy();
        this.stagingXYZ?.destroy();
        this.stagingStats?.destroy();
    }
}

export { mortonCode, mortonDecode, packXYZ, unpackXYZ, spreadBits, compactBits };
