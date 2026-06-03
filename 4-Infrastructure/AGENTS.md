# AGENTS.md - Distributed Compute Fabric Infrastructure

Scope: `distributed-compute-fabric/4-Infrastructure/`

## Repository Origin

Extracted from Research Stack on 2026-06-02. Contains distributed computing infrastructure components including Ray, Kubernetes, VCN, and related systems.

## Scope

This repository focuses on distributed compute infrastructure:
- **Ray**: Distributed compute framework with actor implementations
- **Kubernetes/k3s**: Container orchestration and cluster management  
- **VCN**: Hardware video encoder compute substrate
- **LyteNyte**: Storage and dashboard components
- **Graph/Spatial Hash**: Spatial indexing and graph backends

Storage stack (restic/Garage/rclone), hardware bring-up, and other infrastructure components remain in the parent Research Stack repository.

## Rules

- Keep infrastructure scripts receipt-bearing: every probe should have a
  machine-readable output or update an existing receipt.
- Remote model/API probes must be secret-clean. Read provider credentials from
  environment variables only (`OLLAMA_API_KEY`, `DEEPSEEK_API_KEY`, etc.); never
  embed literal keys in scripts, receipts, prompts, or docs.
- LLM/model outputs are reviewer receipts, not validation. If a model review is
  promoted, store the answer and a machine-readable receipt with prompt/answer
  hashes under `shared-data/artifacts/`, and state which files formed the
  context.

## Preferred Checks

```bash
python3 -m py_compile 4-Infrastructure/shim/<script>.py
python3 -m json.tool <receipt>.json >/dev/null
```

For API-facing or receipt-writing scripts, also run a touched-file secret scan
before staging. Treat the repository credential hook as a backstop, not the
first detector.

## Ray Infrastructure

### Ray Actors
Located in `4-Infrastructure/shim/ray-actors/`:
- `vision_actor.py` - Computer vision processing
- `general_actor.py` - General purpose compute
- `gguf_inference_actor.py` - GGUF model inference
- `deepseek_coder_actor.py` - DeepSeek coding model
- `coder_actor.py` - General coding tasks

### Ray Cluster Configuration
- `4-Infrastructure/kubernetes/ray/raycluster.yaml` - Main Ray cluster deployment
- `4-Infrastructure/kubernetes/ray/redis-deployment.yaml` - Redis backend for Ray

## Kubernetes Infrastructure

### k3s-flake
Located in `4-Infrastructure/k3s-flake/`:
- NixOS-based k3s configuration
- Deployment manifests for various services
- Kustomization configurations
- Integration scripts

### Kubernetes Manifests
Located in `4-Infrastructure/kubernetes/`:
- Service deployments
- Ingress configurations
- Monitoring stack (Prometheus, Grafana)
- Networking configurations

## VCN Compute Substrate

### VCN Shims
Located in `4-Infrastructure/shim/`:
- `vcn_compute_substrate.py` - Hardware video encoder abstraction
- `vcn_famm_transport.py` - FAMM transport integration
- `braid_vcn_encoder.py` - Braid encoding for VCN
- `ray_vcn_bridge.py` - Ray-VCN integration bridge
- `ray_vcn_transport.py` - Ray transport for VCN

### VCN Documentation
- `4-Infrastructure/docs/vcn-lupine-setup.md` - VCN setup guide
- `4-Infrastructure/docs/mesh-networking-over-ray-plan.md` - Ray networking over VCN

## Hermes Orchestration

Located in `4-Infrastructure/shim/hermes/`:
- Orchestrator for distributed compute tasks
- Ray integration layer
- Frame dispatcher for video processing

## LyteNyte Components

### LyteNyte Dashboard
Located in `5-Applications/dashboard/lytenyte-storage/`:
- React-based storage interface
- Integration with distributed storage backends

### Cluster Dashboard
Located in `5-Applications/cluster-dashboard/`:
- Cluster monitoring and management
- Integration with LyteNyte storage

## Graph/Spatial Hash Components

### Spatial Hash Backends
Located in `4-Infrastructure/shim/`:
- `vectorless_spatial_hash_backend*.py` - Spatial hash implementations
- `spatial_hash_grid.py` - Grid-based spatial indexing

### GPU Acceleration
Located in `5-Applications/dashboard/spatial-hash-gpu/`:
- GPU-accelerated spatial hashing
- WebGL/WebGPU implementations

## Lean Formalization

Located in `0-Core-Formalism/lean/Semantics/Semantics/`:
- `BraidVCNBridge.lean` - Formal specification of VCN bridge

## Documentation

Comprehensive documentation in `6-Documentation/docs/gguf-ray-vcn/`:
- Architecture overview
- Deployment guides
- API documentation
- Performance analysis
- Security considerations