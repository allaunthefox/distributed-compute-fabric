#!/usr/bin/env python3
"""
Test Script: Ask Gemma 4 to Review the Codebase

This script tests the GemmaGeneralActor by asking it to review
the ray-actors codebase for issues, improvements, and suggestions.

Usage (on a machine with Ray cluster access):
    python3 test_gemma4_review.py

Or via Ray job submission:
    ray job submit --working-dir . -- python3 test_gemma4_review.py

Requirements:
    - Ray cluster access (neon-64gb node must be available)
    - Gemma-4-E4B-Uncensored-Q8_K_P.gguf model on Garage S3
    - Python 3.10+ with ray package installed
"""

import os
import sys
import time
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add ray-actors directory to path
RAY_ACTORS_DIR = Path(__file__).parent
if str(RAY_ACTORS_DIR) not in sys.path:
    sys.path.insert(0, str(RAY_ACTORS_DIR))


def get_codebase_files() -> dict[str, str]:
    """
    Collect codebase files for review.
    
    Returns:
        Dict mapping filename to content
    """
    files = {}
    
    # Files to include in review
    target_files = [
        "general_actor.py",
        "vision_actor.py",
        "deepseek_coder_actor.py",
        "coder_actor.py",
        "gguf_inference_actor.py",
        "__init__.py"
    ]
    
    for filename in target_files:
        filepath = RAY_ACTORS_DIR / filename
        if filepath.exists():
            with open(filepath, 'r') as f:
                files[filename] = f.read()
    
    return files


def build_review_prompt(files: dict[str, str]) -> str:
    """
    Build a prompt asking Gemma 4 to review the codebase.
    
    Args:
        files: Dict mapping filename to content
        
    Returns:
        Formatted prompt string
    """
    prompt = """You are an expert software engineer reviewing a Python codebase for a Ray-based LLM inference system.

Please review the following code files and provide:
1. **Issues Found**: Any bugs, errors, or problematic patterns
2. **Improvements**: Suggestions for better code quality, performance, or maintainability
3. **Security**: Any security concerns or best practices violations
4. **Architecture**: Feedback on the overall design and structure
5. **Documentation**: Missing or unclear documentation

Be specific and provide line numbers or code snippets when pointing out issues.

"""
    
    for filename, content in files.items():
        prompt += f"\n{'='*60}\n"
        prompt += f"FILE: {filename}\n"
        prompt += f"{'='*60}\n"
        prompt += content
        prompt += "\n"
    
    prompt += """
Please provide your review in a structured format with clear sections for each category above.
Focus on actionable feedback that can be used to improve the codebase.
"""
    
    return prompt


def main():
    """Main test function."""
    import ray
    
    print("=" * 70)
    print("Gemma 4 Codebase Review Test")
    print("=" * 70)
    
    # Initialize Ray
    print("\n[1/5] Connecting to Ray cluster...")
    try:
        if not ray.is_initialized():
            ray.init(
                address="auto",
                ignore_reinit_error=True,
                log_to_driver=True
            )
        print("    ✓ Connected to Ray cluster")
        print(f"    Cluster resources: {ray.cluster_resources()}")
    except Exception as e:
        print(f"    ✗ Failed to connect to Ray cluster: {e}")
        print("\n    Make sure you're running this on a machine with Ray cluster access.")
        print("    Try: ray start --head (for local) or set RAY_ADDRESS")
        sys.exit(1)
    
    # Collect codebase files
    print("\n[2/5] Collecting codebase files...")
    files = get_codebase_files()
    print(f"    ✓ Collected {len(files)} files:")
    for filename in files:
        print(f"      - {filename}")
    
    # Build review prompt
    print("\n[3/5] Building review prompt...")
    prompt = build_review_prompt(files)
    print(f"    ✓ Prompt length: {len(prompt)} characters")
    
    # Create Gemma actor
    print("\n[4/5] Creating GemmaGeneralActor...")
    print("    (This may take a few minutes to download and load the model)")
    try:
        from general_actor import GemmaGeneralActor
        
        actor = GemmaGeneralActor.options(
            resources={
                "node:neon-64gb": 1,
                "gpu_type:CPU": 1
            }
        ).remote()
        print("    ✓ Actor created")
        
        # Wait for model to load
        print("    Waiting for model to load...")
        time.sleep(10)  # Give it time to initialize
        
    except Exception as e:
        print(f"    ✗ Failed to create actor: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Generate review
    print("\n[5/5] Asking Gemma 4 to review the codebase...")
    print("    (This may take several minutes for a large codebase)")
    try:
        result_ref = actor.generate.remote(
            prompt=prompt,
            max_tokens=4000,  # Allow for detailed review
            temperature=0.3,  # Lower temperature for more focused review
            top_p=0.9
        )
        
        # Wait for result with timeout
        result = ray.get(result_ref, timeout=600)  # 10 minute timeout
        
        print("\n" + "=" * 70)
        print("GEMMA 4 CODEBASE REVIEW")
        print("=" * 70)
        print(result)
        print("=" * 70)
        
        # Save review to file
        output_file = Path("/tmp/gemma4_codebase_review.txt")
        with open(output_file, 'w') as f:
            f.write(result)
        print(f"\n✓ Review saved to: {output_file}")
        
    except ray.exceptions.GetTimeoutError:
        print("    ✗ Request timed out (10 minutes)")
        print("    The model may be taking too long. Try reducing max_tokens.")
    except Exception as e:
        print(f"    ✗ Generation failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        print("\nCleaning up...")
        try:
            ray.kill(actor)
            print("    ✓ Actor killed")
        except:
            pass
        ray.shutdown()
        print("    ✓ Ray shutdown")
    
    print("\n" + "=" * 70)
    print("Test complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()