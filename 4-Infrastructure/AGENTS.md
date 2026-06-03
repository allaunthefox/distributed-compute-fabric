# AGENTS.md - Distributed Compute Fabric

Scope: `distributed-compute-fabric/`

## Repository Purpose

Generic, reusable infrastructure patterns for distributed computing systems. Contains Ray, Kubernetes, monitoring, and networking configurations that are not specific to any particular research or application area.

## Components

### Ray Cluster
- **Purpose**: Distributed computing framework with generic resource scheduling
- **Components**:
  - Ray cluster deployment manifests
  - Redis backend for Ray coordination
  - Generic compute actors for common patterns

### Kubernetes Infrastructure
- **Purpose**: Container orchestration and cluster management
- **Components**:
  - k3s configuration (NixOS-based)
  - Deployment manifests for various services
  - Kustomization configurations

### Monitoring
- **Purpose**: Observability and alerting
- **Components**:
  - Prometheus deployment
  - Grafana dashboards
  - Service monitors

### Tailscale Networking
- **Purpose**: Mesh networking for cluster nodes
- **Components**:
  - Subnet router deployment
  - Cluster roles and bindings
  - mDNS configuration

### Hermes Orchestrator
- **Purpose**: Distributed compute orchestration
- **Components**:
  - Orchestrator service
  - Frame dispatcher
  - Ray actor integration

## Rules

- Infrastructure must be generic and reusable across different domains
- All Python files should pass `python3 -m py_compile` before commit
- Kubernetes manifests should be valid YAML
- Secrets must never be committed (use .env files or external secret management)
- Monitor configurations should follow Prometheus operator conventions

## Cross-References

- **research-compute-fabric** - Research-specific components (VCN, Braid, Spatial Hash, etc.)
- **Research Stack** - Parent repository with formalization and documentation
