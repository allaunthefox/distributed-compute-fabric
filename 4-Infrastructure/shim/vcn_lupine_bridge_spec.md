# VCN-LUPINE Bridge — Unified Compute Transport over Video

**Schema:** `vcn_lupine_bridge_spec_v1`
**Date:** 2026-05-29
**Status:** Research artifact — not yet promoted

---

## 1. Motivation

VCN (Video Core Next) and LUPINE are both GPU-over-IP bridges at different layers:

| Layer | VCN | LUPINE |
|-------|-----|--------|
| Transport | H.264/MKV video frames | HTTP/2 |
| Hardware | AMD VCN (video encode) | NVIDIA CUDA (compute) |
| Data model | Braid operations (strand, crossing, PIST) | CUDA driver API calls |
| Use case | Eigensolid compressor, braid crossing loop | CUDA-compute workloads |

Both encode **structured computation** as **byte sequences** that must survive network transmission with integrity guarantees. Both need encryption and error correction.

**Thesis:** These are the same abstraction at different levels of the stack. We can unify them by:

1. Encoding both VCN braid-ops and LUPINE CUDA calls in the **same binary frame format**
2. Transporting those frames via **H.264 video** (the VCN pipeline)
3. Decoding on the GPU node and **dispatching** to the appropriate compute backend

This eliminates the HTTP/2 transport layer for LUPINE — it rides on VCN instead.

---

## 2. Architecture

### 2.1 Network Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Tailscale Mesh                                     │
│                                                                             │
│   ┌──────────────┐                              ┌──────────────────────┐  │
│   │   netcup VPS │  ◄──── MKV stream ────────► │   qfox-1             │  │
│   │  rs-vps      │  (H.264, VCN-encoded)        │  (AMD VCN + NVIDIA) │  │
│   │  (ARM64)     │                              │  100.88.57.96       │  │
│   │  152.53.81.  │                              │                      │  │
│   │  164         │                              │  AMD VCN ← decode   │  │
│   │              │                              │  NVIDIA ← CUDA      │  │
│   │  LUPINE      │                              │                      │  │
│   │  preload     │                              │                      │  │
│   │  libcuda.so.1│                              │                      │  │
│   └──────┬───────┘                              └──────────────────────┘  │
│          │                                                                │
│          │  LD_PRELOAD intercepts CUDA API calls                           │
│          │  Serializes to JSON-braid → unified frame format               │
│          │                                                                │
└──────────┼────────────────────────────────────────────────────────────────┘
           │
           ▼
    IPC socket (abstract)
    /run/vcn-lupine/daemon.sock
```

### 2.2 Compute Flow

**Path A — CUDA compute (LUPINE):**
```
1. Python/C binary calls cuBLAS/cuDNN/cuSOLVER API
2. LD_PRELOAD=libcuda.so.1 intercepts call
3. Call serialized to JSON → JSON-braid frame
4. Frame sent over IPC to vcn-lupine-daemon
5. Daemon: JSON → unified frame bytes (TAG_LUPINE)
6. FFmpeg: frame bytes → H.264 YUV420 frame
7. MKV mux → sent over Tailscale UDP to GPU node
8. GPU node: MKV demux → H.264 decode
9. GPU node dispatch: TAG_LUPINE → LUPINE server → NVIDIA GPU
10. Result serialized → JSON → unified frame (reply)
11. Reverse path back to VPS
12. libcuda.so.1 returns result to calling program
```

**Path B — Braid compute (VCN):**
```
1. braid_vcn_encoder.py builds BraidStrand/BraidBracket dict
2. Calls encode_braid_strand() / encode_braid_crossing()
3. Frame bytes (TAG_STRAND / TAG_CROSSING) → IPC → daemon
4. Daemon → FFmpeg → H.264 → MKV → Tailscale
5. GPU node decode → dispatch: TAG_STRAND → VCN compute path
6. Result (phase_acc, crossing_residual) → reply frame
```

### 2.3 Unified Frame Format

Frames are the same binary format as `vcn_compute_substrate.py` with one new tag:

```python
TAG_STRAND   = 0x01   # braid strand state
TAG_CROSSING = 0x02   # braid crossing operation
TAG_PIST     = 0x03   # PIST spectral data
TAG_LUPINE   = 0x04   # LUPINE CUDA operation (JSON-braid wrapper)
```

**LUPINE frame payload** (when TAG_LUPINE):

```
[4 bytes: request_id (UInt32LE)]
[4 bytes: opcode (UInt32LE: 1=cudaMalloc, 2=cuBLASgemm, 3=cuDNN conv, etc.)]
[4 bytes: payload_length (UInt32LE)]
[payload_length bytes: JSON-encoded argument struct]
```

**JSON argument structure** (matches LUPINE CUDA API calls):
```json
{
  "api": "cudaMalloc",
  "args": {
    "ptr": 0,
    "size": 4096
  }
}
```

Full LUPINE opcode map:
| Opcode | API | JSON args |
|--------|-----|-----------|
| 1 | `cudaMalloc` | `{"ptr": 0, "size": N}` |
| 2 | `cudaFree` | `{"ptr": HANDLE}` |
| 3 | `cudaMemcpy` | `{"dst": HANDLE, "src": HANDLE, "bytes": N, "kind": 1}` |
| 4 | `cuBLASgemm` | `{"handle": H, "transA": 0, "transB": 0, "m": M, "n": N, "k": K, "alpha": FP32, "A": HANDLE, "lda": INT, "B": HANDLE, "ldb": INT, "beta": FP32, "C": HANDLE, "ldc": INT}` |
| 5 | `cuDNNConvolutionForward` | `{"handle": H, "x_desc": HANDLE, "x": HANDLE, "w_desc": HANDLE, "w": HANDLE, "conv_desc": HANDLE, "algo": INT, "workspace": HANDLE, "workSize": N}` |
| 6 | `cuSOLVERDnorgqr` | `{"handle": H, "A": HANDLE, "lda": INT, "n": INT, "tau": HANDLE}` |
| 7 | `nvmlDeviceGetCount` | `{}` |
| 8 | `nvmlDeviceGetName` | `{"index": 0}` |

**Reply frame** (same TAG, different flag):
```
[1 byte: TAG_LUPINE]
[1 byte: flags (0x80 = reply)]
[4 bytes: request_id (echo)]
[4 bytes: status (0=OK, -1=error)]
[4 bytes: result_length]
[result_length bytes: JSON result]
```

---

## 3. Components

### 3.1 `libcuda.so.1` Preload Shim (VPS side)

Intercepts CUDA driver API calls. Lives at `/opt/vcn-lupine/lib/libcuda.so.1` on VPS.

**Intercepted symbols** (from `client.exports`):
```
cudaMalloc, cudaFree, cudaMemcpy, cudaMemcpyAsync,
cuBLAScreate, cuBLASdestroy, cuBLASgemm,
cuDNNcreate, cuDNNdestroy, cuDNNconvolutionForward,
cuSOLVERcreate, cuSOLVERdestroy, cuSOLVERdnorgqr,
nvmlInit, nvmlDeviceGetCount, nvmlDeviceGetName, nvmlDeviceGetHandleByIndex
```

**Flow:**
1. `dlsym(RTLD_NEXT, "cudaMalloc")` gets real libcuda (if any — on CPU-only there is none)
2. Serialize call to JSON
3. Write JSON to `/run/vcn-lupine/daemon.sock` (abstract Unix socket)
4. Read reply JSON from socket
5. Return result to caller

**Socket protocol:**
```
Send:    JSON bytes (length-prefixed with 4-byte UInt32LE)
Recv:    JSON bytes (length-prefixed)
```

### 3.2 `vcn-lupine-daemon` (VPS side)

Daemon running on the VPS. Receives IPC from libcuda shim and braid encoders.

**Endpoints:**
- `bind:unix:/run/vcn-lupine/daemon.sock` — IPC from shim + encoders
- `connect:tcp:100.88.57.96:14834` — MKV stream to GPU node

**One socket pair per request:**
```
IPC client → daemon (Unix socket)
  └─► GPU node (TCP/MKV stream)
        └─► LUPINE server / VCN decoder
        ◄── reply
      ◄─ daemon
    ◄─ IPC client
```

**Commands:**
```
FRAME_SEND  <tag> <seq> <payload_bytes>  → sends frame to GPU node
FRAME_RECV  <tag> <seq>                 → receives frame from GPU node
STATUS                                → returns connection health
```

### 3.3 GPU Node Receiver (qfox-1 side)

Receives MKV stream from VPS. Lives on qfox-1.

**Components:**
1. **MKV demux listener** — TCP:14834, receives VCN-encoded MKV from VPS
2. **H.264 decode** — AMD VCN hardware decode via `ffmpeg -c:v h264_qsv` or `h264_vaapi`
3. **Frame dispatch** — reads TAG byte, routes to:
   - `TAG_LUPINE` → LUPINE CUDA shim (libcuda.so.1) → NVIDIA GPU
   - `TAG_STRAND/TAG_CROSSING/TAG_PIST` → existing `vcn_compute_substrate` decode path

**Reply path:** result encoded as TAG_LUPINE frame → H.264 encode → MKV mux → TCP back to VPS

### 3.4 Unified Frame Byte Layout

All frames share the same outer structure (matches `vcn_compute_substrate.py`):

```
Byte 0:      tag (0x01-0x04)
Byte 1:      flags (0x00=request, 0x80=reply)
Bytes 2-5:   sequence number (UInt32LE, big-endian)
Bytes 6-9:   payload_length (UInt32LE, little-endian)
Bytes 10+:   payload (payload_length bytes)

Payload for TAG_LUPINE:
  [4]  request_id
  [4]  opcode
  [4]  args_length
  [N]  JSON args
```

---

## 4. Implementation Plan

### 4.1 Files to Create

| File | Purpose |
|------|---------|
| `4-Infrastructure/shim/vcn_lupine_bridge.py` | Core: unified frame format, dispatch, socket protocol |
| `4-Infrastructure/shim/vcn_lupine_daemon.py` | VPS-side daemon (IPC socket server, MKV client) |
| `4-Infrastructure/shim/vcn_lupine_gpu_node.py` | GPU-node-side receiver + dispatch |
| `4-Infrastructure/shim/libcuda_preload.c` | CUDA preload shim (C, compiled to .so) |
| `4-Infrastructure/shim/vcn_lupine_opcodes.py` | LUPINE opcode constants + JSON arg schemas |

### 4.2 Existing Files to Modify

| File | Change |
|------|--------|
| `4-Infrastructure/shim/vcn_compute_substrate.py` | Add `TAG_LUPINE = 0x04`, `TAG_REPLY = 0x80`, `OP_LUPINE_CUDA` frame handler |
| `4-Infrastructure/netcup-vps/configuration.nix` | Add vcn-lupine-daemon service, libcuda_preload package |
| `4-Infrastructure/netcup-vps/flake.nix` | Add lupine flake input |

### 4.3 NixOS Service Config (VPS)

```nix
# VPS side: daemon + preload shim
systemd.services.vcn-lupine-daemon = {
  wantedBy = [ "multi-user.target" ];
  after = [ "network.target" ];
  serviceConfig = {
    ExecStart = "${vcn-lupine}/bin/vcn-lupine-daemon";
    RuntimeDirectory = "vcn-lupine";
    RestrictNamespaces = true;
    PrivateTmp = true;
  };
};
environment.etc."ld.so.preload" = {
  text = "/opt/vcn-lupine/lib/libcuda.so.1";
};
```

### 4.4 GPU Node Service Config (qfox-1)

```nix
# qfox-1 side: receiver + dispatch
systemd.services.vcn-lupine-gpu-node = {
  wantedBy = [ "multi-user.target" ];
  after = [ "network.target" ];
  serviceConfig = {
    ExecStart = "${vcn-lupine}/bin/vcn-lupine-gpu-node --port 14834";
    RuntimeDirectory = "vcn-lupine";
  };
};
```

---

## 5. VCN Compute vs LUPINE: Same Abstraction

The key insight is that both systems are doing **structured computation serialization**:

| Aspect | VCN braid compute | LUPINE CUDA compute |
|--------|-----------------|-------------------|
| Input | `BraidStrand` dict | CUDA API call (JSON) |
| Serialization | Binary (21/42 bytes) | JSON text |
| Integrity | RS(255,223) + ChaCha20 | HTTP/2 + TLS |
| Transport | H.264/MKV frames | HTTP/2/TCP |
| Hardware | AMD VCN encode | NVIDIA GPU |
| Computation | Phase accumulation, crossing residual | GEMM, convolution, QR |

**The unification** is encoding both as video frames:
- VCN native: binary → RS → ChaCha20 → VCN frame
- LUPINE: JSON → unified frame → RS → ChaCha20 → VCN frame

Both arrive at the same H.264/MKV output. The GPU node dispatches by TAG.

---

## 6. Seal (Receipt)

No formal proof yet — this is a design document. The formal claim:

> **Unified Transport Thesis:** Every GPU-compute operation (CUDA driver API or braid crossing) can be encoded as an H.264 video frame carrying a binary payload, transmitted over an unreliable UDP-based network, and correctly reconstructed at the receiver with bounded error (RS纠错码 < 16 symbol errors, ChaCha20 authenticated encryption).

This requires two Lean proofs:
1. **Frame encoding soundness** — the binary serialization is bijective for all valid inputs
2. **Dispatch correctness** — TAG routing delivers LUPINE frames to CUDA backend and braid frames to VCN compute path

---

## 7. Open Questions

1. **H.264 encode latency** — VCN encode on AMD takes ~33ms/frame at 1080p30. LUPINE's HTTP/2 is much lower latency. Does the video codec overhead dominate?
2. **MKV container vs raw UDP** — VCN currently uses MKV for frame packaging (container, streaming). LUPINE uses raw HTTP/2. Should we keep MKV or drop to raw H.264 PES?
3. **Multi-GPU dispatch** — LUPINE supports multiple servers (comma-separated). Does the unified bridge need to track which GPU node owns which CUDA device?
4. **LUPINE server on VPS side** — Currently LUPINE server runs on GPU node. Does the unified bridge need a reverse path where GPU node initiates work to VPS?
5. **FFmpeg dependency** — The daemon relies on FFmpeg for H.264 encode/decode. Can we use the VCN hardware encoder directly via libva/AMF, or is FFmpeg sufficient?
