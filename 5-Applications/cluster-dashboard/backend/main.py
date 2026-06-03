"""Research Stack Cluster Dashboard — telemetry collector backend.

Collects node metrics via:
- Kubernetes API (node status, pod counts)
- Tailscale CLI (connection type, bytes)
- SSH to nodes (GPU util, VRAM, CPU, memory)
- nvidia-smi (qfox-1) / sysfs (nixos AMD)

Exposes:
- REST /api/nodes — current snapshot
- WebSocket /ws — live updates every 3s
- GET /health — readiness probe
"""

import asyncio
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dashboard")

app = FastAPI(title="Research Stack Cluster Dashboard")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

KUBECONFIG = os.environ.get("KUBECONFIG", "/tmp/researchstack-kubeconfig.yaml")
POLL_INTERVAL = 3  # seconds

# ── Node data model (field names match frontend App.tsx exactly) ─────────

@dataclass
class NodeMetrics:
    name: str
    ip: str
    role: str
    status: str              # Ready / NotReady / Unknown
    os_image: str
    kernel: str
    # GPU
    gpu_name: str = ""
    gpu_util: float = 0.0
    vram_used_mb: float = 0.0
    vram_total_mb: float = 0.0
    gpu_temp: float = 0.0
    encoder: str = ""
    # System
    cpu_cores: int = 0
    cpu_util: float = 0.0
    mem_used_mb: float = 0.0
    mem_total_mb: float = 0.0
    mem_util: float = 0.0
    # k3s
    pods_running: int = 0
    # Tailscale
    tailscale_ip: str = ""
    tailscale_latency_ms: float = 0.0
    tailscale_relay: str = ""
    tailscale_direct: bool = False
    # VCN substrate
    vcn_codec: str = ""
    vcn_resolution: str = ""
    vcn_fps: int = 0
    # Meta
    last_updated: str = ""
    error: str = ""


# ── Node registry ────────────────────────────────────────────────────────

NODES = {
    "qfox-1": {
        "tailscale_ip": "100.88.57.96",
        "role": "gpu-worker",
        "gpu_name": "RTX 4070 SUPER",
        "gpu_type": "nvidia",
        "ssh_user": "allaun",
    },
    "nixos": {
        "tailscale_ip": "100.102.173.61",
        "role": "control-plane",
        "gpu_name": "AMD Lucienne",
        "gpu_type": "amd",
        "ssh_user": "allaun",
    },
    "steamdeck": {
        "tailscale_ip": "100.85.244.73",
        "role": "gpu-worker",
        "gpu_name": "VanGogh APU",
        "gpu_type": "amd",
        "ssh_user": "deck",
    },
    "361395-1": {
        "tailscale_ip": "100.110.163.82",
        "role": "vps-worker",
        "gpu_name": "",
        "gpu_type": None,
        "ssh_user": "root",
    },
    "racknerd-510bd9c": {
        "tailscale_ip": "100.80.39.40",
        "role": "edge",
        "gpu_name": "",
        "gpu_type": None,
        "ssh_user": "root",
    },
}


# ── Helpers ──────────────────────────────────────────────────────────────

def run_cmd(cmd: list[str], timeout: int = 10) -> str | None:
    """Run a command, return stdout or None on failure."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return None


def parse_k8s_memory(mem_str: str) -> int:
    """Parse k8s memory string (e.g. '16392740Ki') to MB."""
    s = mem_str.strip()
    if s.endswith("Ki"):
        return int(s[:-2]) // 1024
    if s.endswith("Mi"):
        return int(s[:-2])
    if s.endswith("Gi"):
        return int(s[:-2]) * 1024
    return 0


# ── Collectors ───────────────────────────────────────────────────────────

def collect_k8s_nodes() -> dict[str, dict]:
    """Get node info from kubectl JSON output."""
    out = run_cmd(["kubectl", "get", "nodes", "-o", "json", "--kubeconfig", KUBECONFIG])
    if not out:
        return {}
    data = json.loads(out)
    result = {}
    for item in data.get("items", []):
        name = item["metadata"]["name"]
        conditions = item.get("status", {}).get("conditions", [])
        ready = any(c["type"] == "Ready" and c["status"] == "True" for c in conditions)
        # Get InternalIP
        addrs = item.get("status", {}).get("addresses", [])
        internal_ip = next((a["address"] for a in addrs if a["type"] == "InternalIP"), "")
        info = item.get("status", {}).get("nodeInfo", {})
        allocatable = item.get("status", {}).get("allocatable", {})
        result[name] = {
            "status": "Ready" if ready else "NotReady",
            "ip": internal_ip,
            "os_image": info.get("osImage", ""),
            "kernel": info.get("kernelVersion", ""),
            "cpu_cores": int(allocatable.get("cpu", "0")),
            "mem_total_mb": parse_k8s_memory(allocatable.get("memory", "0Ki")),
        }
    return result


def collect_k8s_pods() -> dict[str, int]:
    """Count running pods per node."""
    out = run_cmd(["kubectl", "get", "pods", "-A", "-o", "json", "--kubeconfig", KUBECONFIG])
    if not out:
        return {}
    data = json.loads(out)
    counts: dict[str, int] = {}
    for pod in data.get("items", []):
        phase = pod.get("status", {}).get("phase", "")
        node = pod.get("spec", {}).get("nodeName", "")
        if phase == "Running" and node:
            counts[node] = counts.get(node, 0) + 1
    return counts


def collect_nvidia_gpu(ip: str) -> dict:
    """GPU metrics via SSH + nvidia-smi."""
    out = run_cmd([
        "ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
        f"allaun@{ip}",
        "nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,"
        "temperature.gpu --format=csv,noheader,nounits 2>/dev/null",
    ], timeout=15)
    if not out:
        return {}
    parts = [p.strip() for p in out.split(",")]
    if len(parts) >= 5:
        try:
            return {
                "gpu_name": parts[0],
                "gpu_util": float(parts[1]),
                "vram_used_mb": float(parts[2]),
                "vram_total_mb": float(parts[3]),
                "gpu_temp": float(parts[4]),
            }
        except ValueError:
            return {}
    return {}


def collect_amd_gpu(ip: str) -> dict:
    """GPU metrics via SSH + sysfs (AMD)."""
    out = run_cmd([
        "ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
        f"allaun@{ip}",
        "cat /sys/class/drm/card*/device/gpu_busy_percent 2>/dev/null; "
        "echo '---'; "
        "cat /sys/class/drm/card*/device/mem_info_vram_used 2>/dev/null; "
        "echo '---'; "
        "cat /sys/class/drm/card*/device/mem_info_vram_total 2>/dev/null",
    ], timeout=10)
    if not out:
        return {}
    sections = out.split("---")
    gpu_util = 0.0
    vram_used = 0.0
    vram_total = 0.0
    try:
        if sections[0].strip():
            gpu_util = float(sections[0].strip().split("\n")[0])
        if len(sections) > 1 and sections[1].strip():
            vram_used = float(sections[1].strip().split("\n")[0]) / (1024 * 1024)
        if len(sections) > 2 and sections[2].strip():
            vram_total = float(sections[2].strip().split("\n")[0]) / (1024 * 1024)
    except ValueError:
        pass
    return {
        "gpu_util": gpu_util,
        "vram_used_mb": vram_used,
        "vram_total_mb": vram_total,
    }


def collect_system_metrics(ip: str) -> dict:
    """CPU/memory via SSH + /proc/stat and /proc/meminfo (portable across all Linux distros)."""
    out = run_cmd([
        "ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
        f"allaun@{ip}",
        "cat /proc/stat | head -1; cat /proc/meminfo | head -3",
    ], timeout=10)
    if not out:
        return {}
    result = {}
    # Parse /proc/stat — first line: cpu  user nice system idle iowait irq softirq steal
    cpu_match = re.search(
        r"^cpu\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)",
        out, re.MULTILINE,
    )
    if cpu_match:
        vals = [int(v) for v in cpu_match.groups()]
        idle = vals[3] + vals[4]  # idle + iowait
        total = sum(vals)
        if total > 0:
            result["cpu_util"] = round((1 - idle / total) * 100, 1)
    # Parse /proc/meminfo — MemTotal, MemFree, MemAvailable
    mem_total = re.search(r"MemTotal:\s+(\d+)\s+kB", out)
    mem_avail = re.search(r"MemAvailable:\s+(\d+)\s+kB", out)
    if mem_total:
        total_kb = int(mem_total.group(1))
        result["mem_total_mb"] = total_kb // 1024
    if mem_avail and mem_total:
        total_kb = int(mem_total.group(1))
        avail_kb = int(mem_avail.group(1))
        used_kb = total_kb - avail_kb
        result["mem_used_mb"] = used_kb // 1024
        result["mem_util"] = round(used_kb / total_kb * 100, 1) if total_kb else 0
    return result


def collect_tailscale() -> dict[str, dict]:
    """Tailscale peer status via SSH to host (container doesn't run tailscaled)."""
    out = run_cmd([
        "ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
        "allaun@100.102.173.61", "tailscale status --json",
    ])
    if not out:
        return {}
    data = json.loads(out)
    peers: dict[str, dict] = {}
    # Self
    self_ips = data.get("Self", {}).get("TailscaleIPs", [])
    if self_ips:
        peers[self_ips[0]] = {"relay": "", "direct": True}
    # Peers
    for _, peer in data.get("Peer", {}).items():
        ips = peer.get("TailscaleIPs", [])
        if ips:
            peers[ips[0]] = {
                "relay": peer.get("Relay", ""),
                "direct": bool(peer.get("CurAddr")),
            }
    return peers


# ── Main collection loop ─────────────────────────────────────────────────

async def collect_all() -> list[dict]:
    """Collect metrics from all nodes, return as dicts for JSON."""
    loop = asyncio.get_event_loop()

    # Run blocking collectors in thread pool
    k8s_nodes, pod_counts, ts_status = await asyncio.gather(
        loop.run_in_executor(None, collect_k8s_nodes),
        loop.run_in_executor(None, collect_k8s_pods),
        loop.run_in_executor(None, collect_tailscale),
    )

    nodes = []
    for name, cfg in NODES.items():
        k8s = k8s_nodes.get(name, {})
        nm = NodeMetrics(
            name=name,
            ip=k8s.get("ip", cfg["tailscale_ip"]),
            role=cfg["role"],
            status=k8s.get("status", "Unknown"),
            os_image=k8s.get("os_image", ""),
            kernel=k8s.get("kernel", ""),
            cpu_cores=k8s.get("cpu_cores", 0),
            mem_total_mb=k8s.get("mem_total_mb", 0),
            pods_running=pod_counts.get(name, 0),
            tailscale_ip=cfg["tailscale_ip"],
            last_updated=datetime.now(timezone.utc).isoformat(),
        )

        # Tailscale
        ts = ts_status.get(cfg["tailscale_ip"], {})
        nm.tailscale_relay = ts.get("relay", "")
        nm.tailscale_direct = ts.get("direct", False)

        # GPU + system metrics (skip remote VPS — no SSH)
        gpu_type = cfg.get("gpu_type")
        if gpu_type == "nvidia":
            gpu_data = await loop.run_in_executor(
                None, collect_nvidia_gpu, cfg["tailscale_ip"]
            )
            for k, v in gpu_data.items():
                setattr(nm, k, v)
            if not nm.gpu_name:
                nm.gpu_name = cfg.get("gpu_name", "")
            # Encoder check
            enc_out = await loop.run_in_executor(None, lambda: run_cmd([
                "ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
                f"allaun@{cfg['tailscale_ip']}",
                "nvidia-smi --query-gpu=encoder.stats.sessionCount "
                "--format=csv,noheader,nounits 2>/dev/null",
            ]))
            if enc_out and enc_out.strip().isdigit() and int(enc_out.strip()) > 0:
                nm.encoder = "h264_nvenc"
        elif gpu_type == "amd":
            nm.gpu_name = cfg.get("gpu_name", "")
            if name != "steamdeck":  # VanGogh has no VRAM sysfs
                gpu_data = await loop.run_in_executor(
                    None, collect_amd_gpu, cfg["tailscale_ip"]
                )
                for k, v in gpu_data.items():
                    setattr(nm, k, v)
                nm.encoder = "hevc_vaapi"

        # System metrics (local nodes only)
        if name in ("qfox-1", "nixos", "steamdeck"):
            sys_data = await loop.run_in_executor(
                None, collect_system_metrics, cfg["tailscale_ip"]
            )
            for k, v in sys_data.items():
                setattr(nm, k, v)

        nodes.append(asdict(nm))

    return nodes


# ── Cached state + WebSocket ─────────────────────────────────────────────

_cached_nodes: list[dict] = []
_ws_clients: set[WebSocket] = set()


async def update_loop():
    """Background task: collect metrics every POLL_INTERVAL, push to WS clients."""
    global _cached_nodes
    while True:
        try:
            _cached_nodes = await collect_all()
            payload = json.dumps({"type": "update", "nodes": _cached_nodes})
            dead: set[WebSocket] = set()
            for ws in _ws_clients:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.add(ws)
            _ws_clients.difference_update(dead)
        except Exception as e:
            log.error(f"Collection error: {e}")
        await asyncio.sleep(POLL_INTERVAL)


@app.on_event("startup")
async def startup():
    asyncio.create_task(update_loop())


# ── API routes ───────────────────────────────────────────────────────────

@app.get("/api/nodes")
async def get_nodes():
    return {"nodes": _cached_nodes, "updated": datetime.now(timezone.utc).isoformat()}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    log.info(f"WS client connected ({len(_ws_clients)} total)")
    try:
        await ws.send_text(json.dumps({"type": "update", "nodes": _cached_nodes}))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)
        log.info(f"WS client disconnected ({len(_ws_clients)} total)")


@app.get("/health")
async def health():
    return {"status": "ok", "nodes": len(_cached_nodes)}


# ── Static files (frontend) ──────────────────────────────────────────────

frontend_dist = Path(os.environ.get("STATIC_DIR", "/app/static"))
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")
