# GGUF-Ray-VCN-LUPINE Runbook

**Version:** 1.0.0  
**Last Updated:** 2026-06-01

---

## Table of Contents

1. [Overview](#overview)
2. [Contact Information](#contact-information)
3. [Daily Operations](#daily-operations)
4. [Troubleshooting](#troubleshooting)
5. [Emergency Procedures](#emergency-procedures)
6. [Maintenance Procedures](#maintenance-procedures)
7. [Useful Commands](#useful-commands)

---

## Overview

This runbook provides operational procedures for the GGUF-Ray-VCN-LUPINE deployment.

### System Overview

- **Status Page**: https://status.yourdomain.com (if configured)
- **Grafana Dashboard**: https://grafana.yourdomain.com
- **Ray Dashboard**: https://ray.yourdomain.com/server/ray
- **Hermes API**: https://api.yourdomain.com

### System Components

- **Hermes**: FastAPI orchestrator (hermes namespace)
- **Ray Cluster**: Distributed computing (ray-system namespace)
- **Monitoring**: Prometheus, Grafana, Loki, Tempo (monitoring namespace)
- **Tailscale**: Mesh networking (tailscale namespace)
- **Storage**: Longhorn (longhorn-system namespace)

---

## Contact Information

| Role | Contact | Escalation |
|------|---------|------------|
| Primary On-Call | oncall@yourdomain.com | P0/P1 incidents |
| Secondary On-Call | backup@yourdomain.com | P2 incidents |
| Engineering Team | eng@yourdomain.com | All issues |
| Security Team | security@yourdomain.com | Security issues |

### Escalation Matrix

| Severity | Description | Response Time | Escalation |
|----------|-------------|---------------|------------|
| P0 | System down, data loss, security breach | 15 minutes | Wake up on-call, page |
| P1 | Major functionality broken, high error rate | 1 hour | Page on-call |
| P2 | Degraded performance, minor issues | 4 hours | Notify team |
| P3 | Minor issue, enhancement request | 24 hours | Create ticket |
| P4 | Documentation, cleanup | 1 week | Backlog |

---

## Daily Operations

### Morning Checklist

1. **System Health**
   ```bash
   # Check all namespaces
   kubectl get pods -A
   
   # Check nodes
   kubectl get nodes
   
   # Check Ray cluster
   kubectl get pods -n ray-system
   kubectl get raycluster -n ray-system
   
   # Check Hermes
   kubectl get pods -n hermes
   kubectl get deployments -n hermes
   
   # Check monitoring
   kubectl get pods -n monitoring
   ```

2. **Resource Utilization** (Check Grafana dashboards)
   - CPU/Memory usage across all nodes
   - GPU utilization (qfox-1, steamdeck)
   - Request latency (p50, p95, p99)
   - Error rates
   - Ray cluster metrics

3. **Alerts**
   - Check Slack #alerts channel
   - Check PagerDuty for open incidents
   - Check email for alert notifications

4. **Backups**
   ```bash
   # Check Longhorn backups
   kubectl get backups -n longhorn-system
   kubectl get snapshots -n longhorn-system
   
   # Check backup status
   kubectl get volumes -n longhorn-system
   ```

### Evening Checklist

1. **Deployments**
   ```bash
   # Check for pending deployments
   kubectl get deployments -A --field-selector=status.updatedReplicas!=status.replicas
   
   # Check rollout status
   kubectl rollout status deployment -n hermes hermes-deployment
   ```

2. **Capacity Planning**
   - Review resource trends in Grafana
   - Check auto-scaling behavior
   - Plan for scaling if needed

3. **Security**
   - Check for security alerts
   - Review access logs (if available)

### Weekly Tasks

1. **System Updates**
   - Update k3s (check for new versions)
   - Update Helm charts
   - Update base images

2. **Monitoring Review**
   - Review alert rules
   - Update dashboards
   - Check metrics coverage

3. **Capacity Review**
   - Review auto-scaling behavior
   - Check resource utilization trends
   - Plan capacity changes

4. **Security Review**
   - Review RBAC configurations
   - Rotate credentials
   - Check for vulnerabilities

---

## Troubleshooting

### Common Issues & Resolutions

#### Issue: Ray Cluster Not Healthy

**Symptoms:**
- Ray pods are crashlooping
- Ray dashboard shows errors
- Model inference fails with "Ray not initialized"

**Diagnosis:**
```bash
# Check Ray pod logs
kubectl logs -n ray-system ray-head-xxxx
kubectl logs -n ray-system ray-worker-xxxx

# Check Ray pod status
kubectl describe pod -n ray-system ray-head-xxxx

# Check Ray dashboard (if accessible)
curl -k https://admin:password@ray.yourdomain.com/server/ray/api/nodes
```

**Resolution:**
1. Check if Redis is running (used for GCS):
   ```bash
   kubectl get pods -n ray-system | grep redis
   kubectl logs -n ray-system redis-xxxx
   ```

2. Check resource availability:
   ```bash
   kubectl describe nodes | grep -A 5 "Allocatable"
   ```

3. Check Ray cluster configuration:
   ```bash
   kubectl get raycluster -n ray-system -o yaml
   ```

4. Restart Ray cluster:
   ```bash
   kubectl delete raycluster -n ray-system raycluster
   kubectl apply -f kubernetes/ray/raycluster.yaml
   ```

**Escalation:** If issue persists after 30 minutes, escalate to P1

---

#### Issue: Hermes API Unresponsive

**Symptoms:**
- API requests timeout (504)
- 502/503 errors
- High latency (> 5s)

**Diagnosis:**
```bash
# Check Hermes pod status
kubectl get pods -n hermes
kubectl describe pod -n hermes hermes-xxxx

# Check Hermes logs
kubectl logs -n hermes hermes-xxxx
kubectl logs -n hermes hermes-xxxx --previous  # Previous instance

# Check resource usage
kubectl top pods -n hermes

# Test connectivity to Ray
kubectl exec -n hermes hermes-xxxx -- curl -v http://raycluster-head-svc.ray-system.svc.cluster.local:8265

# Test database connectivity
kubectl exec -n hermes hermes-xxxx -- python -c "
import sqlite3
conn = sqlite3.connect('/data/hermes.db')
cursor = conn.cursor()
cursor.execute('SELECT 1')
print(cursor.fetchone())
conn.close()
"
```

**Resolution:**
1. Check Ray cluster health (see above)
2. Restart Hermes:
   ```bash
   kubectl rollout restart deployment -n hermes hermes-deployment
   ```
3. Scale up Hermes:
   ```bash
   kubectl scale deployment -n hermes hermes-deployment --replicas=4
   ```

**Escalation:** If issue persists after 15 minutes, escalate to P1

---

#### Issue: Model Loading Failed

**Symptoms:**
- Model not available in /models endpoint
- Inference fails with "model not loaded" or "actor not found"
- Actor initialization errors in logs

**Diagnosis:**
```bash
# Check actor logs
kubectl logs -n ray-system ray-worker-xxxx | grep -i "error\|failed\|exception"

# Check model cache
kubectl exec -n ray-system ray-worker-xxxx -- ls -la /cache/models

# Test model download manually
kubectl exec -n ray-system ray-worker-xxxx -- python -c "
from hermes.actors.coder_actor import CoderActor
import asyncio
asyncio.run(CoderActor().load_model())
"
```

**Resolution:**
1. Check if model exists in cache:
   ```bash
   kubectl exec -n ray-system ray-worker-xxxx -- ls -la /cache/models
   ```

2. Check network connectivity to HuggingFace:
   ```bash
   kubectl exec -n ray-system ray-worker-xxxx -- curl -v https://huggingface.co
   ```

3. Clear cache and retry:
   ```bash
   kubectl exec -n ray-system ray-worker-xxxx -- rm -rf /cache/models/*
   kubectl delete pod -n ray-system ray-worker-xxxx
   ```

4. Check disk space:
   ```bash
   kubectl exec -n ray-system ray-worker-xxxx -- df -h
   ```

**Escalation:** If issue persists after 1 hour, escalate to P2

---

#### Issue: GPU Out of Memory

**Symptoms:**
- CUDA out of memory errors in logs
- GPU tasks failing
- High GPU utilization with errors

**Diagnosis:**
```bash
# Check GPU status
kubectl exec -n ray-system ray-worker-xxxx -- nvidia-smi

# Check Ray GPU resources
kubectl exec -n ray-system ray-head-xxxx -- ray nodes

# Check running tasks
kubectl exec -n ray-system ray-head-xxxx -- ray tasks

# Check GPU memory usage
kubectl exec -n ray-system ray-worker-xxxx -- python -c "
import torch
print(f'Total: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB')
print(f'Allocated: {torch.cuda.memory_allocated(0) / 1024**2:.2f} MB')
print(f'Cached: {torch.cuda.memory_reserved(0) / 1024**2:.2f} MB')
"
```

**Resolution:**
1. Check if MPS is running:
   ```bash
   kubectl exec -n ray-system ray-worker-xxxx -- nvidia-smi mps
   ```

2. Restart GPU worker:
   ```bash
   kubectl delete pod -n ray-system ray-worker-gpu-xxxx
   ```

3. Reduce concurrent GPU tasks:
   ```bash
   # Edit raycluster.yaml to reduce maxReplicas for GPU workers
   kubectl apply -f kubernetes/ray/raycluster.yaml
   ```

4. Use smaller models or quantization:
   ```bash
   # Use INT8 quantized models
   kubectl exec -n ray-system ray-worker-xxxx -- python -c "
   from actors.coder_actor import CoderActor
   actor = CoderActor()
   actor.quantization = 'q8_0'
   "
   ```

**Escalation:** If issue persists after 30 minutes, escalate to P1

---

#### Issue: High Error Rate

**Symptoms:**
- High error rate in Grafana (> 5%)
- Many 5xx responses
- Alerts firing for HighErrorRate

**Diagnosis:**
```bash
# Check error logs
kubectl logs -n hermes hermes-xxxx | grep -i error | head -20
kubectl logs -n ray-system ray-worker-xxxx | grep -i error | head -20

# Check Prometheus for error metrics
kubectl exec -n monitoring prometheus-xxxx -- curl -s "
  http://localhost:9090/api/v1/query?query=rate(error_counter[5m])&format=json
" | jq .

# Check which model is failing
kubectl exec -n monitoring prometheus-xxxx -- curl -s "
  http://localhost:9090/api/v1/query?query=rate(error_counter[5m]) by (model)&format=json
" | jq .

# Check circuit breaker status
kubectl exec -n hermes hermes-xxxx -- python -c "
from hermes.frame_dispatcher import dispatcher
import asyncio
asyncio.run(dispatcher.dump_state())
"
```

**Resolution:**
1. Identify failing model and temporarily disable:
   ```python
   # In code/hermes/models.py, comment out the failing model in MODEL_REGISTRY
   # Then redeploy Hermes
   kubectl rollout restart deployment -n hermes hermes-deployment
   ```

2. Check if it's a specific request causing issues:
   ```bash
   # Check recent requests
   kubectl exec -n hermes hermes-xxxx -- python -c "
   import sqlite3
   conn = sqlite3.connect('/data/hermes.db')
   cursor = conn.cursor()
   cursor.execute('SELECT * FROM requests ORDER BY timestamp DESC LIMIT 10')
   for row in cursor.fetchall():
       print(row)
   conn.close()
   "
   ```

3. Restart failing component:
   ```bash
   # Restart Hermes
   kubectl rollout restart deployment -n hermes hermes-deployment
   
   # Or restart specific Ray worker
   kubectl delete pod -n ray-system ray-worker-xxxx
   ```

**Escalation:** If error rate > 10% for 15 minutes, escalate to P1

---

#### Issue: Network Connectivity Problems

**Symptoms:**
- Services cannot communicate
- DNS resolution failures
- Connection timeouts
- "No route to host" errors

**Diagnosis:**
```bash
# Check Tailscale status
kubectl exec -n tailscale tailscale-subnet-router-xxxx -- tailscale status

# Test DNS resolution from Hermes
kubectl exec -n hermes hermes-xxxx -- nslookup raycluster-head-svc.ray-system.svc.cluster.local

# Test DNS resolution from Ray
kubectl exec -n ray-system ray-head-xxxx -- nslookup hermes-service.hermes.svc.cluster.local

# Test connectivity from Hermes to Ray
kubectl exec -n hermes hermes-xxxx -- curl -v http://raycluster-head-svc.ray-system.svc.cluster.local:8265

# Test connectivity from Ray to Hermes
kubectl exec -n ray-system ray-head-xxxx -- curl -v http://hermes-service.hermes.svc.cluster.local:8000/health

# Test external connectivity
curl -v https://api.yourdomain.com/health
curl -v https://ray.yourdomain.com/server/ray
```

**Resolution:**
1. Check Tailscale subnet router:
   ```bash
   kubectl get pods -n tailscale
   kubectl describe pod -n tailscale tailscale-subnet-router-xxxx
   ```

2. Restart Tailscale:
   ```bash
   kubectl delete pods -n tailscale --all
   ```

3. Check network policies:
   ```bash
   kubectl get networkpolicy -A
   kubectl describe networkpolicy -n hermes hermes-allow-internal
   ```

4. Temporarily disable network policies (for testing):
   ```bash
   kubectl delete networkpolicy -A --all
   ```

5. Check if it's a Tailscale DERP issue:
   ```bash
   kubectl exec -n tailscale tailscale-subnet-router-xxxx -- tailscale status --derp
   ```

**Escalation:** If connectivity issue affects production, escalate to P1

---

#### Issue: Storage Full

**Symptoms:**
- Disk full errors
- Failed to write files
- Longhorn volume errors
- "No space left on device"

**Diagnosis:**
```bash
# Check disk usage on all nodes
for node in cupfox qfox-1 neon-64gb steamdeck racknerd; do
  echo "=== $node ==="
  kubectl exec -n ray-system ray-worker-xxxx -- df -h 2>/dev/null || true
done

# Check Longhorn volumes
kubectl get volumes -n longhorn-system
kubectl describe volume -n longhorn-system pvc-xxxx

# Check PVC status
kubectl get pvc -A
kubectl describe pvc -n ray-system redis-data

# Check Longhorn snapshots
kubectl get snapshots -n longhorn-system
kubectl get backups -n longhorn-system
```

**Resolution:**
1. Clean up old models:
   ```bash
   # List model cache
   kubectl exec -n ray-system ray-worker-xxxx -- ls -lh /cache/models
   
   # Remove old models
   kubectl exec -n ray-system ray-worker-xxxx -- rm -rf /cache/models/*-old.gguf
   kubectl exec -n ray-system ray-worker-xxxx -- rm -rf /cache/models/*-v1.gguf
   ```

2. Expand storage:
   ```bash
   # Edit PVC to increase size
   kubectl edit pvc -n ray-system redis-data
   # Increase storage request
   ```

3. Clean up Longhorn snapshots:
   ```bash
   # List snapshots
   kubectl get snapshots -n longhorn-system
   
   # Delete old snapshots
   kubectl delete snapshot -n longhorn-system old-snapshot-xxxx
   ```

4. Clean up Docker images:
   ```bash
   kubectl exec -n ray-system ray-worker-xxxx -- docker system prune -a -f
   ```

**Escalation:** If storage > 90% full, escalate to P2

---

#### Issue: Certificate Expired

**Symptoms:**
- TLS handshake failures
- Certificate expired warnings in browser
- "x509: certificate signed by unknown authority"

**Diagnosis:**
```bash
# Check certificate status
kubectl get certificate -A

# Check certificate details
kubectl describe certificate -n ray-system ray-dashboard-tls

# Check certificate expiry
kubectl exec -n ray-system ray-head-xxxx -- openssl x509 -in /etc/ray/tls/ray-dashboard.crt -noout -dates

# Check cert-manager logs
kubectl logs -n cert-manager -l app=cert-manager | grep -i error
```

**Resolution:**
1. Renew certificate:
   ```bash
   kubectl delete certificate -n ray-system ray-dashboard-tls
   kubectl apply -f kubernetes/ray/certificate.yaml
   ```

2. Check ClusterIssuer:
   ```bash
   kubectl describe clusterissuer letsencrypt-prod
   ```

3. Restart cert-manager:
   ```bash
   kubectl rollout restart deployment -n cert-manager cert-manager
   ```

4. Force certificate renewal:
   ```bash
   kubectl annotate certificate -n ray-system ray-dashboard-tls \
     cert-manager.io/force-renewal="true" --overwrite
   ```

**Escalation:** If certificates cannot be renewed, escalate to P2

---

## Emergency Procedures

### Full System Restart

**When to use:** System is completely unresponsive, all other troubleshooting failed

**Prerequisites:**
- Notify all stakeholders
- Take screenshots of current state (Grafana, Ray dashboard)
- Collect logs from all pods

**Procedure:**

1. Collect current state:
   ```bash
   # Save all pod logs
   mkdir -p emergency-logs-$(date +%Y%m%d-%H%M%S)
   kubectl get pods -A -o name | xargs -I {} kubectl logs {} > emergency-logs-$(date +%Y%m%d-%H%M%S)/{}.log 2>&1 &
   
   # Save cluster state
   kubectl get all -A -o yaml > emergency-logs-$(date +%Y%m%d-%H%M%S)/cluster-state.yaml
   kubectl get nodes -o yaml > emergency-logs-$(date +%Y%m%d-%H%M%S)/nodes.yaml
   ```

2. Restart components in order:
   ```bash
   # 1. Restart monitoring (so we can observe restart)
   kubectl rollout restart deployment -n monitoring prometheus-operator-grafana
   kubectl rollout restart deployment -n monitoring prometheus-operator-kube-state-metrics
   
   # 2. Restart Ray cluster
   kubectl delete raycluster -n ray-system raycluster
   kubectl apply -f kubernetes/ray/raycluster.yaml
   
   # Wait for Ray to be ready
   kubectl wait --for=condition=Ready pod -n ray-system ray-head-xxxx --timeout=300s
   
   # 3. Restart Hermes
   kubectl rollout restart deployment -n hermes hermes-deployment
   
   # 4. Restart Tailscale (if needed)
   kubectl delete pods -n tailscale --all
   ```

3. Verify system health:
   ```bash
   # Check all pods
   kubectl get pods -A
   
   # Check Ray dashboard
   curl -k https://admin:password@ray.yourdomain.com/server/ray/api/nodes
   
   # Check Hermes health
   curl https://api.yourdomain.com/health
   
   # Check Grafana
   curl -k https://grafana.yourdomain.com/api/health
   ```

**Expected Recovery Time:** 10-15 minutes

**Rollback:** If restart fails, restore from backups

---

### Database Migration

**When to use:** Need to migrate data or repair corrupted database

**Prerequisites:**
- Database backup exists
- Maintenance window available

**Procedure:**

1. Backup current database:
   ```bash
   kubectl cp hermes/hermes-xxxx:/data/hermes.db ./hermes-backup-$(date +%Y%m%d-%H%M%S).db -c hermes
   ```

2. Create new database:
   ```bash
   kubectl exec -n hermes hermes-xxxx -c hermes -- python -c "
import sqlite3
conn = sqlite3.connect('/data/hermes-new.db')
cursor = conn.cursor()
cursor.execute('''
  CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    model_type TEXT NOT NULL,
    prompt TEXT NOT NULL,
    generated_text TEXT,
    tokens_generated INTEGER,
    tokens_input INTEGER,
    latency_ms REAL,
    finish_reason TEXT,
    timestamp TEXT NOT NULL,
    user_id TEXT,
    status TEXT DEFAULT 'completed'
  )
''')
cursor.execute('''
  CREATE INDEX IF NOT EXISTS idx_requests_timestamp ON requests(timestamp)
''')
cursor.execute('''
  CREATE INDEX IF NOT EXISTS idx_requests_model ON requests(model)
''')
conn.commit()
conn.close()
print('New database created')
"
   ```

3. Migrate data:
   ```bash
   kubectl exec -n hermes hermes-xxxx -c hermes -- python -c "
import sqlite3
conn_old = sqlite3.connect('/data/hermes.db')
conn_new = sqlite3.connect('/data/hermes-new.db')
conn_old.backup(conn_new)
conn_old.close()
conn_new.close()
print('Data migrated')
"
   ```

4. Update configuration to use new database:
   ```bash
   # Edit code/hermes/config.py
   # DATABASE_URL = 'sqlite:///./hermes-new.db'
   
   # Rebuild and redeploy
   kubectl rollout restart deployment -n hermes hermes-deployment
   ```

5. Verify data integrity:
   ```bash
   kubectl exec -n hermes hermes-xxxx -c hermes -- python -c "
import sqlite3
conn = sqlite3.connect('/data/hermes-new.db')
cursor = conn.cursor()
cursor.execute('SELECT COUNT(*) FROM requests')
print(f'Total requests: {cursor.fetchone()[0]}')
cursor.execute('SELECT model, COUNT(*) FROM requests GROUP BY model')
for row in cursor.fetchall():
    print(f'{row[0]}: {row[1]} requests')
conn.close()
"
   ```

**Expected Downtime:** 5-10 minutes

**Rollback:** Revert to old database if migration fails

---

### Security Incident Response

**When to use:** Security breach, unauthorized access, data leak

**Immediate Actions:**

1. **Isolate**
   - Disconnect affected systems from network
   - Revoke compromised credentials
   - Block malicious IPs

2. **Preserve Evidence**
   - Do NOT modify systems
   - Take forensic snapshots
   - Save all logs
   - Document timeline

3. **Contain**
   - Stop the attack if still ongoing
   - Identify attack vector
   - Prevent further access

4. **Eradicate**
   - Remove the threat
   - Patch vulnerabilities
   - Update configurations

5. **Recover**
   - Restore systems from clean backups
   - Verify system integrity
   - Test before production

6. **Notify**
   - Inform stakeholders
   - Inform affected parties (if data leak)
   - Follow legal requirements

7. **Post-Mortem**
   - Conduct incident review
   - Identify root cause
   - Implement preventive measures
   - Document lessons learned

**Security Contacts:**
- security@yourdomain.com (Primary)
- On-call security engineer
- CISO (for P0 incidents)

**Escalation:** All security incidents are P0

---

## Maintenance Procedures

### Model Update

**Procedure:**

1. Download new model version:
   ```bash
   kubectl exec -n ray-system ray-worker-xxxx -- python -c "
from hermes.models import download_model
import asyncio
asyncio.run(download_model('Qwopus3.5-9B', 'v2', '/cache/models/Qwopus3.5-9B-v2.gguf'))
"
   ```

2. Verify model:
   ```bash
   kubectl exec -n ray-system ray-worker-xxxx -- python -c "
from hermes.actors.coder_actor import CoderActor
import asyncio
actor = CoderActor()
actor.model_path = '/cache/models/Qwopus3.5-9B-v2.gguf'
asyncio.run(actor.load_model())
print('Model loaded successfully')
"
   ```

3. Update MODEL_REGISTRY:
   ```python
   # In code/hermes/models.py
   MODEL_REGISTRY[ModelType.CODE] = ModelSpec(
       name="Qwopus3.5-9B",
       version="2.0.0",  # Updated version
       # ... other fields
   )
   ```

4. Redeploy Hermes:
   ```bash
   kubectl rollout restart deployment -n hermes hermes-deployment
   ```

5. Verify new model is available:
   ```bash
   curl https://api.yourdomain.com/api/v1/models | jq .
   ```

**Expected Downtime:** 2-5 minutes (lazy loading)

**Rollback:** Revert model path to old version

---

### Certificate Rotation

**Procedure:**

1. Check current certificates:
   ```bash
   kubectl get certificate -A
   ```

2. Update ClusterIssuer if needed:
   ```bash
   kubectl apply -f kubernetes/security/letsencrypt-clusterissuer.yaml
   ```

3. Update certificates to force renewal:
   ```bash
   kubectl delete certificate -n ray-system ray-dashboard-tls
   kubectl delete certificate -n hermes hermes-tls
   kubectl delete certificate -n monitoring grafana-tls
   
   kubectl apply -f kubernetes/ray/certificate.yaml
   kubectl apply -f kubernetes/hermes/certificate.yaml
   kubectl apply -f kubernetes/monitoring/certificate.yaml
   ```

4. Restart cert-manager:
   ```bash
   kubectl rollout restart deployment -n cert-manager cert-manager
   ```

5. Verify new certificates are issued:
   ```bash
   kubectl get certificate -A -w
   ```

6. Restart services using certificates:
   ```bash
   kubectl rollout restart deployment -n ray-system ray-head
   kubectl rollout restart deployment -n hermes hermes-deployment
   kubectl rollout restart deployment -n monitoring grafana
   ```

**Expected Time:** 5-10 minutes

**Rollback:** Use existing certificates if new ones fail

---

### Kubernetes Upgrade

**Prerequisites:**
- Backup etcd
- Maintenance window
- All pods are healthy

**Procedure:**

1. Check current version:
   ```bash
   kubectl version
   ```

2. Backup etcd:
   ```bash
   kubectl -n kube-system exec etcd-cupfox -- etcdctl snapshot save /tmp/etcd-backup.db
   kubectl cp kube-system/etcd-cupfox:/tmp/etcd-backup.db ./etcd-backup-$(date +%Y%m%d-%H%M%S).db
   ```

3. Upgrade k3s on master (cupfox):
   ```bash
   curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.28.5+k3s1 sh -
   ```

4. Upgrade k3s on worker nodes:
   ```bash
   # On each worker node
   curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.28.5+k3s1 K3S_URL=https://cupfox:6443 K3S_TOKEN=... sh -
   ```

5. Verify upgrade:
   ```bash
   kubectl get nodes
   kubectl version
   kubectl get pods -A
   ```

**Expected Downtime:** 10-20 minutes

**Rollback:** Restore etcd from backup and reinstall old version

---

### Longhorn Upgrade

**Procedure:**

1. Check current version:
   ```bash
   helm list -n longhorn-system
   ```

2. Backup volumes:
   ```bash
   kubectl get volumes -n longhorn-system
   kubectl get backups -n longhorn-system
   ```

3. Upgrade Longhorn:
   ```bash
   helm upgrade longhorn longhorn/longhorn \
     --namespace longhorn-system \
     --version v1.6.0 \
     --values kubernetes/storage/longhorn-values.yaml
   ```

4. Verify volumes are healthy:
   ```bash
   kubectl get volumes -n longhorn-system
   kubectl get nodes -o wide | grep -E "STATUS|longhorn"
   ```

**Expected Downtime:** 5-10 minutes

**Rollback:** Reinstall old version

---

## Useful Commands

### Ray Cluster

| Command | Description |
|---------|-------------|
| `kubectl get raycluster -n ray-system` | List Ray clusters |
| `kubectl describe raycluster -n ray-system raycluster` | Show cluster details |
| `kubectl get pods -n ray-system` | List Ray pods |
| `kubectl logs -n ray-system ray-head-xxxx` | View Ray head logs |
| `kubectl exec -n ray-system ray-head-xxxx -- ray nodes` | List Ray nodes |
| `kubectl exec -n ray-system ray-head-xxxx -- ray tasks` | List Ray tasks |
| `kubectl exec -n ray-system ray-head-xxxx -- ray dashboard` | Start Ray dashboard locally |
| `kubectl exec -n ray-system ray-head-xxxx -- ray up` | Start Ray cluster manually |
| `kubectl exec -n ray-system ray-head-xxxx -- ray down` | Stop Ray cluster manually |

### Hermes API

| Command | Description |
|---------|-------------|
| `kubectl get pods -n hermes` | List Hermes pods |
| `kubectl logs -n hermes hermes-xxxx` | View Hermes logs |
| `kubectl exec -n hermes hermes-xxxx -- python -c "from hermes.models import MODEL_REGISTRY; print([m.name for m in MODEL_REGISTRY.values()])"` | List models |
| `kubectl exec -n hermes hermes-xxxx -- curl -s http://localhost:8000/health | jq .` | Check health |
| `kubectl exec -n hermes hermes-xxxx -- curl -s http://localhost:8000/status | jq .` | Check status |

### Monitoring

| Command | Description |
|---------|-------------|
| `kubectl get pods -n monitoring` | List monitoring pods |
| `kubectl logs -n monitoring prometheus-xxxx` | View Prometheus logs |
| `kubectl exec -n monitoring prometheus-xxxx -- curl -s http://localhost:9090/api/v1/targets | jq .` | List scrape targets |
| `kubectl exec -n monitoring prometheus-xxxx -- curl -s "http://localhost:9090/api/v1/query?query=up" | jq .` | Check endpoint health |
| `kubectl exec -n monitoring grafana-xxxx -- curl -s http://localhost:3000/api/health` | Check Grafana health |

### Tailscale

| Command | Description |
|---------|-------------|
| `kubectl get pods -n tailscale` | List Tailscale pods |
| `kubectl logs -n tailscale tailscale-subnet-router-xxxx` | View Tailscale logs |
| `kubectl exec -n tailscale tailscale-subnet-router-xxxx -- tailscale status` | Check Tailscale status |
| `kubectl exec -n tailscale tailscale-subnet-router-xxxx -- tailscale status --routes` | Check advertised routes |
| `kubectl exec -n tailscale tailscale-subnet-router-xxxx -- tailscale status --peers` | Check peer connections |

### Storage (Longhorn)

| Command | Description |
|---------|-------------|
| `kubectl get volumes -n longhorn-system` | List Longhorn volumes |
| `kubectl get backups -n longhorn-system` | List Longhorn backups |
| `kubectl get snapshots -n longhorn-system` | List Longhorn snapshots |
| `kubectl describe volume -n longhorn-system pvc-xxxx` | Show volume details |
| `kubectl get settings -n longhorn-system` | List Longhorn settings |

### Certificates

| Command | Description |
|---------|-------------|
| `kubectl get certificate -A` | List all certificates |
| `kubectl describe certificate -n ray-system ray-dashboard-tls` | Show certificate details |
| `kubectl get clusterissuer` | List cluster issuers |
| `kubectl describe clusterissuer letsencrypt-prod` | Show issuer details |
| `kubectl logs -n cert-manager -l app=cert-manager` | View cert-manager logs |

---

*For deployment instructions, see the [Deployment Checklist](DEPLOYMENT_CHECKLIST.md).*
*For architecture details, see the [Architecture Documentation](ARCHITECTURE.md).*
