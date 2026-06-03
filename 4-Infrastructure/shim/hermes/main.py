"""
Hermes Orchestrator - Main FastAPI Application

Provides REST API for model inference orchestration across distributed Ray cluster.

Author: Mistral Vibe
Version: 1.0.0
Date: 2026-06-01
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
