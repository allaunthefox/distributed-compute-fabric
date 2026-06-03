# Phase 5: Hermes Orchestrator

**Objective:** Enhance Hermes to route requests to FrameDispatcher.

**Duration:** 2-4 hours  
**Priority:** Critical (User-facing API)  
**Dependencies:** Phase 1 (Ray), Phase 3 (Actors), Phase 4 (FrameDispatcher)

---

## 🎯 Overview

Hermes is the REST API layer that:
- Accepts HTTP requests from users
- Routes to FrameDispatcher for model selection
- Returns JSON responses
- Provides health checks and monitoring

### Architecture

```
User → Hermes (FastAPI:8000) → FrameDispatcher (Ray) → GGUF Actors
```

### Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/generate` | Single inference request |
| POST | `/generate/batch` | Batch inference requests |
| GET | `/models` | List available models |
| GET | `/health` | Health check |
| GET | `/status` | Detailed status |
| GET | `/metrics` | Prometheus metrics |

---

## 📋 Microsteps

---

### 5.1 Update Hermes Orchestrator

**File:** [`hermes/orchestrator.py`](hermes/orchestrator.py)

**Key features:**
- FastAPI application with Pydantic models
- Smart routing based on task_type
- Async request handling
- Request validation
- Prometheus metrics integration
- Circuit breaker support
- Health checks

**Content highlights:**
```python
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
import ray

app = FastAPI(title="Hermes Orchestrator")

class TaskType(str, Enum):
    CODE = "code"
    VISION = "vision"
    GENERAL = "general"
    MATH = "math"
    ANALYSIS = "analysis"

class GenerationRequest(BaseModel):
    prompt: str
    task_type: Optional[TaskType] = None
    images: Optional[List[str]] = None
    max_tokens: int = 256
    temperature: float = 0.7
    top_p: float = 0.9
    model: Optional[str] = None

@app.post("/generate")
async def generate(request: GenerationRequest, req: Request):
    from frame_dispatcher import FrameDispatcher
    
    model_type = FrameDispatcher.determine_model_type(
        task_type=request.task_type,
        model=request.model,
        images=request.images
    )
    
    result_ref = await FrameDispatcher.dispatch(
        model_type=model_type,
        prompt=request.prompt,
        images=request.images,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        top_p=request.top_p
    )
    
    result = ray.get(result_ref)
    return {"result": result, "model_type": model_type.name}

@app.get("/health")
async def health():
    ray_nodes = ray.list_nodes()
    return {"status": "healthy" if len(ray_nodes) > 0 else "unhealthy"}
```

**Full file:** See [`hermes/orchestrator.py`](hermes/orchestrator.py)

---

### 5.2 Create Hermes Dockerfile

**File:** [`hermes/Dockerfile`](hermes/Dockerfile)

**Content:**
```dockerfile
FROM ghcr.io/youruser/gguf-ray:latest

WORKDIR /app

COPY hermes/ /app/hermes/

RUN pip install --no-cache-dir fastapi[all] uvicorn[standard] python-multipart

ENV RAY_ADDRESS=auto
ENV HERMES_ENV=production
ENV HERMES_LOG_LEVEL=INFO

EXPOSE 8000  # HTTP API
EXPOSE 8001  # Prometheus metrics

CMD ["uvicorn", "hermes.orchestrator:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

**Full file:** See [`hermes/Dockerfile`](hermes/Dockerfile)

---

### 5.3 Deploy Hermes

**Apply Kubernetes manifests:**

```bash
# Apply deployment
kubectl apply -f hermes-deployment.yaml -n services

# Apply service
kubectl apply -f hermes-service.yaml -n services

# Wait for Hermes to be ready
kubectl wait --for=condition=Ready pod -l app=hermes -n services --timeout=5m
```

---

## ✅ Verification

### 5.3.1 Check Hermes Pod

```bash
# Check pod status
kubectl get pods -n services -l app=hermes

# Check logs
kubectl logs -l app=hermes -n services --tail=20

# Expected output:
# ========================================================================
# Starting Hermes Orchestrator v1.0.0
# ========================================================================
# Initializing Ray...
# Ray initialized
# Prometheus metrics server started on port 8001
# Pre-warming actors...
# Pre-warmed CODE_GENERATION actor
# Pre-warmed VISION actor
# ...
# Startup complete
```

### 5.3.2 Test Endpoints

```bash
# Port-forward Hermes
kubectl port-forward svc/hermes 8000:8000 -n services &

# Test health endpoint
curl http://localhost:8000/health | jq

# Expected output:
# {
#   "status": "healthy",
#   "version": "1.0.0",
#   "timestamp": "2026-06-01T12:00:00Z",
#   "ray_status": {"nodes": 4, "actors": 0, "initialized": true},
#   "models": {}
# }

# Test models endpoint
curl http://localhost:8000/models | jq

# Expected output:
# {
#   "models": {
#     "CODE_GENERATION": {...},
#     "VISION": {...},
#     ...
#   },
#   "default": "GENERAL",
#   "count": 5
# }
```

### 5.3.3 Test Generate Endpoint

```bash
# Test code generation
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Write a Python function to reverse a string", "task_type": "code"}' | jq

# Expected output:
# {
#   "request_id": "abc123...",
#   "model_type": "CODE_GENERATION",
#   "task_type": "code",
#   "prompt": "Write a Python function to reverse a string",
#   "result": "def reverse_string(s):\n    return s[::-1]",
#   "tokens_generated": 15,
#   "latency_ms": 1234.56,
#   "status": "success",
#   "timestamp": "2026-06-01T12:00:00Z"
# }

# Test general text
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is the capital of France?", "task_type": "general"}' | jq

# Test batch
curl -X POST http://localhost:8000/generate/batch \
  -H "Content-Type: application/json" \
  -d '{"requests": [{"prompt": "Hello", "task_type": "general"}, {"prompt": "Write code", "task_type": "code"}]}' | jq
```

---

## 🔄 Rollback Plan

If deployment fails:

```bash
# Check logs
kubectl logs -l app=hermes -n services

# Delete deployment
kubectl delete -f hermes-deployment.yaml -n services

# Reapply with changes
kubectl apply -f hermes-deployment.yaml -n services
```

---

## 📊 Success Criteria

| Criteria | Status | Notes |
|----------|--------|-------|
| hermes/orchestrator.py created | ⬜ | All endpoints implemented |
| hermes/Dockerfile created | ⬜ | Based on gguf-ray image |
| Hermes pod running | ⬜ | `kubectl get pods` |
| Health endpoint works | ⬜ | Returns "healthy" |
| Models endpoint works | ⬜ | Returns model list |
| Generate endpoint works | ⬜ | Returns inference result |
| Batch endpoint works | ⬜ | Returns multiple results |

---

## 🚀 Next Phase

Once all criteria are met, proceed to **[Phase 6: Networking](Phase-6-Networking.md)**

---

## 📝 Notes

### Issues You Might Encounter

1. **Pod crashes**
   - **Cause:** Missing dependencies
   - **Fix:** Check logs: `kubectl logs <hermes-pod>`

2. **Import errors**
   - **Cause:** FrameDispatcher not found
   - **Fix:** Ensure frame_dispatcher.py is in PYTHONPATH

3. **Ray connection errors**
   - **Cause:** Ray not running or address wrong
   - **Fix:** Check RAY_ADDRESS env var

4. **Port conflicts**
   - **Cause:** Port 8000 already in use
   - **Fix:** Change port in orchestrator.py

### Useful Commands

```bash
# Check pod status
kubectl get pods -n services -l app=hermes

# Check logs
kubectl logs -l app=hermes -n services -f

# Check port-forward
kubectl port-forward svc/hermes 8000:8000 -n services

# Check service
kubectl get svc hermes -n services -o yaml

# Test endpoints
curl http://localhost:8000/health
curl http://localhost:8000/models
curl -X POST http://localhost:8000/generate -H "Content-Type: application/json" -d '{"prompt": "Hello"}'
```
