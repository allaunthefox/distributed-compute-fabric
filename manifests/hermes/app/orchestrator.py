#!/usr/bin/env python3
"""
Hermes Orchestrator - Multi-Model Chat with Tool Calling

This is the main Hermes service that acts as an orchestrator.
It routes requests to specialist models (coder, math) when needed,
then synthesizes the final response.

Architecture:
    User Request -> Hermes Orchestrator -> (optional: Coder Model) -> Final Response

Environment Variables:
    - CODER_MODEL_URL: URL for the coder specialist model (e.g., http://coder-model:80)
    - MATH_MODEL_URL: URL for math specialist (defaults to coder if not set)
    - HERMES_MODEL_PATH: Path to Hermes' own GGUF model
    - ORCHESTRATOR_ENABLED: "true" to enable tool calling
    - ORCHESTRATOR_TIMEOUT_SECONDS: Timeout for tool calls
    - MATH_PATTERN: Regex to detect math requests
    - CODE_PATTERN: Regex to detect code requests

Endpoints:
    POST /v1/chat/completions - OpenAI-compatible chat endpoint
    GET  /health - Health check
    GET  /ready - Readiness check
"""

import asyncio
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# =============================================================================
# Configuration
# =============================================================================

# Load configuration from environment
CODER_MODEL_URL = os.getenv("CODER_MODEL_URL", "http://coder-model.services.svc.cluster.local")
QWOMPUS_MODEL_URL = os.getenv("QWOMPUS_MODEL_URL", "http://qwopus-model.services.svc.cluster.local")
QWEN2_MODEL_URL = os.getenv("QWEN2_MODEL_URL", "http://qwen2-model.services.svc.cluster.local")
LLAVA_MODEL_URL = os.getenv("LLAVA_MODEL_URL", "http://llava-model.services.svc.cluster.local")
MATH_MODEL_URL = os.getenv("MATH_MODEL_URL", CODER_MODEL_URL)
ORCHESTRATOR_ENABLED = os.getenv("ORCHESTRATOR_ENABLED", "false").lower() == "true"
ORCHESTRATOR_TIMEOUT = float(os.getenv("ORCHESTRATOR_TIMEOUT_SECONDS", "60"))
MAX_RETRIES = int(os.getenv("ORCHESTRATOR_MAX_RETRIES", "3"))

# Compile regex patterns for tool detection
MATH_PATTERN = os.getenv("MATH_PATTERN", r"(math|proof|equation|theorem|formula|calculate|solve|derive|\\int|\\sum|\\frac|\\sqrt)")
CODE_PATTERN = os.getenv("CODE_PATTERN", r"(def |class |import |from |for |while |if |else |return |print\(\)|# |// |/\\*|\\*/|python|javascript|java|cpp|rust)")

try:
    MATH_REGEX = re.compile(MATH_PATTERN, re.IGNORECASE)
except:
    MATH_REGEX = re.compile(r"math|proof|equation", re.IGNORECASE)

try:
    CODE_REGEX = re.compile(CODE_PATTERN, re.IGNORECASE)
except:
    CODE_REGEX = re.compile(r"def |class |import |for |while", re.IGNORECASE)

# Image detection - check for base64 image data or image URLs
IMAGE_PATTERN = r"(data:image/|\.jpg|\.jpeg|\.png|\.gif|\.webp|<image>|base64|attachment)"
try:
    IMAGE_REGEX = re.compile(IMAGE_PATTERN, re.IGNORECASE)
except:
    IMAGE_REGEX = re.compile(r"data:image/|\.jpg|\.png", re.IGNORECASE)

# =============================================================================
# Models (Pydantic)
# =============================================================================

class Message(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: List[Message]
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=4096, ge=1, le=32768)
    stream: Optional[bool] = False
    top_p: Optional[float] = Field(default=0.9, ge=0.0, le=1.0)
    stop: Optional[List[str]] = None

class Choice(BaseModel):
    index: int
    message: Message
    finish_reason: str

class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: Usage

# =============================================================================
# Helper Functions
# =============================================================================

app = FastAPI(title="Hermes Orchestrator")

# Global HTTP client for tool calls
http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(ORCHESTRATOR_TIMEOUT),
    limits=httpx.Limits(max_keepalive_connections=20, max_connections=100)
)

@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()


def generate_id() -> str:
    """Generate a unique ID for responses."""
    return f"hermes-{int(time.time() * 1000)}-{os.urandom(4).hex()}"


def is_math_request(prompt: str) -> bool:
    """Check if the prompt contains math-related content."""
    return bool(MATH_REGEX.search(prompt))


def is_code_request(prompt: str) -> bool:
    """Check if the prompt contains code-related content."""
    return bool(CODE_REGEX.search(prompt))


def has_image(content: str) -> bool:
    """Check if content contains image data (base64 or URL)."""
    # Check for base64 image data
    if IMAGE_REGEX.search(content):
        return True
    # Check if content is a list (OpenAI format with images)
    # In OpenAI API, images are in content array with type: "image_url"
    return False


def has_image_message(messages: List[Dict]) -> bool:
    """Check if any message in the conversation contains images."""
    for msg in messages:
        content = msg.get("content", "")
        # Handle both string and array content formats
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    return True
        elif isinstance(content, str):
            if has_image(content):
                return True
    return False


def needs_tool_call(prompt: str, messages: List[Dict] = None) -> str:
    """
    Determine if a prompt needs tool calling and which tool.
    
    Uses smart routing:
    - [qwopus] or generation keywords → Qwopus (code generation)
    - [code] or analysis keywords → DeepSeek-Coder (code analysis)
    - [math] or math keywords → DeepSeek-Coder (math)
    - [qwen]/[general] → Qwen2 (general)
    - Images → Llava (vision)
    - Auto-detect code → Routes to best coder based on intent
    
    Args:
        prompt: The user's text prompt
        messages: Full message history (for detecting images in content arrays)
    
    Returns: 'math', 'code', 'qwopus', 'qwen2', 'llava', or None
    """
    if not ORCHESTRATOR_ENABLED:
        return None
    
    prompt_lower = prompt.lower()
    
    # Check for explicit tool selection
    if "[math]" in prompt_lower:
        return "code"  # Use DeepSeek for math (MATH_MODEL_URL = CODER_MODEL_URL)
    if "[code]" in prompt_lower or "[analyze]" in prompt_lower or "[review]" in prompt_lower:
        return "code"  # Use DeepSeek for code analysis
    if "[qwopus]" in prompt_lower or "[generate]" in prompt_lower or "[write]" in prompt_lower:
        return "qwopus"  # Use Qwopus for code generation
    if "[qwen]" in prompt_lower or "[general]" in prompt_lower:
        return "qwen2"
    if "[image]" in prompt_lower or "[vision]" in prompt_lower or "[llava]" in prompt_lower:
        return "llava"
    
    # Check for images in message history (OpenAI multimodal format)
    if messages and has_image_message(messages):
        return "llava"
    
    # Check prompt for image references
    if has_image(prompt):
        return "llava"
    
    # Auto-detect based on text patterns
    if is_math_request(prompt):
        return "code"  # DeepSeek is better at math
    if is_code_request(prompt):
        # Smart routing: determine if it's generation or analysis
        if any(word in prompt_lower for word in ["write", "generate", "create", "build", "make", "code for"]):
            return "qwopus"  # Generation task
        else:
            return "code"  # Analysis/review task
    
    # Default to qwen2 for general analysis
    # (Uncomment below to use qwen2 as default specialist)
    # return "qwen2"
    
    return None


async def call_tool_model(
    tool_url: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.1,
    max_tokens: int = 2048
) -> Dict[str, Any]:
    """
    Call a specialist tool model (coder or math) and return the response.
    Uses retry logic for reliability.
    """
    payload = {
        "model": "coder-model",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "stop": ["<|im_start|>", "<|im_end|>"],
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            response = await http_client.post(
                f"{tool_url}/v1/chat/completions",
                json=payload,
                timeout=ORCHESTRATOR_TIMEOUT
            )
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code in (429, 502, 503, 504):
                # Rate limited or server error - retry
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
            else:
                raise HTTPException(
                    status_code=500,
                    detail=f"Tool model error: {response.status_code} - {response.text}"
                )
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise HTTPException(status_code=500, detail=f"Tool model timeout: {e}")
    
    raise HTTPException(status_code=500, detail="Max retries exceeded for tool call")


async def build_tool_prompt(user_prompt: str, tool_type: str) -> List[Dict[str, str]]:
    """
    Build the prompt for a specialist tool based on the request type.
    For Llava, preserves the original message format (which may include images).
    """
    if tool_type == "math":
        system_prompt = """You are a mathematical reasoning assistant. 
Analyze the following math problem, proof, or calculation. 
Provide step-by-step reasoning. If there are errors, point them out clearly.
Be precise and rigorous in your analysis."""
    elif tool_type == "qwopus":
        system_prompt = """You are Qwopus, a code generation specialist. 
Write, generate, or complete the following code. 
Provide working, efficient code with comments where appropriate.
Follow best practices and modern conventions."""
    elif tool_type == "qwen2":
        system_prompt = """You are Qwen2, a general-purpose reasoning assistant. 
Provide a comprehensive analysis of the following request. 
Be thorough, accurate, and helpful in your response."""
    elif tool_type == "llava":
        # For vision, use a minimal system prompt and pass original content
        # The original messages already contain the images in proper format
        system_prompt = """You are Llava, a vision-language assistant. 
Describe and analyze the images provided. Be detailed and accurate."""
    else:  # code (DeepSeek-Coder for analysis)
        system_prompt = """You are a code analysis assistant. 
Review the following code or mathematical work. 
Check for correctness, potential bugs, edge cases, and improvements.
Respond in a structured format with clear analysis."""
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Analyze this: {user_prompt}"}
    ]


async def synthesize_final_response(
    user_prompt: str,
    tool_response: str,
    hermes_model_response: Optional[str] = None
) -> str:
    """
    Synthesize the final response combining tool analysis and Hermes' own response.
    """
    if hermes_model_response:
        # If we have both, combine them intelligently
        return f"""## Tool Analysis

{tool_response}

## Hermes Response

{hermes_model_response}

---
*Note: This response combines automatic tool analysis with Hermes' reasoning.*"""
    
    # If we only have tool response, just return it
    return tool_response


# =============================================================================
# Main Endpoints
# =============================================================================

@app.post("/v1/chat/completions")
async def chat_completion(request: ChatCompletionRequest):
    """
    OpenAI-compatible chat completion endpoint.
    
    If orchestration is enabled and the prompt contains math/code,
    it will first call the specialist model for analysis.
    """
    # Extract the latest user message
    user_message = None
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_message = msg.content
            break
    
    if not user_message:
        raise HTTPException(status_code=400, detail="No user message found")
    
    # Check if we need to use a tool
    tool_type = needs_tool_call(user_message, request.messages)
    tool_response_content = None
    
    if tool_type:
        # Step 1: Call the specialist tool
        # Map tool type to URL
        tool_url_map = {
            "math": MATH_MODEL_URL,
            "code": CODER_MODEL_URL,  # DeepSeek-Coder (analysis)
            "qwopus": QWOMPUS_MODEL_URL,  # Qwopus (generation)
            "qwen2": QWEN2_MODEL_URL,
            "llava": LLAVA_MODEL_URL
        }
        tool_url = tool_url_map.get(tool_type, CODER_MODEL_URL)
        tool_messages = await build_tool_prompt(user_message, tool_type)
        
        try:
            tool_response = await call_tool_model(
                tool_url=tool_url,
                messages=tool_messages,
                temperature=0.1,  # Low temperature for deterministic analysis
                max_tokens=2048
            )
            tool_response_content = tool_response["choices"][0]["message"]["content"]
        except HTTPException as e:
            # If tool call fails, proceed without it but log
            print(f"Warning: Tool call failed: {e.detail}")
            tool_type = None
    
    # Step 2: Build final response
    # For now, if we have tool response, return it directly
    # In a full implementation, you would:
    # 1. Call your own model (Hermes' GGUF) with augmented prompt
    # 2. Combine both responses
    
    if tool_response_content:
        # Return tool analysis as the response
        # (In production, you'd call Hermes' own model here too)
        return ChatCompletionResponse(
            id=generate_id(),
            model=request.model or "hermes-orchestrator",
            created=int(time.time()),
            choices=[
                Choice(
                    index=0,
                    message=Message(
                        role="assistant",
                        content=tool_response_content
                    ),
                    finish_reason="stop"
                )
            ],
            usage=Usage(
                prompt_tokens=sum(len(m.content.split()) for m in request.messages),
                completion_tokens=len(tool_response_content.split()),
                total_tokens=sum(len(m.content.split()) for m in request.messages) + len(tool_response_content.split())
            )
        )
    
    # No tool used - return a placeholder response
    # (In production, call Hermes' own GGUF model here)
    return ChatCompletionResponse(
        id=generate_id(),
        model=request.model or "hermes-orchestrator",
        created=int(time.time()),
        choices=[
            Choice(
                index=0,
                message=Message(
                    role="assistant",
                    content=f"I received your request: {user_message[:100]}... "
                            "(Tool orchestration is configured but no specialist model was invoked. "
                            "In a full deployment, this would call the appropriate model.)"
                ),
                finish_reason="stop"
            )
        ],
        usage=Usage(
            prompt_tokens=sum(len(m.content.split()) for m in request.messages),
            completion_tokens=20,
            total_tokens=sum(len(m.content.split()) for m in request.messages) + 20
        )
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "orchestrator_enabled": ORCHESTRATOR_ENABLED}


@app.get("/ready")
async def readiness_check():
    """Readiness check - verifies tool services are available."""
    checks = {"self": True}
    
    if ORCHESTRATOR_ENABLED:
        # Check all tool services
        tool_urls = {
            "coder_model": CODER_MODEL_URL,      # DeepSeek (analysis)
            "qwopus_model": QWOMPUS_MODEL_URL,    # Qwopus (generation)
            "qwen2_model": QWEN2_MODEL_URL,
            "llava_model": LLAVA_MODEL_URL,
        }
        
        # Only check math if it's different from coder
        if MATH_MODEL_URL not in tool_urls.values():
            tool_urls["math_model"] = MATH_MODEL_URL
        
        for name, url in tool_urls.items():
            try:
                async with httpx.AsyncClient(timeout=5.0) as check_client:
                    response = await check_client.get(f"{url}/health")
                    checks[name] = response.status_code == 200
            except:
                checks[name] = False
    
    all_ready = all(checks.values())
    return {
        "ready": all_ready,
        "checks": checks,
        "orchestrator_enabled": ORCHESTRATOR_ENABLED
    }


@app.get("/models")
async def list_models():
    """List available models (OpenAI-compatible)."""
    return {
        "object": "list",
        "data": [
            {
                "id": "hermes-orchestrator",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "hermes",
                "permission": [{"id": "modelperm-hermes", "object": "model_permission", "created": int(time.time()), "allow_create_engine": False, "allow_sampling": True, "allow_logprobs": True, "allow_search_indices": False, "allow_view": True, "allow_fine_tuning": False, "organization": "*", "group": None, "is_blocking": False}],
                "root": "hermes-orchestrator",
                "parent": None
            },
            {
                "id": "deepseek-coder-6.7b",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "hermes-tools",
                "permission": [{"id": "modelperm-coder", "object": "model_permission", "allow_sampling": True}],
                "root": "deepseek-coder-6.7b",
                "parent": None
            },
            {
                "id": "qwopus-9b-coder-mtp",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "hermes-tools",
                "permission": [{"id": "modelperm-qwopus", "object": "model_permission", "allow_sampling": True}],
                "root": "qwopus-9b-coder-mtp",
                "parent": None
            },
            {
                "id": "qwen2-7b-instruct",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "hermes-tools",
                "permission": [{"id": "modelperm-qwen2", "object": "model_permission", "allow_sampling": True}],
                "root": "qwen2-7b-instruct",
                "parent": None
            },
            {
                "id": "llava-1.5-7b-vision",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "hermes-tools",
                "permission": [{"id": "modelperm-llava", "object": "model_permission", "allow_sampling": True}],
                "root": "llava-1.5-7b-vision",
                "parent": None
            }
        ]
    }


# =============================================================================
# Run the application
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("HERMES_PORT", "8000")),
        log_level="info",
        # Enable for production:
        # workers=4,
        # timeout_keep_alive=ORCHESTRATOR_TIMEOUT + 10
    )
