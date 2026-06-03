# gRPC Inference Proxy

Optional gRPC layer for streaming token generation. Proxies to llama.cpp HTTP servers.

## When to Use

- Streaming tokens as they generate (real-time UI)
- Bidirectional streaming (multi-turn chat)
- Binary protocol efficiency (less overhead than JSON)

## When NOT to Use

- Batch inference (HTTP is fine)
- Simple request/response (HTTP is fine)
- Low-latency critical paths (adds one hop)

## Architecture

```
Client ──gRPC──▶ grpc_proxy.py ──HTTP──▶ llama.cpp server
                    │
                    └── inference.proto (contract)
```

## Setup

```bash
# Generate stubs
pip install grpcio-tools
python generate_stubs.py

# Start proxy
python grpc_proxy.py --port 50051 --model-server http://gemma-model:8000

# Or via environment
export GRPC_PROXY_PORT=50051
export MODEL_SERVER_URL=http://gemma-model.services.svc.cluster.local:8000
python grpc_proxy.py
```

## Proto Definition

```protobuf
service InferenceService {
  rpc Generate(GenerateRequest) returns (GenerateResponse);
  rpc GenerateStream(GenerateRequest) returns (stream TokenChunk);
  rpc Chat(stream ChatMessage) returns (stream TokenChunk);
  rpc Health(HealthRequest) returns (HealthResponse);
}
```

## Client Examples

### Python
```python
import grpc
from inference_pb2 import GenerateRequest
from inference_pb2_grpc import InferenceServiceStub

channel = grpc.insecure_channel("localhost:50051")
stub = InferenceServiceStub(channel)

# Unary
response = stub.Generate(GenerateRequest(
    model="gemma-4",
    prompt="Hello",
    max_tokens=100,
))

# Streaming
for chunk in stub.GenerateStream(GenerateRequest(
    model="gemma-4",
    prompt="Write a story",
    max_tokens=500,
    stream=True,
)):
    print(chunk.token, end="", flush=True)
```

### JavaScript
```javascript
const grpc = require('@grpc/grpc-js');
const protoLoader = require('@grpc/proto-loader');

const packageDef = protoLoader.loadSync('inference.proto');
const proto = grpc.loadPackageDefinition(packageDef).inference;

const client = new proto.InferenceService(
    'localhost:50051',
    grpc.credentials.createInsecure()
);

const stream = client.GenerateStream({
    model: 'gemma-4',
    prompt: 'Write a story',
    max_tokens: 500,
    stream: true
});

stream.on('data', (chunk) => process.stdout.write(chunk.token));
stream.on('end', () => console.log('\n[done]'));
```

## Kubernetes Deployment

```yaml
# Optional - only deploy if gRPC is needed
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grpc-proxy
  namespace: services
spec:
  replicas: 1
  selector:
    matchLabels:
      app: grpc-proxy
  template:
    spec:
      containers:
      - name: proxy
        image: grpc-proxy:latest
        ports:
        - containerPort: 50051
        env:
        - name: MODEL_SERVER_URL
          value: "http://gemma-model.services.svc.cluster.local:8000"
```
