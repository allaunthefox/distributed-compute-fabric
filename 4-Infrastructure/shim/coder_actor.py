#!/usr/bin/env python3
"""
Qwopus3.5-9B Coder Actor

Specialized Ray actor for Qwopus3.5-9B-Coder-MTP-GGUF model.

Features:
- Optimized for code generation tasks
- Runs on qfox-1 with CUDA acceleration
- VCN-LUPINE integration for hardware acceleration
- 32K context window
- 40 GPU layers (optimized for 16GB VRAM)

Author: Mistral Vibe
Version: 1.0.0
Date: 2026-06-01

Usage:
    from coder_actor import QwopusCoderActor
    
    # Create actor on qfox-1 with CUDA
    actor = QwopusCoderActor.options(
        resources={"node:qfox-1": 1, "gpu_type:CUDA": 1, "vcn_enabled": True}
    ).remote()
    
    # Generate code
    result_ref = actor.generate.remote("Write a Python function to reverse a string")
    result = ray.get(result_ref)
"""

import os
import logging
from typing import Optional, Dict, Any

# Import base actor
from .gguf_inference_actor import GGUFInferenceActor, ModelType

# Import Ray
import ray

# Configure logging
logger = logging.getLogger(__name__)

# Model configuration
MODEL_URL = os.environ.get(
    "QWOPUS_MODEL_URL",
    "http://100.88.57.96:3900/models/Qwopus3.5-9B-Coder-MTP-Q4_K_M.gguf"
)


@ray.remote(
    name="QwopusCoderActor",
    resources={
        "node:qfox-1": 1,
        "gpu_type:CUDA": 1,
        "vcn_enabled": True
    },
    runtime_env={
        "env_vars": {
            "LD_PRELOAD": "/usr/local/lib/vcn-lupine.so",
            "RAY_node_name": "qfox-1-coder-actor"
        }
    }
)
class QwopusCoderActor(GGUFInferenceActor):
    """
    Specialized actor for Qwopus3.5-9B-Coder-MTP-GGUF.
    
    This model excels at:
    - Code generation (Python, JavaScript, etc.)
    - Code completion
    - Code explanation
    - MTP (Multi-Task Processing)
    
    Configuration:
    - Model: Qwopus3.5-9B-Coder-MTP-GGUF
    - Quantization: Q4_K_M (4-bit, ~7GB VRAM)
    - Context: 32,768 tokens
    - GPU Layers: 40 (fits on 16GB GPU)
    - Threads: 4
    - Node: qfox-1 (CUDA)
    
    VCN-LUPINE Integration:
    - LD_PRELOAD: /usr/local/lib/vcn-lupine.so
    - Intercepts CUDA calls for H.264 encoding
    - Hardware-accelerated video processing
    """
    
    def __init__(
        self,
        model_url: Optional[str] = None,
        context_length: int = 32768,
        gpu_layers: int = 40,
        threads: int = 4,
        **kwargs: Dict[str, Any]
    ):
        """
        Initialize QwopusCoderActor.
        
        Args:
            model_url: URL to model file (defaults to Garage S3)
            context_length: Model context window
            gpu_layers: Number of GPU layers
            threads: Number of CPU threads
            **kwargs: Additional kwargs for base class
        """
        # Set node name from environment
        node_name = os.environ.get("RAY_node_name", "qfox-1-coder-actor")
        os.environ["RAY_node_name"] = node_name
        
        logger.info(
            f"Initializing QwopusCoderActor on node: {node_name}\n"
            f"  Model URL: {model_url or MODEL_URL}\n"
            f"  Context: {context_length}\n"
            f"  GPU Layers: {gpu_layers}\n"
            f"  Threads: {threads}"
        )
        
        # Call parent constructor
        super().__init__(
            model_path=model_url or MODEL_URL,
            model_type=ModelType.TEXT,
            context_length=context_length,
            gpu_layers=gpu_layers,
            threads=threads,
            # Optimizations for code generation
            repeat_penalty=1.1,
            stop=["\n\n\n", "<|im_end|>", "<|im_sep|>"],
            **kwargs
        )
        
        logger.info(f"QwopusCoderActor initialized successfully on {node_name}")


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_qwopus_actor(
    model_url: Optional[str] = None,
    context_length: int = 32768,
    gpu_layers: int = 40,
    threads: int = 4,
    **kwargs: Dict[str, Any]
) -> ray.ObjectRef:
    """
    Factory function to create QwopusCoderActor.
    
    Args:
        model_url: URL to model file
        context_length: Model context window
        gpu_layers: Number of GPU layers
        threads: Number of CPU threads
        **kwargs: Additional kwargs
        
    Returns:
        ObjectRef to the created actor
    """
    return QwopusCoderActor.options(
        resources={
            "node:qfox-1": 1,
            "gpu_type:CUDA": 1,
            "vcn_enabled": True
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
    print("QwopusCoderActor - Standalone Test")
    print("=" * 60)
    
    try:
        # Create actor
        print("\n[1/3] Creating QwopusCoderActor...")
        actor = create_qwopus_actor()
        print(f"    ✓ Actor created: {actor}")
        
        # Wait for model to load
        print("\n[2/3] Waiting for model to load...")
        import time
        time.sleep(30)  # Give time for model download and loading
        
        # Test generation
        print("\n[3/3] Testing code generation...")
        prompt = "Write a Python function to calculate the Fibonacci sequence"
        print(f"    Prompt: {prompt}")
        
        result_ref = actor.generate.remote(
            prompt=prompt,
            max_tokens=200,
            temperature=0.3
        )
        result = ray.get(result_ref, timeout=120)
        print(f"    Result: {result[:200]}...")
        
        print("\n" + "=" * 60)
        print("✓ QwopusCoderActor test passed!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Don't shutdown Ray - let it run for other tests
        pass
