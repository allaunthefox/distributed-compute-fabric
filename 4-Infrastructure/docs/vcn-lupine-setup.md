# VCN-LUPINE Bridge — Unified Compute Transport over Video

**Schema:** `vcn_lupine_bridge_spec_v1`
**Date:** 2026-05-29
**Status:** Design complete; implementation paused for cluster deployment

---

## 1. What Is VCN-LUPINE

VCN-LUPINE is a unified transport that encodes both **braid-compute operations** (VCN) and **CUDA driver API calls** (LUPINE) as H.264 video frames, transmitted over the Tailscale mesh to a GPU node.

**Core thesis:** Every structured computation operation can be encoded as an H.264 video frame carrying a binary payload, transmitted over an unreliable UDP-based network, and correctly reconstructed at the receiver with bounded error.

### Two Paths Through the Bridge

| Path | Input | Serialization | Hardware | Use Case |
|------|-------|--------------|----------|----------|
| **VCN** (braid) | `BraidStrand` dict | Binary (21/42 bytes) | AMD VCN encode/decode | Eigensolid compressor, braid crossing loop |
| **LUPINE** (CUDA) | CUDA API call (JSON) | JSON text → unified frame | NVIDIA GPU via CUDA driver | GEMM, convolution, QR factorization |

Both paths share the same outer frame format and the same H.264/MKV transport. The GPU node dispatches by TAG byte.

---

## 2. Architecture

### 2.1 Network Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Tailscale Mesh                                     │
│                                                                             │
│   ┌──────────────────┐                    ┌──────────────────────────┐      │
│   │   netcup (VPS)  │  ◄── MKV/H.264 ──► │   qfox-1 (GPU node)   │      │
│   │  rs-vps         │   (UDP, 14834)     │  AMD VCN + NVIDIA GPU  │      │
│   │  152.53.81.164  │                    │  100.88.57.96          │      │
│   │                  │                    │                        │      │
│   │  LD_PRELOAD     │                    │  AMD VCN ← decode      │      │
│   │  libcuda.so.1   │                    │  NVIDIA ← CUDA         │      │
│   └────────┬────────┘                    └──────────────────────────┘      │
│            │                                                             │
│            │ IPC socket (abstract Unix)                                  │
│            │ /run/vcn-lupine/daemon.sock                                 │
│            ▼                                                             │
│   ┌──────────────────┐                                                   │
│   │ vcn-lupine-daemon│                                                   │
│   │  - IPC receiver  │                                                   │
│   │  - FFmpeg H.264  │                                                   │
│   │  - MKV mux/demux │                                                   │
│   └──────────────────┘                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Compute Flow

**Path A — LUPINE (CUDA compute):**
```
1. Python/C binary calls cuBLAS/cuDNN/cuSOLVER API
2. LD_PRELOAD=libcuda.so.1 intercepts call
3. Call serialized to JSON → unified frame (TAG_LUPINE)
4. Frame → IPC socket → vcn-lupine-daemon
5. Daemon: FFmpeg H.264 encode → MKV mux
6. MKV sent over Tailscale UDP to GPU node (100.88.57.96:14834)
7. GPU node: MKV demux → H.264 decode
8. GPU node: TAG_LUPINE → LUPINE server → NVIDIA GPU
9. Result → reply frame → reverse path → libcuda returns to caller
```

**Path B — VCN (braid compute):**
```
1. braid_vcn_encoder.py builds BraidStrand/BraidBracket dict
2. Frame bytes (TAG_STRAND / TAG_CROSSING) → IPC → daemon
3. Daemon → FFmpeg → H.264 → MKV → Tailscale
4. GPU node decode → dispatch: TAG_STRAND → VCN compute path
5. Result (phase_acc, crossing_residual) → reply frame
```

---

## 3. Unified Frame Format

All frames share the same outer structure:

```
Byte 0:      tag (0x01-0x04)
Byte 1:      flags (0x00=request, 0x80=reply)
Bytes 2-5:   sequence number (UInt32LE)
Bytes 6-9:   payload_length (UInt32LE)
Bytes 10+:   payload (payload_length bytes)
```

### Tags

| Tag | Name | Payload |
|-----|------|---------|
| 0x01 | `TAG_STRAND` | 21/42 byte braid strand state |
| 0x02 | `TAG_CROSSING` | braid crossing operation |
| 0x03 | `TAG_PIST` | PIST spectral data |
| 0x04 | `TAG_LUPINE` | LUPINE CUDA operation (JSON args) |

### LUPINE Payload (TAG_LUPINE)

```
[4 bytes]  request_id (UInt32LE)
[4 bytes]  opcode (UInt32LE)
[4 bytes]  args_length (UInt32LE)
[N bytes]  JSON-encoded argument struct
```

### LUPINE Opcodes

| Opcode | API | JSON Args |
|--------|-----|-----------|
| 1 | `cudaMalloc` | `{"ptr": 0, "size": N}` |
| 2 | `cudaFree` | `{"ptr": HANDLE}` |
| 3 | `cudaMemcpy` | `{"dst": HANDLE, "src": HANDLE, "bytes": N, "kind": 1}` |
| 4 | `cuBLASgemm` | `{"handle": H, "transA": 0, "transB": 0, "m": M, "n": N, "k": K, "alpha": FP32, "A": HANDLE, "lda": INT, "B": HANDLE, "ldb": INT, "beta": FP32, "C": HANDLE, "ldc": INT}` |
| 5 | `cuDNNConvolutionForward` | `{"handle": H, "x_desc": HANDLE, "x": HANDLE, "w_desc": HANDLE, "w": HANDLE, "conv_desc": HANDLE, "algo": INT, "workspace": HANDLE, "workSize": N}` |
| 6 | `cuSOLVERDnorgqr` | `{"handle": H, "A": HANDLE, "lda": INT, "n": INT, "tau": HANDLE}` |
| 7 | `nvmlDeviceGetCount` | `{}` |
| 8 | `nvmlDeviceGetName` | `{"index": 0}` |

---

## 4. Component Inventory

### 4.1 Shim Files (`4-Infrastructure/shim/`)

| File | Purpose | Status |
|------|---------|--------|
| `vcn_lupine_bridge_spec.md` | This document — architecture spec | ✅ |
| `vcn_lupine_bridge.py` | Core: unified frame format, dispatch, socket protocol | ✅ |
| `vcn_lupine_daemon.py` | VPS-side daemon (IPC socket server, MKV client) | ✅ |
| `vcn_lupine_gpu_node.py` | GPU-node-side receiver + dispatch | ✅ |
| `vcn_lupine_opcodes.py` | LUPINE opcode constants + JSON arg schemas | ✅ |
| `vcn_compute_substrate.py` | VCN compute substrate (TAG_LUPINE integration) | ✅ |
| `libcuda_preload.c` | CUDA preload shim (C, compiles to `.so`) | ⏸ paused |

### 4.2 VPS Side (netcup)

- **Preload shim:** `/opt/vcn-lupine/lib/libcuda.so.1` — intercepts CUDA driver API calls
- **Daemon:** `vcn-lupine-daemon` — IPC receiver, FFmpeg H.264 encoder, MKV sender
- **Service:** `systemd` unit `vcn-lupine-daemon.service`

### 4.3 GPU Node Side (qfox-1, 100.88.57.96)

- **Receiver:** MKV demux listener on TCP:14834
- **H.264 decode:** FFmpeg with `h264_qsv` (Intel QSV) or `h264_vaapi`
- **Dispatch:** routes by TAG to LUPINE server or VCN compute path

---

## 5. Deployment

### 5.1 Prerequisites

- VPS (netcup): FFmpeg with H.264 support, `libva2` + VAAPI or QSV
- GPU node (qfox-1): AMD VCN hardware decode or Intel QSV, NVIDIA GPU with CUDA
- Tailscale mesh connectivity between all nodes

### 5.2 VPS Deployment Steps

```bash
# 1. Build preload shim
cd 4-Infrastructure/shim
gcc -shared -fPIC -o libcuda.so.1 libcuda_preload.c -ldl

# 2. Install
sudo cp libcuda.so.1 /opt/vcn-lupine/lib/
sudo cp vcn_lupine_daemon.py /opt/vcn-lupine/bin/vcn-lupine-daemon

# 3. Configure ld.so.preload
echo "/opt/vcn-lupine/lib/libcuda.so.1" | sudo tee /etc/ld.so.preload.d/vcn-lupine.conf

# 4. Set env (daemon discovers GPU node via env)
export LUPINE_GPU_NODE=100.88.57.96
export LUPINE_GPU_PORT=14834

# 5. Start daemon
sudo systemctl enable --now vcn-lupine-daemon
```

### 5.3 GPU Node Deployment Steps

```bash
# 1. Install LUPINE server (HTTP/2 on port 8080)
# 2. Start receiver
python3 vcn_lupine_gpu_node.py --port 14834
```

### 5.4 k3s Integration

VCN-LUPINE runs **alongside** k3s, not inside it. The compute flow:

```
k3s pod (Python/CUDA) → LD_PRELOAD shim → VCN-LUPINE daemon → GPU node
                              ↓
                    k3s service (ClusterIP or NodePort)
```

---

## 6. VCN vs LUPINE: Same Abstraction

| Aspect | VCN braid compute | LUPINE CUDA compute |
|--------|-------------------|---------------------|
| Input | `BraidStrand` dict | CUDA API call (JSON) |
| Serialization | Binary (21/42 bytes) | JSON text |
| Integrity | RS(255,223) + ChaCha20 | HTTP/2 + TLS |
| Transport | H.264/MKV frames | H.264/MKV frames |
| Hardware | AMD VCN encode | NVIDIA GPU |
| Computation | Phase accumulation, crossing residual | GEMM, convolution, QR |

**Unification:** JSON (LUPINE) or binary (VCN) → unified frame → RS → ChaCha20 → VCN frame. Both arrive at the same H.264/MKV output. GPU node dispatches by TAG.

---

## 7. Formal Claims (Lean Proof Required)

1. **Frame encoding soundness:** Binary serialization is bijective for all valid inputs
2. **Dispatch correctness:** TAG routing delivers LUPINE frames to CUDA backend and braid frames to VCN compute path

---

## 8. Open Questions

1. **H.264 encode latency** — VCN encode on AMD takes ~33ms/frame at 1080p30. LUPINE's HTTP/2 is much lower latency. Does the video codec overhead dominate?
2. **MKV container vs raw UDP** — VCN currently uses MKV for frame packaging. LUPINE uses raw HTTP/2. Should we keep MKV or drop to raw H.264 PES?
3. **Multi-GPU dispatch** — Does the unified bridge need to track which GPU node owns which CUDA device?
4. **FFmpeg dependency** — The daemon relies on FFmpeg for H.264 encode/decode. Can we use VCN hardware encoder directly via libva/AMF?
