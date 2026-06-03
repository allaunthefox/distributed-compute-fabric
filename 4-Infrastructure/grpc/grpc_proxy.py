#!/usr/bin/env python3
"""
gRPC Proxy for llama.cpp HTTP servers

Optional layer - proxies gRPC calls to existing HTTP inference endpoints.
Enable when you want streaming token generation over gRPC.

Usage:
    # Start proxy
    python grpc_proxy.py --port 50051 --model-server http://localhost:8000
    
    # Or via environment
    export GRPC_PROXY_PORT=50051
    export MODEL_SERVER_URL=http://gemma-model.services.svc.cluster.local:8000
    python grpc_proxy.py

Architecture:
    Client → gRPC (this proxy) → HTTP → llama.cpp server
"""

import argparse
import asyncio
import logging
import os
from concurrent import futures

import grpc
from inference_pb2 import (
    GenerateRequest, GenerateResponse,
    TokenChunk, ChatMessage,
    HealthRequest, HealthResponse,
)
from inference_pb2_grpc import InferenceServiceServicer, add_InferenceServiceServicer_to_server

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grpc-proxy")

# Model server endpoint
MODEL_SERVER = os.environ.get("MODEL_SERVER_URL", "http://localhost:8000")


class InferenceProxy(InferenceServiceServicer):
    """Proxy gRPC calls to llama.cpp HTTP API."""
    
    def __init__(self, model_server: str):
        self.model_server = model_server.rstrip("/")
    
    async def Generate(self, request: GenerateRequest, context: grpc.aio.ServicerContext):
        """Unary generate - call llama.cpp /v1/completions."""
        import httpx
        
        payload = {
            "prompt": request.prompt,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": False,
        }
        payload.update(request.extra_params)
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.model_server}/v1/completions",
                json=payload,
                timeout=300.0,
            )
            resp.raise_for_status()
            data = resp.json()
        
        text = data["choices"][0]["text"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        
        return GenerateResponse(
            text=text,
            tokens_used=tokens,
            latency_ms=0,  # TODO: track latency
            model=request.model,
        )
    
    async def GenerateStream(self, request: GenerateRequest, context: grpc.aio.ServicerContext):
        """Server streaming - proxy SSE tokens from llama.cpp."""
        import httpx
        
        payload = {
            "prompt": request.prompt,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": True,
        }
        payload.update(request.extra_params)
        
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.model_server}/v1/completions",
                json=payload,
                timeout=300.0,
            ) as response:
                index = 0
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        yield TokenChunk(token="", is_final=True, index=index)
                        break
                    
                    import json
                    data = json.loads(data_str)
                    token = data["choices"][0].get("text", "")
                    if token:
                        yield TokenChunk(token=token, is_final=False, index=index)
                        index += 1
    
    async def Chat(self, request_iterator, context):
        """Bidirectional streaming - collect messages, stream tokens."""
        import httpx
        
        messages = []
        async for msg in request_iterator:
            messages.append({"role": msg.role, "content": msg.content})
        
        # Convert to single prompt for llama.cpp
        prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        
        # Use GenerateStream logic
        stream_request = GenerateRequest(
            prompt=prompt,
            max_tokens=2048,
            temperature=0.7,
            stream=True,
        )
        async for chunk in self.GenerateStream(stream_request, context):
            yield chunk
    
    async def Health(self, request: HealthRequest, context):
        """Check model server health."""
        import httpx
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.model_server}/health", timeout=5.0)
                resp.raise_for_status()
                data = resp.json()
            
            return HealthResponse(
                healthy=data.get("status") == "ok",
                model=request.model,
                loaded_layers=0,  # llama.cpp doesn't expose this
                context_size=0,
            )
        except Exception as e:
            log.error(f"Health check failed: {e}")
            return HealthResponse(healthy=False, model=request.model)


async def serve(port: int, model_server: str):
    server = grpc.aio.server()
    add_InferenceServiceServicer_to_server(InferenceProxy(model_server), server)
    server.add_insecure_port(f"[::]:{port}")
    
    log.info(f"gRPC proxy listening on :{proxy_port}, proxying to {model_server}")
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="gRPC proxy for llama.cpp")
    parser.add_argument("--port", type=int, default=int(os.environ.get("GRPC_PROXY_PORT", "50051")))
    parser.add_argument("--model-server", default=MODEL_SERVER)
    args = parser.parse_args()
    
    proxy_port = args.port
    asyncio.run(serve(args.port, args.model_server))
