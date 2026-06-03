#!/usr/bin/env python3
"""
Gemma-4-E4B Multimodal Actor

Specialized Ray actor for Gemma-4-E4B-Uncensored GGUF model.
Gemma 4 is natively multimodal: text + image + audio + video.

Features:
- General text generation
- Image understanding (vision)
- Audio transcription and understanding
- Video understanding (frame sampling)
- Runs on neon-64gb (ARM64 CPU)
- Optional VCN-LUPINE integration
- 32K context window
- CPU-only (no GPU layers)
- Optimized for 16 threads on neon-64gb

Gemma 4 Configuration (from HuggingFace docs):
- Image processor: Gemma4ImageProcessor (resize, normalize, convert to RGB)
- Video processor: Gemma4VideoProcessor (frame sampling, resize, crop)
- Audio: native audio input support via processor
- Vision: native image input support

Author: Mistral Vibe
Version: 1.1.0
Date: 2026-06-02

Usage:
    from general_actor import GemmaGeneralActor
    
    # Create actor on neon-64gb
    actor = GemmaGeneralActor.options(
        resources={"node:neon-64gb": 1}
    ).remote()
    
    # Text-only generation
    result_ref = actor.generate.remote("Explain quantum computing")
    
    # Image + text (vision)
    result_ref = actor.generate.remote(
        prompt="Describe this image",
        images=["https://example.com/photo.jpg"]
    )
    
    result = ray.get(result_ref)
"""

import os
import logging
from typing import Optional, Dict, Any, List, Union
from pathlib import Path

# Import base actor
from .gguf_inference_actor import GGUFInferenceActor, ModelType

# Import Ray
import ray

# Configure logging
logger = logging.getLogger(__name__)

# Model configuration
MODEL_URL = os.environ.get(
    "GEMMA_MODEL_URL",
    "http://100.88.57.96:3900/models/Gemma-4-E4B-Uncensored-Q8_K_P.gguf"
)


@ray.remote(
    name="GemmaGeneralActor",
    resources={
        "node:neon-64gb": 1,
        "gpu_type:CPU": 1
    },
    runtime_env={
        "env_vars": {
            "LD_PRELOAD": "/usr/local/lib/vcn-lupine.so",
            "RAY_node_name": "neon-64gb-general-actor",
            # CPU optimizations
            "OMP_NUM_THREADS": "16",
            "NUMA": "true"
        }
    }
)
class GemmaGeneralActor(GGUFInferenceActor):
    """
    Multimodal actor for Gemma-4-E4B-Uncensored GGUF model.
    
    Gemma 4 is natively multimodal (text + image + audio + video):
    - Text: general generation, conversation, QA, analysis
    - Image: vision understanding, image description, OCR
    - Audio: transcription, audio understanding
    - Video: frame sampling, video understanding
    
    Configuration:
    - Model: Gemma-4-E4B-Uncensored-GGUF
    - Quantization: Q8_K_P (8-bit, ~10GB CPU RAM)
    - Context: 32,768 tokens
    - GPU Layers: None (CPU-only)
    - Threads: 16 (uses all neon-64gb cores)
    - Node: neon-64gb (ARM64)
    
    Gemma 4 Processor Config (from HuggingFace):
    - Image: resize (default 896x896), normalize (ImageNet mean/std), RGB conversion
    - Video: frame sampling (fps-based), resize, center crop
    - Audio: native audio processor integration
    
    VCN-LUPINE Integration:
    - LD_PRELOAD: /usr/local/lib/vcn-lupine.so (optional)
    - Can use for video encoding even on CPU
    
    Note:
    - Runs on ARM64 (neon-64gb)
    - Uses OpenBLAS for ARM64
    - NUMA-optimized for multi-core
    """
    
    def __init__(
        self,
        model_url: Optional[str] = None,
        context_length: int = 32768,
        gpu_layers: Optional[int] = None,
        threads: int = 16,
        **kwargs: Dict[str, Any]
    ):
        """
        Initialize GemmaGeneralActor (multimodal).
        
        Args:
            model_url: URL to model file
            context_length: Model context window
            gpu_layers: Number of GPU layers (None for CPU-only)
            threads: Number of CPU threads (16 for neon-64gb)
            **kwargs: Additional kwargs for base class
        """
        # Set node name from environment
        node_name = os.environ.get("RAY_node_name", "neon-64gb-general-actor")
        os.environ["RAY_node_name"] = node_name
        
        logger.info(
            f"Initializing GemmaGeneralActor (multimodal) on node: {node_name}\n"
            f"  Model URL: {model_url or MODEL_URL}\n"
            f"  Context: {context_length}\n"
            f"  GPU Layers: {gpu_layers}\n"
            f"  Threads: {threads}\n"
            f"  Modalities: text, image, audio, video\n"
            f"  CPU-only: True"
        )
        
        # Call parent constructor with MULTIMODAL type
        # Gemma 4 supports text + image + audio + video natively
        super().__init__(
            model_path=model_url or MODEL_URL,
            model_type=ModelType.MULTIMODAL,  # Gemma 4 is multimodal
            context_length=context_length,
            gpu_layers=gpu_layers,  # None = CPU-only
            threads=threads,
            # ARM64/CPU-specific optimizations
            llm_kwargs={
                "numa": True,  # Enable NUMA for multi-core
                "batch_size": 512,  # Larger batch size for CPU
                "use_mmap": True,  # Memory-mapped files
                "use_mlock": False,  # Don't lock memory (can cause issues on some systems)
                **kwargs.get("llm_kwargs", {})
            }
        )
        
        logger.info(f"GemmaGeneralActor (multimodal) initialized successfully on {node_name}")


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_gemma_actor(
    model_url: Optional[str] = None,
    context_length: int = 32768,
    gpu_layers: Optional[int] = None,
    threads: int = 16,
    **kwargs: Dict[str, Any]
) -> ray.ObjectRef:
    """
    Factory function to create GemmaGeneralActor.
    
    Args:
        model_url: URL to model file
        context_length: Model context window
        gpu_layers: Number of GPU layers
        threads: Number of CPU threads
        **kwargs: Additional kwargs
        
    Returns:
        ObjectRef to the created actor
    """
    return GemmaGeneralActor.options(
        resources={
            "node:neon-64gb": 1,
            "gpu_type:CPU": 1
        }
    ).remote(
        model_url=model_url,
        context_length=context_length,
        gpu_layers=gpu_layers,
        threads=threads,
        **kwargs
    )


# =============================================================================
# MAIN - For testing
# =============================================================================

if __name__ == "__main__":
    import ray
    
    # Initialize Ray
    if not ray.is_initialized():
        ray.init(
            address="auto",
            ignore_reinit_error=True,
            log_to_driver=False,
            log_monitor_interval=10
        )
    
    print("=" * 60)
    print("GemmaGeneralActor - Standalone Test")
    print("=" * 60)
    
    try:
        # Create actor
        print("\n[1/3] Creating GemmaGeneralActor...")
        actor = create_gemma_actor()
        print(f"    ✓ Actor created: {actor}")
        
        # Wait for model to load
        print("\n[2/3] Waiting for model to load...")
        import time
        time.sleep(30)
        
        # Test generation
        print("\n[3/3] Testing general text generation...")
        prompt = "Explain the concept of artificial intelligence in simple terms"
        print(f"    Prompt: {prompt}")
        
        result_ref = actor.generate.remote(
            prompt=prompt,
            max_tokens=200,
            temperature=0.9
        )
        result = ray.get(result_ref, timeout=120)
        print(f"    Result: {result[:200]}...")
        
        print("\n" + "=" * 60)
        print("✓ GemmaGeneralActor test passed!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        pass
