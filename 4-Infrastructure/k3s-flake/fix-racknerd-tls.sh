#!/usr/bin/env bash
# Fix Caddy TLS on racknerd
# 1. Update Porkbun API keys via sops
# 2. Deploy updated NixOS config with production LE CA
# 3. Restart Caddy
#
# Usage: ./fix-racknerd-tls.sh
# Prerequisites: sops age key configured, SSH access to racknerd

set -euo pipefail

RACKNERD_IP="100.80.39.40"
RACKNERD_SSH="root@${RACKNERD_IP}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SECRETS_DIR="${SCRIPT_DIR}/secrets"

echo "=== Step 1: Check current Porkbun keys ==="
echo "Current keys (redacted):"
sops --input-type yaml --output-type yaml -d "${SECRETS_DIR}/porkbun-env.age" 2>/dev/null | sed 's/pk1_[^ ]*/pk1_***/' | sed 's/sk1_[^ ]*/sk1_***/'

echo ""
echo "=== Step 2: Verify production LE CA is in config ==="
grep -n "acme-v02" "${SCRIPT_DIR}/k3s-edge.nix" && echo "✅ Production LE CA configured" || echo "❌ Production LE CA missing"

echo ""
echo "=== Step 3: Deploy to racknerd ==="
echo "To deploy the NixOS config with production LE CA:"
echo "  ssh ${RACKNERD_SSH} 'cd /etc/nixos && sudo nixos-rebuild switch'"
echo ""
echo "Or if using deploy-rs:"
echo "  deploy .#racknerd --hostname ${RACKNERD_IP}"
echo ""
echo "After deploy, restart Caddy:"
echo "  ssh ${RACKNERD_SSH} 'sudo systemctl restart caddy'"
echo ""
echo "Verify:"
echo "  ssh ${RACKNERD_SSH} 'sudo journalctl -u caddy -n 20'"
echo "  curl -vI https://researchstack.info 2>&1 | grep -i issuer"

echo ""
echo "=== Step 4: If Porkbun keys are invalid ==="
echo "1. Go to https://porkbun.com/account/api"
echo "2. Generate new API key pair"
echo "3. Edit the secret:"
echo "   sops ${SECRETS_DIR}/porkbun-env.age"
echo "4. Replace PORKBUN_API_KEY and PORKBUN_SECRET_KEY"
echo "5. Redeploy (Step 3)"
