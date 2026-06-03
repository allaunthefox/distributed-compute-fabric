# GGUF-Ray-VCN-LUPINE Deployment Checklist

**Version:** 1.0.0  
**Last Updated:** 2026-06-01

---

## Overview

This checklist provides step-by-step instructions for deploying the GGUF-Ray-VCN-LUPINE system from scratch. Follow the phases in order, completing all steps in each phase before moving to the next.

---

## Prerequisites Checklist

### Hardware Requirements

- [ ] **cupfox**: 8C/16GB RAM, 500GB SSD, NixOS, x86_64
- [ ] **qfox-1**: 16C/32GB RAM, 1TB NVMe, Ubuntu 22.04, x86_64, RTX 4090 (16GB VRAM)
- [ ] **neon-64gb**: 16C/56GB RAM, 500GB SSD, Ubuntu 22.04, ARM64
- [ ] **steamdeck**: 8C/16GB RAM, 1TB NVMe, SteamOS, x86_64, AMD iGPU
- [ ] **racknerd**: 8C/16GB RAM, 250GB SSD, Ubuntu 22.04, x86_64

### Software Requirements

- [ ] **NVIDIA Drivers**: Version 535+ installed on qfox-1
- [ ] **CUDA Toolkit**: Version 12.4 installed on qfox-1
- [ ] **VAAPI**: Installed and configured on steamdeck
- [ ] **Tailscale**: Installed on all nodes
- [ ] **Docker**: Installed on all nodes (k3s will use its own)
- [ ] **Git**: Installed on all nodes
- [ ] **curl**: Installed on all nodes

### Network Requirements

- [ ] All nodes connected to Tailscale mesh
- [ ] DNS configured for all domains (ray.yourdomain.com, api.yourdomain.com, grafana.yourdomain.com)
- [ ] Ports 80/443 available for ingress
- [ ] UDP 41641 open for Tailscale
- [ ] Firewall allows internal traffic between nodes

### Credentials & Keys

- [ ] Tailscale authentication key
- [ ] HuggingFace API token (for model downloads)
- [ ] Let's Encrypt email (for TLS certificates)
- [ ] JWT secret key (for authentication)
- [ ] Ray dashboard password
- [ ] Grafana admin password
- [ ] Redis password (optional)
- [ ] Slack webhook URL (for alerts)

---

## Phase 1: Infrastructure Setup (5 days)

### Tailscale Setup

- [ ] Install Tailscale on cupfox
- [ ] Install Tailscale on qfox-1
- [ ] Install Tailscale on neon-64gb
- [ ] Install Tailscale on steamdeck
- [ ] Install Tailscale on racknerd
- [ ] Authenticate all nodes to Tailscale
- [ ] Verify node-to-node connectivity via Tailscale IPs
- [ ] Document Tailscale IPs for all nodes
- [ ] Test file transfer between nodes

**Verification:**
```bash
# On any node, test connectivity to others
tailscale ping 100.102.173.61  # cupfox
tailscale ping 100.88.57.96   # qfox-1
tailscale ping 100.64.19.78   # neon-64gb
tailscale ping 100.80.39.40   # racknerd
```

### k3s Cluster Initialization

- [ ] Install k3s on cupfox (master node)
- [ ] Join qfox-1 to cluster as worker
- [ ] Join neon-64gb to cluster as worker
- [ ] Join steamdeck to cluster as worker
- [ ] Join racknerd to cluster as worker
- [ ] Label nodes with appropriate labels
- [ ] Taint nodes as needed (e.g., `desktop=true:NoSchedule`)
- [ ] Verify all nodes are Ready

**Commands:**
```bash
# On cupfox (master)
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--flannel-iface=tailscale0" sh -s - server --cluster-init

# On worker nodes (qfox-1, neon-64gb, steamdeck, racknerd)
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--flannel-iface=tailscale0" sh -s - agent --server https://cupfox:6443 --token NODE_TOKEN

# Label nodes
kubectl label nodes cupfox node-role.kubernetes.io/master=true
kubectl label nodes qfox-1 hardware=gpu gpu-type=nvidia
kubectl label nodes steamdeck hardware=gpu gpu-type=vaapi
kubectl label nodes neon-64gb hardware=cpu arch=arm64
kubectl label nodes racknerd hardware=cpu arch=x86_64

# Taint desktop nodes (if applicable)
kubectl taint nodes qfox-1 desktop=true:NoSchedule
kubectl taint nodes steamdeck desktop=true:NoSchedule
```

**Verification:**
```bash
kubectl get nodes -o wide
# Expected: All nodes should show Ready status
```

### Storage Setup (Longhorn)

- [ ] Install Longhorn via Helm
- [ ] Verify storage class is available
- [ ] Test volume creation
- [ ] Configure default storage class

**Commands:**
```bash
# Add Longhorn repo
helm repo add longhorn https://charts.longhorn.io
helm repo update

# Install Longhorn
helm install longhorn longhorn/longhorn --namespace longhorn-system --create-namespace

# Verify
kubectl get pods -n longhorn-system
kubectl get storageclass
kubectl patch storageclass longhorn -p '{"metadata": {"annotations": {"storageclass.kubernetes.io/is-default-class": "true"}}}'
```

**Verification:**
```bash
kubectl get sc
# Expected: longhorn should be default

# Test volume creation
kubectl create -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: longhorn
  resources:
    requests:
      storage: 1Gi
EOF
kubectl get pvc test-pvc
kubectl delete pvc test-pvc
```

### Network Setup

- [ ] Install MetalLB for LoadBalancer services
- [ ] Configure LoadBalancer IPs
- [ ] Install Traefik ingress controller
- [ ] Verify ingress is working

**Commands:**
```bash
# Install MetalLB
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.13.12/config/manifests/metallb-native.yaml

# Configure IP pool
kubectl apply -f - <<EOF
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: default-pool
  namespace: metallb-system
spec:
  addresses:
  - 192.168.1.100-192.168.1.200
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: default-advertisement
  namespace: metallb-system
spec:
  ipAddressPools:
  - default-pool
EOF

# Install Traefik via Helm
helm repo add traefik https://helm.traefik.io/traefik
helm repo update
helm install traefik traefik/traefik -n traefik --create-namespace \
  --set service.type=LoadBalancer \
  --set ports.websecure.tls.enabled=true
```

**Verification:**
```bash
kubectl get pods -n traefik
kubectl get svc -n traefik
kubectl get ipaddresspool -n metallb-system
```

---

## Phase 2: Ray Cluster Deployment (4 days)

### Ray Operator Installation

- [ ] Add Ray Operator Helm repo
- [ ] Install Ray Operator
- [ ] Verify operator is running

**Commands:**
```bash
# Add Ray repo
helm repo add ray-project https://ray-project.github.io/kuberay-helm/
helm repo update

# Install Ray Operator
helm install kuberay-operator ray-project/kuberay-operator \
  --namespace ray-system --create-namespace \
  --version 1.1.0
```

**Verification:**
```bash
kubectl get pods -n ray-system
# Expected: kuberay-operator pod should be Running
```

### Redis Installation (for Ray GCS)

- [ ] Install Redis for Ray Global Control Store

**Commands:**
```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update
helm install redis bitnami/redis --namespace ray-system \
  --set architecture=standalone \
  --set auth.enabled=false
```

**Verification:**
```bash
kubectl get pods -n ray-system | grep redis
kubectl get svc -n ray-system | grep redis
```

### RayCluster Configuration

- [ ] Create RayCluster custom resource
- [ ] Configure head node on cupfox
- [ ] Configure CPU worker group
- [ ] Configure GPU worker group
- [ ] Configure LD_PRELOAD for VCN-LUPINE
- [ ] Configure Redis for GCS
- [ ] Configure autoscaling

**File:** `kubernetes/ray/raycluster.yaml`
```yaml
apiVersion: ray.io/v1alpha1
kind: RayCluster
metadata:
  name: raycluster
  namespace: ray-system
spec:
  rayVersion: "2.9.0"
  headGroupSpec:
    rayStartParams: {}
    serviceType: ClusterIP
    template:
      spec:
        containers:
        - name: ray-head
          image: rayproject/ray:2.9.0-py313-gpu
          env:
          - name: RAY_GCS_SERVER_PORT
            value: "6379"
          - name: RAY_monitor_target
            value: "0"
          - name: LD_PRELOAD
            value: "/usr/local/lib/libvcn_lupine.so"
        nodeSelector:
          kubernetes.io/hostname: cupfox
  workerGroupSpecs:
  - groupName: cpu-workers
    rayStartParams: {}
    serviceType: ClusterIP
    replicas: 1
    minReplicas: 1
    maxReplicas: 6
    template:
      spec:
        containers:
        - name: ray-worker
          image: rayproject/ray:2.9.0-py313-gpu
          env:
          - name: RAY_GCS_SERVER_PORT
            value: "6379"
          - name: LD_PRELOAD
            value: "/usr/local/lib/libvcn_lupine.so"
          - name: RAY_object_store_allocation_factor
            value: "0.8"
        nodeSelector:
          hardware: cpu
  - groupName: gpu-workers
    rayStartParams: {}
    serviceType: ClusterIP
    replicas: 1
    minReplicas: 1
    maxReplicas: 2
    template:
      spec:
        containers:
        - name: ray-worker
          image: rayproject/ray:2.9.0-py313-gpu
          env:
          - name: RAY_GCS_SERVER_PORT
            value: "6379"
          - name: LD_PRELOAD
            value: "/usr/local/lib/libvcn_lupine.so"
          - name: NVIDIA_VISIBLE_DEVICES
            value: "all"
          - name: NVIDIA_DRIVER_CAPABILITIES
            value: "compute,utility"
        nodeSelector:
          hardware: gpu
        resources:
          limits:
            nvidia.com/gpu: 1
  enableInTreeAutoscaling: true
```

**Apply:**
```bash
kubectl apply -f kubernetes/ray/raycluster.yaml
```

**Verification:**
```bash
kubectl get raycluster -n ray-system
kubectl get pods -n ray-system
kubectl wait --for=condition=Ready pod -n ray-system ray-head-xxxx --timeout=300s
```

### Ray Dashboard Ingress

- [ ] Create Ray service
- [ ] Create Ray dashboard ingress

**File:** `kubernetes/ray/ray-ingress.yaml`
```yaml
apiVersion: v1
kind: Service
metadata:
  name: raycluster-head-svc
  namespace: ray-system
  labels:
    app: ray-head
spec:
  selector:
    ray.io/cluster: raycluster
    ray.io/group: head
  ports:
    - name: dashboard
      port: 8265
      targetPort: 8265
---
apiVersion: traefik.containo.us/v1alpha1
kind: IngressRoute
metadata:
  name: ray-dashboard
  namespace: ray-system
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`ray.yourdomain.com`)
      kind: Rule
      services:
        - name: raycluster-head-svc
          port: 8265
  tls:
    secretName: ray-dashboard-tls
```

**Apply:**
```bash
kubectl apply -f kubernetes/ray/ray-ingress.yaml
```

**Verification:**
```bash
kubectl get ingressroute -n ray-system
kubectl get svc -n ray-system raycluster-head-svc
# Access dashboard: http://ray.yourdomain.com (will be updated to HTTPS in Phase 6)
```

---

## Phase 3: VCN-LUPINE Integration (5 days)

### VCN Compute Substrate Build

- [ ] Build VCN compute substrate with FFmpeg
- [ ] Configure hardware acceleration (NVENC/VAAPI)
- [ ] Test VCN pipeline locally

**Dockerfile:** `Dockerfile.vcn`
```dockerfile
FROM nvcr.io/nvidia/cuda:12.4.1-base-ubuntu22.04

# Install dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    pkg-config \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install CUDA and VAAPI support
RUN apt-get install -y \
    nvidia-driver-535 \
    nvidia-cuda-toolkit \
    libva-dev \
    libva-drm2 \
    vainfo \
    mesa-va-drivers \
    && rm -rf /var/lib/apt/lists/*

# Clone and build VCN-LUPINE
RUN git clone https://github.com/your-org/vcn-lupine.git && \
    cd vcn-lupine && \
    mkdir build && cd build && \
    cmake .. && \
    make -j$(nproc) && \
    make install

# Copy library to standard location
RUN cp /usr/local/lib/libvcn_lupine.so /usr/lib/x86_64-linux-gnu/

# Install Python dependencies
RUN pip install ray[default] numpy opencv-python

ENV LD_PRELOAD=/usr/local/lib/libvcn_lupine.so
ENV VCN_LOG_LEVEL=INFO
```

**Build and push:**
```bash
# Build on qfox-1 (for CUDA)
docker build -t your-registry/vcn-lupine-cuda:latest -f Dockerfile.vcn .
docker push your-registry/vcn-lupine-cuda:latest

# Build on steamdeck (for VAAPI)
# Use similar Dockerfile but with VAAPI dependencies
docker build -t your-registry/vcn-lupine-vaapi:latest -f Dockerfile.vcn.vaapi .
docker push your-registry/vcn-lupine-vaapi:latest
```

### Ray VCN Bridge Implementation

- [ ] Implement Ray VCN bridge
- [ ] Replace TCP/MKV transport with ObjectRef
- [ ] Integrate with FrameDispatcher
- [ ] Enable zero-copy shared memory
- [ ] Add FAMM gate checks

**File:** `code/vcn/ray_vcn_bridge.py`
```python
"""
Ray VCN Bridge

Replaces traditional TCP/MKV transport with Ray ObjectRef transport.
Maintains compatibility with existing FrameDispatcher.
"""

import ray
import logging
from typing import Any, Dict, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class RayVCNBridge:
    """
    Bridge between FrameDispatcher and VCN-LUPINE via Ray.
    
    Provides async transport using Ray ObjectRef instead of TCP/MKV.
    """
    
    def __init__(self, max_workers: int = 4):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.vcn_pipeline = VCNPipeline()
    
    @ray.remote
    def process_frames(self, frames: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process frames through VCN pipeline using Ray.
        
        Args:
            frames: Dictionary containing frame data and metadata
        
        Returns:
            Dictionary containing processed frames and ObjectRef
        """
        # Process through VCN pipeline
        compressed = self.vcn_pipeline.process(frames["data"])
        
        return {
            "compressed": compressed,
            "metadata": frames["metadata"],
            "size": len(compressed),
            "original_size": len(frames["data"]),
        }
    
    async def send(self, frames: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send frames through Ray VCN bridge.
        
        Args:
            frames: Dictionary containing frame data and metadata
        
        Returns:
            Dictionary containing ObjectRef and metadata
        """
        # Submit to Ray for processing
        future = self.process_frames.remote(frames)
        
        return {
            "object_ref": future,
            "metadata": frames["metadata"],
        }
    
    async def receive(self, object_ref: Any) -> Dict[str, Any]:
        """
        Receive processed frames from Ray ObjectRef.
        
        Args:
            object_ref: Ray ObjectRef to retrieve
        
        Returns:
            Dictionary containing decompressed frames
        """
        result = ray.get(object_ref)
        
        # Decompress if needed
        if "compressed" in result:
            result["data"] = self.vcn_pipeline.decompress(result["compressed"])
        
        return result
    
    def get_compression_stats(self) -> Dict[str, float]:
        """Get compression statistics."""
        return self.vcn_pipeline.get_stats()
```

### FrameDispatcher Integration

- [ ] Update FrameDispatcher to use Ray VCN bridge
- [ ] Add transport selection logic

**File:** `code/frame_dispatcher.py` (update)
```python
# Add to FrameDispatcher class
class FrameDispatcher:
    # ... existing code ...
    
    def __init__(self):
        # ... existing init ...
        self.vcn_bridge = RayVCNBridge()
        self.use_vcn = True  # Feature flag
    
    def send_frames(self, frames: Dict[str, Any]) -> Dict[str, Any]:
        """Send frames using VCN bridge if enabled."""
        if self.use_vcn:
            return self.vcn_bridge.send(frames)
        else:
            # Fallback to TCP/MKV
            return self.legacy_send(frames)
```

---

## Phase 4-11: Remaining Phases

For Phases 4-11, refer to the individual phase documents:

- **Phase 4: GGUF Actor Framework** - `Phase-4-GGUF-Actor-Framework.md`
- **Phase 5: Model-Specific Actors** - `Phase-5-Model-Actors.md`
- **Phase 6: Networking & Ingress** - `Phase-6-Networking.md`
- **Phase 7: Hermes Orchestrator** - `Phase-7-Hermes.md`
- **Phase 8: Monitoring & Observability** - `Phase-8-Monitoring.md`
- **Phase 9: Security Hardening** - `Phase-9-Security.md`
- **Phase 10: Performance Optimization** - `Phase-10-Performance.md`
- **Phase 11: Documentation** - `Phase-11-Documentation.md`

Each phase document contains detailed microsteps, verification commands, and troubleshooting guidance.

---

## Post-Deployment Verification

### End-to-End Test

- [ ] All pods are running
- [ ] Ray dashboard is accessible
- [ ] Hermes API is accessible
- [ ] All models are available
- [ ] Generate request succeeds
- [ ] Batch generate request succeeds
- [ ] Monitoring dashboards show data
- [ ] Alerts are configured and working
- [ ] TLS certificates are valid
- [ ] Authentication works
- [ ] Rate limiting works
- [ ] Auto-scaling works

**Test Script:**
```bash
#!/bin/bash
set -e

echo "=== End-to-End Verification ==="
echo

# 1. Check all pods
echo "1. Checking all pods..."
kubectl get pods -A
echo

# 2. Check Ray dashboard
echo "2. Checking Ray dashboard..."
curl -k https://admin:password@ray.yourdomain.com/server/ray/api/nodes | jq .
echo

# 3. Check Hermes health
echo "3. Checking Hermes health..."
curl -k https://api.yourdomain.com/health | jq .
echo

# 4. Check models
echo "4. Checking models..."
curl -k https://api.yourdomain.com/models | jq .
echo

# 5. Test generate
echo "5. Testing generate endpoint..."
TOKEN=$(curl -k -X POST https://api.yourdomain.com/auth/token \
  -d "username=admin&password=your-secret" | jq -r .access_token)
curl -k -X POST https://api.yourdomain.com/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello world", "max_tokens": 10}' | jq .
echo

# 6. Test batch generate
echo "6. Testing batch generate..."
curl -k -X POST https://api.yourdomain.com/generate/batch \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"requests": [{"prompt": "Hello", "max_tokens": 5}, {"prompt": "World", "max_tokens": 5}]}' | jq .
echo

# 7. Check Grafana
echo "7. Checking Grafana..."
curl -k https://grafana.yourdomain.com/api/health | jq .
echo

# 8. Check Prometheus targets
echo "8. Checking Prometheus targets..."
kubectl exec -n monitoring prometheus-xxxx -- curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets | length'
echo

echo "=== All tests passed! ==="
```

---

## Rollback Procedures

If deployment fails, use the following rollback procedures:

### Rollback Phase 1-2

```bash
# Delete Ray cluster
kubectl delete raycluster -n ray-system raycluster
kubectl delete ns ray-system

# Delete k3s cluster
# On each worker node:
/usr/local/bin/k3s-agent-uninstall.sh
# On master node:
/usr/local/bin/k3s-uninstall.sh

# Remove Tailscale
# On each node:
tailscale down
```

### Rollback Phase 3-7

```bash
# Delete Hermes
kubectl delete ns hermes

# Delete monitoring
kubectl delete ns monitoring

# Delete VCN components
kubectl delete ns vcn  # if created
```

---

## Success Criteria

Before considering the deployment complete, verify:

- [ ] All phases 1-11 are complete
- [ ] All verification steps pass
- [ ] All security measures are in place
- [ ] All monitoring is configured and working
- [ ] Performance meets targets (see ARCHITECTURE.md)
- [ ] Documentation is complete
- [ ] Backups are configured
- [ ] Disaster recovery plan is in place
- [ ] Stakeholders are notified
- [ ] Production cutover is successful

---

## Next Steps

1. **Monitor closely** for first 24-48 hours
2. **Tune performance** based on real usage
3. **Address any issues** that arise
4. **Iterate and improve** based on feedback
5. **Plan for scaling** as usage grows

---

*For detailed information, see the [Architecture Documentation](ARCHITECTURE.md) and [Runbook](RUNBOOK.md).*
