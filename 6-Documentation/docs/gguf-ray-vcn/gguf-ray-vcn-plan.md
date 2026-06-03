# GGUF-Ray-VCN-LUPINE Deployment Plan

**Version:** 1.0.0  
**Last Updated:** 2026-06-01  
**Status:** Active Development  
**Author:** Mistral Vibe (Continuing from previous work)

---

## Table of Contents

1. [Executive Summary](#-executive-summary)
2. [Architecture Overview](#-architecture-overview)
3. [Deployment Phases](#-deployment-phases)
4. [Detailed Phase Breakdown](#-detailed-phase-breakdown)
5. [Resource Requirements](#-resource-requirements)
6. [Risk Assessment](#-risk-assessment)
7. [Success Criteria](#-success-criteria)

---

## Executive Summary

### Goal
Deploy GGUF models (Gemma-4-E4B, Qwopus3.5-9B, Llava-1.5-7B, DeepSeek-Coder) on a **distributed Ray cluster** with **VCN-LUPINE acceleration**, orchestrated by **Hermes**, integrated with existing **FrameDispatcher** and **Tailscale mesh networking**.

### Key Innovations
1. **VCN-LUPINE Integration**: Hardware-accelerated video encoding (NVENC/VAAPI) as a computation primitive
2. **Ray ObjectRef Transport**: Replaces TCP/MKV with Ray's distributed object store
3. **Mesh Networking**: Tailscale-based zero-configuration VPN for distributed connectivity
4. **Multi-Architecture**: Support for x86_64 (CUDA) + ARM64 (VAAPI) + CPU-only workloads

### Business Value
- **45x bandwidth reduction** via VCN pipeline (1MB to 22KB per strand)
- **Distributed inference** across heterogeneous hardware
- **Hardware acceleration** for both compute and transport
- **Fault tolerance** through Ray's built-in recovery mechanisms

---

## Architecture Overview

See `gguf-ray-vcn-plan.mmd` for comprehensive Mermaid diagrams.

### Physical Topology
- **Control Plane**: `cupfox` (100.102.173.61) - Ray Head, k3s Master
- **GPU Nodes**: `qfox-1` (CUDA/NVENC), `steamdeck` (VAAPI)
- **CPU Nodes**: `neon-64gb` (ARM64, 16C/56GB), `racknerd` (x86_64, 8C/16GB)

### Model Placement Strategy

| Model | Size | Specialization | Placement | Backend | VRAM Required | RAM Required |
|-------|------|----------------|-----------|---------|---------------|--------------|
| Qwopus3.5-9B | 9B | Code Generation | qfox-1 | CUDA + llama.cpp | 16GB | 8GB |
| Gemma-4-E4B | 4B | General Text | neon-64gb | CPU + llama.cpp | N/A | 16GB |
| Llava-1.5-7B | 7B | Vision (Multimodal) | steamdeck | VAAPI + llama.cpp | 8GB | 12GB |
| DeepSeek-Coder | 6.7B | Code (Fallback) | neon-64gb | CPU + llama.cpp | N/A | 12GB |

---

## Deployment Phases

### Overview

| Phase | Name | Duration | Status | Dependencies |
|-------|------|----------|--------|--------------|
| 1 | Infrastructure Setup | 5 days | Done | None |
| 2 | Ray Cluster Deployment | 4 days | Done | Phase 1 |
| 3 | VCN-LUPINE Integration | 5 days | Done | Phase 2 |
| 4 | GGUF Actor Framework | 5 days | Done | Phase 3 |
| 5 | Model-Specific Actors | 4 days | Done | Phase 4 |
| 6 | Networking & Ingress | 5 days | TODO | Phase 5 |
| 7 | Hermes Orchestrator | 5 days | Partial | Phase 5 |
| 8 | Monitoring & Observability | 5 days | Partial | Phase 5 |
| 9 | Security Hardening | 5 days | TODO | Phase 6 |
| 10 | Performance Optimization | 5 days | TODO | Phase 8 |
| 11 | Documentation | 5 days | TODO | Phase 9 |

---

## Resource Requirements

### Hardware Requirements

| Node | CPU | RAM | GPU | Storage | OS | Architecture |
|------|-----|-----|-----|----------|----|--------------|
| cupfox | 8C | 16GB | None | 500GB SSD | NixOS | x86_64 |
| qfox-1 | 16C | 32GB | RTX 4090 (16GB) | 1TB NVMe | Ubuntu | x86_64 |
| neon-64gb | 16C | 56GB | None | 500GB SSD | Ubuntu | ARM64 |
| steamdeck | 8C | 16GB | AMD iGPU | 1TB NVMe | SteamOS | x86_64 |
| racknerd | 8C | 16GB | None | 250GB SSD | Ubuntu | x86_64 |

### Software Requirements

| Component | Version | Purpose |
|-----------|---------|---------|
| k3s | v1.28.x | Kubernetes distribution |
| Helm | v3.14.x | Package manager |
| Ray | 2.9.0 | Distributed computing |
| Tailscale | 1.6.x | Mesh networking |
| Longhorn | v1.6.x | Distributed storage |
| MetalLB | v0.13.x | Load balancer |
| Prometheus | v2.48.x | Metrics collection |
| Grafana | v10.2.x | Visualization |
| Loki | v2.9.x | Log aggregation |
| Tempo | v2.2.x | Distributed tracing |
| Redis | v7.2.x | Ray GCS backend |
| Traefik | v2.10.x | Ingress controller |
| cert-manager | v1.13.x | TLS certificates |
| llama.cpp | latest | GGUF inference |
| VCN-LUPINE | latest | Video compute substrate |

---

## Risk Assessment

### High Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Single GPU node failure (qfox-1) | Medium | High | Deploy GPU workers on both qfox-1 and steamdeck |
| VCN-LUPINE compatibility issues | Medium | High | Extensive testing on all target architectures |
| Tailscale connectivity issues | Low | High | DERP fallback, keepalive configuration |
| Ray cluster instability | Medium | High | Use stable Ray version (2.9.0), not nightly |
| Model memory requirements exceeded | Medium | High | Resource limits, fallback models |

---

## Success Criteria

### Phase 6: Networking & Ingress
- [ ] Tailscale subnet router deployed
- [ ] Ray dashboard accessible via HTTPS
- [ ] Hermes API accessible via HTTPS
- [ ] Grafana dashboard accessible via HTTPS
- [ ] Service discovery working
- [ ] Cross-cluster communication verified

### Phase 7: Hermes Orchestrator
- [ ] All API endpoints functional
- [ ] Request validation working
- [ ] Model selection logic correct
- [ ] Circuit breaker functional
- [ ] Batch processing optimized
- [ ] Rate limiting effective
- [ ] Authentication integrated

### Phase 8: Monitoring & Observability
- [ ] Prometheus scraping all targets
- [ ] Grafana dashboards complete
- [ ] Alert rules configured
- [ ] Loki collecting logs
- [ ] Tempo collecting traces
- [ ] Metrics coverage > 95%

### Phase 9: Security Hardening
- [ ] All ingress points use HTTPS
- [ ] Authentication required for all endpoints
- [ ] Network policies enforced
- [ ] RBAC configured
- [ ] Secrets encrypted
- [ ] Audit logging enabled

### Phase 10: Performance Optimization
- [ ] Auto-scaling functional
- [ ] GPU sharing configured (if MPS available)
- [ ] Model quantization implemented
- [ ] Request batching optimized
- [ ] Caching strategies in place
- [ ] Performance benchmarks documented

### Phase 11: Documentation
- [ ] API documentation complete
- [ ] Architecture documentation complete
- [ ] Runbook complete
- [ ] Deployment checklist complete

---

## Next Steps

1. Create Phase 6-11 markdown files with detailed microsteps
2. Create documentation files (API.md, ARCHITECTURE.md, RUNBOOK.md, DEPLOYMENT_CHECKLIST.md)
3. Review existing code for completeness and correctness
4. Review existing manifests for best practices

---

*Generated by Mistral Vibe - Continuing deployment plan for GGUF-Ray-VCN-LUPINE*
