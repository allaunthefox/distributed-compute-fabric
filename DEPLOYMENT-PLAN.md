# Deployment Plan: Path-Based Routing with Traefik Ingress (Option A)

## Overview

This document describes the **safe, staged deployment** of path-based routing via Traefik Ingress on **cupfox**, with host Caddy on nixos-laptop as a stable forwarder. This follows **Option A** to avoid etcd thundering herd.

### Current Architecture

```
Internet → edge Caddy (racknerd:443, TLS) → host Caddy (nixos:80, NodePort router) → Services
```

- **cupfox** (100.110.163.82, Debian): k3s **server** (control plane) with Traefik **disabled**
- **nixos-laptop** (100.102.173.61): k3s **agent** + host Caddy (NodePort routing)
- **Traefik**: Currently **NOT running** (disabled on cupfox)
- **neon-64gb** (100.100.75.113 Tailscale / 152.53.81.164 public): ARM64 server, hosts Hermes with GGUF model

### Hermes Model Hosting (NEW)

- **Model file**: `/home/allaun/Downloads/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf` on neon-64gb
- **HostPath mount**: Hermes pod mounts `/home/allaun/Downloads` to `/models/`
- **Garage backup**: Model can be uploaded to Garage S3 at `http://100.88.57.96:3900` (qfox-1)
- **Upload script**: `scripts/upload-hermes-model.sh` for uploading to Garage
- **Fallback**: InitContainer downloads from Garage if host file missing

**Garage S3 Configuration:**
- Endpoint: `http://100.88.57.96:3900`
- Bucket: `hermes-models`
- Credentials: K8s Secret `garage-s3-credentials` (AWS-compatible)

**Direct Download:**
- HuggingFace: `https://huggingface.co/HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive/resolve/main/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf`

---

## Neon Node Deployment

### Add neon-64gb to the Cluster

The neon-64gb node (ARM64, 2TB NVMe) is configured in `flake.nix` as `k3s-neon` and joins the cupfox control plane.

**Node details:**
- Hostname: `neon-64gb`
- Tailscale IP: `100.100.75.113`
- Public IP: `152.53.81.164`
- Role: Heavy compute for LLM inference
- Labels: `kubernetes.io/arch=arm64`, `topology.researchstack.io/role=neon`

**To deploy neon-64gb:**

```bash
# Copy flake files to neon-64gb
rsync -av flake.nix flake.lock k3s-configuration.nix roles/neon.nix \
  root@100.100.75.113:/etc/nixos/k3s-flake/

# Rebuild
ssh root@100.100.75.113 "cd /etc/nixos/k3s-flake && nixos-rebuild switch --flake .#k3s-neon"
```

**Verification:**
```bash
# Check node joined
kubectl get nodes -o wide | grep neon-64gb

# Check labels
kubectl get node neon-64gb --show-labels

# Verify k3s agent is healthy
kubectl describe node neon-64gb | grep -i condition
```

### Model File Placement

**Primary location:** `/home/allaun/Downloads/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf` on neon-64gb

**To place the model file:**
```bash
# On neon-64gb:
# Ensure the Downloads directory exists
mkdir -p /home/allaun/Downloads

# Download directly from HuggingFace (if not already present)
curl -L -o /home/allaun/Downloads/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf \
  "https://huggingface.co/HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive/resolve/main/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf"

# Or copy from local machine
scp /path/to/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf \
  root@100.100.75.113:/home/allaun/Downloads/

# Set correct permissions
chmod 644 /home/allaun/Downloads/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf
```

### Garage Backup (Optional)

Upload the model to Garage S3 for backup/persistence:

```bash
# On neon-64gb or any machine with Garage CLI:
bash upload-hermes-model.sh /home/allaun/Downloads/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf hermes-models
```

This uploads to Garage S3 at `http://100.88.57.96:3900` (qfox-1).

### Deploy Hermes Pod

The Hermes deployment is already configured to:
1. Run on neon-64gb (via nodeSelector)
2. Mount `/home/allaun/Downloads` as `/models` (hostPath)
3. Download from Garage S3 if model missing (initContainer)
4. Fall back to HuggingFace direct download if Garage unavailable

**Apply Hermes manifests:**
```bash
# Already included in deploy-services.sh, but can be applied manually:
kubectl apply -k /etc/nixos/k3s-flake/manifests/hermes/
```

**Verification:**
```bash
# Check pod is running on neon-64gb
kubectl -n services get pods -o wide | grep hermes

# Check logs
kubectl -n services logs -l app=hermes -f

# Test access via Traefik (after Ingress is deployed)
curl -H "Host: researchstack.info" http://100.110.163.82:80/apps/chat/
```

**Troubleshooting:**
- If pod stuck in Init:0/1, check initContainer logs: `kubectl -n services logs <hermes-pod> -c download-model`
- If image pull errors, ensure the node can pull from Docker Hub
- If model not found, verify file exists at `/home/allaun/Downloads/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf` on neon-64gb

---

### Target Architecture (Option A - No etcd cluster)

```
Internet → edge Caddy (racknerd:443, TLS) → host Caddy (nixos:80) → Traefik (cupfox:80) → Services
```

- **cupfox** (100.110.163.82, Debian): k3s **server** (SOLE control plane) + **Traefik ENABLED**
- **nixos-laptop** (100.102.173.61): k3s **agent** + host Caddy (forwards to cupfox:80)
- **All other nodes** (qfox-1, steamdeck): k3s **agents** joining cupfox
- **etcd**: Embedded SQLite on cupfox only (no cluster, no thundering herd)

### Key Design Decisions

1. **cupfox remains sole control plane**: No etcd clustering, no thundering herd
2. **Traefik on cupfox**: Enable Traefik on the existing server node
3. **Host Caddy as forwarder**: NixOS-managed Caddy on nixos-laptop forwards to cupfox
4. **All nodes share resources**: Single k3s cluster, all pods/services visible everywhere

---

## Files Changed

### 1. `k3s-server.nix` — NixOS Agent Node with Host Caddy

**Changes:**
- `role = "agent"` (reverted from server)
- `serverAddr = "https://100.110.163.82:6443"` (joins cupfox)
- Added **host Caddy** configuration that forwards to `100.110.163.82:80` (cupfox's Traefik)
- Added **deploy manifests** systemd service (applies kustomize manifests after k3s starts)
- Simplified firewall (only port 80 needed for host Caddy)

**Host Caddy routes:**
- `researchstack.info` → cupfox:80 (Traefik)
- `auth.researchstack.info` → cupfox:80 (Traefik)
- `mail.*`, `webmail.*` → cupfox:80 (Traefik)
- Legacy subdomain redirects (status, dash, home, media, books, music, vault, pulse, apps, chat, budget, www, ray)
- Wildcard fallback → root

### 2. `manifests/ingress/kustomization.yaml` — Include Ray Ingress

**Added:**
```yaml
resources:
  - middleware.yaml
  - ingress.yaml
  - ray-ingress.yaml
```

### 3. `manifests/ingress/middleware.yaml` — Ray Middleware

**Added:**
```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: strip-server-ray
  namespace: ray-system
spec:
  stripPrefix:
    prefixes:
      - /server/ray
```

### 4. `manifests/ingress/ray-ingress.yaml` — Ray Dashboard Routing

**Updated:** Removed duplicate Middleware definition, kept IngressRoute that routes `/server/ray` → `raycluster-head-svc:8265` with stripPrefix middleware.

---

## Prerequisites: cupfox Setup

**BEFORE deploying nixos-laptop, you MUST enable Traefik on cupfox:**

```bash
# On cupfox (100.110.163.82):
# Edit /etc/rancher/k3s/config.yaml or k3s service
# Remove or comment out: --disable=traefik

# Then restart k3s
systemctl restart k3s

# Verify Traefik is running
kubectl -n kube-system get pods | grep traefik
kubectl -n kube-system get svc traefik
```

**Expected:** Traefik pod running, ServiceLB assigned NodePort (or port 80/443 on the node).

If Traefik is already running on cupfox, you can skip this step.

---

## Deployment Phases

### Phase 0: Pre-Deployment Checklist

- [ ] Verify cupfox (100.110.163.82) is healthy as control-plane
- [ ] Verify Traefik is **ENABLED** on cupfox (not disabled)
- [ ] Verify nixos-laptop (100.102.173.61) is currently an agent node
- [ ] Verify Tailscale connectivity: cupfox ↔ nixos-laptop
- [ ] Verify edge Caddy (racknerd) can reach nixos-laptop:80
- [ ] Backup current k3s-server.nix
- [ ] Ensure SOPS key is available on nixos-laptop (`/var/lib/sops-nix/key.txt`)
- [ ] Verify k3s token exists (`secrets/k3s-token.age`)

### Phase 1: Deploy k3s-server (Internal Only)

**Goal:** Deploy host Caddy on nixos-laptop that forwards to Traefik on cupfox.

```bash
# On a machine with the repo checked out:
cd /home/allaun/repo/4-Infrastructure/k3s-flake

# 1. Copy files to nixos-laptop
ssh root@100.102.173.61 "mkdir -p /etc/nixos/k3s-flake/manifests"
rsync -av --delete manifests/ root@100.102.173.61:/etc/nixos/k3s-flake/manifests/
rsync -av flake.nix flake.lock k3s-server.nix k3s-configuration.nix roles/ secrets/ scripts/ \
  root@100.102.173.61:/etc/nixos/k3s-flake/

# 2. Rebuild nixos-laptop
ssh root@100.102.173.61 "cd /etc/nixos/k3s-flake && nixos-rebuild switch --flake .#k3s-server"
```

**Expected behavior:**
- nixos-laptop remains a k3s **agent** node (joins cupfox)
- Host Caddy starts on :80 and forwards all requests to cupfox:80
- All existing services continue to work (no changes to k3s itself)
- New Ingress routes are NOT yet active (manifests not applied)

**Verification:**
```bash
# From any tailnet node, test host Caddy forwarding to cupfox:
curl -H "Host: researchstack.info" http://100.102.173.61/
# Should return 404 from Traefik (if Traefik running) or cupfox NodePort

# Check host Caddy is running:
ssh root@100.102.173.61 "systemctl status caddy"

# Check k3s agent is healthy:
ssh root@100.102.173.61 "kubectl get nodes -o wide"
# Should show nixos-laptop as Ready, role=agent
```

**Rollback:** If something breaks:
```bash
ssh root@100.102.173.61 "nixos-rebuild switch --rollback"
```

### Phase 2: Apply Ingress Manifests

**Goal:** Deploy path-based routing, forward_auth, and Ray Ingress to cupfox's Traefik.

```bash
# Apply manifests (can be done from any node with kubectl access to cupfox)
# On cupfox:
kubectl apply -k /etc/nixos/k3s-flake/manifests/

# Or from nixos-laptop (after deploy-k3s-services runs):
ssh root@100.102.173.61 "kubectl apply -k /etc/nixos/k3s-flake/manifests/"
```

**Verification:**
```bash
# Check Ingress resources
kubectl -n services get ingress

# Check Middleware
kubectl -n services get middleware

# Check Ray IngressRoute
kubectl -n ray-system get ingressroute

# Check Traefik has the routes (via cupfox:80)
curl -H "Host: researchstack.info" http://100.110.163.82/
# Should redirect to Authentik (302) or serve Homer
```

### Phase 3: Deploy Service Pods

**Goal:** Deploy the new services (hermes, credential-server, control-plane APIs).

The manifests are included in `kustomization.yaml`:
- hermes (chat)
- credential-server
- control-plane (registry, jobs, blobs APIs)
- actual-budget
- vaultwarden

**Apply:**
```bash
# Already done by deploy-k3s-services, but verify:
ssh root@100.102.173.61 "kubectl get pods -n services -o wide"
```

**Expected:** All pods should be Running (or Pending if storage not available).

### Phase 4: Internal End-to-End Testing

**Test all paths via host Caddy on nixos-laptop (which forwards to cupfox:80):**

```bash
# Landing page
curl -H "Host: researchstack.info" http://100.102.173.61/ | grep -i "homer\|authentik"

# SSO-protected paths (should redirect to Authentik)
curl -H "Host: researchstack.info" http://100.102.173.61/apps/chat/ -I | grep "Location.*auth"
curl -H "Host: researchstack.info" http://100.102.173.61/server/status/ -I | grep "Location.*auth"

# API paths (should NOT redirect, return health or 502)
curl -H "Host: researchstack.info" http://100.102.173.61/api/cred/ -I | grep -v "Location.*auth"
curl -H "Host: researchstack.info" http://100.102.173.61/api/registry/health

# Ray dashboard
curl -H "Host: researchstack.info" http://100.102.173.61/server/ray -I

# Auth subdomain
curl -H "Host: auth.researchstack.info" http://100.102.173.61/ | grep -i "authentik"
```

**Expected results:**
- `/`, `/apps/*`, `/server/*` → 302 to Authentik (SSO gate)
- `/api/*` → 200 or 502 (no redirect, token-auth)
- `/server/ray` → Ray dashboard or 502
- `auth.*` → Authentik login page

### Phase 5: Deploy k3s-edge (Public Traffic)

**Goal:** Switch public traffic to the new routing stack. **This is the point of no return for public traffic.**

```bash
# Copy files to edge node (no changes to k3s-edge.nix needed - it already forwards to nixos:80)
rsync -av flake.nix flake.lock k3s-edge.nix k3s-configuration.nix roles/ secrets/ \
  root@100.101.247.127:/etc/nixos/k3s-flake/

# Rebuild edge
ssh root@100.101.247.127 "cd /etc/nixos/k3s-flake && nixos-rebuild switch --flake .#k3s-edge"
```

**Expected behavior:**
- Public HTTPS traffic flows: edge Caddy (TLS) → host Caddy (nixos:80) → Traefik (cupfox:80) → Services
- All legacy subdomain redirects continue to work (defined at both edge and host Caddy)
- Path-based routing is active for public traffic

**Verification:**
```bash
# Quick smoke tests from external network:
curl -sI https://researchstack.info/ | head -5
curl -sI https://auth.researchstack.info/ | head -5
curl -sI https://status.researchstack.info/ | head -5  # should 301

# Or run the full Playwright test suite:
cd /home/allaun/repo/4-Infrastructure/k3s-flake/tests
npm test
```

**Rollback:** If public traffic breaks:
```bash
ssh root@100.101.247.127 "nixos-rebuild switch --rollback"
```

### Phase 6: Post-Deployment

**Run full E2E test suite:**
```bash
cd /home/allaun/repo/4-Infrastructure/k3s-flake/tests
npm test
# Target: All tests passing (40/40)
```

**Verify Ray dashboard:**
- Access https://researchstack.info/server/ray in browser
- Should show Ray cluster dashboard

**Verify resource sharing:**
```bash
# From any node, verify all pods are visible
kubectl get pods -A -o wide

# Verify Traefik can route to pods on any node
kubectl get endpoints -n services
```

---

## Resource Sharing Verification

### All Nodes Share the Same Cluster

| Node | IP | Role | serverAddr | Cluster | Resource Sharing |
|------|-----|------|------------|---------|-----------------|
| cupfox | 100.110.163.82 | **server** | N/A (initial) | ✅ Single-node SQLite | ✅ Full access |
| nixos-laptop | 100.102.173.61 | **agent** | cupfox:6443 | ✅ Joins cupfox | ✅ Full access |
| qfox-1 | 100.88.57.96 | agent | cupfox:6443 | ✅ Joins cupfox | ✅ Full access |
| steamdeck | 100.85.244.73 | agent | cupfox:6443 | ✅ Joins cupfox | ✅ Full access |

**No etcd cluster** — cupfox uses embedded SQLite (single-server mode).
**No thundering herd problem** — only one data store, no replication overhead.

### Verification Commands

```bash
# On any node, verify all nodes are Ready
kubectl get nodes -o wide

# Verify all pods are visible from any node
kubectl get pods -A -o wide

# Verify Services are accessible from any node
kubectl get svc -n services

# Verify Traefik can see all endpoints
kubectl -n services get endpoints

# Test connectivity from nixos-laptop to cupfox Traefik
curl -v http://100.110.163.82:80/
```

---

## Ray Cluster Integration

### Current State
- Ray cluster is **already running** in `ray-system` namespace (per README)
- Ray was deployed separately via KubeRay operator on cupfox
- Ray dashboard service: `raycluster-head-svc:8265`

### Ingress Configuration
- **Path:** `/server/ray`
- **Middleware:** `strip-server-ray` (strips `/server/ray` prefix)
- **Service:** `raycluster-head-svc:8265`
- **Type:** Traefik IngressRoute (CRD, not standard Ingress)
- **Traefik location:** cupfox:80

### Verification Commands

```bash
# Check Ray pods
kubectl -n ray-system get pods -o wide

# Check Ray services
kubectl -n ray-system get svc

# Check IngressRoute
kubectl -n ray-system get ingressroute

# Test Ray dashboard access via Traefik
curl -H "Host: researchstack.info" http://100.110.163.82:80/server/ray

# Or via host Caddy on nixos-laptop
curl -H "Host: researchstack.info" http://100.102.173.61/server/ray
```

### Future: Ray Operator

If Ray needs to be redeployed, use KubeRay:

```bash
# Install KubeRay operator
kubectl apply -f https://raw.githubusercontent.com/ray-project/kuberay/master/manifests/cluster-scoped-resources.yaml
kubectl apply -f https://raw.githubusercontent.com/ray-project/kuberay/master/manifests/namespaced-resources.yaml

# Deploy Ray cluster
kubectl apply -f ray-cluster.yaml
```

---

## VCN/LUPINE Integration

### Current State
- VCN-LUPINE is a **separate compute substrate** running on GPU nodes
- NOT managed by k3s (runs as systemd daemons)
- Uses LD_PRELOAD shim to intercept CUDA calls and encode as H.264 video
- Transmits over Tailscale mesh to GPU nodes for actual compute

### Architecture
```
k3s pod (Python/CUDA) → LD_PRELOAD shim → VCN-LUPINE daemon → Tailscale → GPU node → decode → dispatch
```

### Node Assignments
- **qfox-1** (CachyOS, foxtop): Primary compute, runs VCN/LUPINE daemon
- **steamdeck** (NixOS, core): GPU node, runs GPU receiver daemon

### Ports
| Port | Protocol | Purpose |
|------|----------|---------|
| 14834 | UDP | VCN-LUPINE frame transmission |

### Verification

```bash
# On qfox-1:
systemctl status vcn-lupine-daemon
ss -tulnp | grep 14834

# On steamdeck:
python3 /path/to/vcn_lupine_gpu_node.py --port 14834
systemctl status vcn-lupine-gpu-node
```

### No k3s Changes Required
VCN/LUPINE runs **outside** k3s. No Kubernetes manifests or configuration changes are needed for VCN to work with the new routing stack.

---

## Rollback Scenarios

### Scenario 1: Traefik not enabled on cupfox

**Symptoms:**
- `kubectl -n kube-system get pods` on cupfox shows no Traefik
- Requests to cupfox:80 return connection refused

**Fix:**
```bash
# On cupfox, enable Traefik
# Edit k3s configuration to remove --disable=traefik
systemctl restart k3s

# Verify
kubectl -n kube-system get pods | grep traefik
```

### Scenario 2: Host Caddy not forwarding correctly

**Symptoms:**
- Internal tests (Phase 4) fail
- Requests to nixos-laptop:80 return 502 or timeout

**Debug:**
```bash
# Check Caddy config
ssh root@100.102.173.61 "cat /etc/caddy/Caddyfile"

# Check Caddy logs
ssh root@100.102.173.61 "journalctl -u caddy -f"

# Test direct to cupfox
curl -v http://100.110.163.82:80/

# Test via host Caddy
curl -v http://100.102.173.61/
```

**Fix:**
```bash
# Restart Caddy
ssh root@100.102.173.61 "systemctl restart caddy"

# Rebuild nixos-laptop
ssh root@100.102.173.61 "cd /etc/nixos/k3s-flake && nixos-rebuild switch --flake .#k3s-server"
```

### Scenario 3: Ingress routing misconfigured

**Symptoms:**
- Internal tests (Phase 4) fail with 404
- Specific paths don't route correctly

**Debug:**
```bash
# Check Ingress resources
kubectl -n services get ingress

# Check Middleware
kubectl -n services get middleware

# Check Traefik logs
kubectl -n kube-system logs -l app=traefik -f

# Test specific routes
curl -v -H "Host: researchstack.info" http://100.110.163.82:80/apps/chat/
```

**Fix:** Correct the Ingress/Middleware manifests and reapply:
```bash
kubectl apply -k /etc/nixos/k3s-flake/manifests/
```

### Scenario 4: Public traffic breaks after edge deployment

**Symptoms:**
- Public HTTPS requests return errors
- edge Caddy logs show connection failures to nixos-laptop:80

**Debug:**
```bash
# Check edge Caddy
ssh root@100.101.247.127 "journalctl -u caddy -f"

# Check host Caddy on nixos-laptop
ssh root@100.102.173.61 "journalctl -u caddy -f"

# Check Traefik on cupfox
kubectl -n kube-system logs -l app=traefik -f

# Test chain manually
curl -v http://100.102.173.61:80/  # host Caddy
curl -v http://100.110.163.82:80/  # Traefik on cupfox
```

**Rollback:**
```bash
# Revert edge
ssh root@100.101.247.127 "nixos-rebuild switch --rollback"
```

---

## Monitoring & Validation

### Playwright Test Suite

The E2E test suite in `tests/` validates:

1. **Edge TLS:** Valid certificates, HTTPS accessibility
2. **Legacy Redirects:** Subdomain 301s work correctly
3. **Path Routing:** `/apps/*`, `/server/*`, `/api/*` routes work
4. **Auth Integration:** forward_auth gates SSO-protected paths
5. **API Bypass:** `/api/*` does NOT redirect to Authentik
6. **Stable Subdomains:** `auth.*`, `mail.*` are preserved

**Run tests:**
```bash
cd tests
npm test                    # All tests
npm run test:edge          # TLS + redirect tests
npm run test:routing       # Path routing tests
npm run test:auth          # Auth integration tests
npx playwright show-report test-results  # View HTML report
```

### Expected Test Results After Full Deployment

| Category | Tests | Expected |
|----------|-------|----------|
| Edge TLS | 5 | All pass |
| Legacy Redirects | 9 | All pass |
| Path Routing | 15 | All pass |
| Auth Integration | 11 | All pass |
| **Total** | **40** | **40 pass** |

---

## Troubleshooting Guide

### Traefik Not Running on cupfox

**Check:**
```bash
# On cupfox
kubectl -n kube-system get pods | grep traefik
kubectl -n kube-system get svc traefik

# Check k3s configuration
cat /etc/rancher/k3s/config.yaml | grep traefik
ps aux | grep k3s | grep disable
```

**Fix:** Remove `--disable=traefik` from k3s on cupfox and restart:
```bash
# Edit k3s service to remove --disable=traefik
systemctl restart k3s
```

### Host Caddy Not Forwarding to cupfox

**Check:**
```bash
# Check Caddy is running and forwarding
ssh root@100.102.173.61 "systemctl status caddy"
ssh root@100.102.173.61 "cat /var/lib/caddy/Caddyfile | grep reverse_proxy"

# Test direct
curl -v http://100.110.163.82:80/
curl -v http://100.102.173.61:80/
```

**Fix:** Ensure Caddyfile has correct upstream:
```
reverse_proxy 100.110.163.82:80 {
  header_up Host {host}
  header_up X-Real-IP {remote}
  header_up X-Forwarded-For {remote}
  header_up X-Forwarded-Proto {scheme}
  header_up X-Forwarded-Host {host}
}
```

### Ray Dashboard Not Accessible

**Check:**
```bash
# Ray pods running?
kubectl -n ray-system get pods

# Ray service exists?
kubectl -n ray-system get svc raycluster-head-svc

# IngressRoute applied?
kubectl -n ray-system get ingressroute

# Test directly to Ray service
kubectl -n ray-system port-forward svc/raycluster-head-svc 8265:8265
# Then access http://localhost:8265

# Test via Traefik on cupfox
curl -H "Host: researchstack.info" http://100.110.163.82:80/server/ray
```

**Fix:** If Ray not deployed, install KubeRay:
```bash
kubectl apply -f https://raw.githubusercontent.com/ray-project/kuberay/master/manifests/cluster-scoped-resources.yaml
kubectl apply -f https://raw.githubusercontent.com/ray-project/kuberay/master/manifests/namespaced-resources.yaml
kubectl apply -f ray-cluster.yaml
```

### ForwardAuth Not Working

**Symptoms:** `/apps/*` paths return 200 instead of redirecting to Authentik.

**Check:**
```bash
# ForwardAuth middleware exists?
kubectl -n services get middleware authentik-forward-auth

# Authentik service running?
kubectl -n authentik get pods

# Test forwardAuth URL directly
kubectl -n authentik get svc authentik-server
curl http://authentik-server.authentik.svc.cluster.local/outpost.goauthentik.io/auth/traefik

# Check Ingress annotations
kubectl -n services get ingress rs-apps-chat -o yaml | grep middlewares
```

**Fix:** Ensure Ingress has forward-auth middleware:
```yaml
annotations:
  traefik.ingress.kubernetes.io/router.middlewares: services-authentik-forward-auth@kubernetescrd
```

---

## Summary of Changes

| File | Change | Purpose |
|------|--------|---------|
| `k3s-server.nix` | Role: agent (not server) | Join cupfox's cluster as agent |
| `k3s-server.nix` | Add host Caddy | Forward all to cupfox:80 (Traefik) |
| `k3s-server.nix` | Add deploy service | Auto-apply manifests |
| `k3s-server.nix` | Simplified firewall | Only port 80 for host Caddy |
| `manifests/ingress/kustomization.yaml` | Add ray-ingress.yaml | Deploy Ray Ingress |
| `manifests/ingress/middleware.yaml` | Add strip-server-ray | Ray prefix stripping |
| `manifests/ingress/ray-ingress.yaml` | Remove duplicate Middleware | Use shared middleware |

**No changes to k3s-edge.nix** — it already forwards correctly to `100.102.173.61:80`.

**Manual step required:** Enable Traefik on cupfox (remove `--disable=traefik`).

---

## Timeline Estimate

| Phase | Duration | Notes |
|-------|----------|-------|
| Phase 0 (prep) | 5 min | Verify current state, enable Traefik on cupfox |
| Phase 1 (k3s-server) | 3 min | NixOS rebuild |
| Phase 2 (Ingress) | 1 min | Manifests apply |
| Phase 3 (services) | 1 min | Already included |
| Phase 4 (internal test) | 5 min | Validate all paths |
| Phase 5 (k3s-edge) | 2 min | NixOS rebuild |
| Phase 6 (public test) | 5 min | Full validation |
| **Total** | **~22 min** | Budget 30-45 min with troubleshooting |

---

## Success Criteria

✅ All 40 Playwright E2E tests pass  
✅ `https://researchstack.info/` loads (Homer or Authentik redirect)  
✅ `https://auth.researchstack.info/` serves Authentik login  
✅ `https://researchstack.info/server/ray` shows Ray dashboard  
✅ `https://researchstack.info/api/registry/health` returns without redirect  
✅ Legacy subdomain redirects work (status, dash, home, etc.)  
✅ No TLS errors in browser  
✅ All nodes share resources (pods visible from any node)  

---

*Document generated for path-based routing migration - Option A. Last updated: 2025-06-01*
*Option A: cupfox = sole server + Traefik, nixos-laptop = agent + host Caddy forwarder*
