# Distributed Compute Fabric

Generic compute fabric infrastructure. Not research-specific.

## What This Is

Hardware-agnostic compute substrate. Accelerates ANY compute type via:
- Voltage-mode routing (STORE/COMPUTE/APPROX/MORPHIC)
- Spatial hash indexing (16×16×16 grid in GPU memory)
- VCN/LUPINE hardware acceleration (H.264-encoded compute)
- Ray distributed scheduling across heterogeneous nodes

## Components

### Compute Layer
| Component | Purpose |
|-----------|---------|
| `vcn_lupine_daemon.py` | VCN/LUPINE hardware acceleration daemon |
| `vcn_lupine_bridge_spec.md` | VCN frame encoding specification |
| `spatial-hash-gpu/` | WebGPU GridStorage — vectorless graph database |
| `lytenyte-storage/` | Spatial hash visualization dashboard |

### Orchestration
| Component | Purpose |
|-----------|---------|
| `hermes/` | Voltage-mode orchestrator (routes compute to GPU/ARM/VCN) |
| `manifests/hermes/` | Kubernetes deployment manifests |
| `ray-actors/` | Generic Ray compute actors |

### Hardware Abstractions
| Component | Purpose |
|-----------|---------|
| `0-Core-Formalism/lean/Semantics/BraidVCNBridge.lean` | Formal braid-to-VCN mapping spec |
| Virtio-Net | DMA ring buffer compute substrate |
| SPIR-V | Shader compilation target |
| QEMU framebuffer | `/dev/fb0` compute target |

### Infrastructure
| Component | Purpose |
|-----------|---------|
| `4-Infrastructure/ray/` | Ray cluster manifests |
| `4-Infrastructure/monitoring/` | Prometheus/Grafana stack |
| `4-Infrastructure/tailscale/` | Subnet router for cross-node networking |
| `4-Infrastructure/shim/` | Python actors and utilities |

## Architecture

```
                    ┌─────────────────┐
                    │   Caddy Edge    │
                    │ (TLS + Routing) │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Hermes Orchestr │
                    │ (Voltage Modes) │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───────┐ ┌───▼────┐ ┌──────▼──────┐
     │ GPU (qfox-1)   │ │ ARM    │ │ VCN/LUPINE  │
     │ CUDA + VRAM    │ │ (neon) │ │ H.264 enc   │
     └────────────────┘ └────────┘ └─────────────┘
              │              │              │
              └──────────────┼──────────────┘
                             │
                    ┌────────▼────────┐
                    │ Spatial Hash    │
                    │ (16³ = 4096)    │
                    │ GPU Buffer      │
                    └─────────────────┘
```

## Node Roles

| Node | Role | Hardware |
|------|------|----------|
| cupfox | Control plane | k3s, kuberay-operator, Authentik, Caddy |
| neon-64gb | Heavy lifting | ARM64, Hermes, Gemma model |
| qfox-1 | GPU compute | RTX 4070, CUDA, VCN-LUPINE |
| steamdeck | VAAPI + Ray | VAAPI encode, Ray head + workers |
| nixos | AMD GPU | ROCm |
| racknerd | Edge | Public ingress |

## Quick Start

```bash
# Deploy Hermes orchestrator
kubectl apply -f manifests/hermes/

# Deploy Ray cluster
kubectl apply -f 4-Infrastructure/ray/raycluster.yaml

# Deploy monitoring
kubectl apply -f 4-Infrastructure/monitoring/

# Build LyteNyte dashboard
cd 5-Applications/dashboard/lytenyte-storage && npm install && npm run dev
```

## Configuration

All hardcoded values should be replaced with environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `GARAGE_S3_ENDPOINT` | `http://100.88.57.96:3900` | S3 storage endpoint |
| `LUPINE_GPU_NODE` | `100.88.57.96` | GPU node for VCN acceleration |
| `MAIN_MODEL_URL` | `http://gemma-model.services.svc.cluster.local` | Primary inference endpoint |
| `HERMES_PORT` | `8080` | Orchestrator listen port |

## Voltage Modes

| Mode | Purpose | Hardware |
|------|---------|----------|
| STORE | Persistent storage | S3, NVMe |
| COMPUTE | Active computation | GPU, CPU |
| APPROX | Approximate/sampling | ARM64, quantized models |
| MORPHIC | Adaptive/topological | VCN-LUPINE, braid encoding |
