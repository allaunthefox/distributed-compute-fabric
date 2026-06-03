/**
 * App.tsx — Main LyteNyte dashboard for spatial hash visualization.
 *
 * Features:
 * - 4096-row virtualized grid (16×16×16 spatial hash)
 * - Sort by density descending by default
 * - Filter by voltage_mode (dropdown)
 * - Row grouping by voltage_mode
 * - Cell selection → highlights in 3D WebGPU view (via postMessage)
 * - Real-time buffer simulation (1 Hz poll)
 * - CSV export
 */

import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { Grid, useClientDataSource } from "@1771technologies/lytenyte-core";
import { createColumns } from "./columns";
import {
  generateSpatialHashData,
  simulateBufferUpdate,
  downloadCSV,
  type SpatialHashRow,
  type VoltageMode,
} from "./data";

const VOLTAGE_MODES: VoltageMode[] = ["STORE", "COMPUTE", "APPROX", "MORPHIC"];

const styles: Record<string, React.CSSProperties> = {
  root: {
    width: "100%",
    height: "100vh",
    display: "flex",
    flexDirection: "column",
    background: "#0e1117",
    color: "#e0e0e0",
    fontFamily: "system-ui, -apple-system, sans-serif",
  },
  toolbar: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "10px 16px",
    background: "#161b22",
    borderBottom: "1px solid #30363d",
    flexShrink: 0,
  },
  title: {
    fontSize: 16,
    fontWeight: 700,
    marginRight: 8,
    color: "#58a6ff",
  },
  badge: {
    fontSize: 12,
    background: "#1f6feb33",
    color: "#58a6ff",
    padding: "2px 8px",
    borderRadius: 4,
    fontWeight: 500,
  },
  select: {
    background: "#21262d",
    color: "#e0e0e0",
    border: "1px solid #30363d",
    borderRadius: 6,
    padding: "4px 8px",
    fontSize: 13,
    cursor: "pointer",
  },
  button: {
    background: "#238636",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "6px 14px",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
  },
  toggle: (active: boolean): React.CSSProperties => ({
    background: active ? "#1f6feb" : "#21262d",
    color: active ? "#fff" : "#8b949e",
    border: `1px solid ${active ? "#1f6feb" : "#30363d"}`,
    borderRadius: 6,
    padding: "4px 10px",
    fontSize: 12,
    fontWeight: 500,
    cursor: "pointer",
  }),
  spacer: { flex: 1 },
  gridContainer: {
    flex: 1,
    minHeight: 0,
  },
  statusBar: {
    display: "flex",
    alignItems: "center",
    gap: 16,
    padding: "6px 16px",
    background: "#161b22",
    borderTop: "1px solid #30363d",
    fontSize: 12,
    color: "#8b949e",
    flexShrink: 0,
  },
  selectedPanel: {
    padding: "10px 16px",
    background: "#1c2128",
    borderTop: "1px solid #30363d",
    fontSize: 13,
    flexShrink: 0,
    display: "flex",
    gap: 20,
    flexWrap: "wrap",
  },
  tag: (color: string): React.CSSProperties => ({
    background: color,
    color: "#fff",
    padding: "2px 8px",
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 600,
  }),
};

const VOLTAGE_COLORS: Record<VoltageMode, string> = {
  STORE: "#4a90d9",
  COMPUTE: "#50c878",
  APPROX: "#e8a838",
  MORPHIC: "#e05050",
};

export default function App() {
  // ── State ──
  const [data, setData] = useState<SpatialHashRow[]>(() => generateSpatialHashData());
  const [voltageFilter, setVoltageFilter] = useState<VoltageMode | "ALL">("ALL");
  const [grouped, setGrouped] = useState(false);
  const [liveUpdates, setLiveUpdates] = useState(false);
  const [selectedRow, setSelectedRow] = useState<SpatialHashRow | null>(null);
  const [rowCount, setRowCount] = useState(0);
  const gridApiRef = useRef<any>(null);

  // ── Columns ──
  const columns = useMemo(() => createColumns(), []);

  // ── Filter function ──
  const filterFn = useMemo(() => {
    if (voltageFilter === "ALL") return null;
    return (row: SpatialHashRow) => row.voltage_mode === voltageFilter;
  }, [voltageFilter]);

  // ── Group function ──
  const groupFn = useMemo(() => {
    if (!grouped) return [];
    return [{ id: "voltage_mode" }];
  }, [grouped]);

  // ── Sort: density descending ──
  const sort = useMemo(() => [{ dim: { id: "density" }, sort: "desc" as const }], []);

  // ── Data source ──
  const ds = useClientDataSource({
    data,
    sort,
    filter: filterFn ? [filterFn] : null,
    group: groupFn,
  });

  // ── Real-time buffer simulation ──
  useEffect(() => {
    if (!liveUpdates) return;
    const interval = setInterval(() => {
      setData((prev) => simulateBufferUpdate(prev));
    }, 1000);
    return () => clearInterval(interval);
  }, [liveUpdates]);

  // ── Track row count from data source ──
  useEffect(() => {
    // Approximate: filtered data count
    if (voltageFilter === "ALL") {
      setRowCount(data.length);
    } else {
      setRowCount(data.filter((r) => r.voltage_mode === voltageFilter).length);
    }
  }, [data, voltageFilter]);

  // ── Row click handler → send selection to WebGPU 3D view ──
  const handleRowClick = useCallback(
    (row: SpatialHashRow) => {
      setSelectedRow(row);
      // Post message to parent/3D WebGPU view
      window.postMessage(
        {
          type: "spatial-hash-cell-select",
          cell: { x: row.x, y: row.y, z: row.z },
        },
        "*"
      );
    },
    []
  );

  // ── Export CSV ──
  const handleExport = useCallback(() => {
    const filtered =
      voltageFilter === "ALL"
        ? data
        : data.filter((r) => r.voltage_mode === voltageFilter);
    downloadCSV(filtered);
  }, [data, voltageFilter]);

  // ── Voltage mode stats ──
  const modeStats = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const m of VOLTAGE_MODES) counts[m] = 0;
    for (const r of data) counts[r.voltage_mode]++;
    return counts;
  }, [data]);

  return (
    <div style={styles.root}>
      {/* Toolbar */}
      <div style={styles.toolbar}>
        <span style={styles.title}>⚡ Spatial Hash Dashboard</span>
        <span style={styles.badge}>16×16×16 = 4096 cells</span>

        <div style={styles.spacer} />

        {/* Voltage mode filter */}
        <label style={{ fontSize: 12, color: "#8b949e" }}>Filter:</label>
        <select
          style={styles.select}
          value={voltageFilter}
          onChange={(e) => setVoltageFilter(e.target.value as VoltageMode | "ALL")}
        >
          <option value="ALL">All Modes</option>
          {VOLTAGE_MODES.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>

        {/* Group toggle */}
        <button
          style={styles.toggle(grouped)}
          onClick={() => setGrouped((g) => !g)}
        >
          {grouped ? "⊟" : "⊞"} Group by Mode
        </button>

        {/* Live updates toggle */}
        <button
          style={styles.toggle(liveUpdates)}
          onClick={() => setLiveUpdates((u) => !u)}
        >
          {liveUpdates ? "⏸ Pause" : "▶ Live Updates"}
        </button>

        {/* Export */}
        <button style={styles.button} onClick={handleExport}>
          ⬇ Export CSV
        </button>
      </div>

      {/* LyteNyte Grid */}
      <div style={styles.gridContainer} className="ln-grid">
        <Grid
          columns={columns}
          rowSource={ds}
          rowHeight={32}
          headerHeight={36}
          columnSizeToFit
          rowSelectionMode="single"
          rowSelectionActivator="single-click"
          events={{
            row: {
              click: ({ row }) => {
                if (row.kind === "leaf") {
                  handleRowClick(row.data!);
                }
              },
            },
          }}
        />
      </div>

      {/* Selected row detail panel */}
      {selectedRow && (
        <div style={styles.selectedPanel}>
          <span style={{ fontWeight: 600, color: "#58a6ff" }}>Selected Cell:</span>
          <span>
            ({selectedRow.x}, {selectedRow.y}, {selectedRow.z})
          </span>
          <span>Density: {selectedRow.density}</span>
          <span>FD: {selectedRow.fd.toFixed(2)}</span>
          <span style={styles.tag(VOLTAGE_COLORS[selectedRow.voltage_mode])}>
            {selectedRow.voltage_mode}
          </span>
          <span>Particles: {selectedRow.particle_count}</span>
          <span>Max Neigh: {selectedRow.max_neighbor}</span>
          <span style={{ color: "#484f58", fontSize: 11 }}>
            id: {selectedRow.id}
          </span>
        </div>
      )}

      {/* Status bar */}
      <div style={styles.statusBar}>
        <span>
          {rowCount.toLocaleString()} rows
          {voltageFilter !== "ALL" && ` (filtered by ${voltageFilter})`}
        </span>
        <span>|</span>
        {VOLTAGE_MODES.map((m) => (
          <span key={m} style={{ color: VOLTAGE_COLORS[m] }}>
            {m}: {modeStats[m]}
          </span>
        ))}
        <span style={styles.spacer} />
        <span>{liveUpdates ? "🟢 LIVE" : "⏸ PAUSED"}</span>
      </div>
    </div>
  );
}
