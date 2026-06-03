# AGENTS.md - Infrastructure And Hardware

Scope: `4-Infrastructure/`

## Rules

- Keep infrastructure scripts receipt-bearing: every probe should have a
  machine-readable output or update an existing receipt.
- Separate software witnesses from live hardware witnesses.
- Do not claim FPGA acceleration from bitstream generation alone.
- Do not claim UART/fabric success without observed bytes or a matching hardware
  receipt.
- Treat `/usr/bin/sem` as GNU Parallel on this machine unless proven otherwise;
  use the isolated `sem` binary documented in stack solidification receipts when
  needed.
- Remote model/API probes must be secret-clean. Read provider credentials from
  environment variables only (`OLLAMA_API_KEY`, `DEEPSEEK_API_KEY`, etc.); never
  embed literal keys in scripts, receipts, prompts, or docs.
- LLM/model outputs are reviewer receipts, not validation. If a model review is
  promoted, store the answer and a machine-readable receipt with prompt/answer
  hashes under `shared-data/artifacts/`, and state which files formed the
  context.

## Preferred Checks

```bash
python3 -m py_compile 4-Infrastructure/shim/<script>.py
python3 -m json.tool <receipt>.json >/dev/null
```

For API-facing or receipt-writing scripts, also run a touched-file secret scan
before staging. Treat the repository credential hook as a backstop, not the
first detector.

For Tang Nano 9K work, keep the boundaries explicit:

- **bitstream present**: Compiled `tangnano9k_uart_beacon.fs` and `tangnano9k_uart_loopback.fs` via `build_uart_beacon.sh` and `build_loopback.sh`.
- **SRAM load**: Loaded `tangnano9k_uart_beacon.fs` to SRAM using `sudo openFPGALoader -b tangnano9k tangnano9k_uart_beacon.fs` (CRC check: Success).
- **flash persistence**: Pending.
- **UART beacon**: Tested onboard BL702 bridge; physical UART route is blocked due to bridge firmware limitations (documented in `6-Documentation/docs/fpga_uart_route_analysis_2026-05-09.md`). Custom virtual serial transport `virtual://q16-pty` acts as active verification path.
- **Q16/software witness**: Verified.
- **Q16/live hardware witness**: Requires external USB-UART adapter connected to pins 17/18.


## Storage Stack: restic + Garage + rclone

Three tools, three distinct jobs — no overlap:

| Tool | Job | Does NOT do |
|------|-----|------------|
| **restic** | Deduplicated, encrypted, content-addressed snapshots. Point-in-time restore. Verifiable integrity. | Raw sync, remotes management |
| **Garage** | Self-hosted S3-compatible object store across Tailscale nodes. restic's primary backend. | Dedup, encryption, scheduling |
| **rclone** | Moves raw objects between remotes (Garage↔gdrive, gdrive↔Garage). Cold-copy of restic chunks to gdrive. | Dedup, encryption, snapshots |

### Data flow

```
git commit
    └─(post-commit hook, async)─▶ restic snap ──────────────────▶ Garage:research-stack
                                   restic snap-db (SQLite)         (deduplicated, encrypted)
                                   restic snap-rds (pg_dump|zstd)  │
                                                                    │
Daily 03:00 (systemd timer)                                        │
    ├─ rclone copy ─────────────────────────────────────────────── ▶ gdrive:restic-mirror/
    │  (cold copy of restic chunks — survive Garage loss)
    └─ rclone sync ─── gdrive:research-stack ──▶ Garage:gdrive-mirror
                        (S3-native access to gdrive data)

Restore path A (Garage up):
    restic restore <id> -r s3:http://localhost:3900/research-stack

Restore path B (Garage down, gdrive available):
    restic restore <id> -r rclone:gdrive:restic-mirror
```

### Garage S3 — node topology (Tailscale mesh)

All object storage for this stack uses **Garage v2.3.0** — a single-binary,
Dynamo-style S3-compatible store written in Rust. Replaced rclone serve s3.

### Node topology (Tailscale mesh)

| Node | Tailscale IP | k3s | Garage | Zone | Disk | SSH |
|------|-------------|-----|--------|------|------|-----|
| **qfox-1** (this machine) | 100.88.57.96 | ✅ worker | ✅ 780 GiB | local | 1.8 TB NVMe | local |
| **cupfox** | 100.110.163.82 | ✅ control-plane | ✅ 69 GiB | fra | 125 GB | key OK (361395) |
| **nixos-laptop** | 100.102.173.61 | ✅ worker | ✅ 347 GiB | ord | 459 GB NVMe | key OK |
| **racknerd** | 100.80.39.40 | ✅ worker | ✅ 954 MiB | vps | 9.1 GB VPS | key OK |
| **neon-64gb** | 100.64.19.78 | ✅ worker (ARM64) | ✅ 93 GiB | netcup-arm | 2 TB | root key OK |
| **steamdeck** | 100.85.244.73 | ✅ worker | ✅ 373 GiB | gpu | 476 GB NVMe | key OK |
| rs-vps (netcup) | — | ❌ | ❌ | — | 2 TB | SSH via password |
| dracocomp | 100.100.140.27 | ❌ | ❌ | — | — | unreachable

- RPC port: **3901** (Tailscale-only, not exposed to internet)
- S3 API port: **3900** (qfox-1 only; other nodes bind loopback)
- Admin API port: **3903** (loopback only on all nodes)

### Garage S3 buckets

| Bucket | Purpose |
|--------|---------|
| `research-stack` | Primary project objects |
| `db-scratch` | Active SQLite scratch databases |
| `rds-overflow` | pg_dump / COPY TO exports from Aurora RDS |
| `snap-zone` | ZFS send/receive snapshots |
| `gdrive-mirror` | Mirror of gdrive:research-stack |

### Credentials

Credentials live in `/etc/garage/garage.env` (mode 600, never committed).
Sourced automatically by all storage scripts. Inside devcontainer, set:
```bash
source /etc/garage/garage.env
export AWS_ACCESS_KEY_ID=$GARAGE_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY=$GARAGE_SECRET_ACCESS_KEY
export AWS_ENDPOINT_URL=http://host.containers.internal:3900
export AWS_DEFAULT_REGION=garage
```

### Restic scripts (`4-Infrastructure/storage/restic/`)

| Script | Purpose |
|--------|---------|
| `restic.env` | Source this to load all credentials + repo paths |
| `backup.sh snap [tag]` | Snapshot repo tree → Garage |
| `backup.sh snap-db [dir]` | Snapshot SQLite scratch DBs → Garage |
| `backup.sh snap-rds <table>` | Stream pg_dump \| zstd → restic stdin → Garage |
| `backup.sh cold-copy` | rclone copy Garage:research-stack → gdrive:restic-mirror |
| `backup.sh sync-gdrive` | rclone sync gdrive:research-stack → Garage:gdrive-mirror |
| `backup.sh forget` | Apply retention (7 daily / 4 weekly / 6 monthly) + prune |
| `backup.sh verify` | restic check --read-data-subset=5% |
| `backup.sh snapshots` | List all snapshots |
| `backup.sh restore <id> <dst>` | Restore a snapshot |
| `backup.sh full` | snap + cold-copy + sync-gdrive + forget |

Restic repo: `s3:http://localhost:3900/research-stack` (Garage primary)
Cold copy:   `rclone:gdrive:restic-mirror` (survives Garage loss)
Password:    `/etc/garage/restic-password` (chmod 644, not committed)

Daily timer: `restic-backup.timer` fires at 03:00 ±30 min, runs `backup.sh full`.

### Garage scripts (`4-Infrastructure/storage/garage/`)

| Script | Purpose |
|--------|---------|
| `zfs-pool-setup.sh` | Create ZFS pool on local NVMe (run after reboot into 7.0.9 kernel) |
| `garage-node-bootstrap.sh <ip>` | Install Garage on a new node, register in node-registry.json |
| `garage-cluster-init.sh` | Connect nodes, assign layout, bump replication_factor to 3 |
| `db-consolidate.sh offload [dir]` | Push SQLite DBs → s3://db-scratch/ |
| `db-consolidate.sh rds-dump <table>` | Dump RDS table → s3://rds-overflow/ |
| `db-consolidate.sh consolidate` | Restore static s3://rds-overflow/ objects → RDS |
| `db-consolidate.sh sync-gdrive` | Mirror gdrive:research-stack → s3://gdrive-mirror/ |
| `db-consolidate.sh status` | Show cluster and bucket state |

### Replication status

`replication_factor = 3`, zone redundancy enforced, 6 nodes across 6 zones.
~1.3 TiB total capacity, ~440 GiB effective (RF3).

Add a new Garage node:
```bash
bash 4-Infrastructure/storage/garage/garage-node-bootstrap.sh <tailscale_ip>
```

### Git post-commit hook

`.git/hooks/post-commit` automatically runs `db-consolidate.sh offload` +
`db-consolidate.sh consolidate` in the background after every commit.
Non-blocking. Skipped silently if Garage isn't running.
Log at `~/.cache/garage-post-commit.log`.

### gdrive integration

gdrive is still mounted via rclone at `/home/allaun/gdrive` for direct file
access. The `db-consolidate.sh sync-gdrive` command mirrors it into the
`gdrive-mirror` Garage bucket for S3-native access without hitting Drive API
quotas on every read.

Drive API safe-use rules still apply to any direct rclone → gdrive operations:
- `--drive-pacer-min-sleep 200ms` — ≤5 TPS sustained
- `--drive-pacer-burst 10` — limits burst before pacer beats
- `--dir-cache-time 10m` — warm cache = zero API calls

## Storage Agent (`4-Infrastructure/storage/storage_agent.py`)

Full-loop observer, optimizer, and actor for the restic + Garage + rclone stack.

### Design contract

**Shim boundary** (per AGENTS.md §7.1):

- ALLOWED: subprocess calls to existing CLI tools (`backup.sh`, `db-consolidate.sh`,
  `restic`, `aws s3`), JSON I/O, JSONL log, receipt assembly, threshold
  comparisons on Q16_16-encoded integers.
- FORBIDDEN: reimplementing restic/Garage/rclone logic, Float arithmetic, cost
  functions (those belong in Lean), new external dependencies.

### Observe → Decide → Act → Emit loop

```
Observation          Decision              ActionResult
─────────────────    ──────────────────    ──────────────────
garage_up            trigger_snap          actions_attempted
garage_buckets       trigger_cold_copy     actions_succeeded
restic_snapshot_count trigger_verify       actions_failed
dedup_ratio_q16      trigger_forget        details
backup_log_last_ok   trigger_offload
cold_copy_needed     trigger_garage_restart
errors               alerts / rationale
```

All numeric thresholds are Q16_16 (UInt32, one = 0x00010000 = 65536).
No Float arithmetic. Threshold constants defined at the top of the file.

### Receipt schema: `storage_agent_receipt_v1`

Every cycle emits one receipt:

```json
{
  "schema":           "storage_agent_receipt_v1",
  "version":          "1.0.0",
  "generated_at_utc": "<ISO-8601>",
  "tick":             <int>,
  "parent_hash":      "<sha256 of previous receipt>",
  "observation":      { ... },
  "decision":         { ... },
  "action_result":    { ... },
  "claim_boundary":   "storage-agent-observe-decide-act-only",
  "receipt_hash":     "<sha256 of canonical preimage>"
}
```

Two sinks:
1. **Local JSONL hash-chain**: `~/.cache/storage-agent.jsonl` — fast local access,
   survives Garage loss.
2. **Garage S3**: `s3://research-stack/agent-receipts/<date>/<hash16>.json` —
   durable, indexed by date.

### Trigger model

| Trigger | Condition | Action |
|---------|-----------|--------|
| `trigger_snap` | No snapshots, or backup log shows no recent success | `backup.sh snap agent-triggered` |
| `trigger_cold_copy` | Newest snapshot > 26 h old (daily timer may have missed) | `backup.sh cold-copy` |
| `trigger_verify` | dedup_ratio_q16 < 0.3 AND snapshot_count > 5 | `backup.sh verify` |
| `trigger_forget` | snapshot_count > 30 | `backup.sh forget` (prune) |
| `trigger_offload` | Garage is up (idempotent) | `db-consolidate.sh offload` |
| `trigger_garage_restart` | Garage unreachable | `systemctl restart garage.service` |

### Systemd units

| File | Purpose |
|------|---------|
| `storage-agent.service` | One-shot service (Type=oneshot, User=allaun) |
| `storage-agent.timer`   | Fires every 15 min (OnCalendar=*:0/15, RandomizedDelaySec=60) |

Installation:
```bash
sudo cp 4-Infrastructure/storage/storage-agent.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now storage-agent.timer
```

### Post-commit integration

`.git/hooks/post-commit` runs the agent (`--once`) in the background after
each `backup.sh snap` completes. The agent observes the post-snap state and
takes any follow-on corrective actions (offload, cold-copy if stale, etc.).
Log at `~/.cache/storage-agent.log`.

### Usage

```bash
# One-shot probe (observe only, no actions)
python3 4-Infrastructure/storage/storage_agent.py --probe-only

# One-shot, full loop
python3 4-Infrastructure/storage/storage_agent.py --once

# Show what would be done
python3 4-Infrastructure/storage/storage_agent.py --dry-run

# Skip S3 receipt upload (local JSONL only)
python3 4-Infrastructure/storage/storage_agent.py --no-s3

# Daemon mode (rarely needed; systemd timer is preferred)
python3 4-Infrastructure/storage/storage_agent.py --loop --interval 900
```

### Log paths

| Path | Contents |
|------|---------|
| `~/.cache/storage-agent.jsonl` | Hash-chained JSONL receipt log |
| `~/.cache/storage-agent.log` | Human-readable stdout/stderr from systemd and hook runs |
| `s3://research-stack/agent-receipts/` | Durable S3 receipts (Garage) |

## Current Stack-Solidification Anchors

- `4-Infrastructure/shim/stack_solidification_audit.py`
- `4-Infrastructure/shim/stack_fail_closure_register.py`
- `4-Infrastructure/shim/beaver_mask_freshness_negative_controls.py`
- `4-Infrastructure/shim/tang9k_uart_beacon_probe.py`
- `4-Infrastructure/shim/hutter_jxl_starfield_eigenprobe.py`
- `4-Infrastructure/shim/hutter_jxl_starfield_replay_verify.py`
- `4-Infrastructure/shim/braid_diat_codec.py` — Python extraction of BraidDiatCodec (ChiralityDIAT + MountainPacked + BraidResidual + BraidDiatFrame); benchmark artifact at `shared-data/artifacts/braid_diat_codec_benchmark.json`
- `4-Infrastructure/shim/spirv_copy_if_optimizer.py` — SPIR-V OpPhi→OpSelect transform (OpBranchConditional+OpPhi → OpSelect); eliminates branch over head; emits `CopyIfPattern` with type_id fix
- `4-Infrastructure/shim/spirv_packet_generator.py` — OpPhi-driven packet descriptor generator: SPIR-V asm → copy-if optimizer → JSON packet descriptors (5 OpPhi fields: type_id, cond_id, true_val_id, false_val_id, result_id)
- `4-Infrastructure/shim/virtio_net_transform.py` — Virtio-net ring as computation pipeline: three Class-1 primitives (HASH_REPORT RSS Toeplitz, TSO gso_size split, MRG_RXBUF merge) via virtio_net_hdr_v1_hash; zero backend changes needed
- `4-Infrastructure/shim/vcn_compute_substrate.py` — AMD VCN / NVIDIA NVENC H.264/H.265 hardware video encoder as compute device via MKV trick; dynamically detects GPU vendor (NVIDIA/AMD/Intel) to load math-optimized lossless parameters (YUV444p10le, full-range PC spacing, CABAC offload, VAAPI/NVENC/AMF wrappers); carries BraidStrand/BraidBracket payloads; vectorized packing
- `4-Infrastructure/shim/qemu_framebuffer_packer.py` — QEMU graphics framebuffer packer mapping Q16_16 scalars to ARGB8888/RGB24 pixels for mmap-based zero-copy display DMA loopback
- `4-Infrastructure/shim/rrc_ray_tagger.py` — RRC Ray Layer Tagger; classifies math payloads into RRC shapes and matches them to swappable compute slots and transports
- `4-Infrastructure/cloudflare/src/lib.rs` — Cloudflare Workers edge WASM trinary VM core implementing the Q0_16 scalar compute floor
- `4-Infrastructure/cloudflare/src/index.js` — Cloudflare Workers entry point, POST-only, JSON + binary protocol
- `4-Infrastructure/cloudflare/wrangler.toml` — Wrangler config, deployed at `https://wasm-compute-edge.researchstack.workers.dev`
- `4-Infrastructure/hardware/emergency_boot/emergency_boot_shim.py` — Python I/O shim
  for Geometry Emergency Boot Witness (6502 calculator-efficiency FPGA controller)
  Specification: `6-Documentation/docs/specs/GEOMETRY_EMERGENCY_BOOT_WITNESS_2026-04-08.md`

## Compute Dispatch (WGSL → any substrate)

All compute shaders live as WGSL source. Dispatch follows a single pattern:

  RDS SELECT (input strands, weights) → wgpu SSBO → WGSL compute → readback → RDS INSERT

The wgpu Rust dispatch (pattern: `5-Applications/parquet_compressor/src/gpu.rs`)
probes the adapter and chooses the best available backend transparently:

  Adapter probe:
    └── Vulkan → GPU (discrete or integrated)
    └── Vulkan (lavapipe/SwiftShader) → CPU blitter (L1 cache, ~112 ops/step)
    └── WebGPU (WASM) → Browser GPU or WASM CPU fallback

The algorithm is always WGSL. The dispatch is always wgpu. The backend is
transparent. No path specialization is needed because Q16_16 integer arithmetic
is deterministic across all substrates.

Known dispatch entry points:
- `5-Applications/parquet_compressor/src/gpu.rs` — Rust wgpu compute + XOR/S-box
- `5-Applications/scripts/rgflow_gpu_pipeline.py` — Python wgpu with Vulkan backend
- `4-Infrastructure/gpu/wasmgpu/` — TypeScript WebGPU engine with 47 WGSL shaders
- `4-Infrastructure/shim/erdos_surface_orchestrator/src/main.rs` — WGSL generator

For the braid eigensolid compressor, the dispatch is planned at:
`4-Infrastructure/shim/braid_blitter/` (Rust, following `parquet_compressor/src/gpu.rs`)

### ENE schema additions for DSP volunteer computing (PipeWire/FLAC)

Any Linux node with PipeWire can act as a DSP compute worker regardless of physical audio hardware.
A virtual sound card is created via PipeWire, exposing FLAC audio chunks as compute workloads.

- `ene.dsp_nodes` — PipeWire/FLAC DSP node capabilities: node_id, dsp_available,
  pipewire_available, virtual_soundcard_supported, physical_soundcard, max_sample_rate,
  spectral_bands, latency_target_us, fft_size, overlap_factor, last_seen_at, receipt_hash
- Dispatch: FLAC chunks in MKV audio track → routed to DSP-capable nodes → results
  returned via separate reply channel
- Shim: `4-Infrastructure/shim/flac_dsp_node.py` — node registration, PipeWire probe,
  FLAC chunk spectral analysis (FFT peaks, spectral centroid, RMS level)
- Receipt: every DSP operation writes to `~/.cache/flac_dsp_receipts.jsonl`

### ENE schema additions for braid eigensolid compressor (planned)

These tables extend `ene_substrate_schema.sql` (not yet created):

- `ene.prover_state` — Lean theorem registry: theorem_name, module_path,
  statement_hash, status (pending/verified/failed), dependency DAG
- `ene.prover_instances` — Concrete theorem instantiations: theorem_id,
  input_hash, output_hash, verified boolean
- `ene.sidon_labels` — Powers of 2 (1,2,4,8,16,32,64,128) per strand index
- `ene.crossing_weights` — Q0_2 values encoded as INTEGER with CHECK constraint,
  contractive matrix trigger (row sum < 65536)
- `ene.braid_strands` — Per-snapshot strand state: phase_x, phase_y in Q16_16
- `ene.eigensolid_snapshots` — Converged state: matrix_id, convergence_step,
  phase_hash, residual_total, is_stable
- `ene.receipts ADD theorem_id` — FK to prover_state
- `ene.receipts ADD dispatch_path` — CHECK(vulkan_gpu, cpu_blitter)

## Cross-References

See root `AGENTS.md` for:
- **Post-Interaction Workflow** (mandatory 5-step session-end procedure)
- **Programming Choice Flow** (Lean owns decisions; Python owns I/O — shims must not contain decision/gating/scoring logic)
- **Do Not Sweep** rules (no broad `git add .`)
- **Git Remote Hygiene**
