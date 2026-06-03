# Llava-1.5-7B Vision-Language Model

Multimodal specialist tool for Hermes orchestrator. Enables image understanding, description, and Q&A.

## Architecture

```
Hermes Orchestrator → llava-model (specialist) → Vision Analysis
```

- **Service URL**: `http://llava-model.services.svc.cluster.local`
- **Port**: 80
- **Model**: Llava-1.5-7B with Q4_K_M quantization
- **Memory**: ~5-7GB
- **Storage**: ~5GB (model + mmproj)

## Prerequisites

### Required Files

Three files MUST be placed on neon-64gb at `/home/allaun/Downloads/llava/`:

1. **llava-1.5-7b-q4_k_m.gguf** (~4GB) - Main model weights
   - Download: https://huggingface.co/llava-hf/llava-1.5-7b-GGUF/resolve/main/llava-1.5-7b-q4_k_m.gguf

2. **mmproj-model-f16.bin** (~1GB) - Vision projection model
   - Download: https://huggingface.co/llava-hf/llava-1.5-7b-GGUF/resolve/main/mmproj-model-f16.bin

3. **tokenizer.model** (~100MB, optional) - For better tokenization
   - Download: https://huggingface.co/llava-hf/llava-1.5-7b-GGUF/resolve/main/tokenizer.model

### File Structure on neon-64gb

```
/home/allaun/Downloads/
├── llava/
│   ├── llava-1.5-7b-q4_k_m.gguf
│   ├── mmproj-model-f16.bin
│   └── tokenizer.model
├── Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf
├── DeepSeek-Coder-6.7B-Instruct-Q4_K_M.gguf
└── Qwen2-7B-Instruct-Q4_K_M.gguf
```

## Deployment

### Step 1: Download Model Files

```bash
# On neon-64gb (100.100.75.113):
mkdir -p /home/allaun/Downloads/llava

# Download main model
curl -L -o /home/allaun/Downloads/llava/llava-1.5-7b-q4_k_m.gguf \
  "https://huggingface.co/llava-hf/llava-1.5-7b-GGUF/resolve/main/llava-1.5-7b-q4_k_m.gguf"

# Download mmproj file
curl -L -o /home/allaun/Downloads/llava/mmproj-model-f16.bin \
  "https://huggingface.co/llava-hf/llava-1.5-7b-GGUF/resolve/main/mmproj-model-f16.bin"

# Optional: Download tokenizer
curl -L -o /home/allaun/Downloads/llava/tokenizer.model \
  "https://huggingface.co/llava-hf/llava-1.5-7b-GGUF/resolve/main/tokenizer.model"

# Set permissions
chmod 644 /home/allaun/Downloads/llava/*
```

### Step 2: Deploy to Kubernetes

```bash
# From any machine with kubectl access to cupfox:
cd /home/allaun/Research Stack/4-Infrastructure/k3s-flake

# Deploy Llava service
kubectl apply -k manifests/llava/

# Verify
kubectl -n services get pods -l app=llava-model
kubectl -n services get svc llava-model
```

### Step 3: Verify with Hermes

```bash
# Test direct access to Llava
curl http://llava-model.services.svc.cluster.local/v1/models

# Test via Hermes orchestrator (with image)
# See hermes/app/orchestrator.py for API format
```

## API Usage

### OpenAI-Compatible Endpoint

**POST** `http://llava-model.services.svc.cluster.local/v1/chat/completions`

### Request Format (Multimodal)

```json
{
  "model": "llava-1.5-7b-vision",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": "data:image/jpeg;base64,<base64_encoded_image>"}
      ]
    }
  ],
  "max_tokens": 2048,
  "temperature": 0.7
}
```

### Python Example

```python
import base64
import httpx
import json

# Read image file
with open("image.jpg", "rb") as f:
    image_data = base64.b64encode(f.read()).decode("utf-8")

# Build request
payload = {
    "model": "llava-1.5-7b-vision",
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image in detail."},
                {"type": "image_url", "image_url": f"data:image/jpeg;base64,{image_data}"}
            ]
        }
    ],
    "max_tokens": 2048,
    "temperature": 0.7
}

# Send request
async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://llava-model.services.svc.cluster.local/v1/chat/completions",
        json=payload
    )
    result = response.json()
    print(result["choices"][0]["message"]["content"])
```

## Hermes Orchestration

Hermes automatically routes to Llava when:

1. **Explicit tag**: `[image]`, `[vision]`, or `[llava]` in the prompt
2. **Image detection**: Prompt contains `data:image/`, `.jpg`, `.png`, `.jpeg`, etc.
3. **Content array**: Message contains `type: "image_url"` in content array

### Example Requests to Hermes

```python
# Explicit tag
messages = [{"role": "user", "content": "[image] What's in this picture?"}]

# Auto-detect from URL
messages = [{"role": "user", "content": "Analyze image.jpg"}]

# OpenAI multimodal format
messages = [{
    "role": "user",
    "content": [
        {"type": "text", "text": "What's this?"},
        {"type": "image_url", "image_url": "data:image/jpeg;base64,..."}
    ]
}]
```

## Resource Usage

| Resource | Request | Limit | Notes |
|----------|---------|-------|-------|
| Memory | 5Gi | 7Gi | Model + mmproj + overhead |
| CPU | 1 | 2 | For inference |
| Storage | 5GB | - | Model files on host |

### Coexistence with Other Models

On a 32GB RAM node (neon-64gb):

| Model | Memory | Total |
|-------|--------|-------|
| Llava-1.5-7B | 5-7GB | 5-7GB |
| + DeepSeek-Coder | 8GB | 13-15GB |
| + Qwen2-7B | 6GB | 19-21GB |
| + Hermes (Gemma) | 8GB | **27-29GB** ✅ |

**Conclusion**: All models fit comfortably on a 32GB RAM node.

## Troubleshooting

### Pod Stuck in Init

```bash
kubectl -n services logs <llava-pod> -c deepseek-coder
```

**Common issues:**
- Missing model files at `/home/allaun/Downloads/llava/`
- Incorrect file permissions
- Insufficient memory (need 5-7GB)

### Model Not Found

```bash
# Check files exist on neon-64gb:
ls -lh /home/allaun/Downloads/llava/
```

### Slow Inference

- Llava is CPU-only on ARM64 (no GPU support currently)
- Expected speed: ~10-20 tokens/sec
- For faster performance, consider a GPU node with CUDA support

## Upgrades

### Update Model

1. Download new GGUF file to `/home/allaun/Downloads/llava/`
2. Restart pod:
   ```bash
   kubectl -n services rollout restart deployment llava-model
   ```

### Change Quantization

Update the deployment to use a different quantization:
```yaml
command:
  - "llama-server"
  - "-m"
  - "/models/llava/llava-1.5-7b-q8_0.gguf"  # Different quant
```

## Security

- Runs as non-root user
- Read-only filesystem
- Dropped capabilities
- Resource limits enforced

## License

Llava-1.5-7B is licensed under Apache 2.0. See model card for details.
