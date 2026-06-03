# Phase 4: FrameDispatcher Integration

**Objective:** Route inference requests to appropriate GGUF actors.

**Duration:** 2-4 hours  
**Priority:** Critical (Required for Phase 5)  
**Dependencies:** Phase 1 (Ray cluster), Phase 3 (Actors)

---

## 🎯 Overview

FrameDispatcher is the central router that:
- Maps task types to appropriate GGUF actors
- Implements lazy actor loading (actors created on first request)
- Provides circuit breaker pattern for resilience
- Supports batch processing
- Includes Prometheus metrics

### Architecture

```
Hermes → FrameDispatcher → Ray Actors
    ↓
Request → Model Type Detection → Actor Selection → Inference
```

### Routing Rules

| Task Type | Model Type | Actor | Node |
|-----------|------------|-------|------|
| code | CODE_GENERATION | QwopusCoderActor | qfox-1 |
| analysis | CODE_ANALYSIS | DeepSeekCoderActor | qfox-1 |
| math | MATH | DeepSeekCoderActor | qfox-1 |
| vision | VISION | LlavaVisionActor | steamdeck |
| general | GENERAL | GemmaGeneralActor | neon-64gb |

---

## 📋 Microsteps

---

### 4.1 Create FrameDispatcher

**File:** [`frame_dispatcher.py`](frame_dispatcher.py)

**Key features:**
- ModelType enum for supported models
- ModelConfig dataclass for actor configuration
- MODEL_REGISTRY mapping task types to actors
- Lazy actor loading with caching
- Async dispatch with Ray ObjectRef
- Circuit breaker pattern
- Batch dispatch support

**Content highlights:**
```python
class ModelType(Enum):
    CODE_GENERATION = auto()
    CODE_ANALYSIS = auto()
    VISION = auto()
    GENERAL = auto()
    MATH = auto()

MODEL_REGISTRY = {
    ModelType.CODE_GENERATION: ModelConfig(
        actor_class="QwopusCoderActor",
        actor_module="coder_actor",
        resources={"node:qfox-1": 1, "gpu_type:CUDA": 1, "vcn_enabled": True},
        model_url="http://100.88.57.96:3900/models/Qwopus3.5-9B-Coder-MTP-Q4_K_M.gguf"
    ),
    # ... other models
}

class FrameDispatcher:
    @classmethod
    def _get_actor(cls, model_type: ModelType) -> ray.ObjectRef:
        if model_type not in ACTOR_INSTANCES:
            config = MODEL_REGISTRY[model_type]
            module = __import__(config.actor_module)
            actor_class = getattr(module, config.actor_class)
            actor = actor_class.options(resources=config.resources).remote()
            ACTOR_INSTANCES[model_type] = actor
        return ACTOR_INSTANCES[model_type]
    
    @classmethod
    @circuit(failure_threshold=3, recovery_timeout=60)
    async def dispatch(cls, model_type, prompt, images=None, **kwargs) -> ray.ObjectRef:
        actor = cls._get_actor(model_type)
        config = MODEL_REGISTRY[model_type]
        return await actor.generate.options(resources=config.resources).remote(
            prompt=prompt, images=images, **kwargs
        )
    
    @classmethod
    def determine_model_type(cls, task_type=None, model=None, images=None) -> ModelType:
        if model: return cls._string_to_model_type(model)
        if task_type: return cls._string_to_model_type(task_type)
        if images: return ModelType.VISION
        return ModelType.GENERAL
```

**Full file:** See [`frame_dispatcher.py`](frame_dispatcher.py)

---

### 4.2 Register Actors

**Already done in Step 4.1** - The MODEL_REGISTRY in FrameDispatcher contains:
- QwopusCoderActor (CODE_GENERATION)
- DeepSeekCoderActor (CODE_ANALYSIS, MATH)
- LlavaVisionActor (VISION)
- GemmaGeneralActor (GENERAL)

---

### 4.3 Test Routing

**Create test script:**

```python
# test_framedispatcher.py
import ray
import asyncio
from frame_dispatcher import FrameDispatcher, ModelType

async def test_dispatcher():
    ray.init(address='auto')
    
    # Test code generation
    print("Testing code generation...")
    ref = await FrameDispatcher.dispatch(
        model_type=ModelType.CODE_GENERATION,
        prompt="Write a Python function to reverse a string"
    )
    result = ray.get(ref)
    print(f"Code generation result: {result[:100]}...")
    
    # Test vision
    print("\nTesting vision...")
    ref = await FrameDispatcher.dispatch(
        model_type=ModelType.VISION,
        prompt="Describe this image",
        images=["https://example.com/image.jpg"]  # Replace with actual image
    )
    result = ray.get(ref)
    print(f"Vision result: {result[:100]}...")
    
    # Test general
    print("\nTesting general...")
    ref = await FrameDispatcher.dispatch(
        model_type=ModelType.GENERAL,
        prompt="What is the capital of France?"
    )
    result = ray.get(ref)
    print(f"General result: {result[:100]}...")
    
    ray.shutdown()

if __name__ == "__main__":
    asyncio.run(test_dispatcher())
```

**Run test:**
```bash
python test_framedispatcher.py
```

---

## ✅ Verification

### 4.3.1 Verify Model Registration

```bash
python -c "
from frame_dispatcher import FrameDispatcher
models = FrameDispatcher.list_models()
for name, info in models.items():
    print(f'{name}:')
    print(f'  Actor: {info[\"actor_class\"]}')
    print(f'  Resources: {info[\"resources\"]}')
    print(f'  Model URL: {info[\"model_url\"]}')
"
```

**Expected output:**
```
CODE_GENERATION:
  Actor: QwopusCoderActor
  Resources: {'node:qfox-1': 1, 'gpu_type:CUDA': 1, 'vcn_enabled': True}
  Model URL: http://100.88.57.96:3900/models/Qwopus3.5-9B-Coder-MTP-Q4_K_M.gguf
VISION:
  Actor: LlavaVisionActor
  Resources: {'node:steamdeck': 1, 'gpu_type:VAAPI': 1, 'vcn_enabled': True}
  Model URL: http://100.88.57.96:3900/models/Llava-1.5-7B-Q4_K_M.gguf
GENERAL:
  Actor: GemmaGeneralActor
  Resources: {'node:neon-64gb': 1, 'gpu_type:CPU': 1}
  Model URL: http://100.88.57.96:3900/models/Gemma-4-E4B-Uncensored-Q8_K_P.gguf
... (CODE_ANALYSIS, MATH)
```

### 4.3.2 Test Model Type Determination

```bash
python -c "
from frame_dispatcher import FrameDispatcher, ModelType

test_cases = [
    ({'task_type': 'code'}, ModelType.CODE_GENERATION),
    ({'task_type': 'vision'}, ModelType.VISION),
    ({'images': ['img.jpg']}, ModelType.VISION),
    ({}, ModelType.GENERAL),
    ({'model': 'Qwopus'}, ModelType.CODE_GENERATION)
]

for input_kwargs, expected in test_cases:
    result = FrameDispatcher.determine_model_type(**input_kwargs)
    status = '✓' if result == expected else '✗'
    print(f'{status} {input_kwargs} -> {result.name} (expected {expected.name})')
"
```

**Expected output:**
```
✓ {'task_type': 'code'} -> CODE_GENERATION (expected CODE_GENERATION)
✓ {'task_type': 'vision'} -> VISION (expected VISION)
✓ {'images': ['img.jpg']} -> VISION (expected VISION)
✓ {} -> GENERAL (expected GENERAL)
✓ {'model': 'Qwopus'} -> CODE_GENERATION (expected CODE_GENERATION)
```

### 4.3.3 Test Batch Dispatch

```bash
python -c "
import ray
import asyncio
from frame_dispatcher import FrameDispatcher

async def test_batch():
    ray.init(address='auto')
    
    requests = [
        {'prompt': 'Hello', 'task_type': 'general'},
        {'prompt': 'Write code', 'task_type': 'code'}
    ]
    
    refs = await FrameDispatcher.dispatch_batch(requests)
    print(f'Batch dispatched: {len(refs)} requests')
    
    for i, ref in enumerate(refs):
        result = ray.get(ref)
        print(f'Request {i}: {result[:50]}...')
    
    ray.shutdown()

asyncio.run(test_batch())
```

---

## 🔄 Rollback Plan

If routing fails:

```bash
# Reset actor cache
from frame_dispatcher import reset_actors
reset_actors()

# Kill all actors
from frame_dispatcher import kill_actors
kill_actors()

# Restart Ray
ray stop
ray start --head --port=6379
```

---

## 📊 Success Criteria

| Criteria | Status | Notes |
|----------|--------|-------|
| frame_dispatcher.py created | ⬜ | With all features |
| MODEL_REGISTRY configured | ⬜ | All 5 model types |
| Model type determination works | ⬜ | All test cases pass |
| Single dispatch works | ⬜ | Code, vision, general |
| Batch dispatch works | ⬜ | Multiple requests |
| Circuit breaker configured | ⬜ | failure_threshold=3 |

---

## 🚀 Next Phase

Once all criteria are met, proceed to **[Phase 5: Hermes Orchestrator](Phase-5-Hermes.md)**

---

## 📝 Notes

### Issues You Might Encounter

1. **Actor not found**
   - **Cause:** Actor class not in module
   - **Fix:** Check `actor_module` and `actor_class` in MODEL_REGISTRY

2. **Resource conflict**
   - **Cause:** Multiple actors trying to use same GPU
   - **Fix:** Check Ray resource allocation: `ray memory`

3. **Circuit breaker trips**
   - **Cause:** Too many failures
   - **Fix:** Check actor health: `from frame_dispatcher import list_actors`

### Useful Commands

```bash
# List actors
ray list-actors

# Check actor health
python -c "from frame_dispatcher import list_actors; print(list_actors())"

# Reset actors
python -c "from frame_dispatcher import reset_actors; reset_actors()"

# Test dispatch
python -c "
import ray
import asyncio
from frame_dispatcher import FrameDispatcher
asyncio.run(FrameDispatcher.dispatch(ModelType.GENERAL, 'Hello'))
"
```
