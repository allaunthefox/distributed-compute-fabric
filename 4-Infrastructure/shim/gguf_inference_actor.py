#!/usr/bin/env python3
"""
GGUF Inference Actor for Ray + VCN-LUPINE

Base Ray actor class for loading and running GGUF models with VCN-LUPINE acceleration.

Features:
- Automatic model download from Garage S3 or HTTP
- Async generation with Ray ObjectRef
- Model caching to /tmp/gguf-models
- Health checks and auto-recovery
- VCN-LUPINE integration via LD_PRELOAD
- Support for text and vision models
- Prometheus metrics

Author: Mistral Vibe
Version: 1.0.0
Date: 2026-06-01
"""

import os
import sys
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass, field
from enum import Enum

# Import Ray
import ray

# Import Prometheus metrics
try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    Counter = Histogram = Gauge = None
    start_http_server = lambda *args, **kwargs: None

# Ensure LD_PRELOAD is set for VCN-LUPINE
if "LD_PRELOAD" not in os.environ:
    os.environ["LD_PRELOAD"] = "/usr/local/lib/vcn-lupine.so"

# =============================================================================
# CONFIGURATION
# =============================================================================

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/tmp/ray/gguf_actors.log')
    ]
)
logger = logging.getLogger(__name__)

# Model cache directory
MODEL_CACHE_DIR = Path("/tmp/gguf-models")
MODEL_CACHE_DIR.mkdir(exist_ok=True, parents=True)

# Garage S3 configuration
GARAGE_S3_ENDPOINT = os.environ.get("GARAGE_S3_ENDPOINT", "http://100.88.57.96:3900")
GARAGE_S3_BUCKET = os.environ.get("GARAGE_S3_BUCKET", "models")

# Default generation parameters
DEFAULT_MAX_TOKENS = 256
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_P = 0.9
DEFAULT_CONTEXT_LENGTH = 32768

# Health check configuration
HEALTH_CHECK_INTERVAL = 30  # seconds
MAX_RETRIES = 3

# =============================================================================
# METRICS
# =============================================================================

if PROMETHEUS_AVAILABLE:
    # Request counters
    REQUEST_COUNT = Counter(
        'gguf_actor_requests_total',
        'Total GGUF inference requests',
        ['actor_name', 'model_type', 'node', 'status']
    )
    
    # Request latency
    REQUEST_LATENCY = Histogram(
        'gguf_actor_request_latency_seconds',
        'GGUF inference request latency',
        ['actor_name', 'model_type', 'node'],
        buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60]
    )
    
    # Tokens generated
    TOKENS_GENERATED = Histogram(
        'gguf_actor_tokens_generated',
        'Number of tokens generated per request',
        ['actor_name', 'model_type'],
        buckets=[1, 10, 50, 100, 250, 500, 1000, 2000, 5000]
    )
    
    # Active requests
    ACTIVE_REQUESTS = Gauge(
        'gguf_actor_active_requests',
        'Number of active inference requests',
        ['actor_name', 'node']
    )
    
    # Actor health
    ACTOR_HEALTH = Gauge(
        'gguf_actor_health',
        'Actor health status (1=healthy, 0=unhealthy)',
        ['actor_name', 'node']
    )


# =============================================================================
# ENUMS
# =============================================================================

class ModelType(Enum):
    """Supported model types."""
    TEXT = "text"
    VISION = "vision"
    MULTIMODAL = "multimodal"


class ModelStatus(Enum):
    """Model loading status."""
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    FAILED = "failed"


# =============================================================================
# EXCEPTIONS
# =============================================================================

class GGUFModelError(Exception):
    """Base exception for GGUF model errors."""
    pass


class ModelLoadError(GGUFModelError):
    """Failed to load model."""
    pass


class ModelDownloadError(GGUFModelError):
    """Failed to download model."""
    pass


class InferenceError(GGUFModelError):
    """Failed to run inference."""
    pass


# =============================================================================
# BASE ACTOR CLASS
# =============================================================================

@ray.remote
class GGUFInferenceActor:
    """
    Base Ray actor for GGUF model inference with VCN-LUPINE acceleration.
    
    This actor provides:
    - Automatic model download from remote URLs
    - GGUF model loading via llama.cpp Python bindings
    - Async inference with Ray ObjectRef
    - Health checks and auto-recovery
    - VCN-LUPINE hardware acceleration
    - Prometheus metrics
    
    Usage:
        # Create actor
        actor = GGUFInferenceActor.options(
            resources={"node:qfox-1": 1, "gpu_type:CUDA": 1}
        ).remote(model_path="path/to/model.gguf", model_type="text")
        
        # Generate text
        result_ref = actor.generate.remote(prompt="Hello world")
        result = ray.get(result_ref)
    """
    
    # Class-level model cache
    _MODEL_CACHE = {}
    
    def __init__(
        self,
        model_path: str,
        model_type: Union[str, ModelType] = ModelType.TEXT,
        context_length: int = DEFAULT_CONTEXT_LENGTH,
        gpu_layers: Optional[int] = None,
        threads: int = 4,
        **llm_kwargs: Dict[str, Any]
    ):
        """
        Initialize the GGUF actor.
        
        Args:
            model_path: Path or URL to GGUF file
            model_type: Model type (text, vision, multimodal)
            context_length: Model context window size
            gpu_layers: Number of layers to offload to GPU (None = CPU-only)
            threads: Number of CPU threads
            **llm_kwargs: Additional kwargs for llm.load()
        """
        self.model_path = model_path
        self.model_type = ModelType(model_type) if isinstance(model_type, str) else model_type
        self.context_length = context_length
        self.gpu_layers = gpu_layers
        self.threads = threads
        self.llm_kwargs = llm_kwargs
        
        # Node identification
        self.node = os.environ.get("RAY_node_name", os.uname().nodename)
        self.actor_name = self.__class__.__name__
        
        # State
        self.model = None
        self.model_status = ModelStatus.UNLOADED
        self.retry_count = 0
        self.max_retries = MAX_RETRIES
        self.healthy = False
        self.last_health_check = 0
        
        # Metrics
        if PROMETHEUS_AVAILABLE:
            self.metrics_port = self._start_metrics_server()
            ACTOR_HEALTH.labels(self.actor_name, self.node).set(0)
        
        # Load model
        self._load_model()
        
        # Start background health check
        self._start_background_health_check()
    
    def _start_metrics_server(self) -> int:
        """Start Prometheus metrics server on a random port."""
        import socket
        import random
        
        # Find available port
        for _ in range(100):
            port = random.randint(9000, 10000)
            try:
                with socket.socket() as s:
                    s.bind(('', port))
                start_http_server(port)
                logger.info(f"[{self.node}] Prometheus metrics server started on port {port}")
                return port
            except:
                continue
        
        logger.warning(f"[{self.node}] Failed to start metrics server")
        return 0
    
    def _start_background_health_check(self):
        """Start background health check loop."""
        import threading
        
        def health_check_loop():
            while True:
                time.sleep(HEALTH_CHECK_INTERVAL)
                try:
                    self.check_health()
                except Exception as e:
                    logger.error(f"[{self.node}] Health check failed: {e}")
        
        # Start in background thread
        thread = threading.Thread(target=health_check_loop, daemon=True)
        thread.start()
    
    def _load_model(self):
        """Load GGUF model with llama.cpp."""
        import llm
        
        logger.info(f"[{self.node}] Loading model: {self.model_path}")
        self.model_status = ModelStatus.LOADING
        
        try:
            # Download model if remote URL
            resolved_path = self._resolve_model_path(self.model_path)
            
            # Build llm.load() kwargs
            load_kwargs = {
                "model": resolved_path,
                "n_ctx": self.context_length,
                "n_threads": self.threads,
                "n_gpu_layers": self.gpu_layers,
                **self.llm_kwargs
            }
            
            # Handle vision models (Llava, etc.)
            if self.model_type == ModelType.VISION:
                mmproj_path = resolved_path.replace(".gguf", ".mmproj")
                if Path(mmproj_path).exists():
                    load_kwargs["mmproj"] = mmproj_path
                    load_kwargs["image"] = True
            
            # Load model
            logger.info(f"[{self.node}] Loading model with kwargs: {load_kwargs}")
            self.model = llm.load(**load_kwargs)
            
            self.model_status = ModelStatus.LOADED
            self.healthy = True
            self.retry_count = 0
            
            if PROMETHEUS_AVAILABLE:
                ACTOR_HEALTH.labels(self.actor_name, self.node).set(1)
            
            logger.info(f"[{self.node}] Model loaded successfully: {resolved_path}")
            
        except Exception as e:
            self.model_status = ModelStatus.FAILED
            self.healthy = False
            logger.error(f"[{self.node}] Failed to load model: {e}")
            raise ModelLoadError(f"Failed to load model {self.model_path}: {e}")
    
    def _resolve_model_path(self, path: str) -> str:
        """Resolve model path (download if remote URL)."""
        # Check if already in cache
        if Path(path).exists():
            return str(Path(path).resolve())
        
        # Check if remote URL
        if path.startswith(("http://", "https://", "s3://")):
            return self._download_model(path)
        
        return path
    
    def _download_model(self, url: str) -> str:
        """
        Download model from Garage S3 or HTTP to local cache.
        
        Args:
            url: URL to download from
            
        Returns:
            Local path to downloaded model
        """
        import httpx
        from urllib.parse import urlparse
        
        # Parse URL
        parsed = urlparse(url)
        
        # Determine cache path
        if parsed.scheme in ("http", "https"):
            model_name = parsed.path.split("/")[-1]
        else:
            model_name = url.split("/")[-1]
        
        local_path = MODEL_CACHE_DIR / model_name
        
        # Check if already cached
        if local_path.exists():
            logger.info(f"[{self.node}] Using cached model: {local_path}")
            return str(local_path)
        
        logger.info(f"[{self.node}] Downloading model: {url}")
        
        try:
            # Download with retry
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    with httpx.stream("GET", url, timeout=300) as response:
                        response.raise_for_status()
                        with open(local_path, "wb") as f:
                            for chunk in response.iter_bytes():
                                f.write(chunk)
                    
                    logger.info(f"[{self.node}] Model downloaded to: {local_path}")
                    return str(local_path)
                    
                except httpx.HTTPStatusError as e:
                    if attempt == max_retries - 1:
                        raise ModelDownloadError(f"Failed to download {url}: HTTP {e.response.status_code}")
                    logger.warning(f"[{self.node}] Download attempt {attempt + 1} failed: {e}")
                    time.sleep(2 ** attempt)
            
        except httpx.RequestError as e:
            raise ModelDownloadError(f"Failed to download {url}: {e}")
    
    def check_health(self) -> bool:
        """
        Check if actor is healthy.
        
        Returns:
            True if healthy, False otherwise
        """
        if not self.healthy:
            logger.warning(f"[{self.node}] Actor marked as unhealthy")
            return False
        
        try:
            # Test with small prompt
            test_prompt = "Health check: Say 'ok'"
            result = self.model(test_prompt, max_tokens=5, stream=False)
            
            if "ok" in result.lower():
                self.last_health_check = time.time()
                logger.debug(f"[{self.node}] Health check passed")
                return True
            else:
                logger.warning(f"[{self.node}] Health check: unexpected result: {result}")
                return False
                
        except Exception as e:
            logger.error(f"[{self.node}] Health check failed: {e}")
            self.healthy = False
            if PROMETHEUS_AVAILABLE:
                ACTOR_HEALTH.labels(self.actor_name, self.node).set(0)
            return False
    
    def generate(
        self,
        prompt: str,
        images: Optional[List[Union[str, Path]]] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        top_p: float = DEFAULT_TOP_P,
        stream: bool = False,
        **generate_kwargs: Dict[str, Any]
    ) -> str:
        """
        Generate text from prompt (synchronous, called via Ray remote).
        
        Note: This method is synchronous because llama.cpp's Python bindings
        are synchronous. Ray handles the async dispatch via ObjectRef.
        
        Args:
            prompt: Input text prompt
            images: List of image paths/URLs (for vision models)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-2)
            top_p: Top-p sampling (0-1)
            stream: Whether to stream results
            **generate_kwargs: Additional kwargs for model.generate()
            
        Returns:
            Generated text
            
        Raises:
            RuntimeError: If actor is unhealthy
            InferenceError: If generation fails
        """
        # Track active requests
        if PROMETHEUS_AVAILABLE:
            ACTIVE_REQUESTS.labels(self.actor_name, self.node).inc()
        
        try:
            # Check health before processing
            if not self.healthy:
                self._attempt_recovery()
            
            if not self.healthy:
                raise RuntimeError(f"Actor {self.actor_name} on {self.node} is unhealthy")
            
            # Build prompt with images for vision models
            final_prompt = prompt
            if self.model_type == ModelType.VISION and images:
                final_prompt = self._build_multimodal_prompt(prompt, images)
            
            # Generate with timing
            start_time = time.time()
            
            try:
                result = self.model(
                    final_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    stream=stream,
                    **generate_kwargs
                )
                
                # Record metrics
                latency = time.time() - start_time
                if PROMETHEUS_AVAILABLE:
                    REQUEST_COUNT.labels(
                        self.actor_name,
                        self.model_type.value,
                        self.node,
                        "success"
                    ).inc()
                    REQUEST_LATENCY.labels(
                        self.actor_name,
                        self.model_type.value,
                        self.node
                    ).observe(latency)
                    TOKENS_GENERATED.labels(
                        self.actor_name,
                        self.model_type.value
                    ).observe(len(result.split()) if result else 0)
                
                logger.debug(
                    f"[{self.node}] Generated: len={len(result)}, "
                    f"latency={latency:.2f}s, tokens={len(result.split()) if result else 0}"
                )
                
                return result
                
            except Exception as e:
                if PROMETHEUS_AVAILABLE:
                    REQUEST_COUNT.labels(
                        self.actor_name,
                        self.model_type.value,
                        self.node,
                        "error"
                    ).inc()
                raise InferenceError(f"Generation failed: {e}")
        
        finally:
            if PROMETHEUS_AVAILABLE:
                ACTIVE_REQUESTS.labels(self.actor_name, self.node).dec()
    
    def _build_multimodal_prompt(
        self,
        prompt: str,
        images: List[Union[str, Path]]
    ) -> List[Any]:
        """
        Build multimodal prompt with text and images.
        
        Args:
            prompt: Text prompt
            images: List of image paths or URLs
            
        Returns:
            List of prompt parts (text + images)
        """
        from PIL import Image
        import httpx
        from io import BytesIO
        
        prompt_parts = [prompt]
        
        for img in images:
            try:
                # Handle URL
                if isinstance(img, str) and img.startswith(("http://", "https://")):
                    response = httpx.get(img, timeout=30)
                    response.raise_for_status()
                    img_data = Image.open(BytesIO(response.content))
                # Handle path
                elif isinstance(img, (str, Path)):
                    img_data = Image.open(img)
                else:
                    img_data = img
                
                prompt_parts.append(img_data)
                
            except Exception as e:
                logger.warning(f"[{self.node}] Failed to load image {img}: {e}")
                # Continue without this image
        
        return prompt_parts
    
    def _attempt_recovery(self):
        """Attempt to recover actor after failure."""
        if self.retry_count >= self.max_retries:
            logger.error(
                f"[{self.node}] Actor {self.actor_name} failed after "
                f"{self.max_retries} retries, killing actor"
            )
            ray.kill(self)
            raise RuntimeError("Actor failed, please retry")
        
        self.retry_count += 1
        logger.warning(
            f"[{self.node}] Recovery attempt {self.retry_count}/{self.max_retries} "
            f"for actor {self.actor_name}"
        )
        
        try:
            self._load_model()
            self.healthy = True
            if PROMETHEUS_AVAILABLE:
                ACTOR_HEALTH.labels(self.actor_name, self.node).set(1)
            logger.info(f"[{self.node}] Actor {self.actor_name} recovered")
        
        except Exception as e:
            logger.error(f"[{self.node}] Recovery failed: {e}")
            self.healthy = False
    
    def get_status(self) -> Dict[str, Any]:
        """Get actor status."""
        return {
            "actor_name": self.actor_name,
            "node": self.node,
            "model_path": self.model_path,
            "model_type": self.model_type.value,
            "model_status": self.model_status.value,
            "healthy": self.healthy,
            "retry_count": self.retry_count,
            "gpu_layers": self.gpu_layers,
            "threads": self.threads,
            "context_length": self.context_length,
            "last_health_check": self.last_health_check
        }
    
    def __repr__(self) -> str:
        return (
            f"GGUFInferenceActor("
            f"node={self.node}, "
            f"model={Path(self.model_path).name}, "
            f"type={self.model_type.value}, "
            f"healthy={self.healthy})"
        )


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def list_models() -> Dict[str, Any]:
    """List all loaded models."""
    # Get all actors
    actors = ray.list_actors()
    
    models = {}
    for actor_name, actor_info in actors.items():
        if "GGUFInferenceActor" in actor_name:
            try:
                actor = ray.get_actor(actor_name)
                status = ray.get(actor.get_status.remote())
                models[actor_name] = status
            except Exception as e:
                models[actor_name] = {"error": str(e)}
    
    return models


def health_check_all() -> Dict[str, bool]:
    """Run health check on all actors."""
    actors = ray.list_actors()
    
    results = {}
    for actor_name, actor_info in actors.items():
        if "GGUFInferenceActor" in actor_name:
            try:
                actor = ray.get_actor(actor_name)
                result = ray.get(actor.check_health.remote())
                results[actor_name] = result
            except Exception as e:
                results[actor_name] = False
    
    return results


# =============================================================================
# MAIN - For testing
# =============================================================================

if __name__ == "__main__":
    # Initialize Ray
    if not ray.is_initialized():
        ray.init(address="auto", ignore_reinit_error=True, log_to_driver=False)
    
    # Create test actor
    print("Creating test GGUF actor...")
    
    # Note: This will fail without a valid model path
    # Use one of the specialized actors instead for actual deployment
    try:
        actor = GGUFInferenceActor.options(
            resources={"cpu": 1}
        ).remote(
            model_path="http://example.com/model.gguf",
            model_type="text"
        )
        print(f"Actor created: {actor}")
        
        # Test generation
        result_ref = actor.generate.remote("Hello world")
        result = ray.get(result_ref)
        print(f"Result: {result}")
        
    except Exception as e:
        print(f"Test failed (expected without valid model): {e}")
    
    # Shutdown Ray
    ray.shutdown()
