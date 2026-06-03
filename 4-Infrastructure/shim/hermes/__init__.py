"""
Hermes Orchestrator Package

Hermes is the REST API orchestrator for the GGUF-Ray-VCN-LUPINE deployment.
It provides intelligent model routing, load balancing, circuit breaking,
and batch processing for distributed GGUF model inference.

Main Components:
- main.py: FastAPI application entry point
- config.py: Configuration management
- models.py: Data models and model registry
- orchestrator.py: API router with inference endpoints
- frame_dispatcher.py: Intelligent request router
- actors/: Model-specific Ray actor implementations

Author: Mistral Vibe
Version: 1.0.0
Date: 2026-06-01
"""

# Import core modules that don't have external dependencies
from .models import ModelType, MODEL_REGISTRY, ModelSpec

# Try to import optional modules (may fail if dependencies not installed)
try:
    from .config import settings
except ImportError:
    settings = None

try:
    from .frame_dispatcher import FrameDispatcher, get_dispatcher
except ImportError:
    FrameDispatcher = None
    get_dispatcher = None

try:
    from .orchestrator import router as orchestrator_router
except ImportError:
    orchestrator_router = None

try:
    from .main import app
except ImportError:
    app = None

__all__ = [
    "app",
    "settings",
    "ModelType",
    "MODEL_REGISTRY",
    "ModelSpec",
    "FrameDispatcher",
    "get_dispatcher",
    "orchestrator_router",
]
