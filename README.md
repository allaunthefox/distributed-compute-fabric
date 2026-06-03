# Distributed Compute Fabric

Extracted from Research Stack - Ray/Kubernetes/VCN/LyteNyte/Graph infrastructure components.

## Overview

This repository contains distributed computing infrastructure components including:

- **Ray**: Distributed compute framework with actor implementations
- **Kubernetes/k3s**: Container orchestration and cluster management
- **VCN (Video Compute Node)**: Hardware video encoder compute substrate
- **LyteNyte**: Storage and dashboard components for distributed storage
- **Graph/Spatial Hash**: Spatial indexing and graph backend implementations

## Structure

```
distributed-compute-fabric/
├── 4-Infrastructure/
│   ├── k3s-flake/              # K3s flake configurations
│   ├── kubernetes/             # Kubernetes manifests
│   ├── kube/                   # Additional Kubernetes configs
│   ├── shim/
│   │   ├── ray-actors/         # Ray actor implementations
│   │   ├── vcn_*.py           # VCN-related shims
│   │   ├── hermes/            # Hermes orchestration
│   │   └── vectorless_spatial_hash_backend*.py
│   └── docs/                   # Infrastructure documentation
├── 5-Applications/
│   ├── cluster-dashboard/      # Cluster monitoring dashboard
│   └── dashboard/
│       ├── lytenyte-storage/  # LyteNyte storage interface
│       └── spatial-hash-gpu/  # GPU-accelerated spatial hashing
├── 6-Documentation/
│   └── docs/
│       ├── gguf-ray-vcn/      # Ray+VCN system documentation
│       └── specs/             # Technical specifications
└── 0-Core-Formalism/
    └── lean/
        └── Semantics/
            └── Semantics/
                └── BraidVCNBridge.lean  # VCN bridge formalization
```

## Origin

This repository was extracted from the main Research Stack repository on 2026-06-02 to provide a focused, standalone distributed computing infrastructure codebase.

## Components

### Ray Actors
- Vision processing actor
- General purpose compute actor
- GGUF inference actor
- DeepSeek coder actor
- General coder actor

### VCN Compute Substrate
- Hardware video encoder abstraction (AMD VCN / NVIDIA NVENC)
- Braid encoding pipeline
- Ray-VCN bridge for distributed video compute
- FAMM transport integration

### Kubernetes Infrastructure
- Ray cluster deployment manifests
- Redis for Ray backend
- Monitoring stack (Prometheus, Grafana)
- Service mesh and networking configurations

### LyteNyte Storage
- React-based storage dashboard
- Cluster integration
- Spatial hash GPU indexing

## Documentation

See `6-Documentation/docs/gguf-ray-vcn/` for comprehensive system documentation including:
- Architecture overview
- Deployment guides
- API documentation
- Performance analysis
- Security considerations

## License

Same license as parent Research Stack repository.

## Migration Notes

This is a direct extraction of components from the Research Stack. Some shared utilities have been duplicated to maintain independence. Cross-references to the parent repository should be updated as needed.