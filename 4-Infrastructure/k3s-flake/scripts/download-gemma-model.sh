#!/bin/bash
# Download the Gemma-4-E4B OBLITERATED model + mmproj to Garage S3
# All nodes can then pull layers via VCN-LUPINE for distributed inference.
#
# Usage: bash download-gemma-model.sh [dest_dir]
set -euo pipefail

DEST="${1:-/var/lib/gemma-models}"
BASE_URL="https://huggingface.co/rdhorner/gemma-4-E4B-it-OBLITERATED-GGUF/resolve/main"
MODELS=(
  "gemma-4-E4B-OBLITERATED-Q8_0.gguf:7.5GB:7400000000"
  "mmproj-gemma-4-E4B-OBLITERATED-F16.gguf:945MB:900000000"
)

echo "Downloading Gemma-4-E4B OBLITERATED models to $DEST..."
mkdir -p "$DEST"

for entry in "${MODELS[@]}"; do
  FILE="${entry%%:*}"
  DESC="${entry#*:}"
  DESC="${DESC%%:*}"
  MIN="${entry##*:}"
  MODEL_PATH="$DEST/$FILE"
  SIZE=$(stat -c%s "$MODEL_PATH" 2>/dev/null || echo 0)
  if [ ! -f "$MODEL_PATH" ] || [ "$SIZE" -lt "$MIN" ]; then
    rm -f "$MODEL_PATH"
    echo "Downloading $FILE ($DESC)..."
    curl -fLo "$MODEL_PATH" "$BASE_URL/$FILE" --retry 3 --retry-delay 10 --location
    echo "Done."
  else
    echo "$FILE cached ($SIZE bytes)."
  fi
done

# Upload to Garage S3 for cluster-wide access
# Use the nearest Garage S3 API endpoint (qfox-1 binds :3900 publicly; others loopback only).
GARAGE_S3_HOST="${GARAGE_S3_HOST:-100.88.57.96}"
GARAGE_S3_URL="http://${GARAGE_S3_HOST}:3900"
if command -v rclone &>/dev/null; then
  echo "Uploading to Garage S3 at $GARAGE_S3_URL ..."
  if [ -n "${GARAGE_ACCESS_KEY_ID:-}" ] && [ -n "${GARAGE_SECRET_ACCESS_KEY:-}" ]; then
    rclone mkdir "garage:hermes-models" 2>/dev/null || true
    for entry in "${MODELS[@]}"; do
      FILE="${entry%%:*}"
      rclone copyto "$DEST/$FILE" "garage:hermes-models/$FILE" --s3-endpoint "$GARAGE_S3_URL" --s3-no-check-bucket
    done
    echo "Uploaded via rclone. All nodes can now access via GARAGE_ENDPOINTS."
  else
    echo "WARNING: garage credentials not in env. Skipping upload."
  fi
elif command -v aws &>/dev/null; then
  echo "Uploading via aws cli ..."
  for entry in "${MODELS[@]}"; do
    FILE="${entry%%:*}"
    aws s3 cp "$DEST/$FILE" "s3://hermes-models/$FILE" --endpoint-url "$GARAGE_S3_URL"
  done
fi

echo "Done. Model layers available for VCN-LUPINE distributed inference."
echo "  qfox-1:     RTX 4070      via CUDA/LUPINE          — VRAM-optimized layers"
echo "  nixos:      AMD Radeon    via VCN/VAAPI + /dev/fb0  — DMA backplane + VCN"
echo "  steamdeck:  AMD VanGogh   via VCN/VAAPI             — VCN-accelerated"
echo "  neon-64gb:  ARM CPU x18   via llama.cpp             — CPU fallback"
echo "  racknerd:   virtio-net    via packet-as-computation — light compute"
