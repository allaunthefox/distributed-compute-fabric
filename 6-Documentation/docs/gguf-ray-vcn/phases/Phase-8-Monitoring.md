# Phase 8: Monitoring & Observability

**Phase:** 8  
**Name:** Monitoring & Observability  
**Duration:** 5 days  
**Dependencies:** Phase 7 (Hermes Orchestrator)  
**Status:** Partial (Prometheus/Grafana exist, need completion)  
**Owner:** SRE Team

---

## Overview

This phase implements comprehensive monitoring, logging, and tracing for the entire GGUF-Ray-VCN-LUPINE stack, enabling visibility into system health, performance, and issues.

### Goals
1. Deploy Prometheus for metrics collection
2. Deploy Grafana for visualization
3. Deploy Loki for log aggregation
4. Deploy Tempo for distributed tracing
5. Configure alerts for critical issues
6. Create comprehensive dashboards
7. Instrument application code with metrics

### Key Components
- Prometheus (metrics collection)
- Grafana (visualization)
- Loki (log aggregation)
- Tempo (distributed tracing)
- Alertmanager (alerting)
- Prometheus Operator (management)

---

## Prerequisites

Before starting Phase 8, ensure:
- [ ] Phase 1-7 are complete
- [ ] All services are running
- [ ] Network connectivity is established (Phase 6)
- [ ] Helm is installed
- [ ] Storage provisioner is available

---

## Microsteps

### Day 1: Prometheus Deployment

#### Step 8.1.1: Create Monitoring Namespace
```bash
# File: kubernetes/monitoring/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: monitoring
  labels:
    name: monitoring
```

**Verification:**
```bash
kubectl get ns monitoring
```

#### Step 8.1.2: Install Prometheus Operator
```bash
# Add Helm repo
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Install Prometheus Operator
helm install prometheus-operator prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --version 58.0.0 \
  --values kubernetes/monitoring/prometheus-operator-values.yaml
```

**Values File:**
```yaml
# File: kubernetes/monitoring/prometheus-operator-values.yaml
prometheus:
  prometheusSpec:
    serviceMonitorSelectorNilUsesHelmValues: false
    podMonitorSelectorNilUsesHelmValues: false
    retention: 30d
    retentionSize: "50GiB"
    resources:
      requests:
        memory: 2Gi
        cpu: 1
      limits:
        memory: 4Gi
        cpu: 2
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn
          resources:
            requests:
              storage: 50Gi
    
grafana:
  enabled: true
  adminPassword: ${GRAFANA_ADMIN_PASSWORD}
  ingress:
    enabled: false  # We'll use our own IngressRoute
  service:
    type: ClusterIP
  persistence:
    enabled: true
    storageClassName: longhorn
    size: 10Gi
  
alertmanager:
  enabled: true
  config:
    global:
      resolve_timeout: 5m
      http_config:
        tls_config:
          insecure_skip_verify: true
    receivers:
    - name: default-receiver
      slack_configs:
      - api_url: ${SLACK_WEBHOOK_URL}
        channel: "#alerts"
        send_resolved: true
        title: '[{{ .Status | toUpper }}] {{ .CommonLabels.alertname }}'
        text: '{{ .CommonAnnotations.description }}'
    
    route:
      group_by: ['alertname', 'severity']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 3h
      receiver: default-receiver
```

**Verification:**
```bash
kubectl get pods -n monitoring
# Expected: prometheus-operator, prometheus, grafana, alertmanager pods

kubectl get svc -n monitoring
# Expected: prometheus-operated, grafana, alertmanager-operated services
```

#### Step 8.1.3: Configure ServiceMonitors
```yaml
# File: kubernetes/monitoring/ray-service-monitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: ray-cluster
  namespace: monitoring
  labels:
    release: prometheus-operator
spec:
  selector:
    matchLabels:
      app: ray-head
  endpoints:
  - port: dashboard
    interval: 15s
    path: /metrics
    scheme: http
  namespaceSelector:
    matchNames:
    - ray-system
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: hermes-api
  namespace: monitoring
  labels:
    release: prometheus-operator
spec:
  selector:
    matchLabels:
      app: hermes
  endpoints:
  - port: http
    interval: 15s
    path: /api/v1/metrics
    scheme: http
  namespaceSelector:
    matchNames:
    - hermes
```

**Verification:**
```bash
kubectl get servicemonitor -n monitoring
# Expected: ray-cluster and hermes-api should be listed
```

### Day 2: Grafana Configuration

#### Step 8.2.1: Deploy Grafana Dashboards
```yaml
# File: kubernetes/monitoring/grafana-dashboard.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboards
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  hermes-dashboard.json: |
    {
      "title": "Hermes API",
      "uid": "hermes-api",
      "panels": [
        {
          "title": "Requests per Second",
          "type": "graph",
          "targets": [
            {
              "expr": "rate(request_counter[1m])",
              "legendFormat": "{{model}}"
            }
          ]
        },
        {
          "title": "Average Latency",
          "type": "graph",
          "targets": [
            {
              "expr": "rate(request_latency_seconds_sum[1m]) / rate(request_latency_seconds_count[1m])",
              "legendFormat": "{{model}}"
            }
          ]
        },
        {
          "title": "Tokens Generated",
          "type": "graph",
          "targets": [
            {
              "expr": "rate(token_counter[1m])",
              "legendFormat": "{{model}}"
            }
          ]
        },
        {
          "title": "Error Rate",
          "type": "graph",
          "targets": [
            {
              "expr": "rate(error_counter[1m])",
              "legendFormat": "{{model}}"
            }
          ]
        }
      ]
    }
  ray-dashboard.json: |
    {
      "title": "Ray Cluster",
      "uid": "ray-cluster",
      "panels": [
        {
          "title": "Node Count",
          "type": "stat",
          "targets": [
            {
              "expr": "count(ray_node_info)",
              "format": "time_series"
            }
          ]
        },
        {
          "title": "GPU Available",
          "type": "stat",
          "targets": [
            {
              "expr": "sum(ray_node_gpu_available)",
              "format": "time_series"
            }
          ]
        },
        {
          "title": "CPU Usage",
          "type": "graph",
          "targets": [
            {
              "expr": "100 - (avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)",
              "legendFormat": "{{instance}}"
            }
          ]
        },
        {
          "title": "Memory Usage",
          "type": "graph",
          "targets": [
            {
              "expr": "(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100",
              "legendFormat": "{{instance}}"
            }
          ]
        }
      ]
    }
```

**Verification:**
```bash
kubectl get configmap -n monitoring grafana-dashboards
# Expected: Should exist
```

#### Step 8.2.2: Configure Grafana Data Sources
```yaml
# File: kubernetes/monitoring/grafana-datasources.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-datasources
  namespace: monitoring
  labels:
    grafana_datasource: "1"
data:
  prometheus.yaml: |
    apiVersion: 1
    datasources:
    - name: Prometheus
      type: prometheus
      access: proxy
      url: http://prometheus-operated:9090
      isDefault: true
      editable: false
  loki.yaml: |
    apiVersion: 1
    datasources:
    - name: Loki
      type: loki
      access: proxy
      url: http://loki:3100
      editable: false
  tempo.yaml: |
    apiVersion: 1
    datasources:
    - name: Tempo
      type: tempo
      access: proxy
      url: http://tempo:3200
      editable: false
```

**Verification:**
```bash
# Access Grafana UI and check data sources
# Expected: Prometheus, Loki, Tempo should be configured
```

### Day 3: Loki Deployment (Log Aggregation)

#### Step 8.3.1: Install Loki Stack
```bash
helm install loki grafana/loki-stack \
  --namespace monitoring \
  --version 2.10.0 \
  --values kubernetes/monitoring/loki-values.yaml
```

**Values File:**
```yaml
# File: kubernetes/monitoring/loki-values.yaml
loki:
  enabled: true
  config:
    schema_config:
      configs:
      - from: 2024-01-01
        store: boltdb-shipper
        object_store: filesystem
        schema: v12
        index:
          prefix: index_
          period: 24h
    storage_config:
      boltdb_shipper:
        shared_store: filesystem
        active_index_directory: /data/loki/index
        cache_location: /data/loki/cache
        cache_ttl: 24h
    chunk_store_config:
      max_look_back_period: 0s
    table_manager:
      retention_deletes_enabled: true
      retention_period: 30d
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: longhorn
        resources:
          requests:
            storage: 50Gi
  resources:
    requests:
      memory: 1Gi
      cpu: 500m
    limits:
      memory: 2Gi
      cpu: 1

promtail:
  enabled: true
  config:
    logLevel: info
    serverPort: 3101
    clients:
    - url: http://loki:3100/loki/api/v1/push
```

**Verification:**
```bash
kubectl get pods -n monitoring | grep loki
# Expected: loki and promtail pods running
```

#### Step 8.3.2: Configure Log Collection
```yaml
# File: kubernetes/monitoring/log-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: promtail-config
  namespace: monitoring
data:
  promtail.yaml: |
    server:
      http_listen_port: 9080
      grpc_listen_port: 0
    
    positions:
      filename: /tmp/positions.yaml
    
    clients:
    - url: http://loki:3100/loki/api/v1/push
    
    scrape_configs:
    - job_name: kubernetes-pods
      kubernetes_sd_configs:
      - role: pod
      pipeline_stages:
      - docker: {}
      - drop:
          expression: "^.*log level=debug.*$"
          drop_counter_reason: "debug-level-logs"
      relabel_configs:
      - source_labels: [__meta_kubernetes_namespace]
        target_label: namespace
      - source_labels: [__meta_kubernetes_pod_name]
        target_label: pod
      - source_labels: [__meta_kubernetes_pod_container_name]
        target_label: container
      - action: labelmap
        regex: "__(.*)__"
```

**Verification:**
```bash
# Check Loki for logs
kubectl exec -n monitoring -it loki-0 -- curl -G http://localhost:3100/loki/api/v1/series --data-urlencode 'match={job="kubernetes-pods"}'
# Expected: Should return log series
```

### Day 4: Tempo Deployment (Distributed Tracing)

#### Step 8.4.1: Install Tempo
```bash
helm install tempo grafana/tempo \
  --namespace monitoring \
  --version 1.5.0 \
  --values kubernetes/monitoring/tempo-values.yaml
```

**Values File:**
```yaml
# File: kubernetes/monitoring/tempo-values.yaml
architecture: "simple"
mode: "all-in-one"

storage:
  trace:
    backend: local
    local:
      path: /data/tempo/traces
    wal:
      path: /data/tempo/wal
      truncate_frequency: 10m
  block:
    bloom_filter:
      false_positive: .05
      shard_size_bytes: 1048576
      hash_num: 3

tempo:
  config: |
    multitenancy_enabled: false
    compaction:
      block_retention: 1h
      compacted_block_retention: 1h
      periodic_compaction_interval: 10m
    
  resources:
    requests:
      memory: 2Gi
      cpu: 1
    limits:
      memory: 4Gi
      cpu: 2
  
  persistence:
    enabled: true
    storageClassName: longhorn
    size: 20Gi
```

**Verification:**
```bash
kubectl get pods -n monitoring | grep tempo
# Expected: tempo pod running
```

#### Step 8.4.2: Instrument Application with Tracing
```python
# File: code/hermes/tracing.py
"""
Distributed Tracing Configuration

Integrates OpenTelemetry for distributed tracing.
"""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.ray import RayInstrumentor
from opentelemetry.resources import Resource
from opentelemetry.trace import SpanKind

# Initialize tracer provider
tracer_provider = TracerProvider(
    resource=Resource.create({
        "service.name": "hermes",
        "service.version": "1.0.0",
    })
)

# Configure exporter
otlp_exporter = OTLPSpanExporter(
    endpoint="tempo.monitoring.svc.cluster.local:4317",
    insecure=True,
)

# Add span processor
span_processor = BatchSpanProcessor(otlp_exporter)
tracer_provider.add_span_processor(span_processor)

# Set global tracer provider
trace.set_tracer_provider(tracer_provider)

# Get tracer
tracer = trace.get_tracer(__name__)


def instrument_app(app):
    """Instrument FastAPI app with tracing."""
    FastAPIInstrumentor.instrument_app(app)
    RayInstrumentor().instrument()
    
    return app
```

**Update main.py:**
```python
# Add to code/hermes/main.py
from hermes.tracing import instrument_app

# After app creation
app = instrument_app(app)
```

**Verification:**
```bash
# Send a test request
curl -X POST https://api.yourdomain.com/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello", "max_tokens": 10}'

# Check Tempo for traces
kubectl exec -n monitoring -it tempo-xxxx -- curl -G http://localhost:3200/api/search --data-urlencode 'q={service.name="hermes"}'
# Expected: Should return traces
```

### Day 5: Alerting & Final Configuration

#### Step 8.5.1: Configure Alert Rules
```yaml
# File: kubernetes/monitoring/alert-rules.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: hermes-alerts
  namespace: monitoring
  labels:
    release: prometheus-operator
spec:
  groups:
  - name: hermes.rules
    rules:
    - alert: HighErrorRate
      expr: rate(error_counter[5m]) / rate(request_counter[5m]) > 0.1
      for: 5m
      labels:
        severity: critical
        service: hermes
      annotations:
        summary: "High error rate for Hermes API"
        description: "Error rate is {{ $value }}% for model {{ $labels.model }}"
    
    - alert: HighLatency
      expr: rate(request_latency_seconds_sum[5m]) / rate(request_latency_seconds_count[5m]) > 5
      for: 5m
      labels:
        severity: warning
        service: hermes
      annotations:
        summary: "High latency for Hermes API"
        description: "Average latency is {{ $value }}s for model {{ $labels.model }}"
    
    - alert: ModelUnavailable
      expr: up{job="ray-cluster"} == 0
      for: 2m
      labels:
        severity: critical
        service: ray
      annotations:
        summary: "Ray cluster node down"
        description: "Ray cluster node {{ $labels.instance }} is down"
    
    - alert: HighCPUUsage
      expr: 100 - (avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 90
      for: 5m
      labels:
        severity: warning
        service: node
      annotations:
        summary: "High CPU usage"
        description: "CPU usage is {{ $value }}% on {{ $labels.instance }}"
    
    - alert: HighMemoryUsage
      expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 90
      for: 5m
      labels:
        severity: warning
        service: node
      annotations:
        summary: "High memory usage"
        description: "Memory usage is {{ $value }}% on {{ $labels.instance }}"
```

**Verification:**
```bash
kubectl get prometheusrules -n monitoring
# Expected: hermes-alerts should be listed

# Check active alerts
kubectl exec -n monitoring -it prometheus-prometheus-operator-kube-p-0 -- curl -s http://localhost:9090/api/v1/alerts | jq .
# Expected: Should show active alerts (may be empty)
```

#### Step 8.5.2: Create Prometheus Metrics Middleware
```python
# File: code/hermes/metrics.py
"""
Prometheus Metrics Configuration

Exposes metrics for Prometheus scraping.
"""

from prometheus_client import Counter, Histogram, Gauge, start_http_server
import time

# Request counter
request_counter = Counter(
    'request_counter',
    'Total number of requests',
    ['model', 'endpoint', 'status']
)

# Token counter
token_counter = Counter(
    'token_counter',
    'Total number of tokens generated',
    ['model', 'direction']  # direction: input or output
)

# Latency histogram
request_latency = Histogram(
    'request_latency_seconds',
    'Request latency in seconds',
    ['model', 'endpoint'],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
)

# Error counter
error_counter = Counter(
    'error_counter',
    'Total number of errors',
    ['model', 'error_type']
)

# Active requests gauge
active_requests = Gauge(
    'active_requests',
    'Number of active requests',
    ['model']
)

# Model loaded gauge
models_loaded = Gauge(
    'models_loaded',
    'Number of models loaded in memory',
    ['model', 'node']
)

# Ray cluster metrics
ray_nodes = Gauge(
    'ray_nodes',
    'Number of Ray cluster nodes'
)

ray_cpu_available = Gauge(
    'ray_cpu_available',
    'Available CPU in Ray cluster'
)

ray_gpu_available = Gauge(
    'ray_gpu_available',
    'Available GPU in Ray cluster'
)


def start_metrics_server():
    """Start Prometheus metrics HTTP server."""
    from hermes.config import settings
    
    if settings.PROMETHEUS_ENABLED:
        start_http_server(settings.METRICS_PORT)
        print(f"Prometheus metrics server started on port {settings.METRICS_PORT}")
```

**Update main.py:**
```python
# Add to code/hermes/main.py
from hermes.metrics import start_metrics_server

# Start metrics server on startup
start_metrics_server()
```

**Verification:**
```bash
# Check metrics endpoint
curl http://localhost:9090/metrics
# Expected: Should return Prometheus metrics

# Or via Kubernetes
kubectl exec -n hermes -it hermes-xxxx -- curl http://localhost:9090/metrics
```

#### Step 8.5.3: Configure PodMonitors
```yaml
# File: kubernetes/monitoring/pod-monitors.yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: ray-workers
  namespace: monitoring
  labels:
    release: prometheus-operator
spec:
  selector:
    matchLabels:
      app: ray-worker
  podMetricsEndpoints:
  - port: metrics
    interval: 15s
    path: /metrics
    scheme: http
  namespaceSelector:
    matchNames:
    - ray-system
---
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: hermes-pods
  namespace: monitoring
  labels:
    release: prometheus-operator
spec:
  selector:
    matchLabels:
      app: hermes
  podMetricsEndpoints:
  - port: metrics
    interval: 15s
    path: /metrics
    scheme: http
  namespaceSelector:
    matchNames:
    - hermes
```

**Verification:**
```bash
kubectl get podmonitor -n monitoring
# Expected: ray-workers and hermes-pods should be listed
```

---

## Deliverables

### Files Created/Modified
- [ ] `kubernetes/monitoring/namespace.yaml`
- [ ] `kubernetes/monitoring/prometheus-operator-values.yaml`
- [ ] `kubernetes/monitoring/ray-service-monitor.yaml`
- [ ] `kubernetes/monitoring/grafana-dashboard.yaml`
- [ ] `kubernetes/monitoring/grafana-datasources.yaml`
- [ ] `kubernetes/monitoring/loki-values.yaml`
- [ ] `kubernetes/monitoring/log-config.yaml`
- [ ] `kubernetes/monitoring/tempo-values.yaml`
- [ ] `kubernetes/monitoring/alert-rules.yaml`
- [ ] `kubernetes/monitoring/pod-monitors.yaml`
- [ ] `code/hermes/tracing.py`
- [ ] `code/hermes/metrics.py`
- [ ] `code/hermes/main.py` (updates)

### Services Deployed
- [ ] Prometheus Operator
- [ ] Prometheus (metrics collection)
- [ ] Grafana (visualization)
- [ ] Loki (log aggregation)
- [ ] Tempo (distributed tracing)
- [ ] Alertmanager (alerting)

### Dashboards Created
- [ ] Hermes API dashboard
- [ ] Ray Cluster dashboard
- [ ] Infrastructure dashboard
- [ ] VCN Pipeline dashboard

---

## Verification Checklist

### Prometheus
- [ ] Prometheus pods are running
- [ ] Prometheus is scraping targets
- [ ] ServiceMonitors are configured
- [ ] PodMonitors are configured
- [ ] Alert rules are loaded

### Grafana
- [ ] Grafana pods are running
- [ ] Grafana is accessible via HTTPS (from Phase 6)
- [ ] Data sources are configured (Prometheus, Loki, Tempo)
- [ ] Dashboards are imported

### Loki
- [ ] Loki pods are running
- [ ] Promtail is collecting logs
- [ ] Logs are searchable in Loki

### Tempo
- [ ] Tempo pods are running
- [ ] Traces are being collected
- [ ] Traces are searchable

### Alerting
- [ ] Alertmanager is running
- [ ] Alert rules are configured
- [ ] Notifications are working (Slack/PagerDuty/Email)

---

## Troubleshooting

### Prometheus Not Scraping Targets

**Symptom:** Targets show as down in Prometheus UI

```bash
# Check Prometheus logs
kubectl logs -n monitoring prometheus-prometheus-operator-kube-p-0 -c prometheus

# Check ServiceMonitor configuration
kubectl get servicemonitor -n monitoring -o yaml

# Test direct scrape
kubectl exec -n monitoring -it prometheus-prometheus-operator-kube-p-0 -- curl -v http://raycluster-head-svc.ray-system.svc.cluster.local:8265/metrics
```

**Fix:** Verify ServiceMonitor selector matches service labels

### Grafana Cannot Connect to Prometheus

**Symptom:** Grafana shows "Data source not found" or connection error

```bash
# Check Grafana logs
kubectl logs -n monitoring grafana-xxxx

# Test connectivity from Grafana pod
kubectl exec -n monitoring -it grafana-xxxx -- curl -v http://prometheus-operated:9090

# Check data source configuration
kubectl get configmap -n monitoring grafana-datasources -o yaml
```

**Fix:** Ensure data source URL is correct and service is accessible

### Loki Not Receiving Logs

**Symptom:** No logs appear in Loki

```bash
# Check Loki logs
kubectl logs -n monitoring loki-0 -c loki

# Check Promtail logs
kubectl logs -n monitoring promtail-xxxx

# Test log ingestion
kubectl exec -n monitoring -it loki-0 -- curl -X POST -H "Content-Type: application/json" \
  -d '{"streams":[{"stream":{"job":"test"},"values":[["1234567890","test log line"]]}]}' \
  http://localhost:3100/loki/api/v1/push
```

**Fix:** Verify Promtail configuration and connectivity

### Tempo Not Receiving Traces

**Symptom:** No traces appear in Tempo

```bash
# Check Tempo logs
kubectl logs -n monitoring tempo-xxxx

# Test trace ingestion
kubectl exec -n monitoring -it tempo-xxxx -- curl -X POST \
  -H "Content-Type: application/json" \
  -d @/tmp/test-trace.json \
  http://localhost:4317/v1/traces
```

**Fix:** Verify OpenTelemetry exporter configuration

---

## Rollback Plan

If Phase 8 fails:

1. **Prometheus Operator**: Uninstall Helm chart
   ```bash
   helm uninstall prometheus-operator -n monitoring
   ```

2. **Loki**: Uninstall Helm chart
   ```bash
   helm uninstall loki -n monitoring
   ```

3. **Tempo**: Uninstall Helm chart
   ```bash
   helm uninstall tempo -n monitoring
   ```

4. **Clean up resources**:
   ```bash
   kubectl delete ns monitoring
   ```

---

## Next Phase

After completing Phase 8, proceed to **Phase 9: Security Hardening** to implement authentication, authorization, and encryption for the entire stack.
