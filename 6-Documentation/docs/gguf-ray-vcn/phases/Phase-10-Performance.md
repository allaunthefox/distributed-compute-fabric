# Phase 10: Performance Optimization

**Phase:** 10  
**Name:** Performance Optimization  
**Duration:** 5 days  
**Dependencies:** Phase 9 (Security Hardening)  
**Status:** TODO  
**Owner:** Performance Team

---

## Overview

This phase optimizes the performance of the GGUF-Ray-VCN-LUPINE deployment through auto-scaling, GPU sharing, model quantization, request batching, and caching strategies.

### Goals
1. Implement Kubernetes-based auto-scaling for Ray workers
2. Configure GPU sharing with Multi-Process Service (MPS)
3. Implement model quantization for reduced memory usage
4. Optimize request batching for improved throughput
5. Implement caching strategies for models and results
6. Profile and optimize performance bottlenecks
7. Load test and benchmark the system

### Key Components
- KEDA (Kubernetes Event-driven Autoscaling)
- NVIDIA MPS (Multi-Process Service)
- Model quantization (INT8, INT4)
- Request batching
- Redis caching
- Performance profiling

---

## Prerequisites

Before starting Phase 10, ensure:
- [ ] Phase 1-9 are complete
- [ ] All security measures are in place
- [ ] Monitoring is configured (Phase 8)
- [ ] Helm is installed
- [ ] NVIDIA drivers are installed on GPU nodes

---

## Microsteps

### Day 1: Auto-scaling Configuration

#### Step 10.1.1: Install KEDA
```bash
# Add Helm repo
helm repo add kedacore https://kedacore.github.io/charts
helm repo update

# Install KEDA
helm install keda kedacore/keda \
  --namespace keda \
  --create-namespace \
  --version v2.12.0
```

**Verification:**
```bash
kubectl get pods -n keda
# Expected: keda-operator and keda-admission-webhooks pods

kubectl get crd | grep keda
# Expected: clustertriggerauthentications.keda.sh, scaledobjects.keda.sh, scaledjobs.keda.sh, triggerauthentications.keda.sh
```

#### Step 10.1.2: Configure ScaledObject for Ray CPU Workers
```yaml
# File: kubernetes/autoscaling/ray-cpu-scaledobject.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: ray-cpu-workers
  namespace: ray-system
spec:
  scaleTargetRef:
    name: raycluster-cpu-worker  # Matches your RayCluster worker group
    kind: RayCluster
    apiVersion: ray.io/v1alpha1
  minReplicaCount: 1
  maxReplicaCount: 6
  triggers:
  - type: cpu
    metricType: Utilization
    metadata:
      type: Utilization
      value: "70"
  - type: memory
    metricType: Utilization
    metadata:
      type: Utilization
      value: "80"
  - type: external
    metricType: AverageValue
    metadata:
      metricName: ray_cpu_queue_length
      targetValue: "10"
      url: "http://prometheus-operated.monitoring.svc.cluster.local:9090"
```

**Verification:**
```bash
kubectl get scaledobject -n ray-system
# Expected: ray-cpu-workers should be listed

kubectl describe scaledobject -n ray-system ray-cpu-workers
# Expected: Should show triggers and current scale
```

#### Step 10.1.3: Configure ScaledObject for Ray GPU Workers
```yaml
# File: kubernetes/autoscaling/ray-gpu-scaledobject.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: ray-gpu-workers
  namespace: ray-system
spec:
  scaleTargetRef:
    name: raycluster-gpu-worker  # Matches your RayCluster worker group
    kind: RayCluster
    apiVersion: ray.io/v1alpha1
  minReplicaCount: 1
  maxReplicaCount: 2
  triggers:
  - type: gpu
    metricType: Utilization
    metadata:
      type: Utilization
      value: "60"
  - type: external
    metricType: AverageValue
    metadata:
      metricName: ray_gpu_queue_length
      targetValue: "5"
      url: "http://prometheus-operated.monitoring.svc.cluster.local:9090"
```

**Verification:**
```bash
kubectl get scaledobject -n ray-system
# Expected: ray-gpu-workers should be listed
```

#### Step 10.1.4: Configure ScaledObject for Hermes
```yaml
# File: kubernetes/autoscaling/hermes-scaledobject.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: hermes-api
  namespace: hermes
spec:
  scaleTargetRef:
    name: hermes-deployment  # Matches your Hermes deployment
    kind: Deployment
    apiVersion: apps/v1
  minReplicaCount: 2
  maxReplicaCount: 10
  triggers:
  - type: cpu
    metricType: Utilization
    metadata:
      type: Utilization
      value: "60"
  - type: memory
    metricType: Utilization
    metadata:
      type: Utilization
      value: "70"
  - type: external
    metricType: AverageValue
    metadata:
      metricName: hermes_request_queue_length
      targetValue: "50"
      url: "http://prometheus-operated.monitoring.svc.cluster.local:9090"
```

**Verification:**
```bash
kubectl get scaledobject -n hermes
# Expected: hermes-api should be listed
```

### Day 2: GPU Sharing with MPS

#### Step 10.2.1: Install NVIDIA MPS on GPU Nodes
```bash
# On qfox-1 (GPU node)
# Install NVIDIA MPS
sudo apt-get update
sudo apt-get install -y nvidia-mps

# Configure MPS
sudo nvidia-smi mps -d

# Verify MPS is running
nvidia-smi
# Expected: Should show MPS daemon running
```

#### Step 10.2.2: Configure Ray to Use MPS
```yaml
# File: kubernetes/ray/raycluster.yaml (update for MPS)
spec:
  workerGroupSpecs:
  - groupName: gpu-workers
    replicas: 1
    minReplicas: 1
    maxReplicas: 2
    rayStartParams: {}
    template:
      spec:
        containers:
        - name: ray-worker
          env:
          - name: NVIDIA_MPS_ROOT
            value: "/tmp/nvidia-mps"
          - name: NVIDIA_MPS_PIPE_DIR
            value: "/tmp/nvidia-mps"
          volumeMounts:
          - name: nvidia-mps
            mountPath: /tmp/nvidia-mps
        volumes:
        - name: nvidia-mps
          emptyDir: {}
```

**Verification:**
```bash
# Check Ray worker logs for MPS usage
kubectl logs -n ray-system ray-worker-xxxx | grep -i mps
# Expected: Should show MPS initialization
```

#### Step 10.2.3: Test GPU Sharing
```python
# File: code/tests/test_gpu_sharing.py
import ray
import torch

def test_gpu_sharing():
    """Test that multiple processes can share GPU memory."""
    # Check available GPU memory
    print(f"Total GPU memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB")
    print(f"Allocated GPU memory: {torch.cuda.memory_allocated(0) / 1024**2:.2f} MB")
    
    # Allocate some memory
    x = torch.randn(1000, 1000, device='cuda')
    print(f"After allocation: {torch.cuda.memory_allocated(0) / 1024**2:.2f} MB")
    
    # Free memory
    del x
    torch.cuda.empty_cache()
    print(f"After free: {torch.cuda.memory_allocated(0) / 1024**2:.2f} MB")

# Run test
@ray.remote(num_gpus=0.25)
def run_test():
    test_gpu_sharing()

# Submit multiple tasks
futures = [run_test.remote() for _ in range(4)]
ray.get(futures)
```

**Verification:**
```bash
# Run the test
cd code && python tests/test_gpu_sharing.py
# Expected: Should run without CUDA out of memory errors
```

### Day 3: Model Quantization

#### Step 10.3.1: Quantize GGUF Models
```bash
# Quantize Qwopus3.5-9B to INT8
python -m llm -m /cache/models/Qwopus3.5-9B.gguf \
  -o /cache/models/Qwopus3.5-9B-INT8.gguf \
  -q q8_0

# Quantize to INT4
python -m llm -m /cache/models/Qwopus3.5-9B.gguf \
  -o /cache/models/Qwopus3.5-9B-INT4.gguf \
  -q q4_0

# Quantize Gemma-4-E4B to INT8
python -m llm -m /cache/models/Gemma-4-E4B.gguf \
  -o /cache/models/Gemma-4-E4B-INT8.gguf \
  -q q8_0
```

**Verification:**
```bash
# Check file sizes
ls -lh /cache/models/*.gguf
# Expected: INT8 should be ~50% of original, INT4 should be ~25% of original
```

#### Step 10.3.2: Update Actor to Support Quantized Models
```python
# File: code/actors/gguf_actors.py (update)
class GGUFActor:
    # ... existing code ...
    
    def __init__(self, model_path: str, quantization: str = None):
        self.model_path = model_path
        self.quantization = quantization
        self.model = None
        self.llm = None
        
    async def load_model(self):
        """Load model with optional quantization."""
        if self.quantization:
            # Use quantized model
            quantized_path = self.model_path.replace('.gguf', f'-{self.quantization}.gguf')
            if os.path.exists(quantized_path):
                self.model_path = quantized_path
        
        # Load model
        self.llm = Llama(
            model_path=self.model_path,
            n_gpu_layers=-1 if self.quantization else None,
            n_ctx=4096,
        )
```

**Verification:**
```bash
# Test with quantized model
cd code && python -c "
from actors.coder_actor import CoderActor
import asyncio

async def test():
    actor = CoderActor()
    await actor.load_model()
    result = await actor.generate({'prompt': 'Hello', 'max_tokens': 10})
    print(result)

asyncio.run(test())
"
# Expected: Should work with quantized model
```

### Day 4: Request Batching & Caching

#### Step 10.4.1: Implement Request Batching in Hermes
```python
# File: code/hermes/batching.py
"""
Request Batching Module

Groups similar requests for batch processing.
"""

import asyncio
import time
from collections import defaultdict
from typing import Dict, List, Any, Optional

from hermes.models import ModelType


class BatchQueue:
    """Queue for batching similar requests."""
    
    def __init__(self, max_batch_size: int = 10, max_wait_time: float = 0.5):
        self.max_batch_size = max_batch_size
        self.max_wait_time = max_wait_time
        self.queues: Dict[ModelType, List[Dict[str, Any]]] = defaultdict(list)
        self.locks: Dict[ModelType, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.active: Dict[ModelType, bool] = {}
    
    async def add_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Add a request to the batch queue."""
        model_type = request.get("model_type", ModelType.TEXT)
        
        # Add to queue
        self.queues[model_type].append(request)
        
        # If this is the first request, start a batch
        if len(self.queues[model_type]) == 1:
            asyncio.create_task(self._process_batch(model_type))
        
        # Return a future for the result
        future = asyncio.Future()
        return future
    
    async def _process_batch(self, model_type: ModelType):
        """Process a batch of requests."""
        # Wait for more requests or timeout
        start_time = time.time()
        
        while len(self.queues[model_type]) < self.max_batch_size:
            elapsed = time.time() - start_time
            if elapsed >= self.max_wait_time:
                break
            await asyncio.sleep(0.01)
        
        # Get all requests in the queue
        requests = self.queues[model_type]
        self.queues[model_type] = []
        
        if not requests:
            return
        
        # Dispatch batch
        from hermes.frame_dispatcher import get_dispatcher
        dispatcher = await get_dispatcher()
        
        results = await dispatcher.batch_dispatch(requests)
        
        # TODO: Match results to futures
        # For now, just return results in order
        for i, result in enumerate(results):
            # Would set future result here
            pass
```

**Update orchestrator.py:**
```python
# File: code/hermes/orchestrator.py (update)
from hermes.batching import BatchQueue

# Global batch queue
batch_queue = BatchQueue(max_batch_size=10, max_wait_time=0.5)

@router.post("/generate")
async def generate(
    request: GenerateRequest,
    user: TokenPayload = Depends(is_user),
) -> GenerateResponse:
    # Add to batch queue
    future = await batch_queue.add_request(request.dict())
    
    # Wait for result
    result = await future
    
    # Process result
    # ... existing code ...
```

#### Step 10.4.2: Implement Redis Caching
```python
# File: code/hermes/cache.py
"""
Caching Module

Implements Redis-based caching for models and results.
"""

import json
import hashlib
from typing import Any, Optional

import redis.asyncio as redis

from hermes.config import settings


class CacheClient:
    """Redis cache client."""
    
    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self.enabled = settings.REDIS_HOST is not None
    
    async def connect(self):
        """Connect to Redis."""
        if not self.enabled:
            return
        
        self.redis = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD or None,
            db=0,
        )
    
    async def close(self):
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()
            self.redis = None
    
    async def get(self, key: str) -> Optional[Any]:
        """Get a value from cache."""
        if not self.enabled or not self.redis:
            return None
        
        value = await self.redis.get(key)
        if value:
            return json.loads(value)
        return None
    
    async def set(self, key: str, value: Any, ttl: int = 3600):
        """Set a value in cache with TTL."""
        if not self.enabled or not self.redis:
            return
        
        await self.redis.setex(key, ttl, json.dumps(value))
    
    async def delete(self, key: str):
        """Delete a value from cache."""
        if not self.enabled or not self.redis:
            return
        
        await self.redis.delete(key)
    
    def make_key(self, prefix: str, **kwargs) -> str:
        """Create a cache key from prefix and parameters."""
        key_str = f"{prefix}:{json.dumps(kwargs, sort_keys=True)}"
        return hashlib.sha256(key_str.encode()).hexdigest()[:32]


# Global cache client
cache = CacheClient()


# Cache decorators
def cache_result(ttl: int = 300, prefix: str = "result"):
    """Decorator to cache function results."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Create cache key
            key = cache.make_key(prefix, args=args, kwargs=kwargs)
            
            # Try to get from cache
            cached = await cache.get(key)
            if cached is not None:
                return cached
            
            # Call function
            result = await func(*args, **kwargs)
            
            # Cache result
            await cache.set(key, result, ttl=ttl)
            
            return result
        
        return wrapper
    return decorator
```

**Update actor to use caching:**
```python
# File: code/actors/gguf_actors.py (update)
from hermes.cache import cache_result

class GGUFActor:
    # ... existing code ...
    
    @cache_result(ttl=3600, prefix="generate")
    async def generate(self, prompt: str, max_tokens: int = 512, **kwargs) -> Dict[str, Any]:
        """Generate text with caching."""
        # ... existing generate implementation ...
```

**Verification:**
```bash
# Test caching
cd code && python -c "
import asyncio
from actors.coder_actor import CoderActor

async def test():
    actor = CoderActor()
    
    # First request (not cached)
    start = time.time()
    result1 = await actor.generate({'prompt': 'Hello', 'max_tokens': 10})
    time1 = time.time() - start
    
    # Second request (cached)
    start = time.time()
    result2 = await actor.generate({'prompt': 'Hello', 'max_tokens': 10})
    time2 = time.time() - start
    
    print(f'First request: {time1:.3f}s')
    print(f'Second request: {time2:.3f}s')
    print(f'Speedup: {time1/time2:.1f}x')
    
    assert result1 == result2

asyncio.run(test())
"
# Expected: Second request should be much faster (from cache)
```

### Day 5: Performance Profiling & Load Testing

#### Step 10.5.1: Profile Hermes API
```python
# File: code/tests/profile_api.py
"""
Performance Profiling for Hermes API
"""

import asyncio
import time
import statistics
from typing import List, Dict

import aiohttp


async def benchmark_endpoint(
    url: str,
    payload: Dict,
    num_requests: int = 100,
    concurrency: int = 10,
) -> Dict[str, float]:
    """Benchmark an API endpoint."""
    
    async def make_request(session: aiohttp.ClientSession):
        async with session.post(url, json=payload) as response:
            await response.json()
    
    latencies = []
    
    # Warm up
    async with aiohttp.ClientSession() as session:
        await make_request(session)
    
    # Run benchmark
    start_time = time.time()
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for _ in range(num_requests):
            task = asyncio.create_task(make_request(session))
            tasks.append(task)
        
        # Process in batches
        for i in range(0, len(tasks), concurrency):
            batch = tasks[i:i+concurrency]
            batch_start = time.time()
            await asyncio.gather(*batch)
            batch_time = time.time() - batch_start
            latencies.extend([batch_time / len(batch)] * len(batch))
    
    total_time = time.time() - start_time
    
    return {
        "total_requests": num_requests,
        "total_time": total_time,
        "avg_latency": statistics.mean(latencies),
        "min_latency": min(latencies),
        "max_latency": max(latencies),
        "p50_latency": statistics.median(latencies),
        "p95_latency": sorted(latencies)[int(len(latencies) * 0.95)],
        "requests_per_second": num_requests / total_time,
    }


async def main():
    """Run performance benchmarks."""
    url = "https://api.yourdomain.com/api/v1/generate"
    payload = {
        "prompt": "Explain the concept of machine learning in 100 words.",
        "max_tokens": 100,
        "model_type": "text",
    }
    
    print("Benchmarking Hermes API...")
    results = await benchmark_endpoint(url, payload, num_requests=50, concurrency=5)
    
    print("\nResults:")
    for key, value in results.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.4f}")
        else:
            print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
```

**Verification:**
```bash
# Run benchmark
cd code && python tests/profile_api.py
# Expected: Should show performance metrics
```

#### Step 10.5.2: Load Test with Locust
```python
# File: code/tests/locustfile.py
"""
Locust Load Test for Hermes API
"""

from locust import HttpUser, task, between
import random


class HermesUser(HttpUser):
    wait_time = between(0.5, 2.0)
    
    prompts = [
        "Explain the concept of machine learning.",
        "Write a Python function to sort a list.",
        "What is the capital of France?",
        "Write a haiku about programming.",
        "Explain quantum computing in simple terms.",
    ]
    
    @task(3)
    def generate_text(self):
        """Test /generate endpoint."""
        payload = {
            "prompt": random.choice(self.prompts),
            "max_tokens": random.randint(50, 200),
            "model_type": random.choice(["text", "code"]),
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer YOUR_TOKEN_HERE",
        }
        
        self.client.post("/api/v1/generate", json=payload, headers=headers)
    
    @task(1)
    def generate_batch(self):
        """Test /generate/batch endpoint."""
        requests = [
            {"prompt": f"Prompt {i}", "max_tokens": 50}
            for i in range(random.randint(2, 5))
        ]
        
        payload = {"requests": requests}
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer YOUR_TOKEN_HERE",
        }
        
        self.client.post("/api/v1/generate/batch", json=payload, headers=headers)
    
    @task(1)
    def list_models(self):
        """Test /models endpoint."""
        headers = {"Authorization": "Bearer YOUR_TOKEN_HERE"}
        self.client.get("/api/v1/models", headers=headers)
```

**Run Locust:**
```bash
# Install Locust
pip install locust

# Run load test
locust -f code/tests/locustfile.py \
  --host=https://api.yourdomain.com \
  --users=50 \
  --spawn-rate=10 \
  --headless \
  --run-time=5m \
  --html=load-test-report.html
```

**Verification:**
```bash
# Check load-test-report.html
# Expected: Should show detailed load test results
```

#### Step 10.5.3: Profile VCN Pipeline
```python
# File: code/vcn/profile_vcn.py
"""
Profile VCN-LUPINE Pipeline Performance
"""

import time
import numpy as np
from vcn_compute_substrate import VCNPipeline


def profile_compression():
    """Profile VCN compression pipeline."""
    # Generate test data (1 MB)
    raw_data = np.random.rand(256, 256, 16).astype(np.float32)  # ~1 MB
    
    pipeline = VCNPipeline()
    
    # Warm up
    for _ in range(5):
        pipeline.process(raw_data)
    
    # Benchmark
    num_iterations = 100
    times = []
    sizes = []
    
    for _ in range(num_iterations):
        start = time.time()
        compressed = pipeline.process(raw_data)
        elapsed = time.time() - start
        
        times.append(elapsed)
        sizes.append(len(compressed))
    
    print("VCN Pipeline Benchmark:")
    print(f"  Average time: {np.mean(times) * 1000:.2f} ms")
    print(f"  Min time: {np.min(times) * 1000:.2f} ms")
    print(f"  Max time: {np.max(times) * 1000:.2f} ms")
    print(f"  Average compressed size: {np.mean(sizes) / 1024:.2f} KB")
    print(f"  Compression ratio: {len(raw_data.tobytes()) / np.mean(sizes):.2f}x")


if __name__ == "__main__":
    profile_compression()
```

**Verification:**
```bash
cd code && python vcn/profile_vcn.py
# Expected: Should show VCN pipeline performance metrics
```

---

## Deliverables

### Files Created/Modified
- [ ] `kubernetes/autoscaling/ray-cpu-scaledobject.yaml`
- [ ] `kubernetes/autoscaling/ray-gpu-scaledobject.yaml`
- [ ] `kubernetes/autoscaling/hermes-scaledobject.yaml`
- [ ] `kubernetes/ray/raycluster.yaml` (updated for MPS)
- [ ] `code/actors/gguf_actors.py` (updated for quantization)
- [ ] `code/hermes/batching.py`
- [ ] `code/hermes/cache.py`
- [ ] `code/hermes/orchestrator.py` (updated for batching)
- [ ] `code/tests/test_gpu_sharing.py`
- [ ] `code/tests/profile_api.py`
- [ ] `code/tests/locustfile.py`
- [ ] `code/vcn/profile_vcn.py`

### Performance Optimizations Implemented
- [ ] KEDA auto-scaling for Ray workers and Hermes
- [ ] NVIDIA MPS for GPU sharing
- [ ] Model quantization (INT8, INT4)
- [ ] Request batching
- [ ] Redis caching
- [ ] Performance profiling scripts
- [ ] Load testing scripts

---

## Verification Checklist

### Auto-scaling
- [ ] KEDA is installed and running
- [ ] ScaledObjects are configured
- [ ] Scaling triggers work (CPU, memory, custom metrics)
- [ ] Min/max replica limits are respected

### GPU Sharing
- [ ] NVIDIA MPS is installed on GPU nodes
- [ ] Ray is configured to use MPS
- [ ] Multiple tasks can share GPU memory

### Model Quantization
- [ ] Quantized models are created
- [ ] Actors can load quantized models
- [ ] Quantized models produce acceptable results
- [ ] Memory usage is reduced

### Request Batching
- [ ] Batch queue is implemented
- [ ] Similar requests are grouped
- [ ] Batch processing is faster than individual

### Caching
- [ ] Redis cache is configured
- [ ] Cache decorator works
- [ ] Cache hit/miss ratios are good

### Profiling
- [ ] Performance benchmarks can be run
- [ ] Load tests can be run
- [ ] VCN pipeline can be profiled
- [ ] Results are documented

---

## Troubleshooting

### Auto-scaling Not Working

**Symptom:** ScaledObject shows "Active: False"

```bash
# Check KEDA logs
kubectl logs -n keda -l app=keda-operator

# Check ScaledObject status
kubectl describe scaledobject -n ray-system ray-cpu-workers

# Check metrics
kubectl get hpa -n ray-system
```

**Fix:** Verify metrics are being scraped and triggers are configured correctly

### MPS Not Working

**Symptom:** GPU tasks fail with memory errors

```bash
# Check MPS status
nvidia-smi

# Check Ray worker logs
kubectl logs -n ray-system ray-worker-xxxx | grep -i mps

# Check if MPS is enabled
cat /etc/nvidia/mps/mps-server/log/mps.log
```

**Fix:** Verify MPS is installed and configured correctly

### Quantized Model Issues

**Symptom:** Quantized models produce poor results

```bash
# Check quantization parameters
python -m llm -h

# Try different quantization levels
python -m llm -m model.gguf -o model-q8_0.gguf -q q8_0
python -m llm -m model.gguf -o model-q4_k_m.gguf -q q4_k_m
```

**Fix:** Try different quantization methods and compare results

### Caching Not Working

**Symptom:** Cache misses on repeated requests

```bash
# Check Redis connectivity
kubectl exec -n hermes -it hermes-xxxx -- redis-cli -h redis-service.ray-system.svc.cluster.local ping

# Check cache client
kubectl exec -n hermes -it hermes-xxxx -- python -c "
from hermes.cache import cache
import asyncio

async def test():
    await cache.connect()
    await cache.set('test', {'value': 123})
    result = await cache.get('test')
    print('Cache get:', result)

asyncio.run(test())
"
```

**Fix:** Verify Redis is accessible and cache keys are correct

---

## Rollback Plan

If Phase 10 fails:

1. **KEDA**: Uninstall KEDA
   ```bash
   helm uninstall keda -n keda
   kubectl delete ns keda
   ```

2. **MPS**: Disable MPS
   ```bash
   sudo systemctl stop nvidia-mps
   ```

3. **Quantization**: Revert to full-precision models
   ```bash
   # Remove quantized models
   rm /cache/models/*-INT*.gguf
   ```

4. **Caching**: Disable caching
   ```python
   # In code/hermes/cache.py
   self.enabled = False
   ```

---

## Next Phase

After completing Phase 10, proceed to **Phase 11: Documentation** to create comprehensive documentation for the entire system.
