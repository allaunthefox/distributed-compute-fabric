# AGENTS.md - Distributed Compute Fabric

Scope: `distributed-compute-fabric/`

## Repository Purpose

Generic compute fabric infrastructure. Accelerates ANY compute type via voltage-mode routing, spatial hash indexing, VCN/LUPINE hardware acceleration, and Ray distributed scheduling.

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
| `BraidVCNBridge.lean` | Formal braid-to-VCN mapping spec |
| Virtio-Net | DMA ring buffer compute substrate |
| SPIR-V | Shader compilation target |
| QEMU framebuffer | `/dev/fb0` compute target |

### Infrastructure
| Component | Purpose |
|-----------|---------|
| `ray/` | Ray cluster manifests |
| `monitoring/` | Prometheus/Grafana stack |
| `tailscale/` | Subnet router for cross-node networking |
| `grpc/` | Optional gRPC inference proxy (streaming tokens) |

## Node Roles

| Node | Role | Hardware |
|------|------|----------|
| cupfox | Control plane | k3s, kuberay-operator, Authentik, Caddy |
| neon-64gb | Heavy lifting | ARM64, Hermes, Gemma model |
| qfox-1 | GPU compute | RTX 4070, CUDA, VCN-LUPINE |
| steamdeck | VAAPI + Ray | VAAPI encode, Ray head + workers |
| nixos | AMD GPU | ROCm |
| racknerd | Edge | Public ingress |

## Rules

- All hardcoded IPs/hostnames must use environment variables with defaults
- Python files must pass `python3 -m py_compile` before commit
- Kubernetes manifests must be valid YAML
- Secrets must never be committed (use .env files or external secret management)
- Voltage modes: STORE/COMPUTE/APPROX/MORPHIC — never hardcode routing decisions
- gRPC is optional — default to HTTP unless streaming is required

## Cross-References

- **research-compute-fabric** — Research-specific algorithms (Braid, PIST/RRC, Lean, eigensolid)
- **Research Stack** — Parent repository with formalization and documentation
