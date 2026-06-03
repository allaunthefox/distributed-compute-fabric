# Plan: Mesh Networking Layers Over Ray

## The Stack (top to bottom)

```
┌─────────────────────────────────────────────────────────────┐
│  Application Layer                                            │
│  Braid search, AlphaProof, RG tests, PIST classification     │
├─────────────────────────────────────────────────────────────┤
│  Ray Scheduler                                                │
│  Distributed task scheduling, ObjectRef transport             │
│  @ray.remote, ray.put(), ray.get()                            │
├─────────────────────────────────────────────────────────────┤
│  VCN Pipeline (compression)                                   │
│  Delta+RLE → RS ECC → ChaCha20 → H.264 → MKV               │
│  50x bandwidth reduction over raw data                        │
├─────────────────────────────────────────────────────────────┤
│  FrameDispatcher (routing)                                    │
│  TAG_STRAND → VCNBraidBackend                                 │
│  TAG_CROSSING → VCNBraidBackend                               │
│  TAG_PIST → VCNBraidBackend                                   │
│  TAG_LUPINE → CUDABackend                                     │
├─────────────────────────────────────────────────────────────┤
│  Compute Surfaces (execution)                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ GPU_CUDA │ │ GPU_VAAPI│ │ ETHERNET │ │FRAMEBUFF │       │
│  │ NVENC    │ │ VAAPI    │ │ virtio   │ │ /dev/fb0 │       │
│  │ 12GB VRAM│ │ shared   │ │ TX/RX    │ │ DMA      │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
├─────────────────────────────────────────────────────────────┤
│  Tailscale Mesh (connectivity)                                │
│  WireGuard encryption, DERP relay fallback                    │
│  Direct P2P when possible, relay when NAT'd                  │
│  MagicDNS, subnet routing, exit nodes                         │
├─────────────────────────────────────────────────────────────┤
│  Physical Network                                             │
│  Ethernet, WiFi, 4G/5G, satellite, mesh radio                │
└─────────────────────────────────────────────────────────────┘
```

## What Changes When Tailscale Is the Transport

### Current State (without mesh)

```
qfox-1 ──── direct IP ──── nixos (control plane)
   │
   └──── direct IP ──── racknerd (if reachable)
```

Ray nodes communicate via direct IPs. If a node is behind NAT or unreachable, it's offline. The cluster is limited to nodes with direct connectivity.

### With Tailscale Mesh

```
qfox-1 ─── WireGuard ─── nixos ─── WireGuard ─── racknerd
   │            │            │            │            │
   └── WireGuard ── neon ──── WireGuard ── steamdeck ──┘
                  │
              DERP relay
              (fallback)
```

Every node in the Tailscale mesh becomes a potential Ray worker. The mesh handles:
- NAT traversal (DERP relay when direct fails)
- Encryption (WireGuard, post-quantum Kyber768)
- Discovery (MagicDNS, coordination server)
- Routing (direct P2P when possible, relay when not)

## Architecture: Ray Over Tailscale

### Layer 1: Control Plane (Ray GCS on nixos)

```yaml
# Ray head on nixos (control-plane node)
# Binds to Tailscale IP 100.102.173.61
ray start --head \
  --node-ip=100.102.173.61 \
  --dashboard-host=0.0.0.0 \
  --port=6379
```

- Ray GCS (Global Control Store) on nixos
- Dashboard accessible via Tailscale funnel
- All workers connect via Tailscale IPs

### Layer 2: GPU Workers (qfox-1)

```
qfox-1 (100.88.57.96)
├── Ray GPU worker (RTX 4070 SUPER)
│   └── @ray.remote(num_gpus=1)
├── Ray CPU worker (AMD iGPU)
│   └── @ray.remote(resources={"APU": 1})
├── VCN encode/decode (FFmpeg NVENC/VAAPI)
└── FrameDispatcher (VCNBraidBackend + CUDABackend)
```

- Highest capability tier (GPU_CUDA + GPU_APU)
- Handles all FFmpeg-dependent tasks
- NVENC for H.264 encode, VAAPI for AMD encode
- ObjectRef transfers to/from nixos over Tailscale

### Layer 3: CPU Workers (neon-64gb)

```
neon-64gb (100.64.19.78)
├── Ray ARM64 worker (18 cores)
│   └── @ray.remote(num_cpus=16)
├── VCN encode (software libx264)
└── k3s agent (needs control plane fix)
```

- ARM64 compute for parallel CPU tasks
- Software H.264 encode (no GPU)
- Tailscale provides connectivity despite IP change

### Layer 4: Ethernet Workers (racknerd)

```
racknerd (100.80.39.40)
├── Ray lightweight worker (2 vCPU)
├── PistPacket computation (virtio-net TX/RX rings)
│   └── Host vhost-user does matrix transforms
├── Framebuffer DMA (/dev/fb0, 1024x768, 1.57 MB)
└── Tier: ETHERNET + FRAMEBUFFER
```

- Can't run FFmpeg, can't do GPU work
- CAN send PistPackets via virtio-net
- CAN write Q16_16 to /dev/fb0
- Tailscale encrypts all traffic to/from this node
- DERP relay fallback if NAT'd

### Layer 5: Edge Workers (steamdeck, ESP32, sensors)

```
steamdeck (100.85.244.73)
├── Ray worker (RDNA 2 iGPU, when online)
└── Tier: GPU_APU

ESP32 (hypothetical)
├── Q0_16 scalar in FreeRTOS idle hook
├── 520 KB SRAM, 240 MHz Xtensa
└── Tier: ESP32

DS18B20 (hypothetical)
├── 1-Wire trits during 750ms temperature conversion
└── Tier: RELAY (data collection only)
```

## Data Flow: Task Submission to Result

```
User submits task
    │
    ▼
Ray scheduler (on nixos)
    │
    ├── Is it GPU work? → qfox-1 (GPU_CUDA)
    │   └── NVENC encode → ObjectRef → Tailscale → result
    │
    ├── Is it CPU-parallel? → neon-64gb (GPU_APU/CPU_FFMPEG)
    │   └── ARM64 parallel → ObjectRef → Tailscale → result
    │
    ├── Is it lightweight? → racknerd (ETHERNET)
    │   └── PistPacket → virtio-net TX ring → host transform → RX ring
    │   └── OR framebuffer → /dev/fb0 DMA → host reads → result
    │
    └── Is it data collection? → ESP32/sensors (RELAY)
        └── 1-Wire/I2C/SPI → data → Tailscale → Ray scheduler
```

## VCN Compression Over Tailscale

The VCN pipeline compresses data before sending over the Tailscale mesh:

```
Raw braid data: 1 MB per strand
    ↓ Delta+RLE: 200 KB (5x)
    ↓ RS ECC: 250 KB (with parity)
    ↓ ChaCha20: 250 KB (encrypted)
    ↓ H.264 frame: 20 KB (50x)
    ↓ MKV container: 22 KB

Tailscale WireGuard overhead: ~60 bytes per packet
Total per strand: ~22 KB over mesh

1000 strands:
  Raw: 1000 MB over mesh → 80 seconds at 100 Mbps
  VCN: 22 MB over mesh → 1.8 seconds at 100 Mbps
```

DERP relay adds ~129ms per hop, but the 50x compression means the data transfer is negligible. The latency becomes the bottleneck, not bandwidth.

## Mesh-Aware Scheduling

Ray should be aware of the Tailscale mesh topology:

```python
@ray.remote(
    num_gpus=1,
    scheduling_strategy="NODE_AFFINITY",
    affinity_node="100.88.57.96",  # qfox-1 (GPU)
)
def gpu_task(data):
    ...
```

### Latency Classes (from RouteCost.lean)

| Class | RTT | Tailscale Path | FPGA Voltage |
|-------|-----|----------------|--------------|
| LOCAL | <1ms | Same node | 1.2V |
| NEAR | <10ms | Direct P2P | 1.0V |
| FAR | <100ms | Multi-hop | 0.8V |
| DERP | <1s | Relay | 0.6V |
| OFFLINE | ≥1s | Unreachable | 0V |

### Placement Strategy

```python
def get_placement(caps: DeviceCapabilities, latency_class: str) -> dict:
    """Mesh-aware Ray placement strategy."""
    base = get_ray_placement_strategy(caps)

    # Penalize DERP-relayed nodes (129ms extra latency)
    if latency_class == "DERP":
        base["resources"]["derp_penalty"] = 1

    # Prefer direct P2P nodes
    if latency_class in ("LOCAL", "NEAR"):
        base["resources"]["direct_link"] = 1

    return base
```

## Implementation Steps

### Phase 1: Ray over Tailscale (current)
- [x] Ray cluster on qfox-1 (head + workers)
- [x] KubeRay operator on nixos
- [x] nftables fix for pod-to-pod networking
- [ ] Fix neon-64gb k3s agent → nixos control plane
- [ ] Ray head binds to Tailscale IP
- [ ] Workers connect via Tailscale IPs

### Phase 2: Multi-tier scheduling
- [x] Device capability probe (GPU_CUDA → ESP32)
- [x] Framebuffer fallback (qemu_framebuffer_packer.py)
- [x] Ethernet tier (virtio-net PistPacket)
- [ ] Mesh-aware placement strategy
- [ ] VCN compression for cross-node ObjectRef transfers

### Phase 3: Framebuffer + Ethernet integration
- [ ] Host-side framebuffer reader (QEMU display buffer)
- [ ] Host-side PistPacket transform engine (vhost-user)
- [ ] Ray actor for framebuffer devices
- [ ] Ray actor for Ethernet devices
- [ ] Round-trip test: write → host transform → readback

### Phase 4: Edge devices
- [ ] ESP32 firmware (Q0_16 scalar, FreeRTOS idle hook)
- [ ] 1-Wire sensor integration (DS18B20 trit stream)
- [ ] Ray relay for data collection devices
- [ ] Tailscale exit node for internet access

## Key Insight

The mesh networking layer doesn't just provide connectivity — it provides a **capability-adaptive compute fabric**. Every device in the Tailscale mesh is a potential compute node. The capability probe determines what each device can do, and Ray schedules work accordingly.

The hierarchy:
1. **Tailscale** connects everything (mesh networking)
2. **Ray** schedules work across the mesh (distributed computing)
3. **VCN** compresses data for the mesh (bandwidth optimization)
4. **FrameDispatcher** routes to the right backend (tag-based routing)
5. **Compute surfaces** execute the work (GPU, CPU, framebuffer, Ethernet, MCU)

The framebuffer and Ethernet surfaces are the breakthrough — they turn devices that "can't run Ray" into compute nodes. A microVM with no GPU and no FFmpeg can still participate via /dev/fb0 or virtio-net. An ESP32 with 520 KB SRAM can still contribute Q0_16 scalars.
