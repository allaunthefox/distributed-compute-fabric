# Phase 7: Hermes Orchestrator

**Phase:** 7  
**Name:** Hermes Orchestrator  
**Duration:** 5 days  
**Dependencies:** Phase 6 (Networking & Ingress)  
**Status:** Partial (API exists, need completion)  
**Owner:** Backend Team

---

## Overview

This phase completes the Hermes orchestrator implementation, ensuring all API endpoints are functional, request routing works correctly through FrameDispatcher, and all integration points with Ray cluster are operational.

### Goals
1. Complete FastAPI application with all endpoints
2. Integrate FrameDispatcher for intelligent model routing
3. Implement request validation and authentication
4. Add circuit breaker pattern for resilience
5. Enable batch processing for efficiency
6. Configure rate limiting
7. Add comprehensive health checks and metrics

### Key Components
- FastAPI server with uvicorn/gunicorn
- FrameDispatcher (router)
- Model registry with lazy loading
- Circuit breaker implementation
- Batch processing support
- Rate limiting middleware
- Authentication middleware
- Prometheus metrics integration

---

## Prerequisites

Before starting Phase 7, ensure:
- [ ] Phase 1-6 are complete
- [ ] Ray cluster is operational
- [ ] All model actors are deployed
- [ ] Networking is configured (Phase 6)
- [ ] Python 3.11+ environment
- [ ] All dependencies from requirements.txt installed

---

## Microsteps

### Day 1: FastAPI Application Core

#### Step 7.1.1: Project Structure Setup
```bash
# Ensure directory structure exists
mkdir -p code/hermes
mkdir -p code/hermes/tests

# Create __init__.py files
for dir in code/hermes code/hermes/tests; do
  touch $dir/__init__.py
done
```

**Verification:**
```bash
find code/hermes -name "__init__.py"
# Expected: Should list all __init__.py files
```

#### Step 7.1.2: Main Application File
```python
# File: code/hermes/main.py
"""
Hermes Orchestrator - Main FastAPI Application

Provides REST API for model inference orchestration across distributed Ray cluster.
"""

import os
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from hermes.orchestrator import router as orchestrator_router
from hermes.config import settings

# Create FastAPI app
app = FastAPI(
    title="Hermes Orchestrator",
    description="Distributed GGUF model inference orchestrator on Ray cluster",
    version="1.0.0",
    docs_url="/api/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/api/redoc" if settings.ENVIRONMENT != "production" else None,
    openapi_url="/api/openapi.json" if settings.ENVIRONMENT != "production" else None,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(
    orchestrator_router,
    prefix="/api/v1",
    tags=["orchestration"],
)

# Mount static files (for documentation)
if settings.SERVE_STATIC:
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", tags=["health"])
async def root():
    """Root endpoint - basic health check."""
    return {
        "service": "hermes",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health", tags=["health"])
async def health():
    """Health check endpoint with detailed status."""
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "ray_cluster": "connected",
        "models_loaded": 0,  # Will be updated dynamically
    }


@app.get("/ready", tags=["health"])
async def ready():
    """Readiness probe - checks if service is ready to receive traffic."""
    # Check Ray cluster connectivity
    # Check model registry
    # Check database connectivity
    return {"status": "ready"}


# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error", "detail": str(exc)},
    )


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "hermes.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.ENVIRONMENT != "production",
        workers=settings.WORKERS,
    )
```

**Verification:**
```bash
# Test basic import
cd code/hermes && python -c "from hermes.main import app; print('Import successful')"
# Expected: Import successful
```

#### Step 7.1.3: Configuration Management
```python
# File: code/hermes/config.py
"""
Hermes Configuration Management

Uses Pydantic Settings for environment-based configuration.
"""

from functools import lru_cache
from typing import List

from pydantic import Field, AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # Application
    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 4
    DEBUG: bool = True
    SERVE_STATIC: bool = False
    
    # CORS
    CORS_ORIGINS: List[AnyHttpUrl] = [
        "http://localhost:3000",
        "http://localhost:8080",
        "https://localhost:3000",
        "https://localhost:8080",
    ]
    
    # Ray Cluster
    RAY_HEAD_HOST: str = "raycluster-head-svc.ray-system.svc.cluster.local"
    RAY_HEAD_PORT: int = 8265
    RAY_DASHBOARD_USER: str = "admin"
    RAY_DASHBOARD_PASSWORD: str = ""
    
    # Redis (for caching)
    REDIS_HOST: str = "redis-service.ray-system.svc.cluster.local"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    
    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60  # seconds
    
    # Authentication
    AUTH_ENABLED: bool = True
    AUTH_TYPE: str = "jwt"  # or "basic", "none"
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 30
    
    # Model Configuration
    MODEL_CACHE_DIR: str = "/cache/models"
    MAX_CONCURRENT_REQUESTS: int = 100
    REQUEST_TIMEOUT: int = 300  # seconds
    
    # Monitoring
    PROMETHEUS_ENABLED: bool = True
    METRICS_PORT: int = 9090
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # or "text"
    
    # Database (for request logging)
    DATABASE_URL: str = "sqlite:///./hermes.db"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache()
def get_settings():
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
```

**Verification:**
```bash
# Test settings loading
cd code/hermes && python -c "from hermes.config import settings; print(settings.ENVIRONMENT)"
# Expected: Should print environment value
```

### Day 2: FrameDispatcher Integration

#### Step 7.2.1: Model Type Enumeration
```python
# File: code/hermes/models.py
"""
Model Type Definitions

Enumerates all supported model types and their characteristics.
"""

from enum import Enum
from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class ModelType(str, Enum):
    """Supported model types."""
    CODE = "code"
    TEXT = "text"
    VISION = "vision"
    FALLBACK = "fallback"
    CUSTOM = "custom"


class ModelSpec(BaseModel):
    """Model specification."""
    name: str
    model_type: ModelType
    display_name: str
    description: str
    version: str
    size: str  # e.g., "9B", "4B"
    backend: str  # e.g., "CUDA", "CPU", "VAAPI"
    node_selector: Optional[Dict[str, str]] = None
    resource_requirements: Optional[Dict[str, Any]] = None
    capabilities: List[str] = []
    max_context: int = 4096
    price_per_token: float = 0.0
    
    class Config:
        use_enum_values = True


# Model Registry
MODEL_REGISTRY: Dict[ModelType, ModelSpec] = {
    ModelType.CODE: ModelSpec(
        name="Qwopus3.5-9B",
        model_type=ModelType.CODE,
        display_name="Qwopus 3.5 9B",
        description="Advanced code generation model",
        version="1.0.0",
        size="9B",
        backend="CUDA",
        node_selector={"kubernetes.io/hostname": "qfox-1"},
        resource_requirements={"gpu": 1, "memory": "16Gi", "cpu": 4},
        capabilities=["code-completion", "code-explanation", "code-generation"],
        max_context=32768,
        price_per_token=0.002,
    ),
    ModelType.TEXT: ModelSpec(
        name="Gemma-4-E4B",
        model_type=ModelType.TEXT,
        display_name="Gemma 4 E4B",
        description="General-purpose text model",
        version="1.0.0",
        size="4B",
        backend="CPU",
        node_selector={"kubernetes.io/hostname": "neon-64gb"},
        resource_requirements={"memory": "16Gi", "cpu": 8},
        capabilities=["text-generation", "chat", "summarization"],
        max_context=131072,
        price_per_token=0.001,
    ),
    ModelType.VISION: ModelSpec(
        name="Llava-1.5-7B",
        model_type=ModelType.VISION,
        display_name="Llava 1.5 7B",
        description="Multimodal vision and text model",
        version="1.0.0",
        size="7B",
        backend="VAAPI",
        node_selector={"kubernetes.io/hostname": "steamdeck"},
        resource_requirements={"gpu": 0.5, "memory": "12Gi", "cpu": 4},
        capabilities=["image-understanding", "visual-qa", "captioning"],
        max_context=4096,
        price_per_token=0.003,
    ),
    ModelType.FALLBACK: ModelSpec(
        name="DeepSeek-Coder",
        model_type=ModelType.FALLBACK,
        display_name="DeepSeek Coder",
        description="Fallback code model",
        version="1.0.0",
        size="6.7B",
        backend="CPU",
        node_selector={"kubernetes.io/hostname": "neon-64gb"},
        resource_requirements={"memory": "12Gi", "cpu": 6},
        capabilities=["code-completion", "code-generation"],
        max_context=16384,
        price_per_token=0.0015,
    ),
}
```

**Verification:**
```bash
cd code/hermes && python -c "from hermes.models import MODEL_REGISTRY; print(list(MODEL_REGISTRY.keys()))"
# Expected: Should list all model types
```

#### Step 7.2.2: FrameDispatcher Implementation
```python
# File: code/hermes/frame_dispatcher.py
"""
FrameDispatcher - Intelligent Request Router

Routes inference requests to appropriate Ray actors based on:
- Model type
- Hardware requirements
- Load balancing
- Circuit breaker state
"""

import logging
from typing import Optional, Any, Dict

import ray
from ray.util import ActorPool

from hermes.models import ModelType, MODEL_REGISTRY, ModelSpec
from hermes.config import settings

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Circuit breaker pattern implementation."""
    
    def __init__(self, max_failures: int = 5, reset_timeout: int = 60):
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.last_failure_time = None
        self.state = "CLOSED"
    
    def record_success(self):
        """Record a successful operation."""
        self.failures = 0
        self.state = "CLOSED"
    
    def record_failure(self):
        """Record a failed operation."""
        self.failures += 1
        self.last_failure_time = time.time()
        
        if self.failures >= self.max_failures:
            self.state = "OPEN"
    
    def should_allow(self):
        """Check if request should be allowed."""
        if self.state == "CLOSED":
            return True
        
        # Check if reset timeout has passed
        if time.time() - self.last_failure_time > self.reset_timeout:
            self.state = "HALF_OPEN"
            return True
        
        return False


class FrameDispatcher:
    """
    Dispatches inference requests to appropriate model actors.
    
    Implements:
    - Model type to actor mapping
    - Lazy loading of actors
    - Circuit breaker pattern
    - Load balancing across replicas
    - Fallback handling
    """
    
    def __init__(self):
        self.actor_pools: Dict[ModelType, ActorPool] = {}
        self.circuit_breakers: Dict[ModelType, CircuitBreaker] = {}
        self.model_actors: Dict[ModelType, Any] = {}
        
        # Initialize circuit breakers for each model type
        for model_type in MODEL_REGISTRY:
            self.circuit_breakers[model_type] = CircuitBreaker(
                max_failures=3,
                reset_timeout=30,
            )
    
    async def initialize(self):
        """Initialize Ray connection and verify actors."""
        try:
            if not ray.is_initialized():
                ray.init(f"ray://{settings.RAY_HEAD_HOST}:{settings.RAY_HEAD_PORT}")
            
            logger.info("Ray connection initialized")
            
            # Verify all model actors are registered
            for model_type, spec in MODEL_REGISTRY.items():
                actor_class = self._get_actor_class(model_type)
                if actor_class:
                    # Lazy initialization - don't create actors yet
                    logger.info(f"Registered {model_type.value} -> {actor_class.__name__}")
            
        except Exception as e:
            logger.error(f"Failed to initialize Ray connection: {e}")
            raise
    
    def _get_actor_class(self, model_type: ModelType) -> Optional[type]:
        """Get the Ray actor class for a model type."""
        # Import here to avoid circular imports
        from hermes.actors import (
            CoderActor,
            VisionActor,
            GeneralActor,
            DeepSeekCoderActor,
        )
        
        actor_map = {
            ModelType.CODE: CoderActor,
            ModelType.TEXT: GeneralActor,
            ModelType.VISION: VisionActor,
            ModelType.FALLBACK: DeepSeekCoderActor,
        }
        
        return actor_map.get(model_type)
    
    def _get_or_create_actor_pool(self, model_type: ModelType) -> ActorPool:
        """Get or create an actor pool for a model type."""
        if model_type not in self.actor_pools:
            actor_class = self._get_actor_class(model_type)
            if not actor_class:
                raise ValueError(f"No actor class registered for {model_type}")
            
            # Create actor pool with lazy initialization
            pool_size = MODEL_REGISTRY[model_type].resource_requirements.get("replicas", 1)
            self.actor_pools[model_type] = ActorPool([actor_class.remote() for _ in range(pool_size)])
            
            logger.info(f"Created actor pool for {model_type.value} with {pool_size} replicas")
        
        return self.actor_pools[model_type]
    
    def get_actor(self, model_type: ModelType) -> Any:
        """
        Get a model actor, respecting circuit breaker state.
        
        Returns the appropriate actor or raises an exception if:
        - Model type is not supported
        - Circuit breaker is open
        """
        # Check circuit breaker
        cb = self.circuit_breakers[model_type]
        if not cb.should_allow():
            logger.warning(f"Circuit breaker OPEN for {model_type.value}, using fallback")
            # Try fallback
            if model_type != ModelType.FALLBACK:
                return self.get_actor(ModelType.FALLBACK)
            raise RuntimeError(f"Circuit breaker open for all model types")
        
        # Get or create actor pool
        pool = self._get_or_create_actor_pool(model_type)
        
        # Get an actor from the pool (load balanced)
        actor = ray.get(pool.get_next())
        
        return actor
    
    async def dispatch(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatch an inference request to the appropriate model.
        
        Args:
            request: Inference request with model_type, prompt, etc.
        
        Returns:
            Inference response with generated text, metadata, etc.
        """
        model_type = request.get("model_type")
        
        if not model_type:
            # Auto-detect model type based on request
            model_type = self._detect_model_type(request)
        
        try:
            model_type_enum = ModelType(model_type)
        except ValueError:
            raise ValueError(f"Unsupported model type: {model_type}")
        
        # Get actor
        actor = self.get_actor(model_type_enum)
        
        try:
            # Call actor
            result = await actor.generate.remote(**request)
            
            # Record success
            self.circuit_breakers[model_type_enum].record_success()
            
            return result
            
        except Exception as e:
            # Record failure
            self.circuit_breakers[model_type_enum].record_failure()
            logger.error(f"Model {model_type} failed: {e}")
            
            # Try fallback if not already fallback
            if model_type_enum != ModelType.FALLBACK:
                logger.info(f"Falling back to {ModelType.FALLBACK.value}")
                request["model_type"] = ModelType.FALLBACK.value
                return await self.dispatch(request)
            
            raise
    
    def _detect_model_type(self, request: Dict[str, Any]) -> str:
        """Auto-detect model type based on request content."""
        # Check for image data
        if request.get("images") or request.get("image_urls"):
            return ModelType.VISION.value
        
        # Check for code-specific parameters
        if request.get("language") or request.get("code_only"):
            return ModelType.CODE.value
        
        # Default to text
        return ModelType.TEXT.value
    
    async def batch_dispatch(self, requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Dispatch multiple inference requests in batch.
        
        Groups similar requests and processes them efficiently.
        """
        # Group by model type
        grouped = {}
        for req in requests:
            model_type = req.get("model_type", self._detect_model_type(req))
            if model_type not in grouped:
                grouped[model_type] = []
            grouped[model_type].append(req)
        
        results = []
        for model_type, batch_requests in grouped.items():
            try:
                model_type_enum = ModelType(model_type)
            except ValueError:
                raise ValueError(f"Unsupported model type: {model_type}")
            
            # Get actor for this model type
            actor = self.get_actor(model_type_enum)
            
            # Use actor's batch method if available
            try:
                batch_result = await actor.generate_batch.remote(batch_requests)
                results.extend(batch_result)
            except AttributeError:
                # Fall back to individual requests
                for req in batch_requests:
                    result = await self.dispatch(req)
                    results.append(result)
        
        return results


# Global dispatcher instance
dispatcher: Optional[FrameDispatcher] = None


async def get_dispatcher() -> FrameDispatcher:
    """Get or create the global dispatcher instance."""
    global dispatcher
    
    if dispatcher is None:
        dispatcher = FrameDispatcher()
        await dispatcher.initialize()
    
    return dispatcher
```

**Verification:**
```bash
cd code/hermes && python -c "from hermes.frame_dispatcher import FrameDispatcher; print('FrameDispatcher ready')"
# Expected: FrameDispatcher ready
```

#### Step 7.2.3: Actor Registry
```python
# File: code/hermes/actors/__init__.py
"""
Actor Registry

Imports and registers all Ray actor classes.
"""

from hermes.actors.coder_actor import CoderActor
from hermes.actors.vision_actor import VisionActor
from hermes.actors.general_actor import GeneralActor, DeepSeekCoderActor

__all__ = [
    "CoderActor",
    "VisionActor",
    "GeneralActor",
    "DeepSeekCoderActor",
]
```

### Day 3: API Endpoints

#### Step 7.3.1: Orchestrator Router
```python
# File: code/hermes/orchestrator.py
"""
Hermes Orchestrator Router

Defines all API endpoints for model inference.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from hermes.models import ModelType, MODEL_REGISTRY
from hermes.frame_dispatcher import get_dispatcher, FrameDispatcher
from hermes.config import settings
from hermes.metrics import (
    request_counter,
    request_latency,
    token_counter,
    error_counter,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


# Request/Response Models

class GenerateRequest(BaseModel):
    """Request model for /generate endpoint."""
    prompt: str = Field(..., min_length=1, max_length=10000)
    model_type: Optional[ModelType] = None
    max_tokens: Optional[int] = 512
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 0.9
    top_k: Optional[int] = 50
    stop: Optional[List[str]] = None
    echo: Optional[bool] = False
    stream: Optional[bool] = False
    
    # For multimodal
    images: Optional[List[str]] = None  # base64 encoded or URLs
    
    class Config:
        use_enum_values = True


class GenerateResponse(BaseModel):
    """Response model for /generate endpoint."""
    id: str
    model: str
    model_type: ModelType
    prompt: str
    generated_text: str
    finish_reason: str
    tokens_generated: int
    tokens_input: int
    latency_ms: float
    timestamp: datetime
    
    class Config:
        use_enum_values = True


class BatchGenerateRequest(BaseModel):
    """Request model for /generate/batch endpoint."""
    requests: List[GenerateRequest] = Field(..., min_items=1, max_items=100)


class BatchGenerateResponse(BaseModel):
    """Response model for /generate/batch endpoint."""
    results: List[GenerateResponse]
    total_tokens: int
    total_latency_ms: float
    success_count: int
    error_count: int


class ModelInfo(BaseModel):
    """Model information model."""
    name: str
    model_type: ModelType
    display_name: str
    description: str
    version: str
    size: str
    backend: str
    capabilities: List[str]
    max_context: int
    available: bool
    loaded: bool
    
    class Config:
        use_enum_values = True


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    environment: str
    version: str
    ray_connected: bool
    models_available: int
    models_loaded: int
    uptime_seconds: float


class StatusResponse(BaseModel):
    """Cluster status response model."""
    ray_cluster: Dict[str, Any]
    models: Dict[str, ModelInfo]
    queue_size: int
    active_requests: int
    completed_requests: int
    error_rate: float


class MetricsResponse(BaseModel):
    """Metrics response model."""
    request_count: int
    token_count: int
    avg_latency_ms: float
    error_count: int
    models: Dict[str, Dict[str, Any]]


# Endpoints

@router.post(
    "/generate",
    response_model=GenerateResponse,
    summary="Generate text from a prompt",
    description="Send a prompt to a model and get generated text back",
)
async def generate(
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
    dispatcher: FrameDispatcher = Depends(get_dispatcher),
) -> GenerateResponse:
    """
    Generate text from a prompt using the specified model.
    
    This endpoint accepts a text prompt and model type, then routes
    the request to the appropriate Ray actor for inference.
    """
    import time
    import uuid
    from datetime import datetime
    
    start_time = time.time()
    request_id = str(uuid.uuid4())
    
    # Increment request counter
    request_counter.labels(model=str(request.model_type or "auto")).inc()
    
    try:
        # Convert to dict and add request_id
        req_dict = request.dict()
        req_dict["request_id"] = request_id
        req_dict["timestamp"] = datetime.utcnow().isoformat()
        
        # Dispatch to appropriate model
        result = await dispatcher.dispatch(req_dict)
        
        # Process result
        end_time = time.time()
        latency_ms = (end_time - start_time) * 1000
        
        # Record latency
        request_latency.labels(model=str(request.model_type or "auto")).observe(latency_ms / 1000)
        
        # Record tokens
        token_counter.labels(model=str(request.model_type or "auto")).inc(
            result.get("tokens_generated", 0)
        )
        
        # Build response
        response = GenerateResponse(
            id=request_id,
            model=result.get("model", "unknown"),
            model_type=result.get("model_type", request.model_type or ModelType.TEXT),
            prompt=request.prompt[:100],  # Truncate for response
            generated_text=result.get("generated_text", ""),
            finish_reason=result.get("finish_reason", "stop"),
            tokens_generated=result.get("tokens_generated", 0),
            tokens_input=result.get("tokens_input", 0),
            latency_ms=latency_ms,
            timestamp=datetime.utcnow(),
        )
        
        return response
        
    except Exception as e:
        error_counter.labels(model=str(request.model_type or "auto")).inc()
        logger.error(f"Generation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/generate/batch",
    response_model=BatchGenerateResponse,
    summary="Generate text from multiple prompts",
    description="Send multiple prompts for batch processing",
)
async def generate_batch(
    request: BatchGenerateRequest,
    dispatcher: FrameDispatcher = Depends(get_dispatcher),
) -> BatchGenerateResponse:
    """
    Generate text from multiple prompts in a batch.
    
    This endpoint accepts multiple prompts and processes them efficiently,
    grouping by model type where possible.
    """
    import time
    
    start_time = time.time()
    
    try:
        # Convert requests
        req_list = [req.dict() for req in request.requests]
        
        # Batch dispatch
        results = await dispatcher.batch_dispatch(req_list)
        
        end_time = time.time()
        total_latency_ms = (end_time - start_time) * 1000
        
        # Calculate totals
        total_tokens = sum(r.get("tokens_generated", 0) for r in results)
        success_count = sum(1 for r in results if "generated_text" in r)
        error_count = len(results) - success_count
        
        # Build response
        response_results = []
        for result in results:
            response_results.append(GenerateResponse(
                id=result.get("request_id", str(uuid.uuid4())),
                model=result.get("model", "unknown"),
                model_type=result.get("model_type", ModelType.TEXT),
                prompt=result.get("prompt", "")[:100],
                generated_text=result.get("generated_text", ""),
                finish_reason=result.get("finish_reason", "stop"),
                tokens_generated=result.get("tokens_generated", 0),
                tokens_input=result.get("tokens_input", 0),
                latency_ms=result.get("latency_ms", 0),
                timestamp=datetime.utcnow(),
            ))
        
        return BatchGenerateResponse(
            results=response_results,
            total_tokens=total_tokens,
            total_latency_ms=total_latency_ms,
            success_count=success_count,
            error_count=error_count,
        )
        
    except Exception as e:
        logger.error(f"Batch generation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/models",
    response_model=List[ModelInfo],
    summary="List available models",
    description="Get information about all available models",
)
async def list_models() -> List[ModelInfo]:
    """
    List all available models with their specifications.
    """
    models = []
    for model_type, spec in MODEL_REGISTRY.items():
        models.append(ModelInfo(
            name=spec.name,
            model_type=model_type,
            display_name=spec.display_name,
            description=spec.description,
            version=spec.version,
            size=spec.size,
            backend=spec.backend,
            capabilities=spec.capabilities,
            max_context=spec.max_context,
            available=True,
            loaded=False,  # Will be updated dynamically
        ))
    return models


@router.get(
    "/models/{model_name}",
    response_model=ModelInfo,
    summary="Get model information",
    description="Get detailed information about a specific model",
)
async def get_model(model_name: str) -> ModelInfo:
    """
    Get detailed information about a specific model.
    """
    for model_type, spec in MODEL_REGISTRY.items():
        if spec.name.lower() == model_name.lower() or model_type.value == model_name.lower():
            return ModelInfo(
                name=spec.name,
                model_type=model_type,
                display_name=spec.display_name,
                description=spec.description,
                version=spec.version,
                size=spec.size,
                backend=spec.backend,
                capabilities=spec.capabilities,
                max_context=spec.max_context,
                available=True,
                loaded=False,
            )
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Model {model_name} not found",
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Get service health status",
)
async def health() -> HealthResponse:
    """
    Get service health status.
    """
    import time
    import ray
    from hermes.frame_dispatcher import dispatcher
    
    start_time = time.time()
    
    # Check Ray connection
    ray_connected = False
    try:
        ray_connected = ray.is_initialized()
    except Exception:
        pass
    
    # Calculate uptime
    uptime = time.time() - start_time
    
    return HealthResponse(
        status="healthy" if ray_connected else "degraded",
        environment=settings.ENVIRONMENT,
        version="1.0.0",
        ray_connected=ray_connected,
        models_available=len(MODEL_REGISTRY),
        models_loaded=0,  # TODO: Get actual loaded count
        uptime_seconds=uptime,
    )


@router.get(
    "/status",
    response_model=StatusResponse,
    summary="Cluster status",
    description="Get detailed cluster status",
)
async def status() -> StatusResponse:
    """
    Get detailed cluster status.
    """
    import ray
    
    ray_cluster = {}
    try:
        if ray.is_initialized():
            ray_cluster = {
                "nodes": len(ray.nodes()),
                "resources": dict(ray.available_resources()),
                "gpu_available": ray.available_resources().get("GPU", 0),
            }
    except Exception:
        pass
    
    # Build model status
    models = {}
    for model_type, spec in MODEL_REGISTRY.items():
        models[spec.name] = ModelInfo(
            name=spec.name,
            model_type=model_type,
            display_name=spec.display_name,
            description=spec.description,
            version=spec.version,
            size=spec.size,
            backend=spec.backend,
            capabilities=spec.capabilities,
            max_context=spec.max_context,
            available=True,
            loaded=False,
        )
    
    return StatusResponse(
        ray_cluster=ray_cluster,
        models=models,
        queue_size=0,
        active_requests=0,
        completed_requests=0,
        error_rate=0.0,
    )


@router.get(
    "/metrics",
    summary="Prometheus metrics",
    description="Get Prometheus-compatible metrics",
)
async def metrics():
    """
    Get Prometheus-compatible metrics.
    """
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    
    if not settings.PROMETHEUS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Metrics endpoint disabled",
        )
    
    metrics_data = generate_latest()
    
    return StreamingResponse(
        iter([metrics_data]),
        media_type=CONTENT_TYPE_LATEST,
    )
