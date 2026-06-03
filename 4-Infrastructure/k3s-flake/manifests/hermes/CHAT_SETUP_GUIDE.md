# chat.researchstack.info Setup Guide with Hermes

## Overview

This guide sets up `chat.researchstack.info` to serve Hermes (LLM chat interface) via the k3s cluster.

## Architecture

```
Internet → edge Caddy (microvm-racknerd:443, TLS) 
          → host Caddy (nixos-laptop:80) 
          → Traefik (cupfox:80) 
          → Hermes Service (neon-64gb, port 8000) 
          → GGUF Model (Gemma-4-E4B)
```

## Prerequisites

1. ✅ k3s cluster running on cupfox (100.110.163.82)
2. ✅ Traefik enabled on cupfox
3. ✅ neon-64gb node joined to cluster with ARM64 label
4. ✅ Hermes model file at `/home/allaun/Downloads/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf` on neon-64gb
5. ✅ Authentik running and accessible at auth.researchstack.info

## Files Created/Modified

### 1. Kustomization Update
**File**: `/home/allaun/repo/4-Infrastructure/k3s-flake/manifests/hermes/kustomization.yaml`

Added `chat-ingress.yaml` to resources list:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
  - configmap.yaml
  - chat-ingress.yaml  # <-- Added
```

### 2. Ingress Resource
**File**: `/home/allaun/repo/4-Infrastructure/k3s-flake/manifests/hermes/chat-ingress.yaml`

Creates Ingress that routes `chat.researchstack.info` to Hermes service with Authentik forward-auth:
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: chat-researchstack-info
  namespace: services
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: web
    traefik.ingress.kubernetes.io/router.middlewares: services-authentik-forward-auth@kubernetescrd
spec:
  rules:
    - host: chat.researchstack.info
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: hermes
                port:
                  number: 80
```

### 3. Caddy Configuration (microvm-racknerd)
**File**: Update `/etc/caddy/Caddyfile` on microvm-racknerd

Replace the existing `chat.researchstack.info` block:

```caddy
chat.researchstack.info {
    # Forward authentication to Authentik
    forward_auth * http://100.119.165.120:9000 {
        uri /outpost.goauthentik.io/auth/caddy
        copy_headers X-Authentik-Username X-Authentik-Email X-Authentik-Name X-Authentik-Uid X-Authentik-Jwt X-Authentik-Meta-Jwt X-Authentik-Meta-App X-Authentik-Meta-Version
    }
    
    # Reverse proxy to Traefik on cupfox (routes to Hermes via Ingress)
    reverse_proxy http://100.110.163.82:80 {
        header_up Host chat.researchstack.info
    }
}
```

## Deployment Steps

### Step 1: Apply k3s Manifests

On cupfox (100.110.163.82):

```bash
# Navigate to manifests directory
cd /etc/nixos/k3s-flake/manifests

# Apply Hermes manifests (includes chat-ingress)
kubectl apply -k ./hermes/

# Verify Ingress was created
kubectl -n services get ingress chat-researchstack-info

# Verify Hermes deployment is running
kubectl -n services get pods -l app=hermes
```

### Step 2: Update Caddy on microvm-racknerd

On microvm-racknerd:

```bash
# Edit Caddyfile
nano /etc/caddy/Caddyfile

# Replace chat.researchstack.info block with the new configuration
# (see Caddy Configuration section above)

# Test configuration
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

# Reload Caddy (zero downtime)
caddy reload

# Or restart if needed
systemctl restart caddy
```

### Step 3: Create Authentik Application (if not exists)

In Authentik admin (https://auth.researchstack.info/admin):

1. **Create Provider** (if not exists):
   - Name: `research-stack-chat`
   - Authorization flow: `default-provider-authorization-implicit-consent`
   - Internal host: `http://100.101.247.127` (or use cupfox internal IP)
   - External host: `https://chat.researchstack.info`
   - Mode: `Forward domain`

2. **Create Application**:
   - Name: `Research Stack Chat`
   - Slug: `research-stack-chat`
   - Provider: `research-stack-chat`

3. **Add to Outpost**:
   - Add `Research Stack Chat` to the **authentik Embedded Outpost**

### Step 4: Verify DNS

Check that DNS resolves correctly:

```bash
# Check DNS resolution
dig chat.researchstack.info +short

# Should resolve to microvm-racknerd's public IP
# Or to cupfox directly if using direct Traefik access
```

If DNS is not set up, you can:
- Add A record in your DNS provider (Porkbun, Cloudflare, etc.)
- Point to microvm-racknerd's public IP
- Or temporarily test by adding to /etc/hosts: `echo "<microvm-ip> chat.researchstack.info" >> /etc/hosts`

### Step 5: Test Access

```bash
# Test HTTPS access
curl -I https://chat.researchstack.info

# Should return 200 or 302 (redirect to Authentik if not logged in)

# Test in browser
# Navigate to https://chat.researchstack.info
# Should prompt for Authentik login, then show Hermes interface
```

### Step 6: Verify Hermes Pod Logs

```bash
# Check Hermes pod logs
kubectl -n services logs -l app=hermes -f

# Look for:
# - Model loaded successfully
# - Server started on port 8000
# - No errors in initialization
```

## Troubleshooting

### Issue: 502 Bad Gateway

**Cause**: Hermes pod not running or not ready

**Solution**:
```bash
# Check pod status
kubectl -n services get pods -l app=hermes

# Check pod logs
kubectl -n services logs <hermes-pod-name>

# Check if model file exists on neon-64gb
ssh root@100.100.75.113 "ls -lh /home/allaun/Downloads/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf"

# If model is missing, download it:
ssh root@100.100.75.113 "curl -L -o /home/allaun/Downloads/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf \
  'https://huggingface.co/HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive/resolve/main/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf'"
```

### Issue: 503 Service Unavailable

**Cause**: Traefik not routing correctly or Ingress not applied

**Solution**:
```bash
# Check Ingress exists
kubectl -n services get ingress

# Check Traefik logs
kubectl -n traefik logs -l app.kubernetes.io/name=traefik

# Check if Traefik is running
kubectl -n traefik get pods
```

### Issue: Infinite redirect loop or 404

**Cause**: Caddy configuration issue

**Solution**:
```bash
# On microvm-racknerd, check Caddy logs
journalctl -u caddy -f

# Verify Caddy config syntax
caddy validate

# Test Caddy config in isolation
caddy start --config /etc/caddy/Caddyfile --adapter caddyfile
```

### Issue: Authentication not working

**Cause**: Authentik forward-auth middleware not configured correctly

**Solution**:
```bash
# Check middleware exists in k3s
kubectl -n services get middleware

# Check Authentik outpost logs
kubectl -n authentik logs -l app=authentik
```

## Configuration Summary

| Component | Location | Status |
|-----------|----------|--------|
| Hermes Deployment | k3s cupfox, neon-64gb | ✅ Ready |
| Hermes Service | k3s services namespace | ✅ Ready |
| Chat Ingress | k3s Traefik | ✅ Created |
| Caddy Edge | microvm-racknerd | ⚠️ Needs Update |
| Authentik App | auth.researchstack.info | ⚠️ Needs Setup |
| DNS | Porkbun/Cloudflare | ⚠️ Needs Verification |

## Final Notes

- The Hermes deployment will automatically download the model from Garage S3 or HuggingFace if not present on the host
- The deployment uses a hostPath mount to `/home/allaun/Downloads` on neon-64gb
- Model file: `Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf` (22GB)
- Ports: Hermes container 8000 → Service port 80 → Traefik port 80 → Caddy port 443
