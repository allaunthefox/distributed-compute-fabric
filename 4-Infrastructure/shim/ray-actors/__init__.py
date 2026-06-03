"""
GGUF Ray VCN-LUPINE Actors Package

This package contains the base actor classes for GGUF model inference
with Ray distributed computing and VCN-LUPINE hardware acceleration.

Main Classes:
- GGUFInferenceActor: Base class for all GGUF model actors

Author: Mistral Vibe
Version: 1.0.0
Date: 2026-06-01
"""

from .gguf_inference_actor import GGUFInferenceActor, ModelType

__all__ = [
    "GGUFInferenceActor",
    "ModelType",
]
