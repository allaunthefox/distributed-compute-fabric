import { useEffect, useRef, useState, useCallback } from "react";
import { Grid, useClientDataSource } from "@1771technologies/lytenyte-core";
import type { Grid as LnGrid } from "@1771technologies/lytenyte-core";
import "@1771technologies/lytenyte-core/dark.css";

// ── Types ────────────────────────────────────────────────────────────────────

interface NodeMetrics {
  name: string;
  ip: string;
  role: string;
  status: string;
  os_image: string;
  kernel: string;
  gpu_name: string;
  gpu_util: number;
  vram_used_mb: number;
  vram_total_mb: number;
  gpu_temp: number;
  encoder: string;
  cpu_cores: number;
  cpu_util: number;
  mem_used_mb: number;
  mem_total_mb: number;
  mem_util: number;
  pods_running: number;
  tailscale_ip: string;
  tailscale_latency_ms: number;
  tailscale_relay: string;
  tailscale_direct: boolean;
  vcn_codec: string;
  vcn_resolution: string;
  vcn_fps: number;
  last_updated: string;
  error: string;
}

// ── Column definitions ───────────────────────────────────────────────────────

const columns: LnGrid.Column[] = [
  {
    id: "status",
    name: "●",
    field: (p) => {
      const row = p.row.data as NodeMetrics;
      return row?.status === "Ready" ? "●" : "○";
    },
    width: 40,
    type: "string",
    cellRenderer: (params) => {
      const row = params.row.data as NodeMetrics;
      const color = row?.status === "Ready" ? "#22c55e" : "#ef4444";
      return (
        <span style={{ color, fontSize: 18, lineHeight: 1 }}>●</span>
      );
    },
  },
  {
    id: "name",
    name: "Node",
    field: "name",
    width: 150,
    type: "string",
    pin: "start",
  },
  {
    id: "ip",
    name: "IP",
    field: "ip",
    width: 130,
    type: "string",
  },
  {
    id: "role",
    name: "Role",
    field: "role",
    width: 100,
    type: "string",
  },
  {
    id: "gpu_name",
    name: "GPU",
    field: "gpu_name",
    width: 160,
    type: "string",
  },
  {
    id: "gpu_util",
    name: "GPU %",
    field: "gpu_util",
    width: 80,
    type: "number",
    cellRenderer: (params) => {
      const val = (params.row.data as NodeMetrics)?.gpu_util ?? 0;
      const color = val > 80 ? "#ef4444" : val > 50 ? "#f59e0b" : "#22c55e";
      return (
        <span style={{ color, fontWeight: 600 }}>
          {val > 0 ? `${val.toFixed(0)}%` : "—"}
        </span>
      );
    },
  },
  {
    id: "vram",
    name: "VRAM",
    field: (p) => {
      const row = p.row.data as NodeMetrics;
      if (!row?.vram_total_mb) return "—";
      return `${(row.vram_used_mb / 1024).toFixed(1)}/${(row.vram_total_mb / 1024).toFixed(1)} GB`;
    },
    width: 110,
    type: "string",
    cellRenderer: (params) => {
      const row = params.row.data as NodeMetrics;
      if (!row?.vram_total_mb) return <span style={{ color: "#666" }}>—</span>;
      const pct = (row.vram_used_mb / row.vram_total_mb) * 100;
      const color = pct > 80 ? "#ef4444" : pct > 50 ? "#f59e0b" : "#22c55e";
      return (
        <div style={{ display: "flex", alignItems: "center", gap: 6, width: "100%" }}>
          <div style={{
            flex: 1, height: 6, background: "#1a1a2e", borderRadius: 3, overflow: "hidden",
          }}>
            <div style={{
              width: `${pct}%`, height: "100%", background: color, borderRadius: 3,
              transition: "width 0.3s ease",
            }} />
          </div>
          <span style={{ fontSize: 11, whiteSpace: "nowrap" }}>
            {(row.vram_used_mb / 1024).toFixed(1)}/{(row.vram_total_mb / 1024).toFixed(1)}
          </span>
        </div>
      );
    },
  },
  {
    id: "gpu_temp",
    name: "GPU °C",
    field: "gpu_temp",
    width: 75,
    type: "number",
    cellRenderer: (params) => {
      const val = (params.row.data as NodeMetrics)?.gpu_temp ?? 0;
      if (!val) return <span style={{ color: "#666" }}>—</span>;
      const color = val > 80 ? "#ef4444" : val > 65 ? "#f59e0b" : "#22c55e";
      return <span style={{ color }}>{val.toFixed(0)}°</span>;
    },
  },
  {
    id: "encoder",
    name: "Codec",
    field: "encoder",
    width: 120,
    type: "string",
  },
  {
    id: "cpu_util",
    name: "CPU %",
    field: "cpu_util",
    width: 80,
    type: "number",
    cellRenderer: (params) => {
      const row = params.row.data as NodeMetrics;
      const val = row?.cpu_util ?? 0;
      if (!val && !row?.cpu_cores) return <span style={{ color: "#666" }}>—</span>;
      const color = val > 80 ? "#ef4444" : val > 50 ? "#f59e0b" : "#22c55e";
      return <span style={{ color, fontWeight: 600 }}>{val.toFixed(0)}%</span>;
    },
  },
  {
    id: "mem",
    name: "Memory",
    field: (p) => {
      const row = p.row.data as NodeMetrics;
      if (!row?.mem_total_mb) return "—";
      return `${(row.mem_used_mb / 1024).toFixed(1)}/${(row.mem_total_mb / 1024).toFixed(1)} GB`;
    },
    width: 120,
    type: "string",
    cellRenderer: (params) => {
      const row = params.row.data as NodeMetrics;
      if (!row?.mem_total_mb) return <span style={{ color: "#666" }}>—</span>;
      const pct = row.mem_util;
      const color = pct > 85 ? "#ef4444" : pct > 60 ? "#f59e0b" : "#22c55e";
      return (
        <div style={{ display: "flex", alignItems: "center", gap: 6, width: "100%" }}>
          <div style={{
            flex: 1, height: 6, background: "#1a1a2e", borderRadius: 3, overflow: "hidden",
          }}>
            <div style={{
              width: `${pct}%`, height: "100%", background: color, borderRadius: 3,
              transition: "width 0.3s ease",
            }} />
          </div>
          <span style={{ fontSize: 11, whiteSpace: "nowrap" }}>
            {(row.mem_used_mb / 1024).toFixed(1)}/{(row.mem_total_mb / 1024).toFixed(1)}
          </span>
        </div>
      );
    },
  },
  {
    id: "pods",
    name: "Pods",
    field: "pods_running",
    width: 65,
    type: "number",
  },
  {
    id: "tailscale",
    name: "Tailscale",
    field: (p) => {
      const row = p.row.data as NodeMetrics;
      if (!row?.tailscale_ip) return "—";
      return row.tailscale_direct ? "direct" : row.tailscale_relay || "relay";
    },
    width: 90,
    type: "string",
    cellRenderer: (params) => {
      const row = params.row.data as NodeMetrics;
      if (!row?.tailscale_ip) return <span style={{ color: "#666" }}>—</span>;
      const direct = row.tailscale_direct;
      return (
        <span style={{ color: direct ? "#22c55e" : "#f59e0b", fontSize: 12 }}>
          {direct ? "● direct" : `↗ ${row.tailscale_relay || "relay"}`}
        </span>
      );
    },
  },
  {
    id: "os",
    name: "OS",
    field: "os_image",
    width: 180,
    type: "string",
  },
  {
    id: "kernel",
    name: "Kernel",
    field: "kernel",
    width: 140,
    type: "string",
  },
];

// ── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [nodes, setNodes] = useState<NodeMetrics[]>([]);
  const [connected, setConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number | null>(null);

  const connect = useCallback(() => {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/ws`);

    ws.onopen = () => {
      setConnected(true);
      console.log("[dashboard] WebSocket connected");
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "update" && msg.nodes) {
          setNodes(msg.nodes);
          setLastUpdate(new Date().toLocaleTimeString());
        }
      } catch (e) {
        console.error("[dashboard] parse error:", e);
      }
    };

    ws.onclose = () => {
      setConnected(false);
      console.log("[dashboard] WebSocket closed, reconnecting in 3s...");
      reconnectRef.current = window.setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };

    wsRef.current = ws;
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectRef.current != null) clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const ds = useClientDataSource<NodeMetrics>({
    data: nodes,
  });

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div style={{
        padding: "12px 20px",
        background: "#0d0d14",
        borderBottom: "1px solid #1a1a2e",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: "#e0e0e8" }}>
            ⬡ Research Stack
          </span>
          <span style={{
            fontSize: 11,
            padding: "2px 8px",
            borderRadius: 4,
            background: "#1a1a2e",
            color: "#888",
          }}>
            CLUSTER DASHBOARD
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 13 }}>
          <span style={{ color: "#888" }}>{nodes.length} nodes</span>
          <span style={{
            display: "flex", alignItems: "center", gap: 6,
          }}>
            <span style={{
              width: 8, height: 8, borderRadius: "50%",
              background: connected ? "#22c55e" : "#ef4444",
              boxShadow: connected ? "0 0 6px #22c55e" : "0 0 6px #ef4444",
            }} />
            <span style={{ color: connected ? "#22c55e" : "#ef4444", fontSize: 12 }}>
              {connected ? "LIVE" : "DISCONNECTED"}
            </span>
          </span>
          {lastUpdate && (
            <span style={{ color: "#666", fontSize: 11 }}>
              {lastUpdate}
            </span>
          )}
        </div>
      </div>

      {/* Grid */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <Grid
          columns={columns}
          rowSource={ds}
          rowHeight={44}
          headerHeight={36}
          styles={{
            viewport: {
              style: {
                background: "#0a0a0f",
              },
            },
            header: {
              style: {
                background: "#0d0d14",
                borderColor: "#1a1a2e",
                color: "#e0e0e8",
              },
            },
            row: {
              style: {
                borderColor: "#141420",
              },
            },
            cell: {
              style: {
                color: "#e0e0e8",
                borderColor: "#141420",
              },
            },
          }}
        >
          <Grid.Viewport>
            <Grid.Header>
              {(cells) => (
                <Grid.HeaderRow>
                  {cells.map((cell) => {
                    if (cell.kind === "group") return null;
                    return <Grid.HeaderCell key={cell.id} cell={cell} />;
                  })}
                </Grid.HeaderRow>
              )}
            </Grid.Header>
            <Grid.RowsContainer>
              <Grid.RowsCenter>
                {(row) => {
                  if (row.kind === "full-width") return null;
                  return (
                    <Grid.Row key={row.id} row={row}>
                      {row.cells.map((cell) => (
                        <Grid.Cell key={cell.id} cell={cell} />
                      ))}
                    </Grid.Row>
                  );
                }}
              </Grid.RowsCenter>
            </Grid.RowsContainer>
          </Grid.Viewport>
        </Grid>
      </div>
    </div>
  );
}
