"""
Hermes Orchestrator Router

Defines all API endpoints for model inference.

Author: Mistral Vibe
Version: 1.0.0
Date: 2026-06-01
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
import time

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from hermes.models import ModelType, MODEL_REGISTRY, ModelSpec
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
        token_counter.labels(model=str(request.model_type or "auto"), direction="output").inc(
            result.get("tokens_generated", 0)
        )
        token_counter.labels(model=str(request.model_type or "auto"), direction="input").inc(
            result.get("tokens_input", 0)
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
        error_counter.labels(model=str(request.model_type or "auto"), error_type="generation").inc()
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
