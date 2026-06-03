#!/usr/bin/env python3
"""
Llava-1.5-7B Vision Actor

Specialized Ray actor for Llava-1.5-7B vision model.

Features:
- Multimodal (text + image) inference
- Runs on steamdeck with VAAPI acceleration
- VCN-LUPINE integration for hardware video processing
- 32K context window
- 35 GPU layers (optimized for VAAPI)

NOTE: Gemma 4 Alternative for Vision Tasks
-------------------------------------------
Gemma 4 (GemmaGeneralActor) is natively multimodal and can also handle
vision tasks (image + audio + video) on CPU without VAAPI:
- Model: Gemma-4-E4B-Uncensored-Q8_K_P.gguf
- Node: neon-64gb (ARM64 CPU)
- Modalities: text + image + audio + video
- See: https://huggingface.co/docs/transformers/en/model_doc/gemma4

Use LlavaVisionActor when:
- You need VAAPI hardware acceleration (steamdeck)
- You want GPU-accelerated vision processing
- You need VCN-LUPINE video encoding integration

Use GemmaGeneralActor when:
- You need audio or video understanding (not just images)
- You prefer CPU-only inference (neon-64gb)
- You want a single model for all modalities

Author: Mistral Vibe
Version: 1.1.0
Date: 2026-06-02

Usage:
    from vision_actor import LlavaVisionActor
    
    # Create actor on steamdeck with VAAPI
    actor = LlavaVisionActor.options(
        resources={"node:steamdeck": 1, "gpu_type:VAAPI": 1, "vcn_enabled": True}
    ).remote()
    
    # Generate vision response
    result_ref = actor.generate.remote(
        prompt="Describe this image",
        images=["https://example.com/image.jpg"]
    )
    result = ray.get(result_ref)
"""

import os
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

# Import base actor (ray-actors dir added to sys.path by frame_dispatcher)
from gguf_inference_actor import GGUFInferenceActor, ModelType

# Import Ray
import ray

# Configure logging
logger = logging.getLogger(__name__)

# Model configuration
MODEL_URL = os.environ.get(
    "LLAVA_MODEL_URL",
    "http://100.88.57.96:3900/models/Llava-1.5-7B-Q4_K_M.gguf"
)

# MMProj file (required for vision models)
MMPROJ_URL = os.environ.get(
    "LLAVA_MMPROJ_URL",
    "http://100.88.57.96:3900/models/Llava-1.5-7B-mmproj-Q4_K_M.gguf"
)


@ray.remote(
    name="LlavaVisionActor",
    resources={
        "node:steamdeck": 1,
        "gpu_type:VAAPI": 1,
        "vcn_enabled": True
    },
    runtime_env={
        "env_vars": {
            "LD_PRELOAD": "/usr/local/lib/vcn-lupine.so",
            "RAY_node_name": "steamdeck-vision-actor",
            # VAAPI-specific environment variables
            "LIBVA_DRIVER_NAME": "iHD",  # Intel or "r600" for AMD
            "LIBVA_DRIVERS_PATH": "/usr/lib/x86_64-linux-gnu/dri"
        }
    }
)
class LlavaVisionActor(GGUFInferenceActor):
    """
    Specialized actor for Llava-1.5-7B vision model.
    
    This model excels at:
    - Image description
    - Visual question answering
    - Image analysis
    - Multimodal understanding
    
    Configuration:
    - Model: Llava-1.5-7B-GGUF
    - MMProj: Llava-1.5-7B-mmproj-Q4_K_M.gguf
    - Quantization: Q4_K_M (4-bit, ~8GB VRAM)
    - Context: 32,768 tokens
    - GPU Layers: 35 (optimized for VAAPI)
    - Threads: 4
    - Node: steamdeck (VAAPI)
    
    VCN-LUPINE Integration:
    - LD_PRELOAD: /usr/local/lib/vcn-lupine.so
    - Intercepts VAAPI calls for H.264 encoding
    - Hardware-accelerated video processing
    
    Requirements:
    - llm Python bindings with multimodal support
    - Pillow for image processing
    - httpx for image downloading
    """
    
    def __init__(
        self,
        model_url: Optional[str] = None,
        mmproj_url: Optional[str] = None,
        context_length: int = 32768,
        gpu_layers: int = 35,
        threads: int = 4,
        **kwargs: Dict[str, Any]
    ):
        """
        Initialize LlavaVisionActor.
        
        Args:
            model_url: URL to model file
            mmproj_url: URL to mmproj file
            context_length: Model context window
            gpu_layers: Number of GPU layers
            threads: Number of CPU threads
            **kwargs: Additional kwargs for base class
        """
        # Set node name from environment
        node_name = os.environ.get("RAY_node_name", "steamdeck-vision-actor")
        os.environ["RAY_node_name"] = node_name
        
        # Store mmproj URL for potential download
        self.mmproj_url = mmproj_url or MMPROJ_URL
        
        logger.info(
            f"Initializing LlavaVisionActor on node: {node_name}\n"
            f"  Model URL: {model_url or MODEL_URL}\n"
            f"  MMProj URL: {self.mmproj_url}\n"
            f"  Context: {context_length}\n"
            f"  GPU Layers: {gpu_layers}\n"
            f"  Threads: {threads}"
        )
        
        # Download mmproj if needed
        self._download_mmproj()
        
        # Call parent constructor
        super().__init__(
            model_path=model_url or MODEL_URL,
            model_type=ModelType.VISION,
            context_length=context_length,
            gpu_layers=gpu_layers,
            threads=threads,
            **kwargs
        )
        
        logger.info(f"LlavaVisionActor initialized successfully on {node_name}")
    
    def _download_mmproj(self):
        """Download MMProj file if not already present."""
        from pathlib import Path
        from .gguf_inference_actor import MODEL_CACHE_DIR
        import httpx
        
        # Expected mmproj path
        expected_mmproj = (Path(self.model_path) if Path(self.model_path).exists() 
                        else Path(MODEL_CACHE_DIR) / Path(self.model_path).name).replace(
            ".gguf", ".mmproj"
        )
        
        # Check if mmproj exists
        if expected_mmproj.exists():
            logger.info(f"[{os.environ.get('RAY_node_name', 'unknown')}] MMProj already exists: {expected_mmproj}")
            return
        
        # Download mmproj
        logger.info(f"[{os.environ.get('RAY_node_name', 'unknown')}] Downloading MMProj from: {self.mmproj_url}")
        
        try:
            with httpx.stream("GET", self.mmproj_url, timeout=300) as response:
                response.raise_for_status()
                with open(expected_mmproj, "wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
            
            logger.info(f"[{os.environ.get('RAY_node_name', 'unknown')}] MMProj downloaded to: {expected_mmproj}")
            
        except Exception as e:
            logger.error(f"[{os.environ.get('RAY_node_name', 'unknown')}] Failed to download MMProj: {e}")
            # Continue anyway - model might work without it
    
    def generate(
        self,
        prompt: str,
        images: Optional[List[str]] = None,
        max_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 0.9,
        **kwargs
    ) -> str:
        """
        Generate response from prompt and images.
        
        For vision models, images are required for meaningful responses.
        
        Args:
            prompt: Text prompt describing what to do with images
            images: List of image URLs or paths
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Top-p sampling
            **kwargs: Additional kwargs
            
        Returns:
            Generated text describing or analyzing the images
        """
        # Warn if no images provided for vision model
        if not images:
            logger.warning(
                f"[{os.environ.get('RAY_node_name', 'unknown')}] "
                "No images provided for vision model. Results may be poor."
            )
        
        # Call parent generate (handles multimodal prompt building)
        return super().generate(
            prompt=prompt,
            images=images,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            **kwargs
        )


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_llava_actor(
    model_url: Optional[str] = None,
    mmproj_url: Optional[str] = None,
    context_length: int = 32768,
    gpu_layers: int = 35,
    threads: int = 4,
    **kwargs: Dict[str, Any]
) -> ray.ObjectRef:
    """
    Factory function to create LlavaVisionActor.
    
    Args:
        model_url: URL to model file
        mmproj_url: URL to mmproj file
        context_length: Model context window
        gpu_layers: Number of GPU layers
        threads: Number of CPU threads
        **kwargs: Additional kwargs
        
    Returns:
        ObjectRef to the created actor
    """
    return LlavaVisionActor.options(
        resources={
            "node:steamdeck": 1,
            "gpu_type:VAAPI": 1,
            "vcn_enabled": True
        }
    ).remote(
        model_url=model_url,
        mmproj_url=mmproj_url,
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
    print("LlavaVisionActor - Standalone Test")
    print("=" * 60)
    
    try:
        # Create actor
        print("\n[1/3] Creating LlavaVisionActor...")
        actor = create_llava_actor()
        print(f"    ✓ Actor created: {actor}")
        
        # Wait for model to load
        print("\n[2/3] Waiting for model to load...")
        import time
        time.sleep(30)
        
        # Test with a simple prompt (no images - just test model loads)
        print("\n[3/3] Testing vision model (no images)...")
        prompt = "Describe what you see."
        print(f"    Prompt: {prompt}")
        
        result_ref = actor.generate.remote(
            prompt=prompt,
            max_tokens=50
        )
        result = ray.get(result_ref, timeout=60)
        print(f"    Result: {result[:200]}...")
        
        print("\n" + "=" * 60)
        print("✓ LlavaVisionActor test passed!")
        print("=" * 60)
        print("\nNote: For full vision testing, provide actual images.")
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        pass
