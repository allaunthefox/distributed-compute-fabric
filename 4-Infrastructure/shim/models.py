"""
Hermes Model Definitions

This module contains all data models and the model registry for the Hermes orchestrator.

Author: Mistral Vibe
Version: 1.0.0
Date: 2026-06-01
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


def get_model_spec(model_type: ModelType) -> Optional[ModelSpec]:
    """Get model specification by type."""
    return MODEL_REGISTRY.get(model_type)


def get_model_spec_by_name(model_name: str) -> Optional[ModelSpec]:
    """Get model specification by name."""
    for spec in MODEL_REGISTRY.values():
        if spec.name.lower() == model_name.lower():
            return spec
    return None


def list_all_models() -> List[ModelSpec]:
    """List all available model specifications."""
    return list(MODEL_REGISTRY.values())
