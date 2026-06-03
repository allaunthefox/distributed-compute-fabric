# Phase 6: Networking & Ingress

**Phase:** 6  
**Name:** Networking & Ingress  
**Duration:** 5 days  
**Dependencies:** Phase 5 (Model-Specific Actors)  
**Status:** TODO  
**Owner:** Infrastructure Team

---

## Overview

This phase establishes secure, reliable network connectivity across the distributed Ray cluster using Tailscale mesh networking, and configures HTTPS ingress for all external-facing services.

### Goals
1. Deploy Tailscale subnet router for Kubernetes pod connectivity
2. Configure HTTPS ingress for Ray dashboard
3. Configure HTTPS ingress for Hermes API
4. Configure HTTPS ingress for Grafana dashboard
5. Enable service discovery across the mesh
6. Test cross-cluster communication

### Key Components
- Tailscale subnet router (DaemonSet)
- Traefik ingress controller (existing from Phase 1)
- Ray ingress configuration
- Hermes ingress configuration
- Grafana ingress configuration
- mDNS for service discovery

---

## Prerequisites

Before starting Phase 6, ensure:
- [ ] Phase 1-5 are complete
- [ ] All nodes are connected to Tailscale mesh
- [ ] k3s cluster is operational
- [ ] MetalLB is installed and configured
- [ ] Traefik ingress controller is deployed
- [ ] All service ClusterIPs are assigned

---

## Microsteps

### Day 1: Tailscale Subnet Router Deployment

#### Step 6.1.1: Create Tailscale Namespace
```bash
# File: kubernetes/tailscale/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: tailscale
  labels:
    name: tailscale
```

**Verification:**
```bash
kubectl get ns tailscale
# Expected: NAME       STATUS   AGE
#          tailscale   Active   10s
```

#### Step 6.1.2: Create Tailscale Secret
```bash
# Store Tailscale auth key as Kubernetes secret
kubectl create secret generic tailscale-auth \
  --namespace tailscale \
  --from-literal=auth-key=$(cat /path/to/tailscale-auth-key)
```

**Verification:**
```bash
kubectl get secret -n tailscale tailscale-auth
# Expected: NAME              TYPE     DATA   AGE
#          tailscale-auth    Opaque   1      10s
```

#### Step 6.1.3: Create Service Account
```bash
# File: kubernetes/tailscale/service-account.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: tailscale-subnet-router
  namespace: tailscale
```

**Verification:**
```bash
kubectl get sa -n tailscale
# Expected: NAME                     SECRETS   AGE
#          tailscale-subnet-router   1          10s
```

#### Step 6.1.4: Create ClusterRole for Subnet Routes
```bash
# File: kubernetes/tailscale/cluster-role.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: tailscale-subnet-router
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
```

**Verification:**
```bash
kubectl get clusterrole tailscale-subnet-router
# Expected: NAME                          CREATED AT
#          tailscale-subnet-router       2024-06-XX
```

#### Step 6.1.5: Create ClusterRoleBinding
```bash
# File: kubernetes/tailscale/cluster-role-binding.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: tailscale-subnet-router
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: tailscale-subnet-router
subjects:
- kind: ServiceAccount
  name: tailscale-subnet-router
  namespace: tailscale
```

**Verification:**
```bash
kubectl get clusterrolebinding tailscale-subnet-router
# Expected: NAME                          ROLE                          AGE
#          tailscale-subnet-router       tailscale-subnet-router      10s
```

#### Step 6.1.6: Deploy Tailscale Subnet Router DaemonSet
```bash
# File: kubernetes/tailscale/tailscale-subnet-router.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: tailscale-subnet-router
  namespace: tailscale
  labels:
    app: tailscale-subnet-router
spec:
  selector:
    matchLabels:
      app: tailscale-subnet-router
  template:
    metadata:
      labels:
        app: tailscale-subnet-router
    spec:
      serviceAccountName: tailscale-subnet-router
      hostNetwork: true
      dnsPolicy: ClusterFirstWithHostNet
      containers:
      - name: tailscale
        image: tailscale/tailscale:v1.60
        env:
        - name: TAILSCALE_AUTH_KEY
          valueFrom:
            secretKeyRef:
              name: tailscale-auth
              key: auth-key
        - name: TAILSCALE_STATE_DIR
          value: /var/lib/tailscale
        - name: TAILSCALE_HOSTNAME
          valueFrom:
            fieldRef:
              fieldPath: spec.nodeName
        - name: TAILSCALE_ROUTES
          value: "10.42.0.0/16,10.43.0.0/16"  # k3s default CNI ranges
        securityContext:
          privileged: true
          capabilities:
            add: ["NET_ADMIN", "NET_RAW"]
        volumeMounts:
        - name: var-lib-tailscale
          mountPath: /var/lib/tailscale
        - name: dev-net-tun
          mountPath: /dev/net/tun
      volumes:
      - name: var-lib-tailscale
        hostPath:
          path: /var/lib/tailscale
          type: DirectoryOrCreate
      - name: dev-net-tun
        hostPath:
          path: /dev/net/tun
          type: CharDevice
```

**Verification:**
```bash
# Check pods are running
kubectl get pods -n tailscale -o wide
# Expected: All nodes should have a tailscale-subnet-router pod

# Check Tailscale status on a pod
kubectl exec -n tailscale -it tailscale-subnet-router-XXXX -- tailscale status
# Expected: Should show connected state with routes advertised

# Check routes are advertised
kubectl exec -n tailscale -it tailscale-subnet-router-XXXX -- tailscale status --routes
# Expected: Should show k3s subnet routes
```

#### Step 6.1.7: Verify Tailscale Connectivity from Pods
```bash
# Test connectivity from a Ray pod to Tailscale nodes
kubectl exec -n ray-system -it ray-head-xxxx -- curl -v http://100.102.173.61:8265
# Expected: Should connect successfully (may get 401/403, but connection should work)

# Test DNS resolution
kubectl exec -n ray-system -it ray-head-xxxx -- nslookup cupfox.ts.net
# Expected: Should resolve to 100.102.173.61
```

### Day 2: Ray Dashboard Ingress

#### Step 6.2.1: Create TLS Secret for Ray Dashboard
```bash
# If using cert-manager (recommended)
# File: kubernetes/ray/certificate.yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: ray-dashboard-tls
  namespace: ray-system
spec:
  secretName: ray-dashboard-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - ray.yourdomain.com

# If not using cert-manager, create secret manually
# kubectl create secret tls ray-dashboard-tls \
#   --namespace ray-system \
#   --cert=ray.crt \
#   --key=ray.key
```

**Verification:**
```bash
kubectl get secret -n ray-system ray-dashboard-tls
# Expected: Should exist with tls.crt and tls.key
```

#### Step 6.2.2: Create Ray Dashboard IngressRoute
```bash
# File: kubernetes/ray/ray-ingress.yaml
apiVersion: traefik.containo.us/v1alpha1
kind: IngressRoute
metadata:
  name: ray-dashboard
  namespace: ray-system
  annotations:
    kubernetes.io/ingress.class: traefik
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`ray.yourdomain.com`)
      kind: Rule
      services:
        - name: raycluster-head-svc
          port: 8265
      middlewares:
        - name: ray-strip-prefix
          namespace: ray-system
  tls:
    secretName: ray-dashboard-tls
    domains:
      - main: ray.yourdomain.com

---
apiVersion: traefik.containo.us/v1alpha1
kind: Middleware
metadata:
  name: ray-strip-prefix
  namespace: ray-system
spec:
  stripPrefix:
    prefixes: ["/server/ray"]
```

**Verification:**
```bash
kubectl get ingressroute -n ray-system
# Expected: ray-dashboard should be listed

kubectl get middleware -n ray-system
# Expected: ray-strip-prefix should be listed
```

#### Step 6.2.3: Configure Ray Dashboard Authentication
```bash
# File: kubernetes/ray/raycluster.yaml (update)
# Add to rayStartParams:
rayStartParams:
  dashboard-user: admin
  dashboard-password: ${RAY_DASHBOARD_PASSWORD}
  dashboard-host: 0.0.0.0

# Create secret for password
apiVersion: v1
kind: Secret
metadata:
  name: ray-dashboard-creds
  namespace: ray-system
type: Opaque
stringData:
  RAY_DASHBOARD_PASSWORD: "your-secure-password-here"
```

**Verification:**
```bash
# Access dashboard via browser: https://ray.yourdomain.com/server/ray
# Expected: Should prompt for username/password
```

### Day 3: Hermes API Ingress

#### Step 6.3.1: Create TLS Secret for Hermes API
```bash
# File: kubernetes/hermes/certificate.yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: hermes-tls
  namespace: hermes
spec:
  secretName: hermes-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - api.yourdomain.com
  - hermes.yourdomain.com
```

**Verification:**
```bash
kubectl get secret -n hermes hermes-tls
# Expected: Should exist with tls.crt and tls.key
```

#### Step 6.3.2: Create Hermes IngressRoute
```bash
# File: kubernetes/hermes/hermes-ingress.yaml
apiVersion: traefik.containo.us/v1alpha1
kind: IngressRoute
metadata:
  name: hermes-api
  namespace: hermes
  annotations:
    kubernetes.io/ingress.class: traefik
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`api.yourdomain.com`) || Host(`hermes.yourdomain.com`)
      kind: Rule
      services:
        - name: hermes-service
          port: 8000
  tls:
    secretName: hermes-tls
    domains:
      - main: api.yourdomain.com
      - sans:
        - hermes.yourdomain.com
```

**Verification:**
```bash
kubectl get ingressroute -n hermes
# Expected: hermes-api should be listed

# Test connectivity
curl -vk https://api.yourdomain.com/health
# Expected: Should return HTTP 200 with health status
```

#### Step 6.3.3: Configure CORS for Hermes
```bash
# File: code/hermes/orchestrator.py (update CORS middleware)
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://yourdomain.com",
        "https://*.yourdomain.com",
        "http://localhost:3000",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Verification:**
```bash
# Test CORS headers
curl -v -X OPTIONS -H "Origin: https://yourdomain.com" \
  -H "Access-Control-Request-Method: POST" \
  https://api.yourdomain.com/generate
# Expected: Should return Access-Control-Allow-Origin header
```

### Day 4: Grafana Dashboard Ingress

#### Step 6.4.1: Create TLS Secret for Grafana
```bash
# File: kubernetes/monitoring/certificate.yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: grafana-tls
  namespace: monitoring
spec:
  secretName: grafana-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - grafana.yourdomain.com
```

**Verification:**
```bash
kubectl get secret -n monitoring grafana-tls
# Expected: Should exist with tls.crt and tls.key
```

#### Step 6.4.2: Create Grafana IngressRoute
```bash
# File: kubernetes/monitoring/grafana-ingress.yaml
apiVersion: traefik.containo.us/v1alpha1
kind: IngressRoute
metadata:
  name: grafana-dashboard
  namespace: monitoring
  annotations:
    kubernetes.io/ingress.class: traefik
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`grafana.yourdomain.com`)
      kind: Rule
      services:
        - name: grafana-service
          port: 3000
  tls:
    secretName: grafana-tls
    domains:
      - main: grafana.yourdomain.com
```

**Verification:**
```bash
kubectl get ingressroute -n monitoring
# Expected: grafana-dashboard should be listed

# Access Grafana via browser: https://grafana.yourdomain.com
# Expected: Should load Grafana login page
```

#### Step 6.4.3: Configure Grafana Authentication
```bash
# File: kubernetes/monitoring/grafana-values.yaml (Helm values)
grafana:
  adminPassword: ${GRAFANA_ADMIN_PASSWORD}
  ingress:
    enabled: false  # Using our own IngressRoute
  service:
    type: ClusterIP

auth:
  anonymous:
    enabled: false
```

**Verification:**
```bash
# Access Grafana: https://grafana.yourdomain.com
# Expected: Should prompt for login (not anonymous access)
```

### Day 5: Service Discovery & Testing

#### Step 6.5.1: Enable mDNS for Service Discovery
```bash
# File: kubernetes/tailscale/mdns-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: tailscale-mdns
  namespace: tailscale
data:
  # Enable mDNS for service discovery across Tailscale
  mdns: "true"
```

**Verification:**
```bash
# From any node, try to resolve service names
kubectl exec -n ray-system -it ray-head-xxxx -- nslookup hermes-service.hermes.svc.cluster.local
# Expected: Should resolve to ClusterIP
```

#### Step 6.5.2: Test Cross-Cluster Communication
```bash
# Test from Ray pod to Hermes service
kubectl exec -n ray-system -it ray-head-xxxx -- curl -v http://hermes-service.hermes.svc.cluster.local:8000/health
# Expected: Should return HTTP 200

# Test from Hermes pod to Ray dashboard
kubectl exec -n hermes -it hermes-xxxx -- curl -v http://raycluster-head-svc.ray-system.svc.cluster.local:8265
# Expected: Should return Ray dashboard or 401 (if auth enabled)

# Test from monitoring pod to all services
kubectl exec -n monitoring -it prometheus-xxxx -- curl -v http://hermes-service.hermes.svc.cluster.local:8000/metrics
# Expected: Should return Prometheus metrics
```

#### Step 6.5.3: Test External Access
```bash
# Test Ray dashboard externally
curl -vk https://ray.yourdomain.com/server/ray
# Expected: Should return 401 Unauthorized (auth required)

# Test Hermes API externally
curl -vk https://api.yourdomain.com/health
# Expected: Should return HTTP 200 with health status

# Test Grafana externally
curl -vk https://grafana.yourdomain.com
# Expected: Should return HTTP 200 with Grafana login page
```

#### Step 6.5.4: Configure DERP Fallback
```bash
# File: kubernetes/tailscale/derp-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: tailscale-derp
  namespace: tailscale
data:
  # Configure DERP regions for fallback
  derp-map: |
    {
      "RegionID": 1,
      "RegionCode": "frac",
      "RegionName": "France",
      "Nodes": [
        {"Name": "frac1", "RegionID": 1, "HostName": "frac1.derp.tailscale.com:443"}
      ]
    }
```

**Verification:**
```bash
# Temporarily disconnect from direct peer connection
# and verify traffic routes through DERP
kubectl exec -n tailscale -it tailscale-subnet-router-xxxx -- tailscale status --derp
# Expected: Should show DERP connections when direct fails
```

#### Step 6.5.5: Performance Testing
```bash
# Test latency between services
kubectl exec -n ray-system -it ray-head-xxxx -- ping -c 5 hermes-service.hermes.svc.cluster.local
# Expected: < 10ms latency

# Test throughput
kubectl exec -n ray-system -it ray-head-xxxx -- curl -o /dev/null -w "%{time_total}s\n" http://hermes-service.hermes.svc.cluster.local:8000/health
# Expected: < 0.1s response time
```

---

## Deliverables

### Files Created/Modified
- [ ] `kubernetes/tailscale/namespace.yaml`
- [ ] `kubernetes/tailscale/secret.yaml` (or created via kubectl)
- [ ] `kubernetes/tailscale/service-account.yaml`
- [ ] `kubernetes/tailscale/cluster-role.yaml`
- [ ] `kubernetes/tailscale/cluster-role-binding.yaml`
- [ ] `kubernetes/tailscale/tailscale-subnet-router.yaml`
- [ ] `kubernetes/ray/certificate.yaml`
- [ ] `kubernetes/ray/ray-ingress.yaml` (updated)
- [ ] `kubernetes/ray/raycluster.yaml` (updated with auth)
- [ ] `kubernetes/hermes/certificate.yaml`
- [ ] `kubernetes/hermes/hermes-ingress.yaml`
- [ ] `code/hermes/orchestrator.py` (CORS update)
- [ ] `kubernetes/monitoring/certificate.yaml`
- [ ] `kubernetes/monitoring/grafana-ingress.yaml`
- [ ] `kubernetes/monitoring/grafana-values.yaml`
- [ ] `kubernetes/tailscale/mdns-config.yaml`
- [ ] `kubernetes/tailscale/derp-config.yaml`

### Services Deployed
- [ ] Tailscale subnet router (DaemonSet)
- [ ] Ray dashboard HTTPS ingress
- [ ] Hermes API HTTPS ingress
- [ ] Grafana dashboard HTTPS ingress
- [ ] mDNS service discovery
- [ ] DERP fallback configuration

---

## Verification Checklist

### Tailscale Subnet Router
- [ ] DaemonSet deployed to all nodes
- [ ] Pods are Running
- [ ] Tailscale status shows connected
- [ ] k3s subnet routes are advertised
- [ ] Pod-to-pod connectivity via Tailscale IPs works

### Ray Dashboard Ingress
- [ ] TLS certificate is valid
- [ ] IngressRoute is created
- [ ] Middleware for prefix stripping is configured
- [ ] Dashboard is accessible via HTTPS
- [ ] Authentication is required

### Hermes API Ingress
- [ ] TLS certificate is valid
- [ ] IngressRoute is created
- [ ] API is accessible via HTTPS
- [ ] CORS headers are correct
- [ ] Health endpoint returns 200

### Grafana Dashboard Ingress
- [ ] TLS certificate is valid
- [ ] IngressRoute is created
- [ ] Grafana is accessible via HTTPS
- [ ] Authentication is required

### Service Discovery
- [ ] DNS resolution works across namespaces
- [ ] Services can communicate using Kubernetes DNS names
- [ ] External services can be reached via Tailscale IPs

### External Access
- [ ] All external endpoints use HTTPS
- [ ] TLS certificates are valid (not self-signed)
- [ ] All services respond to external requests

---

## Troubleshooting

### Tailscale Subnet Router Issues

**Symptom:** Pods stuck in Init:Error
```bash
kubectl describe pod -n tailscale tailscale-subnet-router-xxxx
# Look for errors in init containers or volume mounts
```

**Fix:** Ensure hostPath volumes exist and have correct permissions
```bash
# On each node:
sudo mkdir -p /var/lib/tailscale
sudo chmod 755 /var/lib/tailscale
```

### Ingress Not Working

**Symptom:** HTTPS requests timeout
```bash
# Check Traefik logs
kubectl logs -n traefik -l app.kubernetes.io/name=traefik

# Check IngressRoute status
kubectl get ingressroute -A
kubectl describe ingressroute -n ray-system ray-dashboard
```

**Fix:** Verify TLS secret exists and is valid
```bash
kubectl get secret -n ray-system ray-dashboard-tls -o yaml
```

### TLS Certificate Issues

**Symptom:** Browser shows certificate warning
```bash
# Check certificate status
kubectl describe certificate -n ray-system ray-dashboard-tls

# Check cert-manager logs
kubectl logs -n cert-manager -l app=cert-manager
```

**Fix:** Ensure DNS records are correct and cert-manager has permissions
```bash
# Verify DNS
nslookup ray.yourdomain.com

# Check ClusterIssuer
kubectl get clusterissuer letsencrypt-prod -o yaml
```

### Connectivity Issues

**Symptom:** Services cannot communicate
```bash
# Test DNS resolution
kubectl run -it --rm --restart=Never dns-test --image=busybox:1.28 -- nslookup hermes-service.hermes.svc.cluster.local

# Test direct IP connectivity
kubectl get svc -n hermes hermes-service
kubectl run -it --rm --restart=Never conn-test --image=curlimages/curl -- curl -v http://<CLUSTER_IP>:8000/health
```

---

## Rollback Plan

If Phase 6 fails:

1. **Tailscale Subnet Router**: Delete DaemonSet and RBAC
   ```bash
   kubectl delete ds -n tailscale tailscale-subnet-router
   kubectl delete clusterrole tailscale-subnet-router
   kubectl delete clusterrolebinding tailscale-subnet-router
   kubectl delete sa -n tailscale tailscale-subnet-router
   ```

2. **Ingress Routes**: Delete IngressRoute resources
   ```bash
   kubectl delete ingressroute -n ray-system ray-dashboard
   kubectl delete ingressroute -n hermes hermes-api
   kubectl delete ingressroute -n monitoring grafana-dashboard
   ```

3. **Revert to HTTP**: Temporarily use web entrypoint
   ```yaml
   # In IngressRoute, change:
   entryPoints:
     - web  # Instead of websecure
   
   # And remove tls section
   ```

---

## Next Phase

After completing Phase 6, proceed to **Phase 7: Hermes Orchestrator** to ensure the orchestrator is fully functional with all the networking in place.
