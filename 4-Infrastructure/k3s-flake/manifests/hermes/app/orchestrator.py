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
from fastapi.responses import HTMLResponse, StreamingResponse
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
MAIN_MODEL_URL = os.getenv("MAIN_MODEL_URL", "")

# Voltage mode routing: COMPUTE = hot path (GPU), APPROX = verification (ARM)
ARM_MODEL_URL = os.getenv("ARM_MODEL_URL", CODER_MODEL_URL)
GPU_MODEL_URL = os.getenv("GPU_MODEL_URL", "http://hermes.services.svc.cluster.local")

# Sampling profiles per voltage mode (Q16_16: 0x00010000 = 1.0)
SAMPLING_PROFILES = {
    "compute": {
        "temperature": 0.7,      # 0x0000B333 — balanced chat, official Google default
        "top_p": 0.9,
        "top_k": 50,
        "repeat_penalty": 1.0,
    },
    "approx": {
        "temperature": 0.0,      # 0x00000000 — greedy deterministic for verification
        "top_p": 1.0,
        "top_k": 0,
        "repeat_penalty": 1.0,
    },
    "morphic": {
        "temperature": 0.9,      # 0x0000E666 — high exploration for frontier
        "top_p": 0.95,
        "top_k": 100,
        "repeat_penalty": 1.0,
    },
}

# Per-task tuning within APPROX mode
APPROX_TASK_PROFILES = {
    "code":    {"temperature": 0.05, "top_p": 0.95, "top_k": 20},   # review
    "math":    {"temperature": 0.0,  "top_p": 1.0,  "top_k": 10},   # proof check
    "qwopus":  {"temperature": 0.2,  "top_p": 0.95, "top_k": 40},   # code gen
}

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


def has_image_message(messages: List) -> bool:
    """Check if any message in the conversation contains images."""
    for msg in messages:
        content = msg["content"] if isinstance(msg, dict) else msg.content
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    return True
        elif isinstance(content, str):
            if has_image(content):
                return True
    return False


def classify_voltage_mode(prompt: str, tool_type: str) -> str:
    """Classify request into voltage mode for substrate routing.
    
    COMPUTE — hot path, needs fast GPU inference (chat, generation)
    APPROX — verification, stable patterns, ARM CPU is sufficient (code review, math check)
    MORPHIC — frontier, run on multiple substrates and compare
    
    ARM CPUs (neon-64gb, 18 cores) handle APPROX-mode tasks efficiently
    in parallel, freeing the GPU for COMPUTE-mode chat.
    """
    if not tool_type:
        return "compute"
    if tool_type in ("code", "math"):
        return "approx"
    if tool_type == "qwopus":
        return "compute"
    return "compute"


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
    tool_type: str = None,
    voltage_mode: str = "approx",
    max_tokens: int = 2048
) -> Dict[str, Any]:
    """
    Call a specialist tool model with voltage-mode-aware sampling.
    APPROX tasks (code review, math) use low/deterministic temperature.
    COMPUTE tasks (generation) use higher temperature.
    """
    # Start with voltage-mode profile, then override with task-specific
    params = SAMPLING_PROFILES.get(voltage_mode, SAMPLING_PROFILES["approx"]).copy()
    if voltage_mode == "approx" and tool_type in APPROX_TASK_PROFILES:
        params.update(APPROX_TASK_PROFILES[tool_type])

    payload = {
        "model": "coder-model",
        "messages": messages,
        "temperature": params["temperature"],
        "top_p": params["top_p"],
        "top_k": params["top_k"],
        "repeat_penalty": params["repeat_penalty"],
        "max_tokens": max_tokens,
        "stream": False,
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

@app.get("/")
async def root():
    return HTMLResponse(content=CHAT_UI, status_code=200)


CHAT_UI = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hermes Chat</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, sans-serif; background: #111; color: #e0e0e0; display: flex; flex-direction: column; height: 100vh; }
  header { background: #1a1a2e; padding: 12px 20px; border-bottom: 1px solid #333; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 16px; font-weight: 600; color: #fff; }
  header span { font-size: 11px; color: #888; }
  #messages { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 16px; }
  .msg { max-width: 80%; padding: 12px 16px; border-radius: 12px; line-height: 1.5; font-size: 14px; white-space: pre-wrap; word-break: break-word; }
  .user { background: #2a3a5c; align-self: flex-end; border-bottom-right-radius: 4px; }
  .assistant { background: #1e2a3a; align-self: flex-start; border-bottom-left-radius: 4px; }
  .thinking { color: #888; font-style: italic; font-size: 12px; align-self: flex-start; }
  #input-area { padding: 16px 20px; border-top: 1px solid #333; background: #1a1a2e; display: flex; gap: 12px; }
  #input { flex: 1; padding: 10px 14px; border: 1px solid #444; border-radius: 8px; background: #222; color: #e0e0e0; font-size: 14px; resize: none; outline: none; }
  #input:focus { border-color: #4a6fa5; }
  #send { padding: 10px 20px; border: none; border-radius: 8px; background: #4a6fa5; color: #fff; font-size: 14px; cursor: pointer; }
  #send:hover { background: #5a7fb5; }
  #send:disabled { background: #444; cursor: not-allowed; }
  .model-info { font-size: 11px; color: #666; padding: 4px 0; }
</style>
</head>
<body>
<header>
  <h1>Hermes</h1>
  <span>orchestrator — voltage-mode routed</span>
</header>
<div id="messages"></div>
<div id="input-area">
  <textarea id="input" rows="1" placeholder="Type a message..." onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}"></textarea>
  <button id="send" onclick="send()">Send</button>
</div>
<script>
const messages = document.getElementById('messages');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send');

function addMsg(role, content) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = content;
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

async function send() {
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  addMsg('user', text);
  sendBtn.disabled = true;
  const think = document.createElement('div');
  think.className = 'thinking';
  think.textContent = 'thinking...';
  messages.appendChild(think);
  try {
    const res = await fetch('/v1/chat/completions', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model: 'hermes-orchestrator', messages: [{role: 'user', content: text}], stream: false})
    });
    const data = await res.json();
    think.remove();
    addMsg('assistant', data.choices[0].message.content);
  } catch(e) {
    think.remove();
    addMsg('assistant', 'Error: ' + e.message);
  }
  sendBtn.disabled = false;
  input.focus();
}
</script>
</body>
</html>"""


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
    
    # Voltage-mode routing: which substrate handles this?
    voltage_mode = classify_voltage_mode(user_message, tool_type)
    
    if tool_type:
        # Route by voltage mode:
        #   APPROX → ARM CPU (coder model on neon-64gb, 18 cores)
        #   COMPUTE → GPU (main model on RTX 4070)
        #   MORPHIC → both, compare results
        if voltage_mode == "approx":
            tool_url = ARM_MODEL_URL
        else:
            tool_url = GPU_MODEL_URL
        
        # If no specialist tool URL for this mode, fall back to tool-type map
        tool_url_map = {
            "math": MATH_MODEL_URL,
            "code": CODER_MODEL_URL,
            "qwopus": QWOMPUS_MODEL_URL,
            "qwen2": QWEN2_MODEL_URL,
            "llava": LLAVA_MODEL_URL
        }
        if not tool_url:
            tool_url = tool_url_map.get(tool_type, CODER_MODEL_URL)
        tool_messages = await build_tool_prompt(user_message, tool_type)
        
        try:
            tool_response = await call_tool_model(
                tool_url=tool_url,
                messages=tool_messages,
                tool_type=tool_type,
                voltage_mode=voltage_mode,
                max_tokens=2048
            )
            tool_response_content = tool_response["choices"][0]["message"]["content"]
        except HTTPException as e:
            # If tool call fails, proceed without it but log
            print(f"Warning: Tool call failed: {e.detail}")
            tool_type = None
    
    # Step 2: Call main model (on GPU/remote) for COMPUTE or synthesize MORPHIC
    if MAIN_MODEL_URL:
        params = SAMPLING_PROFILES.get(voltage_mode, SAMPLING_PROFILES["compute"])
        if voltage_mode == "approx" and tool_type in APPROX_TASK_PROFILES:
            params.update(APPROX_TASK_PROFILES[tool_type])
        payload = {
            "model": "hermes",
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature or params["temperature"],
            "max_tokens": request.max_tokens or params.get("max_tokens", 2048),
        }
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                r = await client.post(f"{MAIN_MODEL_URL}/v1/chat/completions", json=payload)
                if r.status_code == 200:
                    data = r.json()
                    return ChatCompletionResponse(
                        id=generate_id(), model=request.model or "hermes-orchestrator",
                        created=int(time.time()),
                        choices=[Choice(index=0, message=Message(role="assistant", content=data["choices"][0]["message"]["content"]), finish_reason="stop")],
                        usage=Usage(prompt_tokens=data["usage"]["prompt_tokens"], completion_tokens=data["usage"]["completion_tokens"], total_tokens=data["usage"]["total_tokens"])
                    )
        except Exception as e:
            print(f"Main model call failed: {e}")

    return ChatCompletionResponse(
        id=generate_id(), model=request.model or "hermes-orchestrator",
        created=int(time.time()),
        choices=[Choice(index=0, message=Message(role="assistant", content=f"I received your request: {user_message[:100]}... (Model server not connected. Set MAIN_MODEL_URL to an OpenAI-compatible endpoint.)"), finish_reason="stop")],
        usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
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
