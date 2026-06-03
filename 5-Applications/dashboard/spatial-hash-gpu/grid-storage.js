// ============================================================
// grid-storage.js — JavaScript module wrapping WebGPU operations
// Maps to LyteNyte-style API: insert, filter, sort, group
// Returns results as typed arrays (Uint32Array, Float32Array)
// ============================================================

const GRID_DIM = 16;
const GRID_SIZE = GRID_DIM * GRID_DIM * GRID_DIM; // 4096
const CELL_STRIDE = 8; // 8 × u32 per cell

export class GridStorage {
  constructor() {
    this.device = null;
    this.gridBuffer = null;
    this.filterMaskBuffer = null;
    this.sortIndexBuffer = null;
    this.paramsBuffer = null;
    this.particlesBuffer = null;
    this.aggResultBuffer = null;
    this.scratchBuffer = null;
    this.computePipelines = {};
    this.renderPipeline = null;
    this.bindGroupLayout = null;
    this.bindGroup = null;
    this.initialized = false;
    this.stats = {
      cellCount: GRID_SIZE,
      filterMatches: 0,
      maxDensity: 0,
      totalParticles: 0,
    };
  }

  async init(device) {
    this.device = device;
    this._createBuffers();
    this._createBindGroupLayout();
    this._createBindGroup();
    await this._createComputePipelines();
    this.initialized = true;
    return this;
  }

  _createBuffers() {
    const size = GRID_SIZE * CELL_STRIDE * 4; // 4 bytes per u32

    this.gridBuffer = this.device.createBuffer({
      size,
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST,
    });

    this.filterMaskBuffer = this.device.createBuffer({
      size: GRID_SIZE * 4,
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC,
    });

    this.sortIndexBuffer = this.device.createBuffer({
      size: GRID_SIZE * 4,
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC,
    });

    this.paramsBuffer = this.device.createBuffer({
      size: 16, // 4 × u32
      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
    });

    // Particle entry buffer (max 100k particles)
    this.particlesBuffer = this.device.createBuffer({
      size: 100000 * 8, // 2 × u32 per particle
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
    });

    this.aggResultBuffer = this.device.createBuffer({
      size: 16, // 4 × u32
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC,
    });

    this.scratchBuffer = this.device.createBuffer({
      size: GRID_SIZE * 4,
      usage: GPUBufferUsage.STORAGE,
    });
  }

  _createBindGroupLayout() {
    this.bindGroupLayout = this.device.createBindGroupLayout({
      entries: [
        { binding: 0, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
        { binding: 1, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
        { binding: 2, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
        { binding: 3, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'uniform' } },
        { binding: 4, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
        { binding: 5, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
        { binding: 6, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
      ],
    });
  }

  _createBindGroup() {
    this.bindGroup = this.device.createBindGroup({
      layout: this.bindGroupLayout,
      entries: [
        { binding: 0, resource: { buffer: this.gridBuffer } },
        { binding: 1, resource: { buffer: this.filterMaskBuffer } },
        { binding: 2, resource: { buffer: this.sortIndexBuffer } },
        { binding: 3, resource: { buffer: this.paramsBuffer } },
        { binding: 4, resource: { buffer: this.particlesBuffer } },
        { binding: 5, resource: { buffer: this.aggResultBuffer } },
        { binding: 6, resource: { buffer: this.scratchBuffer } },
      ],
    });
  }

  async _createComputePipelines() {
    const shaderCode = await fetch('./shaders.wgsl').then(r => r.text());
    const shaderModule = this.device.createShaderModule({ code: shaderCode });

    const pipelineLayout = this.device.createPipelineLayout({
      bindGroupLayouts: [this.bindGroupLayout],
    });

    const shaderNames = [
      'insertShader',
      'clearShader',
      'neighborShader',
      'filterShader',
      'sortShader',
      'aggregateShader',
    ];

    for (const name of shaderNames) {
      this.computePipelines[name] = this.device.createComputePipeline({
        layout: pipelineLayout,
        compute: {
          module: shaderModule,
          entryPoint: name,
        },
      });
    }
  }

  // ── LyteNyte-style API ──────────────────────────────────

  /**
   * insert(rows) — Insert particles into the spatial hash grid.
   * Each row is { x, y, z } or { cell_idx, count }.
   * Coordinates are quantized to 0..15 and hashed.
   */
  insert(rows) {
    const entries = new Uint32Array(rows.length * 2);
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      let idx;
      if (r.cell_idx !== undefined) {
        idx = r.cell_idx;
      } else {
        const x = (r.x | 0) % GRID_DIM;
        const y = (r.y | 0) % GRID_DIM;
        const z = (r.z | 0) % GRID_DIM;
        idx = x + y * GRID_DIM + z * GRID_DIM * GRID_DIM;
      }
      entries[i * 2] = idx;
      entries[i * 2 + 1] = r.count || 1;
    }

    this.device.queue.writeBuffer(this.particlesBuffer, 0, entries);
    this.device.queue.writeBuffer(this.paramsBuffer, 0,
      new Uint32Array([0, rows.length, 0, 0]));

    const encoder = this.device.createCommandEncoder();
    const pass = encoder.beginComputePass();
    pass.setPipeline(this.computePipelines.insertShader);
    pass.setBindGroup(0, this.bindGroup);
    pass.dispatchWorkgroups(Math.ceil(rows.length / 64));
    pass.end();
    this.device.queue.submit([encoder.finish()]);

    this.stats.totalParticles += rows.length;
  }

  /**
   * clear() — Zero all cells and masks.
   */
  clear() {
    const encoder = this.device.createCommandEncoder();
    const pass = encoder.beginComputePass();
    pass.setPipeline(this.computePipelines.clearShader);
    pass.setBindGroup(0, this.bindGroup);
    pass.dispatchWorkgroups(Math.ceil(GRID_SIZE / 64));
    pass.end();
    this.device.queue.submit([encoder.finish()]);

    this.stats.totalParticles = 0;
    this.stats.filterMatches = 0;
    this.stats.maxDensity = 0;
  }

  /**
   * filter(predicate) — Filter cells by density threshold.
   * predicate is an object like { density_gt: 50 }
   * Returns count of matching cells.
   */
  filter(predicate) {
    const threshold = predicate.density_gt ?? predicate.threshold ?? 0;
    this.device.queue.writeBuffer(this.paramsBuffer, 0,
      new Uint32Array([threshold, 0, 0, 0]));

    const encoder = this.device.createCommandEncoder();
    const pass = encoder.beginComputePass();
    pass.setPipeline(this.computePipelines.filterShader);
    pass.setBindGroup(0, this.bindGroup);
    pass.dispatchWorkgroups(Math.ceil(GRID_SIZE / 64));
    pass.end();
    this.device.queue.submit([encoder.finish()]);

    return this._readFilterCount();
  }

  /**
   * sort(column) — Sort grid cells by the given column (bitonic sort on GPU).
   * Currently supports 'density' column. Runs all bitonic stages.
   */
  sort(column = 'density') {
    const numStages = Math.ceil(Math.log2(GRID_SIZE));
    const encoder = this.device.createCommandEncoder();

    for (let stage = 0; stage < numStages; stage++) {
      for (let step = stage; step >= 0; step--) {
        // Write sort params into threshold/count fields
        this.device.queue.writeBuffer(this.paramsBuffer, 0,
          new Uint32Array([stage, step, 0, 0]));

        const pass = encoder.beginComputePass();
        pass.setPipeline(this.computePipelines.sortShader);
        pass.setBindGroup(0, this.bindGroup);
        pass.dispatchWorkgroups(Math.ceil(GRID_SIZE / 256));
        pass.end();
      }
    }

    this.device.queue.submit([encoder.finish()]);
  }

  /**
   * neighbor() — Compute max neighbor density for each cell (3×3×3 scan).
   */
  neighbor() {
    const encoder = this.device.createCommandEncoder();
    const pass = encoder.beginComputePass();
    pass.setPipeline(this.computePipelines.neighborShader);
    pass.setBindGroup(0, this.bindGroup);
    pass.dispatchWorkgroups(Math.ceil(GRID_SIZE / 64));
    pass.end();
    this.device.queue.submit([encoder.finish()]);
  }

  /**
   * aggregate() — Parallel reduction: sum, count, min, max of filtered densities.
   */
  aggregate() {
    // Reset aggregate result
    this.device.queue.writeBuffer(this.aggResultBuffer, 0,
      new Uint32Array([0, 0, 0xFFFFFFFF, 0]));

    const encoder = this.device.createCommandEncoder();
    const pass = encoder.beginComputePass();
    pass.setPipeline(this.computePipelines.aggregateShader);
    pass.setBindGroup(0, this.bindGroup);
    pass.dispatchWorkgroups(Math.ceil(GRID_SIZE / 64));
    pass.end();
    this.device.queue.submit([encoder.finish()]);
  }

  /**
   * group(column) — Group cells by voltage_mode, return counts per mode.
   * This is a CPU-side post-process after reading grid data.
   */
  async group(column = 'voltage_mode') {
    const gridData = await this.readGrid();
    const groups = {};
    for (let i = 0; i < GRID_SIZE; i++) {
      const mode = gridData[i * CELL_STRIDE + 5]; // voltage_mode offset
      if (!groups[mode]) groups[mode] = [];
      groups[mode].push(i);
    }
    return groups;
  }

  // ── Readback methods ─────────────────────────────────────

  /**
   * readGrid() — Read full grid buffer as Uint32Array.
   */
  async readGrid() {
    const size = GRID_SIZE * CELL_STRIDE * 4;
    const staging = this.device.createBuffer({
      size,
      usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST,
    });

    const encoder = this.device.createCommandEncoder();
    encoder.copyBufferToBuffer(this.gridBuffer, 0, staging, 0, size);
    this.device.queue.submit([encoder.finish()]);

    await staging.mapAsync(GPUMapMode.READ);
    const data = new Uint32Array(staging.getMappedRange().slice(0));
    staging.unmap();
    staging.destroy();

    return data;
  }

  /**
   * readFilterMask() — Read filter mask as Uint32Array (0 or 1 per cell).
   */
  async readFilterMask() {
    const staging = this.device.createBuffer({
      size: GRID_SIZE * 4,
      usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST,
    });

    const encoder = this.device.createCommandEncoder();
    encoder.copyBufferToBuffer(this.filterMaskBuffer, 0, staging, 0, GRID_SIZE * 4);
    this.device.queue.submit([encoder.finish()]);

    await staging.mapAsync(GPUMapMode.READ);
    const data = new Uint32Array(staging.getMappedRange().slice(0));
    staging.unmap();
    staging.destroy();

    return data;
  }

  /**
   * readSortIndex() — Read sorted indices as Uint32Array.
   */
  async readSortIndex() {
    const staging = this.device.createBuffer({
      size: GRID_SIZE * 4,
      usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST,
    });

    const encoder = this.device.createCommandEncoder();
    encoder.copyBufferToBuffer(this.sortIndexBuffer, 0, staging, 0, GRID_SIZE * 4);
    this.device.queue.submit([encoder.finish()]);

    await staging.mapAsync(GPUMapMode.READ);
    const data = new Uint32Array(staging.getMappedRange().slice(0));
    staging.unmap();
    staging.destroy();

    return data;
  }

  async _readFilterCount() {
    const mask = await this.readFilterMask();
    let count = 0;
    for (let i = 0; i < mask.length; i++) {
      if (mask[i]) count++;
    }
    this.stats.filterMatches = count;
    return count;
  }

  /**
   * readStats() — Compute grid statistics from a grid readback.
   */
  async readStats() {
    const gridData = await this.readGrid();
    let maxDensity = 0;
    let totalParticles = 0;
    let occupiedCells = 0;
    const modeCounts = [0, 0, 0, 0];

    for (let i = 0; i < GRID_SIZE; i++) {
      const density = gridData[i * CELL_STRIDE + 3];
      const mode = gridData[i * CELL_STRIDE + 5];
      if (density > 0) occupiedCells++;
      if (density > maxDensity) maxDensity = density;
      totalParticles += density;
      if (mode < 4) modeCounts[mode]++;
    }

    this.stats = {
      cellCount: GRID_SIZE,
      occupiedCells,
      filterMatches: this.stats.filterMatches,
      maxDensity,
      totalParticles,
      modeCounts,
    };

    return this.stats;
  }

  /**
   * exportParquetCompatible() — Export grid state as Arrow/Parquet-compatible
   * columnar format (JSON with typed arrays).
   */
  async exportParquetCompatible() {
    const gridData = await this.readGrid();
    const columns = {
      x: new Uint32Array(GRID_SIZE),
      y: new Uint32Array(GRID_SIZE),
      z: new Uint32Array(GRID_SIZE),
      density: new Uint32Array(GRID_SIZE),
      fd: new Uint32Array(GRID_SIZE),
      voltage_mode: new Uint32Array(GRID_SIZE),
      particle_count: new Uint32Array(GRID_SIZE),
      max_neighbor: new Uint32Array(GRID_SIZE),
    };

    for (let i = 0; i < GRID_SIZE; i++) {
      const off = i * CELL_STRIDE;
      columns.x[i] = gridData[off];
      columns.y[i] = gridData[off + 1];
      columns.z[i] = gridData[off + 2];
      columns.density[i] = gridData[off + 3];
      columns.fd[i] = gridData[off + 4];
      columns.voltage_mode[i] = gridData[off + 5];
      columns.particle_count[i] = gridData[off + 6];
      columns.max_neighbor[i] = gridData[off + 7];
    }

    return {
      schema: {
        fields: [
          { name: 'x', type: 'u32' },
          { name: 'y', type: 'u32' },
          { name: 'z', type: 'u32' },
          { name: 'density', type: 'u32' },
          { name: 'fd', type: 'u32' },
          { name: 'voltage_mode', type: 'u32' },
          { name: 'particle_count', type: 'u32' },
          { name: 'max_neighbor', type: 'u32' },
        ],
        length: GRID_SIZE,
      },
      columns,
    };
  }

  /**
   * setVoltageModes() — Set voltage_mode for cells matching filter mask.
   */
  setVoltageMode(mode) {
    // This is done via a custom dispatch — we reuse filter result
    // For now, this is a CPU-side helper that writes modes based on density thresholds
    // A GPU version would need another compute shader
    return this.readGrid().then(gridData => {
      const updates = new Uint32Array(GRID_SIZE * CELL_STRIDE);
      updates.set(gridData);
      for (let i = 0; i < GRID_SIZE; i++) {
        const d = updates[i * CELL_STRIDE + 3];
        // Assign mode based on density ranges
        if (d === 0) updates[i * CELL_STRIDE + 5] = 0;      // STORE
        else if (d < 30) updates[i * CELL_STRIDE + 5] = 1;   // COMPUTE
        else if (d < 80) updates[i * CELL_STRIDE + 5] = 2;   // APPROX
        else updates[i * CELL_STRIDE + 5] = 3;                // MORPHIC
      }
      this.device.queue.writeBuffer(this.gridBuffer, 0, updates);
    });
  }

  destroy() {
    this.gridBuffer?.destroy();
    this.filterMaskBuffer?.destroy();
    this.sortIndexBuffer?.destroy();
    this.paramsBuffer?.destroy();
    this.particlesBuffer?.destroy();
    this.aggResultBuffer?.destroy();
    this.scratchBuffer?.destroy();
  }
}

export default GridStorage;
