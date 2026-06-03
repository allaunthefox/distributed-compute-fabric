# Phase 2: Docker Images

**Objective:** Build multi-architecture Docker images for GGUF inference.

**Duration:** 1-2 hours  
**Priority:** Critical (Required for Phase 3)  
**Dependencies:** Phase 1 (Ray cluster running)

---

## 🎯 Overview

Create a multi-architecture Docker image that contains:
- Ray runtime
- llama.cpp compiled from source
- GGUF inference capabilities
- VCN-LUPINE integration
- All Python dependencies

### Supported Architectures
- **linux/amd64** - For qfox-1 and steamdeck (x86_64)
- **linux/arm64** - For neon-64gb (ARM64)

---

## 📋 Microsteps

---

### 2.1 Create Dockerfile

**File:** [`Dockerfile.gguf`](Dockerfile.gguf)

**Key features:**
- Multi-stage build (builder + runtime)
- Compiles llama.cpp with CUDA/VAAPI support
- Installs all runtime dependencies
- Optimized for both ARM64 and x86_64

**Content highlights:**
```dockerfile
# Stage 1: Builder
FROM --platform=$BUILDPLATFORM python:3.11-slim as builder
RUN apt-get update && apt-get install -y build-essential cmake git
WORKDIR /llama.cpp
RUN git clone --recursive https://github.com/ggerganov/llama.cpp .
RUN mkdir -p build && cd build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release -DLLAMA_CUBLAS=ON -DLLAMA_VULKAN=ON && \
    make -j$(nproc) && cd .. && rm -rf build

# Stage 2: Runtime
FROM --platform=$TARGETPLATFORM python:3.11-slim
RUN apt-get update && apt-get install -y libopenblas-dev libva-dev libvulkan-dev ffmpeg
COPY --from=builder /llama.cpp/llama-server /usr/local/bin/
COPY --from=builder /llama.cpp/llama /usr/local/bin/
COPY --from=builder /llama.cpp/libllama.so /usr/local/lib/
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir llama-cpp-python
COPY gguf_actors.py coder_actor.py vision_actor.py general_actor.py frame_dispatcher.py /app/
COPY vcn-lupine.so /usr/local/lib/
ENV LD_PRELOAD=/usr/local/lib/vcn-lupine.so
```

**Full file:** See [`Dockerfile.gguf`](Dockerfile.gguf)

---

### 2.2 Create requirements.txt

**File:** [`requirements.txt`](requirements.txt)

**Content:**
```text
ray[default]>=2.9.0,<2.10.0
fastapi>=0.104.0,<0.105.0
uvicorn[standard]>=0.24.0,<0.25.0
httpx>=0.25.0,<0.26.0
pydantic>=2.5.0,<2.6.0
llama-cpp-python>=0.2.0,<0.3.0
Pillow>=10.0.0,<11.0.0
numpy>=1.24.0,<2.0.0
prometheus-client>=0.19.0,<0.20.0
circuitbreaker>=1.4.0,<2.0.0
python-json-logger>=2.0.7,<3.0.0
python-dotenv>=1.0.0,<2.0.0
tenacity>=8.2.0,<9.0.0
```

**Full file:** See [`requirements.txt`](requirements.txt)

---

### 2.3 Build and Push Multi-Architecture Image

**Setup Docker Buildx:**
```bash
# Create builder if not exists
docker buildx create --use

# Verify builder
docker buildx ls
```

**Build and push:**
```bash
# Build for both architectures and push to registry
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t ghcr.io/youruser/gguf-ray:latest \
  -t ghcr.io/youruser/gguf-ray:v1.0.0 \
  --push \
  -f Dockerfile.gguf \
  .
```

**Build for specific architecture (testing):**
```bash
# AMD64 only
docker buildx build --platform linux/amd64 -t ghcr.io/youruser/gguf-ray:amd64-test --load -f Dockerfile.gguf .

# ARM64 only  
docker buildx build --platform linux/arm64 -t ghcr.io/youruser/gguf-ray:arm64-test --load -f Dockerfile.gguf .
```

**Expected output:**
```
[+] Building 120.5s (15/15) FINISHED
 => [internal] load build definition from Dockerfile.gguf       0.1s
 => => transferring dockerfile: 32B                                        0.0s
 => [internal] load .dockerignore                                          0.0s
 => => transferring context: 2B                                          0.0s
 => [internal] load metadata for docker.io/library/python:3.11-slim  1.2s
 => [internal] load build context                                          0.1s
 => => transferring dockerfile: 1.5kB                                    0.0s
 => CACHED [builder 1/7] FROM docker.io/library/python:3.11-slim@sha256:...  0.0s
 => [builder 2/7] RUN apt-get update && apt-get install -y build-essential...  45.2s
...
 => [internal] load build context                                          0.0s
 => => transferring context: 3.5kB                                      0.0s
 => exporting to image                                                     10.2s
 => => exporting layers                                                   10.1s
 => => writing image sha256:abc...                                       0.1s
 => => naming to ghcr.io/youruser/gguf-ray:latest                         0.1s
 => => naming to ghcr.io/youruser/gguf-ray:v1.0.0                          0.1s
 => pushing layers...                                                    25.4s
 => => pushing layer sha256:def...                                       5.2s
 => => pushing layer sha256:ghi...                                       7.8s
 => => pushing manifest for ghcr.io/youruser/gguf-ray:latest            0.5s
 => => pushing manifest for ghcr.io/youruser/gguf-ray:v1.0.0             0.5s
```

---

## ✅ Verification

### 2.3.1 Verify Multi-Arch Image

```bash
# Check image manifest
docker buildx imagetools inspect ghcr.io/youruser/gguf-ray:latest

# Expected output:
# Name:      ghcr.io/youruser/gguf-ray:latest
# Media:     application/vnd.oci.image.manifest.v1+json
# Digests:   sha256:abc123...
# 
# Platforms:
#   linux/amd64:    image index: sha256:def456...
#   linux/arm64:    image index: sha256:ghi789...
```

### 2.3.2 Test AMD64 Image

```bash
# Pull and run test
docker pull ghcr.io/youruser/gguf-ray:latest

# Test Python environment
docker run --rm -it --platform linux/amd64 ghcr.io/youruser/gguf-ray:latest \
  python -c "import ray; import llm; print('✓ Ray and llm imports work')"

# Test llama-server
docker run --rm -it --platform linux/amd64 ghcr.io/youruser/gguf-ray:latest \
  llama-server --help | head -5
```

**Expected output:**
```
✓ Ray and llm imports work
llama server

Usage: llama-server [options] ...

Options:
  -h, --help           Show this help message
```

### 2.3.3 Test ARM64 Image (if ARM64 node available)

```bash
# Pull ARM64-specific image
docker pull --platform linux/arm64 ghcr.io/youruser/gguf-ray:latest

# Test on ARM64
docker run --rm -it --platform linux/arm64 ghcr.io/youruser/gguf-ray:latest \
  python -c "import ray; import llm; print('✓ ARM64: Ray and llm imports work')"
```

---

## 🔄 Rollback Plan

If build fails:

```bash
# Delete failed image
docker rmi ghcr.io/youruser/gguf-ray:latest

# Clean build cache
docker builder prune -a

# Rebuild with simpler configuration
docker buildx build --platform linux/amd64 -t ghcr.io/youruser/gguf-ray:test --load -f Dockerfile.gguf .
```

---

## 📊 Success Criteria

| Criteria | Status | Notes |
|----------|--------|-------|
| Docker Buildx configured | ⬜ | `docker buildx ls` |
| Multi-arch image built | ⬜ | Both amd64 and arm64 |
| Image pushed to registry | ⬜ | `docker pull ghcr.io/youruser/gguf-ray:latest` |
| Python dependencies installed | ⬜ | Test import in container |
| llama.cpp compiled | ⬜ | `llama-server --help` works |
| VCN-LUPINE shim included | ⬜ | File exists in image |
| ARM64 compatibility | ⬜ | ARM64 image runs |

---

## 🚀 Next Phase

Once all criteria are met, proceed to **[Phase 3: GGUF Ray Actors](Phase-3-Actors.md)**

---

## 📝 Notes

### Issues You Might Encounter

1. **Build fails with CUDA errors**
   - **Cause:** CUDA not available in builder
   - **Fix:** Remove `-DLLAMA_CUBLAS=ON` for non-GPU nodes, or use NVIDIA CUDA image as base

2. **Buildx not available**
   - **Cause:** Docker Buildx not installed
   - **Fix:** Install with `docker buildx install`

3. **Permission denied for /dev/dri**
   - **Cause:** Missing privileges
   - **Fix:** Run with `--security-opt seccomp=unconfined` or add device

4. **ARM64 build fails**
   - **Cause:** OpenBLAS not available for ARM64
   - **Fix:** Add `libopenblas-arm64` installation in Dockerfile

### Useful Commands

```bash
# List all images
docker images | grep gguf-ray

# Inspect image
docker inspect ghcr.io/youruser/gguf-ray:latest

# Check image history
docker history ghcr.io/youruser/gguf-ray:latest

# Clean up
docker system prune -a

# Build without cache
docker buildx build --no-cache --platform linux/amd64 -t test .
```

### Optimization Tips

```dockerfile
# Reduce image size
RUN apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Use smaller base image
FROM python:3.11-alpine as builder
FROM python:3.11-alpine as runtime

# Multi-stage build reduces final image size significantly
```
