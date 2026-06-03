#!/usr/bin/env bash
# k3s agent bootstrap — run on any Linux node to join the cluster
# Usage: curl -sfL <url> | bash -s -- --role edge --server https://100.102.173.61:6443 --token <token>
set -euo pipefail

ROLE="core"
SERVER="https://100.110.163.82:6443" # cupfox control-plane (migrated from nixos)
TOKEN=""
NODE_IP=""
LABELS=""

while [ $# -gt 0 ]; do
  case "$1" in
    --role) ROLE="$2"; shift 2 ;;
    --server) SERVER="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    --node-ip) NODE_IP="$2"; shift 2 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

if [ -z "$TOKEN" ]; then
  echo "ERROR: --token is required"
  echo "Get it from the server: sudo cat /var/lib/rancher/k3s/server/node-token"
  exit 1
fi

# Detect node IP if not provided
if [ -z "$NODE_IP" ]; then
  NODE_IP=$(hostname -I | awk '{print $1}')
fi

# Map role → labels and taints
case "$ROLE" in
  core)
    LABELS="topology.researchstack.io/role=core,topology.researchstack.io/gpu=true,topology.researchstack.io/storage-tier=nvme-ssd,topology.researchstack.io/compute-class=core"
    ;;
  edge)
    LABELS="topology.researchstack.io/role=edge,topology.researchstack.io/gpu=false,topology.researchstack.io/storage-tier=vps-ssd,topology.researchstack.io/compute-class=edge"
    TAINT="pulse-only=true:NoSchedule"
    ;;
  mirror)
    LABELS="topology.researchstack.io/role=mirror,topology.researchstack.io/gpu=false,topology.researchstack.io/storage-tier=vps-ssd,topology.researchstack.io/compute-class=mirror"
    ;;
  foxtop)
    LABELS="topology.researchstack.io/role=foxtop,topology.researchstack.io/gpu=true,topology.researchstack.io/storage-tier=nvme-ssd,topology.researchstack.io/compute-class=primary"
    ;;
  *)
    echo "Unknown role: $ROLE (core|edge|mirror|foxtop)"
    exit 1
    ;;
esac

echo "[join-agent] Installing k3s agent for role=$ROLE on $NODE_IP"

# Install k3s
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="v1.35.4+k3s1" K3S_URL="$SERVER" \
  K3S_TOKEN="$TOKEN" \
  K3S_NODE_IP="$NODE_IP" \
  K3S_NODE_NAME="$(hostname -s)" \
  INSTALL_K3S_EXEC="agent \
    --node-label $LABELS" \
  sh -

# Apply taint for edge nodes
if [ -n "${TAINT:-}" ]; then
  echo "[join-agent] Applying taint: $TAINT"
  kubectl taint nodes "$(hostname -s)" "$TAINT" --overwrite 2>/dev/null || true
fi

echo "[join-agent] Done. Node $(hostname -s) joined with role=$ROLE"
