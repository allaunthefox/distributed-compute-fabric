# Distributed Compute Fabric

Infrastructure-as-code patterns for distributed resource management and computing.

## Overview

This repository provides generic, reusable infrastructure patterns for distributed computing systems. It focuses on standard tools and configurations that can be applied across different domains, not specific to any particular research or application area.

## Core Components

### Ray Cluster
- **Purpose**: Distributed computing framework with generic resource scheduling
- **Components**:
  - Ray cluster deployment manifests
  - Redis backend for Ray coordination
  - Generic compute actors for common patterns

### Kubernetes Infrastructure
- **Purpose**: Container orchestration and cluster management
- **Components**:
  - Standard Kubernetes service manifests
  - Ingress configurations and routing
  - Core networking patterns

### Monitoring Stack
- **Purpose**: Observability and monitoring for distributed systems
- **Components**:
  - Prometheus for metrics collection
  - Grafana for visualization
  - Service monitors for Kubernetes integration

## Structure

```
distributed-compute-fabric/
├── 4-Infrastructure/
│   ├── kubernetes/             # Kubernetes manifests
│   │   ├── ray/               # Ray cluster configuration
│   │   ├── monitoring/        # Prometheus/Grafana stack
│   │   └── kube/              # Additional Kubernetes configs
│   ├── shim/
│   │   └── ray-actors/        # Generic Ray compute actors
│   └── AGENTS.md              # Infrastructure guidelines
└── README.md                  # This file
```

## Origin

This repository was extracted from the Research Stack on 2026-06-02, then refined on 2026-06-02 to focus on infrastructure-as-code patterns. Research-stack-specific components (VCN, LyteNyte, Braid encoding, ML-specific actors, etc.) were removed to create a generic, reusable infrastructure foundation.

## What Was Removed

The following research-stack-specific components were removed during refinement:
- k3s-flake (NixOS-specific configurations)
- VCN (Video Compute Node) - video encoding infrastructure
- LyteNyte - research-specific storage system
- Braid encoding - specialized compression algorithms
- Spatial Hash - domain-specific indexing
- Hermes orchestration - research task orchestration
- ML-specific actors (GGUF, DeepSeek, Vision)
- Lean formalization - mathematical proof components
- Application dashboards - UI components
- Research-specific documentation

## Usage

### Ray Cluster Deployment
```bash
kubectl apply -f 4-Infrastructure/kubernetes/ray/
```

### Monitoring Stack
```bash
kubectl apply -f 4-Infrastructure/kubernetes/monitoring/
```

### Generic Actor Patterns
```bash
# Use the generic actor patterns as templates
from distributed_compute_fabric.shim.ray_actors import general_actor, coder_actor
```

## Infrastructure as Code Principles

This repository follows these principles:

1. **Declarative Configuration**: Use Kubernetes manifests for reproducible deployments
2. **Generic Patterns**: Avoid domain-specific optimizations in core infrastructure
3. **Observable Design**: Include monitoring and logging patterns by default
4. **Modular Components**: Keep Ray, Kubernetes, and monitoring as separate concerns
5. **Standard Tools**: Use industry-standard tools (Ray, Kubernetes, Prometheus)

## Contributing

When adding new components:
- Keep patterns generic and reusable across domains
- Avoid domain-specific optimizations or algorithms
- Include appropriate monitoring and observability
- Document the infrastructure pattern clearly
- Test with standard tools (kubectl, ray CLI)

## License

Same license as parent Research Stack repository.