#!/usr/bin/env bash
set -euo pipefail

###########################################################################
# deploy-services.sh
#
# Idempotent service deployer for the k3s unified topology.
# Called by the deploy-k3s-services systemd oneshot on the server node.
#
# Flow:
#   1. Wait for k3s cluster to be healthy
#   2. Ensure namespaces exist
#   3. Create the K8s Secret for authentik from the sops-decrypted file
#   4. Apply authentik HelmChart CRD
#   5. Apply all service manifests (kustomize where available)
#
# URL contract (canonical paths served by internal Caddy router):
#   /                    → Homer
#   /apps/chat/*         → Hermes
#   /apps/jellyfin/*     → Jellyfin
#   /apps/books/*        → Audiobookshelf
#   /apps/music/*        → Navidrome
#   /apps/budget/*       → Actual Budget
#   /server/status/*     → Uptime Kuma
#   /server/dash/*       → Homarr
#   /server/vault/*      → Vaultwarden
#   /api/cred/*          → Credential Server
#   /api/registry/*      → Registry API
#   /api/jobs/*          → Job Router
#   /api/blobs/*         → Blob Plane
#   auth.researchstack.info → Authentik (stable OIDC issuer)
###########################################################################

MANIFESTS_DIR="/etc/nixos/k3s-flake/manifests"

echo "[deploy] waiting for k3s cluster to be healthy..."
until kubectl cluster-info --request-timeout=5s >/dev/null 2>&1; do
  sleep 3
done
echo "[deploy] cluster is healthy"

echo "[deploy] ensuring CoreDNS has schedulable replicas..."
kubectl -n kube-system scale deployment/coredns --replicas=3

echo "[deploy] ensuring namespaces exist..."
kubectl get namespace services >/dev/null 2>&1 || kubectl create namespace services
kubectl get namespace media >/dev/null 2>&1 || kubectl create namespace media

# ── Authentik secrets from sops (age-encrypted) ─────────────────────────
# The AUTHENTIK_SECRETS file is decrypted by sops-nix from secrets/authentik-secrets.age
# It contains: secret-key, postgresql-password, and optionally bootstrap-password
# All values are age-encrypted at rest in the repository.
if [ -n "${AUTHENTIK_SECRETS:-}" ] && [ -f "$AUTHENTIK_SECRETS" ]; then
  echo "[deploy] creating authentik-secrets from age-encrypted sops file..."
  kubectl delete secret --ignore-not-found -n services authentik-secrets
  kubectl create secret generic -n services authentik-secrets \
    --from-env-file="$AUTHENTIK_SECRETS"

  secret_key=$(sed -n 's/^secret-key=//p' "$AUTHENTIK_SECRETS")
  postgresql_password=$(sed -n 's/^postgresql-password=//p' "$AUTHENTIK_SECRETS")
  bootstrap_password=$(sed -n 's/^bootstrap-password=//p' "$AUTHENTIK_SECRETS")
  
  if kubectl get secret -n services authentik-env >/dev/null 2>&1; then
    echo "[deploy] preserving existing authentik-env runtime secret"
  elif [ -n "$secret_key" ] && [ -n "$postgresql_password" ]; then
    echo "[deploy] creating authentik-env from age-decrypted sops file..."
    
    # Build the kubectl create command with optional bootstrap password
    kubectl_cmd=(
      kubectl create secret generic -n services authentik-env
      --from-literal=AUTHENTIK_SECRET_KEY="$secret_key"
      --from-literal=AUTHENTIK_POSTGRESQL__PASSWORD="$postgresql_password"
      --from-literal=AUTHENTIK_POSTGRESQL__HOST=authentik-postgresql
      --from-literal=AUTHENTIK_POSTGRESQL__PORT=5432
      --from-literal=AUTHENTIK_POSTGRESQL__NAME=authentik
      --from-literal=AUTHENTIK_POSTGRESQL__USER=authentik
    )
    
    # Add bootstrap password if present (for initial akadmin user)
    if [ -n "$bootstrap_password" ]; then
      echo "[deploy] including AUTHENTIK_BOOTSTRAP_PASSWORD for initial admin setup"
      kubectl_cmd+=(--from-literal=AUTHENTIK_BOOTSTRAP_PASSWORD="$bootstrap_password")
    fi
    
    "${kubectl_cmd[@]}"
  fi
fi

# ── Apply manifests ──────────────────────────────────────────────────────
echo "[deploy] applying authentik HelmChart..."
kubectl apply -f "$MANIFESTS_DIR/authentik/helm-chart.yaml"

echo "[deploy] applying all service manifests..."
find "$MANIFESTS_DIR" -maxdepth 1 -type d | sort | while read -r dir; do
  name=$(basename "$dir")
  [ "$dir" = "$MANIFESTS_DIR" ] && continue
  [ "$name" = "authentik" ] && continue
  if [ -f "$dir/kustomization.yaml" ] || [ -f "$dir/kustomization.yml" ]; then
    echo "[deploy]   applying $name (kustomize)..."
    kubectl apply -k "$dir"
  else
    echo "[deploy]   applying $name..."
    kubectl apply -f "$dir"
  fi
done

echo "[deploy] done — all services applied"
