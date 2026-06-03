#!/usr/bin/env python3
"""
DeepSeek Coder Actor

Specialized Ray actor for DeepSeek-Coder model as fallback.

Features:
- Code generation and completion
- Runs on neon-64gb (ARM64 CPU)
- Fallback model for code tasks
- 16K context window
- CPU-only execution

Author: Mistral Vibe
Version: 1.0.0
Date: 2026-06-01

Usage:
    from deepseek_coder_actor import DeepSeekCoderActor
    
    # Create actor on neon-64gb
    actor = DeepSeekCoderActor.options(
        resources={"node:neon-64gb": 1}
    ).remote()
    
    # Generate code
    result_ref = actor.generate.remote("Write a Python class for a binary tree")
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
    "DEEPSEEK_MODEL_URL",
    "http://100.88.57.96:3900/models/DeepSeek-Coder-6.7B-Instruct-Q4_K_M.gguf"
)


@ray.remote(
    name="DeepSeekCoderActor",
    resources={
        "node:neon-64gb": 1,
        "cpu": 6,
        "memory": 12 * 1024 * 1024 * 1024,  # 12GB
    },
    runtime_env={
        "env_vars": {
            "RAY_node_name": "neon-64gb-deepseek-actor"
        }
    }
)
class DeepSeekCoderActor(GGUFInferenceActor):
    """
    Specialized actor for DeepSeek-Coder-6.7B-Instruct-GGUF.
    
    This model excels at:
    - Code generation (Python, JavaScript, Java, C++, etc.)
    - Code completion
    - Code explanation
    - Code repair
    - Code optimization
    
    Configuration:
    - Model: DeepSeek-Coder-6.7B-Instruct-GGUF
    - Quantization: Q4_K_M (4-bit, ~4.5GB RAM)
    - Context: 16,384 tokens
    - CPU-only execution
    - Threads: 6
    - Node: neon-64gb (ARM64)
    """
    
    def __init__(
        self,
        model_url: Optional[str] = None,
        context_length: int = 16384,
        gpu_layers: int = 0,
        threads: int = 6,
        **kwargs: Dict[str, Any]
    ):
        """
        Initialize DeepSeekCoderActor.
        
        Args:
            model_url: URL to model file (defaults to Garage S3)
            context_length: Model context window
            gpu_layers: Number of GPU layers (0 for CPU-only)
            threads: Number of CPU threads
            **kwargs: Additional kwargs for base class
        """
        # Set node name from environment
        node_name = os.environ.get("RAY_node_name", "neon-64gb-deepseek-actor")
        os.environ["RAY_node_name"] = node_name
        
        logger.info(
            f"Initializing DeepSeekCoderActor on node: {node_name}\n"
            f"  Model URL: {model_url or MODEL_URL}\n"
            f"  Context: {context_length}\n"
            f"  Threads: {threads}\n"
            f"  CPU-only: {gpu_layers == 0}"
        )
        
        # Call parent constructor
        super().__init__(
            model_path=model_url or MODEL_URL,
            model_type=ModelType.TEXT,  # DeepSeek is a text/code model
            context_length=context_length,
            gpu_layers=gpu_layers,
            threads=threads,
            # Optimizations for code generation
            repeat_penalty=1.1,
            stop=["\n\n\n", "<|EOT|>", "<|end|>"],
            **kwargs
        )
        
        logger.info(f"DeepSeekCoderActor initialized successfully on {node_name}")


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_deepseek_actor(
    model_url: Optional[str] = None,
    context_length: int = 16384,
    threads: int = 6,
    **kwargs: Dict[str, Any]
) -> ray.ObjectRef:
    """
    Factory function to create DeepSeekCoderActor.
    
    Args:
        model_url: URL to model file
        context_length: Model context window
        threads: Number of CPU threads
        **kwargs: Additional kwargs
        
    Returns:
        ObjectRef to the created actor
    """
    return DeepSeekCoderActor.options(
        resources={
            "node:neon-64gb": 1,
            "cpu": 6,
            "memory": 12 * 1024 * 1024 * 1024,
        }
    ).remote(
        model_url=model_url,
        context_length=context_length,
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
    print("DeepSeekCoderActor - Standalone Test")
    print("=" * 60)
    
    try:
        # Create actor
        print("\n[1/3] Creating DeepSeekCoderActor...")
        actor = create_deepseek_actor()
        print(f"    ✓ Actor created: {actor}")
        
        # Wait for model to load
        print("\n[2/3] Waiting for model to load...")
        import time
        time.sleep(30)  # Give time for model download and loading
        
        # Test generation
        print("\n[3/3] Testing code generation...")
        prompt = "Write a Python function to implement quicksort algorithm"
        print(f"    Prompt: {prompt}")
        
        result_ref = actor.generate.remote(
            prompt=prompt,
            max_tokens=200,
            temperature=0.3
        )
        result = ray.get(result_ref, timeout=120)
        print(f"    Result: {result[:200]}...")
        
        print("\n" + "=" * 60)
        print("✓ DeepSeekCoderActor test passed!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Don't shutdown Ray - let it run for other tests
        pass
