# Phase 3: GGUF Ray Actors

**Objective:** Implement base and specialized GGUF inference actors.

**Duration:** 4-8 hours  
**Priority:** Critical (Core inference functionality)  
**Dependencies:** Phase 1 (Ray cluster), Phase 2 (Docker image)

---

## 🎯 Overview

Create Ray actors that:
- Load GGUF models from Garage S3
- Perform inference via llama.cpp
- Integrate with VCN-LUPINE for hardware acceleration
- Support async processing via Ray ObjectRef
- Include health checks and auto-recovery

### Actors to Create

| Actor | Model | Node | Purpose | Acceleration |
|-------|-------|------|---------|--------------|
| QwopusCoderActor | Qwopus3.5-9B | qfox-1 | Code generation | CUDA + VCN |
| LlavaVisionActor | Llava-1.5-7B | steamdeck | Vision tasks | VAAPI + VCN |
| GemmaGeneralActor | Gemma-4-E4B | neon-64gb | General text | CPU |
| DeepSeekCoderActor | DeepSeek-Coder | qfox-1 | Code analysis | CUDA + VCN |

---

## 📋 Microsteps

---

### 3.1 Create Base GGUF Actor

**File:** [`gguf_actors.py`](gguf_actors.py)

**Key features:**
- Base class for all GGUF actors
- Automatic model download from remote URLs
- Model caching to `/tmp/gguf-models`
- Async inference with Ray ObjectRef
- Health checks with auto-recovery
- Prometheus metrics
- Support for text and vision models

**Content highlights:**
```python
@ray.remote
class GGUFInferenceActor:
    def __init__(self, model_path, model_type, context_length, gpu_layers, threads):
        # Download model from Garage S3 or HTTP
        self.model_path = self._download_model(model_path)
        
        # Load model with llama.cpp
        self.model = llm.load(
            model=self.model_path,
            n_ctx=context_length,
            n_threads=threads,
            n_gpu_layers=gpu_layers
        )
        
        # Start background health check
        self._start_background_health_check()
    
    async def generate(self, prompt, images=None, max_tokens=256, temperature=0.7):
        # Build multimodal prompt for vision models
        if self.model_type == "vision" and images:
            prompt = self._build_multimodal_prompt(prompt, images)
        
        # Generate with timing and metrics
        result = self.model(prompt, max_tokens=max_tokens, temperature=temperature)
        return result
    
    def check_health(self):
        # Test with small prompt
        result = self.model("Health check", max_tokens=5)
        return "ok" in result.lower()
```

**Full file:** See [`gguf_actors.py`](gguf_actors.py)

---

### 3.2 Create Qwopus Coder Actor

**File:** [`coder_actor.py`](coder_actor.py)

**Purpose:** Code generation (Qwopus3.5-9B-Coder-MTP)

**Content:**
```python
@ray.remote(
    name="QwopusCoderActor",
    resources={
        "node:qfox-1": 1,
        "gpu_type:CUDA": 1,
        "vcn_enabled": True
    },
    runtime_env={
        "env_vars": {
            "LD_PRELOAD": "/usr/local/lib/vcn-lupine.so"
        }
    }
)
class QwopusCoderActor(GGUFInferenceActor):
    def __init__(self):
        super().__init__(
            model_path="http://100.88.57.96:3900/models/Qwopus3.5-9B-Coder-MTP-Q4_K_M.gguf",
            model_type="text",
            context_length=32768,
            gpu_layers=40,
            threads=4
        )
```

**Full file:** See [`coder_actor.py`](coder_actor.py)

---

### 3.3 Create Llava Vision Actor

**File:** [`vision_actor.py`](vision_actor.py)

**Purpose:** Vision tasks (Llava-1.5-7B)

**Content:**
```python
@ray.remote(
    name="LlavaVisionActor",
    resources={
        "node:steamdeck": 1,
        "gpu_type:VAAPI": 1,
        "vcn_enabled": True
    },
    runtime_env={
        "env_vars": {
            "LD_PRELOAD": "/usr/local/lib/vcn-lupine.so",
            "LIBVA_DRIVER_NAME": "iHD",
            "LIBVA_DRIVERS_PATH": "/usr/lib/x86_64-linux-gnu/dri"
        }
    }
)
class LlavaVisionActor(GGUFInferenceActor):
    def __init__(self):
        super().__init__(
            model_path="http://100.88.57.96:3900/models/Llava-1.5-7B-Q4_K_M.gguf",
            model_type="vision",
            context_length=32768,
            gpu_layers=35,
            threads=4
        )
```

**Full file:** See [`vision_actor.py`](vision_actor.py)

---

### 3.4 Create Gemma General Actor

**File:** [`general_actor.py`](general_actor.py)

**Purpose:** General text (Gemma-4-E4B-Uncensored)

**Content:**
```python
@ray.remote(
    name="GemmaGeneralActor",
    resources={
        "node:neon-64gb": 1,
        "gpu_type:CPU": 1
    },
    runtime_env={
        "env_vars": {
            "LD_PRELOAD": "/usr/local/lib/vcn-lupine.so",
            "OMP_NUM_THREADS": "16",
            "NUMA": "true"
        }
    }
)
class GemmaGeneralActor(GGUFInferenceActor):
    def __init__(self):
        super().__init__(
            model_path="http://100.88.57.96:3900/models/Gemma-4-E4B-Uncensored-Q8_K_P.gguf",
            model_type="text",
            context_length=32768,
            gpu_layers=None,  # CPU-only
            threads=16,
            llm_kwargs={
                "numa": True,
                "batch_size": 512
            }
        )
```

**Full file:** See [`general_actor.py`](general_actor.py)

---

## ✅ Verification

### 3.4.1 Test Actor Creation

```bash
# Start Ray (if not already running)
ray start --head --port=6379

# Test Qwopus actor creation
python -c "
import ray
from coder_actor import QwopusCoderActor

actor = QwopusCoderActor.options(
    resources={'node:qfox-1': 1, 'gpu_type:CUDA': 1}
).remote()
print(f'QwopusCoderActor created: {actor}')
"

# Test Llava actor creation
python -c "
import ray
from vision_actor import LlavaVisionActor

actor = LlavaVisionActor.options(
    resources={'node:steamdeck': 1, 'gpu_type:VAAPI': 1}
).remote()
print(f'LlavaVisionActor created: {actor}')
"

# Test Gemma actor creation
python -c "
import ray
from general_actor import GemmaGeneralActor

actor = GemmaGeneralActor.options(
    resources={'node:neon-64gb': 1}
).remote()
print(f'GemmaGeneralActor created: {actor}')
"
```

**Expected output:**
```
QwopusCoderActor created: QwopusCoderActor__(id=abc123...)
LlavaVisionActor created: LlavaVisionActor__(id=def456...)
GemmaGeneralActor created: GemmaGeneralActor__(id=ghi789...)
```

### 3.4.2 Test Inference

```bash
# Test Qwopus code generation
python -c "
import ray
from coder_actor import create_qwopus_actor
import time

# Create actor
actor = create_qwopus_actor()
print(f'Created actor: {actor}')

# Wait for model to load (30-60 seconds)
print('Waiting for model to load...')
time.sleep(45)

# Test generation
result_ref = actor.generate.remote('Write a Python function to reverse a string')
result = ray.get(result_ref, timeout=120)
print(f'Result: {result[:200]}...')
"
```

**Expected output:**
```
Created actor: QwopusCoderActor__(id=abc123...)
Waiting for model to load...
Result: def reverse_string(s):
    return s[::-1]...
```

### 3.4.3 Check Actor Status

```bash
# List all Ray actors
ray list-actors

# Get actor status
python -c "
import ray
from frame_dispatcher import list_actors
actors = list_actors()
for name, status in actors.items():
    print(f'{name}: {status}')
"
```

---

## 🔄 Rollback Plan

If actors fail to load:

```bash
# Kill all actors
from frame_dispatcher import kill_actors
kill_actors()

# Reset actor cache
from frame_dispatcher import reset_actors
reset_actors()

# Check model download
kubectl exec -it <ray-worker-pod> -n services -- ls -la /tmp/gguf-models/

# Clear model cache
kubectl exec -it <ray-worker-pod> -n services -- rm -rf /tmp/gguf-models/*
```

---

## 📊 Success Criteria

| Criteria | Status | Notes |
|----------|--------|-------|
| gguf_actors.py created | ⬜ | Base class with all features |
| coder_actor.py created | ⬜ | Qwopus3.5-9B specialization |
| vision_actor.py created | ⬜ | Llava-1.5-7B specialization |
| general_actor.py created | ⬜ | Gemma-4-E4B specialization |
| All actors instantiate | ⬜ | No errors on creation |
| Model downloads work | ⬜ | From Garage S3 |
| Inference works (test) | ⬜ | Sample generation succeeds |

---

## 🚀 Next Phase

Once all criteria are met, proceed to **[Phase 4: FrameDispatcher](Phase-4-FrameDispatcher.md)**

---

## 📝 Notes

### Issues You Might Encounter

1. **Model download fails**
   - **Cause:** Garage S3 not accessible
   - **Fix:** Verify S3 endpoint: `curl -v http://100.88.57.96:3900/models/`

2. **OOM errors**
   - **Cause:** Model too large for available memory
   - **Fix:** Reduce `gpu_layers` or use smaller quantization

3. **CUDA errors on qfox-1**
   - **Cause:** NVIDIA drivers not available in container
   - **Fix:** Mount NVIDIA libraries: `/usr/lib/x86_64-linux-gnu/libnvidia-ml.so`

4. **VAAPI errors on steamdeck**
   - **Cause:** VAAPI drivers not available
   - **Fix:** Mount `/dev/dri` and set `LIBVA_DRIVER_NAME`

5. **ARM64 import errors**
   - **Cause:** Wrong Python wheel for ARM64
   - **Fix:** Use `--platform linux/arm64` in pip install

### Resource Allocation

| Actor | Model | VRAM/CPU | Node | Allocation |
|-------|-------|----------|------|------------|
| QwopusCoderActor | Qwopus3.5-9B | 7GB VRAM | qfox-1 | 15GB/16GB |
| LlavaVisionActor | Llava-1.5-7B | 8GB VRAM | steamdeck | 8GB/16GB |
| GemmaGeneralActor | Gemma-4-E4B | 10GB CPU | neon-64gb | 10GB/56GB |
| DeepSeekCoderActor | DeepSeek-Coder | 8GB VRAM | qfox-1 | 15GB/16GB |

### Useful Commands

```bash
# List actors
ray list-actors

# Get actor details
ray get-actor <actor-id>

# Kill actor
ray kill <actor-id>

# Get actor logs
ray logs <actor-id>

# Test model loading
python -c "import llm; model = llm.load('/path/to/model.gguf')"

# Check GPU memory
kubectl exec -it <pod-on-qfox-1> -- nvidia-smi
```
