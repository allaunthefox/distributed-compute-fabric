# Phase 1: Ray Cluster Setup

**Objective:** Fix Ray cluster distribution across Tailscale mesh.

**Duration:** 2-4 hours  
**Priority:** Critical (Blocker for all other phases)  
**Dependencies:** None

---

## 🎯 Overview

Your existing Ray cluster has all workers pinned to `qfox-1`, creating a single point of failure. This phase distributes workers across your Tailscale mesh nodes and adds VCN-LUPINE integration.

### Before This Phase
```
❌ Head node: qfox-1 (single point of failure)
❌ All workers: qfox-1 (resource contention)
❌ LD_PRELOAD: Not configured
❌ minReplicas: 0 (workers don't start automatically)
❌ Image: nightly-py313-gpu (unstable)
```

### After This Phase
```
✅ Head node: cupfox (control plane)
✅ GPU workers: qfox-1 (CUDA + VCN)
✅ ARM64 workers: neon-64gb (CPU)
✅ VAAPI workers: steamdeck (VAAPI + VCN)
✅ LD_PRELOAD: Configured on all workers
✅ minReplicas: 1 (workers always available)
✅ Image: rayproject/ray:2.9.0-py313-gpu (stable)
```

---

## 📋 Microsteps

---

### 1.1 Update `raycluster.yaml`

**File:** [`raycluster.yaml`](raycluster.yaml)

**Changes to make:**

1. **Move head node to cupfox**
   ```yaml
   headGroupSpec:
     template:
       spec:
         nodeSelector:
           kubernetes.io/hostname: cupfox  # Changed from qfox-1
   ```

2. **Add dashboard authentication**
   ```yaml
   headGroupSpec:
     rayStartParams:
       dashboard-user: "admin"
       dashboard-password: "${RAY_DASHBOARD_PASSWORD}"
   ```

3. **Distribute worker groups**
   ```yaml
   workerGroupSpecs:
     # GPU Workers
     - groupName: gpu-workers
       nodeSelector:
         kubernetes.io/hostname: qfox-1
       resources:
         nvidia.com/gpu: 1
         memory: 24Gi
         cpu: 8
       env:
         - name: LD_PRELOAD
           value: "/usr/local/lib/vcn-lupine.so"
       volumeMounts:
         - name: vcn-shim
           mountPath: /usr/local/lib/vcn-lupine.so
       volumes:
         - name: vcn-shim
           hostPath:
             path: /usr/local/lib/vcn-lupine.so
   
     # ARM64 Workers
     - groupName: arm64-workers
       nodeSelector:
         kubernetes.io/hostname: neon-64gb
       resources:
         memory: 56Gi
         cpu: 16
       env:
         - name: LD_PRELOAD
           value: "/usr/local/lib/vcn-lupine.so"
   
     # VAAPI Workers
     - groupName: vaapi-workers
       nodeSelector:
         kubernetes.io/hostname: steamdeck
       resources:
         memory: 16Gi
         cpu: 4
       env:
         - name: LD_PRELOAD
           value: "/usr/local/lib/vcn-lupine.so"
         - name: LIBVA_DRIVER_NAME
           value: "iHD"
         - name: LIBVA_DRIVERS_PATH
           value: "/usr/lib/x86_64-linux-gnu/dri"
       volumeMounts:
         - name: dri
           mountPath: /dev/dri
       volumes:
         - name: dri
           hostPath:
             path: /dev/dri
   ```

4. **Set minimum replicas**
   ```yaml
   workerGroupSpecs:
     - groupName: gpu-workers
       minReplicas: 1  # Changed from 0
       maxReplicas: 2
     - groupName: arm64-workers
       minReplicas: 1  # Changed from 0
       maxReplicas: 3
     - groupName: vaapi-workers
       minReplicas: 1  # Changed from 0
       maxReplicas: 1
   ```

5. **Switch to stable Ray image**
   ```yaml
   image: rayproject/ray:2.9.0-py313-gpu  # Changed from nightly
   ```

**Full file:** See [`raycluster.yaml`](raycluster.yaml)

---

### 1.2 Create Ray Dashboard Secret

**Command:**
```bash
# Create secret for Ray dashboard authentication
kubectl create secret generic ray-dashboard-secret -n services \
  --from-literal=password=YOUR_SECURE_PASSWORD

# Verify secret
kubectl get secret ray-dashboard-secret -n services -o yaml
```

**Example:**
```bash
kubectl create secret generic ray-dashboard-secret -n services \
  --from-literal=password='S3cur3P@ssw0rd!'
```

---

### 1.3 Apply Ray Cluster Configuration

**Command:**
```bash
# Apply the updated configuration
kubectl apply -f raycluster.yaml -n services

# Wait for head node to be ready (timeout: 10 minutes)
kubectl wait --for=condition=Ready pod -l ray.io/ray-node-type=head -n services --timeout=10m

# Wait for worker nodes to be ready
kubectl wait --for=condition=Ready pod -l ray.io/ray-node-type=worker -n services --timeout=10m
```

**Expected output:**
```
raycluster.ray.io/vcn-ray-cluster configured
```

---

## ✅ Verification

### 1.3.1 Check Ray Dashboard

```bash
# Port-forward Ray dashboard
kubectl port-forward svc/raycluster-head-svc 8265:8265 -n services &

# Access dashboard in browser: http://localhost:8265
# Login with: username=admin, password=YOUR_SECURE_PASSWORD
```

**Expected:**
- Ray dashboard is accessible
- Shows 1 head node (cupfox)
- Shows 3 worker nodes (qfox-1, neon-64gb, steamdeck)

### 1.3.2 Check Nodes via CLI

```bash
# List Ray nodes
ray list-nodes

# Expected output:
# Node: cupfox (head)
# Node: qfox-1 (gpu-worker)
# Node: neon-64gb (arm64-worker)
# Node: steamdeck (vaapi-worker)
```

### 1.3.3 Check LD_PRELOAD Configuration

```bash
# Check environment variable on a worker pod
kubectl exec -it <ray-worker-pod> -n services -- env | grep LD_PRELOAD

# Expected output:
# LD_PRELOAD=/usr/local/lib/vcn-lupine.so
```

### 1.3.4 Check Resource Allocation

```bash
# Check resource requests/limits
kubectl describe pod <ray-worker-pod> -n services | grep -A 5 "Resources"

# Expected:
#   Limits:
#     nvidia.com/gpu: 1 (for qfox-1)
#     memory: 24Gi (for qfox-1)
#     cpu: 8 (for qfox-1)
```

---

## 🔄 Rollback Plan

If something goes wrong:

```bash
# Save current state
kubectl get all -n services -o yaml > backup-before-rollback.yaml

# Revert to previous configuration
kubectl delete -f raycluster.yaml -n services

# Restore from backup
kubectl apply -f <previous-raycluster.yaml> -n services

# Or start fresh with original
kubectl apply -f backup-before-rollback.yaml -n services
```

---

## 📊 Success Criteria

| Criteria | Status | Notes |
|----------|--------|-------|
| Ray cluster deployed | ⬜ | `kubectl get raycluster -n services` |
| Head node on cupfox | ⬜ | `kubectl get pods -n services -o wide` |
| GPU worker on qfox-1 | ⬜ | Check node selector |
| ARM64 worker on neon-64gb | ⬜ | Check node selector |
| VAAPI worker on steamdeck | ⬜ | Check node selector |
| All workers have minReplicas=1 | ⬜ | Check workerGroupSpecs |
| LD_PRELOAD set on all workers | ⬜ | Check pod env |
| Ray dashboard accessible | ⬜ | Port-forward test |
| Ray dashboard has auth | ⬜ | Login test |

---

## 🚀 Next Phase

Once all criteria are met, proceed to **[Phase 2: Docker Images](Phase-2-Docker.md)**

---

## 📝 Notes

### Issues You Might Encounter

1. **Image pull errors**
   - **Cause:** Using `ray:nightly` instead of stable version
   - **Fix:** Use `rayproject/ray:2.9.0-py313-gpu`

2. **Node not found**
   - **Cause:** Node selector doesn't match actual node hostname
   - **Fix:** Verify hostname with `kubectl get nodes -o wide`

3. **Permission denied**
   - **Cause:** VCN-LUPINE shim not accessible
   - **Fix:** Ensure file exists at `/usr/local/lib/vcn-lupine.so` on all nodes

4. **GPU not found**
   - **Cause:** Missing NVIDIA device plugin
   - **Fix:** Install `nvidia-device-plugin-daemonset`

### Useful Commands

```bash
# Check Ray cluster events
kubectl get events -n services --sort-by='.metadata.creationTimestamp'

# Check Ray pod logs
kubectl logs <ray-head-pod> -n services
kubectl logs <ray-worker-pod> -n services

# Check Ray cluster status
kubectl describe raycluster vcn-ray-cluster -n services

# Check node labels
kubectl get nodes --show-labels
```
