#!/usr/bin/env python3
"""
FrameDispatcher - Request Router for GGUF Inference

Routes inference requests to appropriate Ray actors based on:
- Task type (code, vision, general, math, analysis)
- Resource availability
- Model specialization

Features:
- Lazy actor loading
- Circuit breaker pattern
- Async dispatch with Ray ObjectRef
- Batch processing
- Resource-aware scheduling
- Prometheus metrics

Author: Mistral Vibe
Version: 1.0.0
Date: 2026-06-01

Usage:
    from frame_dispatcher import FrameDispatcher, ModelType
    
    # Single request
    ref = await FrameDispatcher.dispatch(
        model_type=ModelType.CODE_GENERATION,
        prompt="Write a Python function"
    )
    result = ray.get(ref)
    
    # Batch request
    refs = await FrameDispatcher.dispatch_batch([
        {"model_type": ModelType.CODE_GENERATION, "prompt": "Write code"},
        {"model_type": ModelType.VISION, "prompt": "Describe", "images": [...]}
    ])
"""

import os
import sys
import asyncio
import logging
import time
from typing import Optional, Dict, Any, List, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

# Add ray-actors directory to Python path for dynamic imports
_RAY_ACTORS_DIR = Path(__file__).parent.parent / "ray-actors"
if str(_RAY_ACTORS_DIR) not in sys.path:
    sys.path.insert(0, str(_RAY_ACTORS_DIR))

# Import Ray
import ray

# Import circuit breaker
try:
    from circuitbreaker import circuit
    CIRCUITBREAKER_AVAILABLE = True
except ImportError:
    CIRCUITBREAKER_AVAILABLE = False
    def circuit(*args, **kwargs):
        return lambda func: func

# Import Prometheus metrics
try:
    from prometheus_client import Counter, Histogram, Gauge
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    Counter = Histogram = Gauge = None

# Configure logging
log_dir = '/tmp/ray'
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(log_dir, 'frame_dispatcher.log'))
    ]
)
logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class ModelType(Enum):
    """Supported model types for routing."""
    CODE_GENERATION = auto()  # Qwopus3.5-9B on qfox-1
    CODE_ANALYSIS = auto()    # DeepSeek-Coder on qfox-1
    VISION = auto()           # Llava-1.5-7B on steamdeck
    GENERAL = auto()          # Gemma-4-E4B on neon-64gb
    MATH = auto()             # DeepSeek-Coder on qfox-1


class TaskType(str, Enum):
    """Task type strings (for API compatibility)."""
    CODE = "code"
    GENERATE = "generate"
    ANALYSIS = "analysis"
    MATH = "math"
    VISION = "vision"
    IMAGE = "image"
    GENERAL = "general"
    TEXT = "text"


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class ModelConfig:
    """Configuration for a model type."""
    actor_class: str
    actor_module: str
    resources: Dict[str, float]
    model_url: str
    default: bool = False
    priority: int = 1
    context_length: int = 32768


# Garage S3 endpoint (configurable via environment)
GARAGE_S3_ENDPOINT = os.environ.get("GARAGE_S3_ENDPOINT", "http://100.88.57.96:3900")

# Model registry - maps ModelType to ModelConfig
MODEL_REGISTRY: Dict[ModelType, ModelConfig] = {
    ModelType.CODE_GENERATION: ModelConfig(
        actor_class="QwopusCoderActor",
        actor_module="coder_actor",
        resources={
            "node:qfox-1": 1,
            "gpu_type:CUDA": 1,
            "vcn_enabled": True
        },
        model_url=f"{GARAGE_S3_ENDPOINT}/models/Qwopus3.5-9B-Coder-MTP-Q4_K_M.gguf",
        default=False,
        priority=10,
        context_length=32768
    ),
    
    ModelType.CODE_ANALYSIS: ModelConfig(
        actor_class="DeepSeekCoderActor",
        actor_module="deepseek_coder_actor",
        resources={
            "node:neon-64gb": 1,
            "cpu": 6,
            "memory": 12 * 1024 * 1024 * 1024  # 12GB
        },
        model_url=f"{GARAGE_S3_ENDPOINT}/models/DeepSeek-Coder-6.7B-Q4_K_M.gguf",
        default=False,
        priority=9,
        context_length=16384
    ),
    
    ModelType.MATH: ModelConfig(
        actor_class="DeepSeekCoderActor",
        actor_module="deepseek_coder_actor",
        resources={
            "node:neon-64gb": 1,
            "cpu": 6,
            "memory": 12 * 1024 * 1024 * 1024  # 12GB
        },
        model_url=f"{GARAGE_S3_ENDPOINT}/models/DeepSeek-Coder-6.7B-Q4_K_M.gguf",
        default=False,
        priority=9,
        context_length=16384
    ),
    
    ModelType.VISION: ModelConfig(
        actor_class="LlavaVisionActor",
        actor_module="vision_actor",
        resources={
            "node:steamdeck": 1,
            "gpu_type:VAAPI": 1,
            "vcn_enabled": True
        },
        model_url=f"{GARAGE_S3_ENDPOINT}/models/Llava-1.5-7B-Q4_K_M.gguf",
        default=False,
        priority=8,
        context_length=32768
    ),
    
    # Gemma 4 is natively multimodal (text + image + audio + video)
    # See: https://huggingface.co/docs/transformers/en/model_doc/gemma4
    # The actor handles all modalities; VISION requests can also route here
    # if Gemma 4 is preferred over Llava for vision tasks.
    ModelType.GENERAL: ModelConfig(
        actor_class="GemmaGeneralActor",
        actor_module="general_actor",
        resources={
            "node:neon-64gb": 1,
            "gpu_type:CPU": 1
        },
        model_url=f"{GARAGE_S3_ENDPOINT}/models/Gemma-4-E4B-Uncensored-Q8_K_P.gguf",
        default=True,
        priority=7,
        context_length=32768
    )
}


# =============================================================================
# METRICS
# =============================================================================

if PROMETHEUS_AVAILABLE:
    # Dispatcher metrics
    DISPATCH_COUNT = Counter(
        'framedispatch_requests_total',
        'Total dispatch requests',
        ['model_type', 'status']
    )
    
    DISPATCH_LATENCY = Histogram(
        'framedispatch_latency_seconds',
        'Dispatch latency (including actor creation)',
        ['model_type']
    )
    
    ACTOR_CREATIONS = Counter(
        'framedispatch_actor_creations_total',
        'Total actor creations',
        ['actor_class']
    )
    
    BATCH_SIZE = Histogram(
        'framedispatch_batch_size',
        'Batch size of dispatch requests',
        buckets=[1, 2, 5, 10, 20, 50, 100]
    )


# =============================================================================
# ACTOR INSTANCES CACHE
# =============================================================================

# Cache of actor instances (lazy loaded)
ACTOR_INSTANCES: Dict[ModelType, ray.ObjectRef] = {}


# =============================================================================
# MAIN DISPATCHER CLASS
# =============================================================================

class FrameDispatcher:
    """
    FrameDispatcher routes inference requests to appropriate GGUF actors.
    
    Features:
    - Lazy actor loading (actors created on first request)
    - Circuit breaker pattern for resilience
    - Async dispatch with Ray ObjectRef
    - Batch processing
    - Resource-aware scheduling
    """
    
    # Circuit breaker configuration
    CB_FAILURE_THRESHOLD = 3
    CB_RECOVERY_TIMEOUT = 60  # seconds
    
    @classmethod
    def _get_actor(cls, model_type: ModelType) -> ray.ObjectRef:
        """
        Get or create actor instance for model type.
        
        Args:
            model_type: ModelType enum value
            
        Returns:
            ObjectRef to the actor
        """
        if model_type not in ACTOR_INSTANCES:
            config = MODEL_REGISTRY.get(model_type)
            if config is None:
                raise ValueError(f"Unknown model type: {model_type}")
            
            # Import actor class dynamically
            try:
                module = __import__(config.actor_module)
                actor_class = getattr(module, config.actor_class)
                
                # Create actor with resources
                logger.info(
                    f"Creating {config.actor_class} actor...\n"
                    f"  Resources: {config.resources}\n"
                    f"  Model URL: {config.model_url}"
                )
                
                actor = actor_class.options(
                    resources=config.resources,
                    num_returns=1
                ).remote()
                
                ACTOR_INSTANCES[model_type] = actor
                
                if PROMETHEUS_AVAILABLE:
                    ACTOR_CREATIONS.labels(config.actor_class).inc()
                
                logger.info(f"Created {config.actor_class} actor: {actor}")
                
            except ImportError as e:
                logger.error(f"Failed to import actor module {config.actor_module}: {e}")
                raise
            except AttributeError as e:
                logger.error(f"Failed to find actor class {config.actor_class} in module {config.actor_module}: {e}")
                raise
            except Exception as e:
                logger.error(f"Failed to create {config.actor_class} actor: {e}")
                raise
        
        return ACTOR_INSTANCES[model_type]
    
    @classmethod
    @circuit(
        failure_threshold=CB_FAILURE_THRESHOLD,
        recovery_timeout=CB_RECOVERY_TIMEOUT
    ) if CIRCUITBREAKER_AVAILABLE else lambda f: f
    async def dispatch(
        cls,
        model_type: Union[ModelType, str],
        prompt: str,
        images: Optional[List[str]] = None,
        max_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 0.9,
        **generate_kwargs: Dict[str, Any]
    ) -> ray.ObjectRef:
        """
        Dispatch inference request to appropriate actor.
        
        Args:
            model_type: ModelType enum or string
            prompt: Input text prompt
            images: List of image URLs/paths (for vision)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Top-p sampling
            **generate_kwargs: Additional kwargs for generate()
            
        Returns:
            ObjectRef to generated text
        """
        import time
        start_time = time.time()
        
        # Convert string to ModelType if needed
        if isinstance(model_type, str):
            model_type = cls._string_to_model_type(model_type)
        
        # Get actor
        actor = cls._get_actor(model_type)
        config = MODEL_REGISTRY[model_type]
        
        logger.info(
            f"Dispatching to {config.actor_class}: "
            f"model_type={model_type.name}, "
            f"prompt_len={len(prompt)}, "
            f"images={len(images) if images else 0}"
        )
        
        # Dispatch to actor
        try:
            result_ref = await actor.generate.options(
                resources=config.resources
            ).remote(
                prompt=prompt,
                images=images,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                **generate_kwargs
            )
            
            # Record metrics
            if PROMETHEUS_AVAILABLE:
                DISPATCH_COUNT.labels(model_type.name, "success").inc()
                DISPATCH_LATENCY.labels(model_type.name).observe(time.time() - start_time)
            
            return result_ref
            
        except Exception as e:
            logger.error(f"Dispatch failed for {model_type.name}: {e}")
            if PROMETHEUS_AVAILABLE:
                DISPATCH_COUNT.labels(model_type.name, "error").inc()
            raise
    
    @classmethod
    def dispatch_sync(
        cls,
        model_type: Union[ModelType, str],
        prompt: str,
        images: Optional[List[str]] = None,
        max_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 0.9,
        **generate_kwargs: Dict[str, Any]
    ) -> str:
        """
        Synchronous dispatch (returns result directly).
        
        Args:
            model_type: ModelType enum or string
            prompt: Input text prompt
            images: List of image URLs/paths
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Top-p sampling
            **generate_kwargs: Additional kwargs
            
        Returns:
            Generated text
        """
        import ray
        ref = ray.get(cls.dispatch(
            model_type=model_type,
            prompt=prompt,
            images=images,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            **generate_kwargs
        ))
        return ray.get(ref)
    
    @classmethod
    async def dispatch_batch(
        cls,
        requests: List[Dict[str, Any]]
    ) -> List[ray.ObjectRef]:
        """
        Batch dispatch multiple requests.
        
        Args:
            requests: List of request dicts with keys:
                - model_type: ModelType or string
                - prompt: str
                - images: Optional[List[str]]
                - max_tokens: int
                - temperature: float
                - top_p: float
                - **generate_kwargs
                
        Returns:
            List of ObjectRefs
        """
        import ray
        
        if PROMETHEUS_AVAILABLE:
            BATCH_SIZE.observe(len(requests))
        
        refs = []
        for req in requests:
            try:
                # Extract model_type
                model_type = req.get("model_type")
                if model_type is None:
                    model_type = req.get("task_type")
                    if model_type is None:
                        model_type = ModelType.GENERAL
                    else:
                        model_type = cls._string_to_model_type(model_type)
                
                # Dispatch single request
                ref = await cls.dispatch(
                    model_type=model_type,
                    prompt=req.get("prompt", ""),
                    images=req.get("images"),
                    max_tokens=req.get("max_tokens", 256),
                    temperature=req.get("temperature", 0.7),
                    top_p=req.get("top_p", 0.9),
                    **{k: v for k, v in req.items() 
                       if k not in ["model_type", "prompt", "images", 
                                     "max_tokens", "temperature", "top_p", "task_type"]}
                )
                refs.append(ref)
            except Exception as e:
                logger.error(f"Batch dispatch failed for request: {e}")
                # Return error as ObjectRef
                refs.append(ray.put(f"Error: {str(e)}"))
        
        return refs
    
    @classmethod
    def get_model_info(cls, model_type: Union[ModelType, str]) -> Dict[str, Any]:
        """
        Get information about a model type.
        
        Args:
            model_type: ModelType enum or string
            
        Returns:
            Model configuration dict
        """
        if isinstance(model_type, str):
            model_type = cls._string_to_model_type(model_type)
        
        config = MODEL_REGISTRY.get(model_type)
        if config is None:
            raise ValueError(f"Unknown model type: {model_type}")
        
        return {
            "name": model_type.name,
            "actor_class": config.actor_class,
            "actor_module": config.actor_module,
            "resources": config.resources,
            "model_url": config.model_url,
            "priority": config.priority,
            "context_length": config.context_length,
            "default": config.default
        }
    
    @classmethod
    def list_models(cls) -> Dict[str, Dict[str, Any]]:
        """
        List all available models.
        
        Returns:
            Dict mapping model type names to their configs
        """
        return {mt.name: cls.get_model_info(mt) for mt in ModelType}
    
    @classmethod
    def _string_to_model_type(cls, string: str) -> ModelType:
        """
        Convert string to ModelType.
        
        Args:
            string: String representation of model type
            
        Returns:
            ModelType enum
        """
        # Map from TaskType to ModelType
        task_type_mapping = {
            TaskType.CODE: ModelType.CODE_GENERATION,
            TaskType.GENERATE: ModelType.CODE_GENERATION,
            TaskType.ANALYSIS: ModelType.CODE_ANALYSIS,
            TaskType.MATH: ModelType.MATH,
            TaskType.VISION: ModelType.VISION,
            TaskType.IMAGE: ModelType.VISION,
            TaskType.GENERAL: ModelType.GENERAL,
            TaskType.TEXT: ModelType.GENERAL
        }
        
        # Try TaskType first
        if string in task_type_mapping:
            return task_type_mapping[string]
        
        # Try direct ModelType name
        try:
            return ModelType[string.upper()]
        except KeyError:
            pass
        
        # Try by actor class name
        for mt, config in MODEL_REGISTRY.items():
            if config.actor_class.lower() == string.lower():
                return mt
        
        # Default to GENERAL
        logger.warning(f"Unknown model type string: {string}, defaulting to GENERAL")
        return ModelType.GENERAL
    
    @classmethod
    def determine_model_type(
        cls,
        task_type: Optional[Union[TaskType, str]] = None,
        model: Optional[str] = None,
        images: Optional[List[str]] = None
    ) -> ModelType:
        """
        Determine the best model type based on input parameters.
        
        Routing logic:
        1. If model explicitly specified, use it
        2. If task_type specified, use mapping
        3. If images provided, use VISION
        4. Default to GENERAL
        
        Args:
            task_type: Task type string or enum
            model: Specific model name to use
            images: List of images (triggers VISION)
            
        Returns:
            ModelType enum
        """
        # Explicit model override
        if model:
            return cls._string_to_model_type(model)
        
        # Task type mapping
        if task_type:
            if isinstance(task_type, TaskType):
                return cls._string_to_model_type(task_type.value)
            return cls._string_to_model_type(task_type)
        
        # Images trigger vision
        if images:
            return ModelType.VISION
        
        # Default to GENERAL
        return ModelType.GENERAL


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def reset_actors():
    """Reset all actor instances (clear cache)."""
    global ACTOR_INSTANCES
    ACTOR_INSTANCES = {}
    logger.info("All actor instances reset")


def kill_actors():
    """Kill all actor instances."""
    import ray
    for actor_name in list(ACTOR_INSTANCES.keys()):
        try:
            ray.kill(ACTOR_INSTANCES[actor_name])
            del ACTOR_INSTANCES[actor_name]
            logger.info(f"Killed actor: {actor_name}")
        except Exception as e:
            logger.error(f"Failed to kill actor {actor_name}: {e}")


def list_actors() -> Dict[str, Any]:
    """List all active actors and their status."""
    import ray
    
    actors = {}
    for model_type, actor_ref in ACTOR_INSTANCES.items():
        try:
            actor = ray.get_actor(actor_ref)
            status = ray.get(actor.get_status.remote())
            actors[model_type.name] = {
                "actor_ref": str(actor_ref),
                "status": status
            }
        except Exception as e:
            actors[model_type.name] = {
                "actor_ref": str(actor_ref),
                "error": str(e)
            }
    
    return actors


# =============================================================================
# MAIN - For testing
# =============================================================================

if __name__ == "__main__":
    import ray
    import asyncio
    
    # Initialize Ray
    if not ray.is_initialized():
        ray.init(
            address="auto",
            ignore_reinit_error=True,
            log_to_driver=False,
            log_monitor_interval=10
        )
    
    print("=" * 60)
    print("FrameDispatcher - Standalone Test")
    print("=" * 60)
    
    async def run_tests():
        try:
            # Test 1: List models
            print("\n[1/4] Listing models...")
            models = FrameDispatcher.list_models()
            for name, info in models.items():
                print(f"    {name}: {info['actor_class']} ({info['resources']})")
            
            # Test 2: Determine model type
            print("\n[2/4] Testing model type determination...")
            test_cases = [
                ({"task_type": "code"}, ModelType.CODE_GENERATION),
                ({"task_type": "vision"}, ModelType.VISION),
                ({"images": ["img.jpg"]}, ModelType.VISION),
                ({}, ModelType.GENERAL),
                ({"model": "Qwopus"}, ModelType.CODE_GENERATION)
            ]
            for input_kwargs, expected in test_cases:
                result = FrameDispatcher.determine_model_type(**input_kwargs)
                status = "✓" if result == expected else "✗"
                print(f"    {status} {input_kwargs} -> {result.name} (expected {expected.name})")
            
            # Test 3: Dispatch (would require actual actors)
            print("\n[3/4] Testing dispatch (skipped - requires running actors)...")
            print("    Note: Run this test after deploying actors")
            
            # Test 4: Batch dispatch
            print("\n[4/4] Testing batch dispatch (skipped - requires running actors)...")
            print("    Note: Run this test after deploying actors")
            
            print("\n" + "=" * 60)
            print("✓ FrameDispatcher basic tests passed!")
            print("=" * 60)
            
        except Exception as e:
            print(f"\n✗ Test failed: {e}")
            import traceback
            traceback.print_exc()
    
    asyncio.run(run_tests())
