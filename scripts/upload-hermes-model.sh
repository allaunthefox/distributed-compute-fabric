#!/bin/bash
# upload-hermes-model.sh — Upload GGUF model to Garage for Hermes
#
# Usage: bash upload-hermes-model.sh /path/to/model.gguf [bucket_name]
#
# Prerequisites:
#   - Garage CLI installed (garage)
#   - Garage config at /etc/garage/garage.toml
#   - Garage cluster healthy
#   - AWS credentials configured for S3 API (or use garage admin API)
#
# Model info:
#   File: Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf
#   Direct download: https://huggingface.co/HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive/resolve/main/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf

set -euo pipefail

MODEL_PATH="${1:-/home/allaun/Downloads/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf}"
BUCKET_NAME="${2:-hermes-models}"
MODEL_NAME=$(basename "$MODEL_PATH")

# Direct download URL (if needed for reference)
DIRECT_URL="https://huggingface.co/HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive/resolve/main/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf"

# Find garage binary
GARAGE_BIN=""
for p in /usr/local/bin/garage /run/current-system/sw/bin/garage /usr/bin/garage; do
    if [ -x "$p" ]; then
        GARAGE_BIN="$p"
        break
    fi
done

if [ -z "$GARAGE_BIN" ]; then
    echo "ERROR: garage binary not found" >&2
    exit 1
fi

# Check if model file exists
if [ ! -f "$MODEL_PATH" ]; then
    echo "ERROR: Model file not found: $MODEL_PATH" >&2
    exit 1
fi

# Get model size
MODEL_SIZE=$(du -h "$MODEL_PATH" | cut -f1)
echo "Uploading $MODEL_NAME ($MODEL_SIZE) to Garage bucket '$BUCKET_NAME'..."

# Create bucket if it doesn't exist
if ! $GARAGE_BIN -c /etc/garage/garage.toml bucket list 2>/dev/null | grep -q "$BUCKET_NAME"; then
    echo "Creating bucket '$BUCKET_NAME'..."
    $GARAGE_BIN -c /etc/garage/garage.toml bucket create "$BUCKET_NAME"
fi

# Upload model
$GARAGE_BIN -c /etc/garage/garage.toml object put --bucket "$BUCKET_NAME" \
    --key "$MODEL_NAME" \
    --content-type "application/octet-stream" \
    --content-disposition "attachment; filename=\"$MODEL_NAME\"" \
    "$MODEL_PATH"

echo "✅ Uploaded $MODEL_NAME to bucket '$BUCKET_NAME'"
echo ""
echo "S3 Access (if S3 API enabled):"
echo "  s3://$BUCKET_NAME/$MODEL_NAME"
echo ""
echo "Garage CLI access:"
echo "  garage object get --bucket $BUCKET_NAME --key $MODEL_NAME -o /path/to/save.gguf"
echo ""
echo "To use with Hermes, set these environment variables:"
echo "  GARAGE_ENDPOINT=http://<garage-node-ip>:3900"
echo "  GARAGE_BUCKET=$BUCKET_NAME"
echo "  GARAGE_KEY=$MODEL_NAME"
