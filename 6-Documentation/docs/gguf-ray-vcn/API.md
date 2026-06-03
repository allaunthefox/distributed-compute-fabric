# Hermes API Documentation

**Version:** 1.0.0  
**Base URL:** `https://api.yourdomain.com/api/v1`

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Endpoints](#endpoints)
4. [Request/Response Models](#requestresponse-models)
5. [Error Codes](#error-codes)
6. [Rate Limiting](#rate-limiting)
7. [Examples](#examples)

---

## Overview

Hermes Orchestrator provides a REST API for distributed GGUF model inference on a Ray cluster with VCN-LUPINE acceleration.

### Features
- Multi-model inference (code, text, vision)
- Batch processing
- Async generation with ObjectRef transport
- Hardware-accelerated video compression
- Distributed across heterogeneous hardware

### Models Available

| Model | Type | Specialization | Backend | Max Context |
|-------|------|----------------|---------|--------------|
| Qwopus3.5-9B | CODE | Code Generation | CUDA | 32768 |
| Gemma-4-E4B | TEXT | General Text | CPU | 131072 |
| Llava-1.5-7B | VISION | Multimodal | VAAPI | 4096 |
| DeepSeek-Coder | FALLBACK | Code | CPU | 16384 |

---

## Authentication

All endpoints (except `/auth/token`) require JWT authentication.

### Get Token

**Endpoint:** `POST /auth/token`

**Request:**
```json
{
  "username": "your_username",
  "password": "your_password"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**cURL Example:**
```bash
curl -X POST https://api.yourdomain.com/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=your-secret"
```

### Use Token

Include the token in the `Authorization` header:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### OAuth2 (Optional)

Initiate OAuth2 flow:
```bash
curl https://api.yourdomain.com/api/v1/auth/github/login
```

Response includes `auth_url` for redirecting user to provider.

---

## Endpoints

### Generate Text

**Endpoint:** `POST /generate`

Generate text from a prompt using the specified model.

**Request:**
```json
{
  "prompt": "Explain machine learning",
  "model_type": "text",
  "max_tokens": 512,
  "temperature": 0.7,
  "top_p": 0.9,
  "top_k": 50,
  "stop": ["\\n\\n"],
  "echo": false,
  "stream": false,
  "images": ["base64_encoded_image_string"]
}
```

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| prompt | string | Yes | - | Text prompt for the model |
| model_type | string | No | auto | Model type: "code", "text", "vision", "fallback" |
| max_tokens | integer | No | 512 | Maximum tokens to generate |
| temperature | number | No | 0.7 | Sampling temperature (0-1) |
| top_p | number | No | 0.9 | Nucleus sampling parameter |
| top_k | integer | No | 50 | Top-k sampling parameter |
| stop | array | No | null | Stop sequences |
| echo | boolean | No | false | Echo the prompt in output |
| stream | boolean | No | false | Stream tokens (SSE) |
| images | array | No | null | Base64 images for multimodal |

**Response:**
```json
{
  "id": "unique-request-id-uuid",
  "model": "Gemma-4-E4B",
  "model_type": "text",
  "prompt": "Explain machine learning",
  "generated_text": "Machine learning is a subset of artificial intelligence...",
  "finish_reason": "stop",
  "tokens_generated": 42,
  "tokens_input": 3,
  "latency_ms": 123.45,
  "timestamp": "2024-06-01T12:00:00Z"
}
```

**cURL Example:**
```bash
curl -X POST https://api.yourdomain.com/api/v1/generate \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Explain machine learning",
    "model_type": "text",
    "max_tokens": 100
  }'
```

---

### Batch Generate

**Endpoint:** `POST /generate/batch`

Generate text from multiple prompts in a batch.

**Request:**
```json
{
  "requests": [
    {
      "prompt": "Explain Python",
      "model_type": "text",
      "max_tokens": 100
    },
    {
      "prompt": "Write a sorting function",
      "model_type": "code",
      "max_tokens": 200
    }
  ]
}
```

**Response:**
```json
{
  "results": [
    {
      "id": "req-1",
      "model": "Gemma-4-E4B",
      "model_type": "text",
      "prompt": "Explain Python",
      "generated_text": "Python is a high-level...",
      "finish_reason": "stop",
      "tokens_generated": 50,
      "tokens_input": 2,
      "latency_ms": 200.12,
      "timestamp": "2024-06-01T12:00:00Z"
    },
    {
      "id": "req-2",
      "model": "Qwopus3.5-9B",
      "model_type": "code",
      "prompt": "Write a sorting function",
      "generated_text": "def sort(arr):\\n    return sorted(arr)",
      "finish_reason": "stop",
      "tokens_generated": 15,
      "tokens_input": 4,
      "latency_ms": 350.23,
      "timestamp": "2024-06-01T12:00:00Z"
    }
  ],
  "total_tokens": 65,
  "total_latency_ms": 550.35,
  "success_count": 2,
  "error_count": 0
}
```

---

### List Models

**Endpoint:** `GET /models`

List all available models.

**Response:**
```json
[
  {
    "name": "Qwopus3.5-9B",
    "model_type": "code",
    "display_name": "Qwopus 3.5 9B",
    "description": "Advanced code generation model",
    "version": "1.0.0",
    "size": "9B",
    "backend": "CUDA",
    "capabilities": ["code-completion", "code-explanation", "code-generation"],
    "max_context": 32768,
    "available": true,
    "loaded": false
  },
  {
    "name": "Gemma-4-E4B",
    "model_type": "text",
    "display_name": "Gemma 4 E4B",
    "description": "General-purpose text model",
    "version": "1.0.0",
    "size": "4B",
    "backend": "CPU",
    "capabilities": ["text-generation", "chat", "summarization"],
    "max_context": 131072,
    "available": true,
    "loaded": false
  }
]
```

---

### Get Model

**Endpoint:** `GET /models/{model_name}`

Get information about a specific model.

**Response:**
```json
{
  "name": "Gemma-4-E4B",
  "model_type": "text",
  "display_name": "Gemma 4 E4B",
  "description": "General-purpose text model",
  "version": "1.0.0",
  "size": "4B",
  "backend": "CPU",
  "capabilities": ["text-generation", "chat", "summarization"],
  "max_context": 131072,
  "available": true,
  "loaded": false
}
```

---

### Health Check

**Endpoint:** `GET /health`

Get service health status.

**Response:**
```json
{
  "status": "healthy",
  "environment": "production",
  "version": "1.0.0",
  "ray_connected": true,
  "models_available": 4,
  "models_loaded": 2,
  "uptime_seconds": 3600.5
}
```

---

### Cluster Status

**Endpoint:** `GET /status`

Get detailed cluster status.

**Response:**
```json
{
  "ray_cluster": {
    "nodes": 5,
    "resources": {
      "CPU": 40,
      "GPU": 2,
      "memory": "200Gi"
    },
    "gpu_available": 1
  },
  "models": {
    "Qwopus3.5-9B": {
      "name": "Qwopus3.5-9B",
      "model_type": "code",
      "available": true,
      "loaded": true
    }
  },
  "queue_size": 0,
  "active_requests": 0,
  "completed_requests": 1000,
  "error_rate": 0.01
}
```

---

### Prometheus Metrics

**Endpoint:** `GET /metrics`

Get Prometheus-compatible metrics.

**Response:** Prometheus metric format (text/plain)

---

### Get Current User

**Endpoint:** `GET /auth/me`

Get information about the authenticated user.

**Response:**
```json
{
  "username": "john_doe",
  "user_id": "user-123",
  "roles": ["user"],
  "expires_at": "2024-06-01T12:30:00Z"
}
```

---

## Request/Response Models

### GenerateRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| prompt | string | Yes | Text prompt |
| model_type | string | No | Model type enum |
| max_tokens | integer | No | Maximum tokens |
| temperature | number | No | Sampling temperature |
| top_p | number | No | Nucleus sampling |
| top_k | integer | No | Top-k sampling |
| stop | array[string] | No | Stop sequences |
| echo | boolean | No | Echo prompt |
| stream | boolean | No | Stream tokens |
| images | array[string] | No | Base64 images |

### GenerateResponse

| Field | Type | Description |
|-------|------|-------------|
| id | string | Unique request ID |
| model | string | Model name |
| model_type | string | Model type |
| prompt | string | Input prompt |
| generated_text | string | Generated text |
| finish_reason | string | Why generation stopped |
| tokens_generated | integer | Tokens generated |
| tokens_input | integer | Tokens in prompt |
| latency_ms | number | Request latency |
| timestamp | string | ISO 8601 timestamp |

---

## Error Codes

| Code | Name | Description | Retry |
|------|------|-------------|-------|
| 400 | Bad Request | Invalid request parameters | No |
| 401 | Unauthorized | Missing or invalid authentication | No |
| 403 | Forbidden | Insufficient permissions | No |
| 404 | Not Found | Resource not found | No |
| 429 | Rate Limited | Too many requests | Yes (after reset) |
| 500 | Internal Server Error | Unexpected server error | Yes |
| 502 | Bad Gateway | Invalid response from upstream | Yes |
| 503 | Service Unavailable | Service temporarily unavailable | Yes |
| 504 | Gateway Timeout | Upstream request timeout | Yes |

---

## Rate Limiting

Requests are rate limited based on user role:

| Role | Requests/Minute | Burst |
|------|-----------------|-------|
| Anonymous | 10 | 20 |
| User | 100 | 150 |
| Premium | 1000 | 1500 |
| Admin | Unlimited | Unlimited |

**Rate Limit Headers:**
- `X-RateLimit-Limit`: Total requests allowed
- `X-RateLimit-Remaining`: Requests remaining
- `X-RateLimit-Reset`: Time when limit resets (UTC timestamp)

---

## Examples

### Python Example

```python
import requests

# Get token
auth_response = requests.post(
    "https://api.yourdomain.com/api/v1/auth/token",
    data={"username": "your_username", "password": "your_password"}
)
token = auth_response.json()["access_token"]

# Generate text
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

data = {
    "prompt": "Write a Python function to calculate factorial",
    "model_type": "code",
    "max_tokens": 200,
    "temperature": 0.3
}

response = requests.post(
    "https://api.yourdomain.com/api/v1/generate",
    headers=headers,
    json=data
)

result = response.json()
print(f"Generated: {result['generated_text']}")
print(f"Tokens: {result['tokens_generated']}")
print(f"Latency: {result['latency_ms']}ms")
```

### Batch Processing Example

```python
import requests

token = "YOUR_TOKEN"
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

# Batch of requests
batch = {
    "requests": [
        {"prompt": "Explain AI", "max_tokens": 100},
        {"prompt": "Write a poem", "max_tokens": 150},
        {"prompt": "Code review tips", "max_tokens": 200}
    ]
}

response = requests.post(
    "https://api.yourdomain.com/api/v1/generate/batch",
    headers=headers,
    json=batch
)

results = response.json()["results"]
for result in results:
    print(f"ID: {result['id']}, Tokens: {result['tokens_generated']}")
```

### Multimodal Example

```python
import requests
import base64

# Read and encode image
with open("image.jpg", "rb") as f:
    image_data = base64.b64encode(f.read()).decode("utf-8")

token = "YOUR_TOKEN"
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

data = {
    "prompt": "Describe this image",
    "model_type": "vision",
    "max_tokens": 300,
    "images": [image_data]
}

response = requests.post(
    "https://api.yourdomain.com/api/v1/generate",
    headers=headers,
    json=data
)

result = response.json()
print(result["generated_text"])
```

---

*For more information, see the [Architecture Documentation](ARCHITECTURE.md).*
