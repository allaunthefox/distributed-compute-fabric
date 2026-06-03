# GGUF-Ray-VCN-LUPINE Architecture

**Version:** 1.0.0  
**Last Updated:** 2026-06-01

---

## Table of Contents

1. [Overview](#overview)
2. [Physical Topology](#physical-topology)
3. [Logical Architecture](#logical-architecture)
4. [Component Details](#component-details)
5. [Data Flow](#data-flow)
6. [Network Architecture](#network-architecture)
7. [Security Architecture](#security-architecture)
8. [Performance Considerations](#performance-considerations)

---

## Overview

GGUF-Ray-VCN-LUPINE is a distributed inference system for running GGUF models on a Ray cluster with hardware-accelerated video compression (VCN-LUPINE) and transport.

### Key Innovations

1. **VCN-LUPINE Integration**: Uses hardware-accelerated video encoding (NVENC/VAAPI) as a computation primitive
2. **Ray ObjectRef Transport**: Replaces traditional TCP/MKV transport with Ray's distributed object store
3. **Mesh Networking**: Tailscale-based zero-configuration VPN for distributed connectivity
4. **Multi-Architecture**: Support for x86_64 (CUDA) + ARM64 (VAAPI) + CPU-only workloads

### Business Value

- **45x bandwidth reduction** via VCN pipeline (1MB → 22KB per strand)
- **Distributed inference** across heterogeneous hardware
- **Hardware acceleration** for both compute and transport
- **Fault tolerance** through Ray's built-in recovery mechanisms

---

## Physical Topology

### Nodes

| Node | Tailscale IP | Architecture | GPU | Role | OS |
|------|--------------|--------------|-----|------|----|
| cupfox | 100.102.173.61 | x86_64 | None | Control Plane, k3s Master, Ray Head | NixOS |
| qfox-1 | 100.88.57.96 | x86_64 | RTX 4090 (16GB) | GPU Worker, CUDA/NVENC | Ubuntu |
| neon-64gb | 100.64.19.78 | ARM64 | None | CPU Worker | Ubuntu |
| steamdeck | 100.x.x.x | x86_64 | AMD iGPU | GPU Worker, VAAPI | SteamOS |
| racknerd | 100.80.39.40 | x86_64 | None | CPU Worker | Ubuntu |

### Resource Allocation

| Node | CPU | RAM | GPU VRAM | Storage |
|------|-----|-----|----------|---------|
| cupfox | 8C | 16GB | None | 500GB SSD |
| qfox-1 | 16C | 32GB | 16GB | 1TB NVMe |
| neon-64gb | 16C | 56GB | None | 500GB SSD |
| steamdeck | 8C | 16GB | 4GB (shared) | 1TB NVMe |
| racknerd | 8C | 16GB | None | 250GB SSD |

---

## Logical Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          External Clients                                   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       Traefik Ingress (HTTPS)                              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┬───────────────────────────┐
        │ ray.yourdomain.com:443    │ api.yourdomain.com:443    │
        ▼                           ▼                           ▼
┌─────────────┐         ┌─────────────┐         ┌─────────────┐
│  Ray        │         │  Hermes     │         │  Grafana    │
│  Dashboard  │         │  API        │         │             │
│  (8265)    │         │  (8000)     │         │  (3000)     │
└─────────────┘         └──────┬──────┘         └─────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Tailscale Mesh (100.x.x.x)                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │   cupfox    │    │   qfox-1    │    │ neon-64gb   │    │  steamdeck  │  │
│  │ 100.x.x.x   │    │ 100.x.x.x   │    │ 100.x.x.x   │    │ 100.x.x.x   │  │
│  └─────────────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘  │
└───────────────────────────────────────────┬──────────────┬──────────────┘
                                                    │              │
┌───────────────────────────────────────────▼──────────────▼──────────────┐
│                      k3s Cluster (Kubernetes)                              │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                      Ray Cluster                                    │    │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │    │
│  │  │  Ray Head    │    │ CPU Workers  │    │ GPU Workers  │              │    │
│  │  │  (cupfox)    │    │ (neon-64gb) │    │ (qfox-1)    │              │    │
│  │  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘              │    │
│  │         │                   │                   │                      │    │
│  │         └───────────────────┼───────────────────┘                      │    │
│  │                             │                                          │    │
│  │                    ┌────────┴────────┐                                  │    │
│  │                    │   Ray Object Store│  (Redis + Shared Memory)      │    │
│  │                    │    (Ray GCS)     │                                  │    │
│  │                    └──────────────────┘                                  │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                      VCN-LUPINE Pipeline                             │    │
│  │  Raw Data → Delta+RLE → Reed-Solomon → ChaCha20 → H.264 → MKV      │    │
│  │                          ↓                                              │    │
│  │                 ┌─────────────────┐                                   │    │
│  │                 │ Compute Surfaces │  (NVENC / VAAPI)                  │    │
│  │                 └─────────────────┘                                   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                      Monitoring Stack                                │    │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │    │
│  │  │ Prometheus  │    │   Grafana    │    │    Loki     │              │    │
│  │  └─────────────┘    └─────────────┘    └─────────────┘              │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. Hermes Orchestrator

**Purpose:** Main API server that orchestrates inference requests across the Ray cluster.

**Responsibilities:**
- Request validation and authentication
- Model selection via FrameDispatcher
- Load balancing across model instances
- Circuit breaker pattern for resilience
- Batch processing for efficiency
- Rate limiting
- Metrics collection

**Technology Stack:**
- FastAPI (Python)
- Uvicorn + Gunicorn
- Redis (caching)
- SQLite (local storage)

**Key Files:**
- `code/hermes/main.py` - FastAPI application
- `code/hermes/orchestrator.py` - API endpoints
- `code/hermes/frame_dispatcher.py` - Request routing
- `code/hermes/auth.py` - Authentication
- `code/hermes/cache.py` - Caching
- `code/hermes/batching.py` - Batch processing

---

### 2. Ray Cluster

**Purpose:** Provides distributed computing infrastructure for running model inference.

**Components:**
- **Ray Head**: Cluster coordinator (cupfox)
  - Dashboard (port 8265)
  - Global Control Store (GCS)
  - Autoscaler

- **CPU Workers**: Run CPU-only models (neon-64gb, racknerd)
  - Min: 1, Max: 6 replicas
  - 4 CPUs, 8GB RAM each

- **GPU Workers**: Run GPU-accelerated models (qfox-1, steamdeck)
  - Min: 1, Max: 2 replicas
  - 1 GPU, 16GB RAM each

- **Object Store**: Distributed shared memory
  - Redis backend for persistence
  - In-memory for performance

**Configuration:**
- Ray Operator manages the cluster
- Custom RayCluster resource defines worker groups
- LD_PRELOAD for VCN-LUPINE integration
- Node selectors for hardware-specific scheduling

**Key Files:**
- `kubernetes/ray/raycluster.yaml` - Cluster definition
- `kubernetes/ray/ray-ingress.yaml` - Dashboard access

---

### 3. VCN-LUPINE Substrate

**Purpose:** Provides hardware-accelerated video compression and transport.

**Pipeline Stages:**

| Stage | Operation | Reduction | Hardware |
|-------|-----------|-----------|----------|
| 1 | Delta Encoding | ~2x | CPU |
| 2 | RLE Compression | ~2.5x additional | CPU |
| 3 | Reed-Solomon ECC | ~1.2x overhead | CPU |
| 4 | ChaCha20 Encryption | Minimal | CPU |
| 5 | H.264 Hardware Encode | ~50x | NVENC/VAAPI |
| 6 | MKV Containerization | Minimal | CPU |

**Total Compression:** ~45x (1MB → 22KB per strand)

**Hardware Acceleration:**
- **NVENC**: NVIDIA RTX 4090 (qfox-1)
- **VAAPI**: AMD iGPU (steamdeck)

**Key Files:**
- `code/vcn/vcn_compute_substrate.py` - Compression pipeline
- `code/vcn/ray_vcn_bridge.py` - Ray integration

---

### 4. GGUF Model Actors

**Purpose:** Ray actors that run GGUF models with llama.cpp backend.

**Actor Types:**

| Actor | Model | Specialization | Backend | Node | VRAM | RAM |
|-------|-------|----------------|---------|------|------|-----|
| CoderActor | Qwopus3.5-9B | Code Generation | CUDA | qfox-1 | 16GB | 8GB |
| VisionActor | Llava-1.5-7B | Multimodal Vision | VAAPI | steamdeck | 8GB | 12GB |
| GeneralActor | Gemma-4-E4B | General Text | CPU | neon-64gb | N/A | 16GB |
| DeepSeekCoderActor | DeepSeek-Coder | Code (Fallback) | CPU | neon-64gb | N/A | 12GB |

**Features:**
- Lazy loading of models (on first request)
- Health checks and metrics collection
- Async generation with ObjectRef
- Multimodal support (text + images)
- Local caching with checksum verification

**Key Files:**
- `code/actors/gguf_actors.py` - Base actor class
- `code/actors/coder_actor.py` - CoderActor
- `code/actors/vision_actor.py` - VisionActor
- `code/actors/general_actor.py` - GeneralActor

---

### 5. Tailscale Mesh Networking

**Purpose:** Provides zero-configuration VPN for distributed connectivity across all nodes.

**Nodes:**
- cupfox: Control plane (100.102.173.61)
- qfox-1: GPU worker (100.88.57.96)
- neon-64gb: CPU worker (100.64.19.78)
- steamdeck: GPU worker (100.x.x.x)
- racknerd: CPU worker (100.80.39.40)

**Components:**
- **Tailscale DaemonSet**: Runs on all Kubernetes nodes
- **Subnet Router**: Routes Kubernetes subnet traffic through Tailscale
- **DERP**: Fallback relay for when direct peer-to-peer fails
- **MagicDNS**: Automatic DNS for Tailscale IPs (*.ts.net)

**Key Files:**
- `kubernetes/tailscale/tailscale-subnet-router.yaml` - DaemonSet
- `kubernetes/tailscale/cluster-role.yaml` - RBAC
- `kubernetes/tailscale/namespace.yaml` - Namespace

---

### 6. Monitoring Stack

**Purpose:** Provides comprehensive observability for the system.

**Components:**
- **Prometheus**: Metrics collection and storage
- **Grafana**: Visualization and dashboards
- **Loki**: Log aggregation and querying
- **Tempo**: Distributed tracing
- **Alertmanager**: Alert notifications
- **Prometheus Operator**: Manages monitoring resources

**Key Metrics:**
- Request count and latency
- Token generation rate
- Error rates
- Model loading times
- Resource utilization (CPU, Memory, GPU)
- Ray cluster health
- VCN pipeline performance

**Key Files:**
- `kubernetes/monitoring/prometheus-operator-values.yaml`
- `kubernetes/monitoring/grafana-dashboard.yaml`
- `kubernetes/monitoring/alert-rules.yaml`

---

## Data Flow

### Request Flow

```
┌─────────┐     POST /generate      ┌──────────────┐
│ User    │───────────────────────▶│ Hermes API   │
└─────────┘                        └──────┬───────┘
                                             │
                                             ▼
┌──────────────────────────────────────────────────────────────┐
│                        Hermes Processing                         │
│  1. Validate request (JWT, parameters)                          │
│  2. Check rate limits                                             │
│  3. FrameDispatcher selects model                                 │
│     - Auto-detect model type if not specified                     │
│     - Look up MODEL_REGISTRY                                     │
│     - Check circuit breaker state                                 │
│     - Select appropriate actor                                   │
└──────────────────────────────────────────────────────────────┘
                                             │
                                             ▼
┌──────────────────────────────────────────────────────────────┐
│                      Ray Cluster Processing                       │
│  1. Ray Head schedules task                                     │
│  2. Worker node executes actor                                  │
│  3. Actor loads model (lazy, on first request)                  │
│     - Check local cache                                          │
│     - Download from HuggingFace if needed                        │
│     - Verify checksum                                            │
│     - Load with llama.cpp                                        │
│  4. Model generates response                                     │
│  5. Return ObjectRef (distributed reference)                     │
└──────────────────────────────────────────────────────────────┘
                                             │
                                             ▼
┌──────────────────────────────────────────────────────────────┐
│                     VCN Pipeline (Optional)                      │
│  If request includes video/frame data:                           │
│  1. Delta + RLE compression (5x reduction)                      │
│  2. Reed-Solomon ECC (error correction)                          │
│  3. ChaCha20 encryption (256-bit)                                │
│  4. H.264 hardware encode (50x reduction)                       │
│     - NVENC on qfox-1                                            │
│     - VAAPI on steamdeck                                        │
│  5. MKV containerization                                         │
│                                                                  │
│  Result: ~45x compression (1MB → 22KB)                          │
└──────────────────────────────────────────────────────────────┘
                                             │
                                             ▼
┌──────────────────────────────────────────────────────────────┐
│                      Response Flow                                │
│  1. Ray returns ObjectRef to Hermes                               │
│  2. Hermes retrieves result from Object Store                    │
│  3. Format response (JSON or SSE)                                 │
│  4. Record metrics (latency, tokens, etc.)                       │
│  5. Return to user                                                │
└──────────────────────────────────────────────────────────────┘
                                             │
                                             ▼
                                    ┌─────────┐
                                    │ User    │
                                    └─────────┘
```

### Model Loading Flow

```
┌──────────────────────────────────────────────────────────────┐
│                    Model Loading Sequence                         │
└──────────────────────────────────────────────────────────────┘

1. First request for a model type
   └─ FrameDispatcher checks if actor exists
   └─ If not, create new actor

2. Actor.__init__()
   └─ Store model path and configuration
   └─ Register with Ray

3. Actor.load_model() [async, lazy]
   └─ Check if model exists in local cache
       ├─ If yes: Load from cache
       └─ If no: Download from HuggingFace
           └─ Download model file
           └─ Download mmproj (for multimodal)
           └─ Verify checksum
           └─ Save to cache
   └─ Load model with llama.cpp
       └─ Configure GPU layers (if CUDA)
       └─ Configure context size
       └─ Configure threads
   └─ Run health check
   └─ Register as available

4. Model ready for inference
   └─ Actor.mark_loaded()
   └─ Update MODEL_REGISTRY
   └─ Emit metrics

5. Subsequent requests
   └─ Actor already loaded
   └─ Skip loading, go directly to inference
```

### Batch Processing Flow

```
┌──────────────────────────────────────────────────────────────┐
│                      Batch Processing                              │
└──────────────────────────────────────────────────────────────┘

1. User sends batch request
   └─ POST /generate/batch
   └─ {requests: [req1, req2, req3, ...]}

2. Hermes receives request
   └─ Parse batch
   └─ Group by model type

3. For each model type group
   └─ Get actor for that model type
   └─ If actor supports batch
       └─ Call actor.generate_batch()
   └─ Else
       └─ Call actor.generate() for each request

4. Ray processes batch
   └─ Schedule batch task
   └─ Worker executes batch
   └─ Return list of results

5. Hermes aggregates results
   └─ Combine results from all model types
   └─ Calculate totals
   └─ Return batch response

Benefits:
- Reduces overhead (single task vs multiple)
- Better GPU utilization
- Reduced network traffic
- Consistent ordering
```

---

## Network Architecture

### Service Discovery

Kubernetes DNS names for internal service discovery:

| Service | DNS Name | Port | Namespace |
|---------|----------|------|----------|
| Ray Head | raycluster-head-svc.ray-system.svc.cluster.local | 8265 | ray-system |
| Ray Workers | raycluster-worker-svc.ray-system.svc.cluster.local | Various | ray-system |
| Hermes API | hermes-service.hermes.svc.cluster.local | 8000 | hermes |
| Prometheus | prometheus-operated.monitoring.svc.cluster.local | 9090 | monitoring |
| Grafana | grafana-service.monitoring.svc.cluster.local | 3000 | monitoring |
| Redis | redis-service.ray-system.svc.cluster.local | 6379 | ray-system |
| Loki | loki.monitoring.svc.cluster.local | 3100 | monitoring |
| Tempo | tempo.monitoring.svc.cluster.local | 3200 | monitoring |

### External Access

| Service | Domain | Port | Protocol | Ingress |
|---------|--------|------|----------|---------|
| Ray Dashboard | ray.yourdomain.com | 443 | HTTPS | Traefik IngressRoute |
| Hermes API | api.yourdomain.com | 443 | HTTPS | Traefik IngressRoute |
| Grafana | grafana.yourdomain.com | 443 | HTTPS | Traefik IngressRoute |

### Tailscale Integration

Tailscale provides:
- **Mesh Networking**: All nodes connected via WireGuard
- **Service Discovery**: mDNS for service names (*.ts.net)
- **Subnet Routing**: Kubernetes pod IPs routed through Tailscale
- **DERP**: Fallback relay for NAT traversal

**Tailscale IPs:**
- cupfox: 100.102.173.61
- qfox-1: 100.88.57.96
- neon-64gb: 100.64.19.78
- steamdeck: 100.x.x.x
- racknerd: 100.80.39.40

---

## Security Architecture

### Authentication

| Component | Authentication Method | Credentials |
|-----------|----------------------|-------------|
| Hermes API | JWT Bearer Tokens | Username/Password or OAuth2 |
| Ray Dashboard | Basic Auth | Username/Password |
| Grafana | Basic Auth | Username/Password |
| Prometheus | None (internal) | - |
| Loki | None (internal) | - |
| Tempo | None (internal) | - |

### Authorization

| Role | Permissions | Access |
|------|-------------|--------|
| Anonymous | Read-only (rate limited) | Public endpoints |
| User | Generate requests | /generate, /models |
| Premium | Higher rate limits | All endpoints |
| Admin | Full access | All endpoints, admin APIs |
| Service | Internal access | Service-to-service |

### Data Protection

| Layer | Protection Method | Implementation |
|-------|-------------------|----------------|
| Network | TLS 1.3 | cert-manager + Let's Encrypt |
| Storage | Encryption at rest | Kubernetes secrets encryption |
| Transit | Encryption | All inter-service TLS |
| VCN | ChaCha20 | VCN-LUPINE pipeline |

### Network Policies

Default-deny with explicit allow rules:

- **Ray Cluster**: Allow internal Ray traffic + monitoring
- **Hermes**: Allow Ray cluster + monitoring + external HTTPS
- **Monitoring**: Allow internal scraping + external HTTPS

---

## Performance Considerations

### Scaling

| Component | Min | Max | Auto-scaling | Trigger |
|-----------|-----|-----|--------------|---------|
| Ray Head | 1 | 1 | No | - |
| Ray CPU Workers | 1 | 6 | Yes (KEDA) | CPU/Memory |
| Ray GPU Workers | 1 | 2 | Yes (KEDA) | GPU/Queue |
| Hermes API | 2 | 10 | Yes (KEDA) | CPU/Requests |

### Resource Allocation

**Ray Workers:**
- CPU: 4 vCPUs, 8GB RAM each
- GPU: 1 GPU, 16GB VRAM each

**Hermes:**
- 2 vCPUs, 4GB RAM per replica
- Horizontal pod autoscaling

### Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| Request Latency (p95) | < 1s | From request to first token |
| Tokens/Second | > 100 | Across all models |
| Model Load Time | < 5s | Cold start to ready |
| Compression Ratio | > 40x | VCN pipeline efficiency |
| GPU Utilization | > 80% | Average across GPU nodes |
| CPU Utilization | > 70% | Average across CPU nodes |

### Optimization Techniques

1. **GPU Sharing**: NVIDIA MPS for multi-process GPU access
2. **Model Quantization**: INT8 (50% size), INT4 (25% size)
3. **Request Batching**: Group similar requests for batch processing
4. **Caching**: Redis cache for frequent requests
5. **Lazy Loading**: Models loaded on first request
6. **Circuit Breaker**: Prevent cascading failures

---

*For deployment instructions, see the [Deployment Checklist](DEPLOYMENT_CHECKLIST.md).*
*For operational procedures, see the [Runbook](RUNBOOK.md).*
