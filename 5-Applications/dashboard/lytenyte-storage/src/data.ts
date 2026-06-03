/**
 * data.ts — Data layer for spatial hash grid visualization.
 *
 * Generates synthetic 16×16×16 spatial hash data (4096 cells).
 * In production, this would connect to a WebGPU buffer via SharedArrayBuffer
 * or postMessage from the compute shader. For now we generate representative data
 * that mimics what the GPU spatial hash would produce.
 */

export type VoltageMode = "STORE" | "COMPUTE" | "APPROX" | "MORPHIC";

export interface SpatialHashRow {
  id: string;
  x: number;
  y: number;
  z: number;
  density: number;       // 0..255
  fd: number;            // fractal dimension ~2.0..3.0
  voltage_mode: VoltageMode;
  particle_count: number;
  max_neighbor: number;
}

const GRID_SIZE = 16;
const VOLTAGE_MODES: VoltageMode[] = ["STORE", "COMPUTE", "APPROX", "MORPHIC"];

/** Deterministic seeded PRNG (xoshiro128**) */
function makeRng(seed: number) {
  let s0 = seed | 0;
  let s1 = (seed * 1664525 + 1013904223) | 0;
  let s2 = (s1 * 1664525 + 1013904223) | 0;
  let s3 = (s2 * 1664525 + 1013904223) | 0;

  return () => {
    const result = Math.imul(s1, 5) | 0;
    const t = s1 << 9;
    s2 ^= s0;
    s3 ^= s1;
    s1 ^= s2;
    s0 ^= s3;
    s2 ^= t;
    s3 = (s3 << 11) | (s3 >>> 21);
    return (result >>> 0) / 4294967296;
  };
}

/** Generate 4096 rows of synthetic spatial hash data */
export function generateSpatialHashData(): SpatialHashRow[] {
  const rng = makeRng(42);
  const rows: SpatialHashRow[] = [];

  for (let xi = 0; xi < GRID_SIZE; xi++) {
    for (let yi = 0; yi < GRID_SIZE; yi++) {
      for (let zi = 0; zi < GRID_SIZE; zi++) {
        // Density peaks in center, sparse at edges
        const cx = xi / GRID_SIZE - 0.5;
        const cy = yi / GRID_SIZE - 0.5;
        const cz = zi / GRID_SIZE - 0.5;
        const dist = Math.sqrt(cx * cx + cy * cy + cz * cz);
        const baseDensity = Math.max(0, 1 - dist * 3) * 200 + rng() * 55;

        // Fractal dimension correlates with density
        const fd = 2.0 + (baseDensity / 255) + (rng() - 0.5) * 0.2;

        // Voltage mode assignment: dense regions tend toward MORPHIC/COMPUTE
        let voltageMode: VoltageMode;
        if (baseDensity > 200) voltageMode = rng() > 0.5 ? "MORPHIC" : "COMPUTE";
        else if (baseDensity > 100) voltageMode = rng() > 0.5 ? "COMPUTE" : "APPROX";
        else voltageMode = rng() > 0.3 ? "STORE" : "APPROX";

        rows.push({
          id: `${xi}-${yi}-${zi}`,
          x: xi,
          y: yi,
          z: zi,
          density: Math.round(Math.min(255, Math.max(0, baseDensity))),
          fd: Math.round(fd * 100) / 100,
          voltage_mode: voltageMode,
          particle_count: Math.round(baseDensity * 0.8 + rng() * 40),
          max_neighbor: Math.round(6 + rng() * 20),
        });
      }
    }
  }

  return rows;
}

/**
 * Simulate a WebGPU buffer update — mutates density/particle_count
 * with small deltas to model real-time compute shader output.
 */
export function simulateBufferUpdate(rows: SpatialHashRow[]): SpatialHashRow[] {
  const rng = makeRng(Date.now());
  return rows.map((r) => {
    if (rng() > 0.1) return r; // Only update ~10% of cells per tick
    const dDensity = Math.round((rng() - 0.5) * 20);
    return {
      ...r,
      density: Math.min(255, Math.max(0, r.density + dDensity)),
      particle_count: Math.max(0, r.particle_count + Math.round(dDensity * 0.8)),
    };
  });
}

/**
 * Export rows to CSV string.
 */
export function exportToCSV(rows: SpatialHashRow[]): string {
  const header = "x,y,z,density,fd,voltage_mode,particle_count,max_neighbor";
  const body = rows
    .map(
      (r) =>
        `${r.x},${r.y},${r.z},${r.density},${r.fd},${r.voltage_mode},${r.particle_count},${r.max_neighbor}`
    )
    .join("\n");
  return `${header}\n${body}`;
}

/** Trigger a browser download of CSV data */
export function downloadCSV(rows: SpatialHashRow[]) {
  const csv = exportToCSV(rows);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "spatial-hash-export.csv";
  a.click();
  URL.revokeObjectURL(url);
}
