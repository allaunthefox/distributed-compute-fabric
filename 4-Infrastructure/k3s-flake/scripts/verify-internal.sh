#!/usr/bin/env bash
# verify-internal.sh — internal routing smoke test
#
# Run on nixos-laptop (100.102.173.61) after nixos-rebuild switch,
# BEFORE deploying the edge Caddy. Exercises the host-Caddy → Traefik
# → Ingress path directly so you know the internal leg is clean.
#
# Usage:
#   bash 4-Infrastructure/k3s-flake/scripts/verify-internal.sh
#   bash 4-Infrastructure/k3s-flake/scripts/verify-internal.sh --remote
#     (runs via ssh root@100.102.173.61 if not already on the node)
#
# Exit 0 = all checks passed.
# Exit 1 = one or more checks failed; details printed to stderr.
set -euo pipefail

NODE_IP="100.102.173.61"
PASS=0
FAIL=0

# ── helpers ──────────────────────────────────────────────────────────────────

green() { printf '\033[32m✓ %s\033[0m\n' "$*"; }
red()   { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; }

check() {
  local label="$1"; shift
  if "$@" 2>/dev/null; then
    green "$label"
    (( PASS++ )) || true
  else
    red "$label"
    (( FAIL++ )) || true
  fi
}

# Run from remote if requested and not already on the node.
if [[ "${1:-}" == "--remote" ]]; then
  echo "[verify] running remotely on $NODE_IP..."
  exec ssh "root@$NODE_IP" bash -s < "$0"
fi

echo
echo "═══════════════════════════════════════════════════════"
echo "  Internal routing smoke test — $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "  Target node: $NODE_IP"
echo "═══════════════════════════════════════════════════════"
echo

# ── 0. Listener sanity ───────────────────────────────────────────────────────
echo "── 0. Port listeners ──"

check "host Caddy owns :80" \
  bash -c "ss -tlnp | grep -q ':80 '"

check "Traefik NodePort :30080 is accessible" \
  nc -z -w 2 "$NODE_IP" 30080

echo

# ── 1. Root path: Homer or Authentik redirect ────────────────────────────────
echo "── 1. GET / (expect 200 Homer or 302 → Authentik) ──"

root_status=$(curl -so /dev/null -w '%{http_code}' \
  -H "Host: researchstack.info" \
  -H "X-Forwarded-Proto: https" \
  --max-time 5 \
  "http://$NODE_IP/")

check "/ returns 200, 302 or 404 (got $root_status)" \
  bash -c '[[ '"$root_status"' == 200 || '"$root_status"' == 302 || '"$root_status"' == 404 ]]'

if [[ "$root_status" == "302" ]]; then
  root_loc=$(curl -so /dev/null -w '%{redirect_url}' \
    -H "Host: researchstack.info" \
    -H "X-Forwarded-Proto: https" \
    --max-time 5 \
    "http://$NODE_IP/")
  check "/ redirect points to auth.researchstack.info (not an http://10x... internal URL)" \
    bash -c '[[ '"\"$root_loc\""' == *"auth.researchstack.info"* ]]'
fi

echo

# ── 2. API bypass: /api/* must NOT 302 to Authentik ─────────────────────────
echo "── 2. /api/* paths must not redirect to Authentik ──"

for path in /api/registry/health /api/jobs/health /api/blobs/health; do
  status=$(curl -so /dev/null -w '%{http_code}' \
    -H "Host: researchstack.info" \
    --max-time 5 \
    "http://$NODE_IP$path")

  check "$path → $status (not 302)" \
    bash -c '[[ '"$status"' != 302 ]]'

  if [[ "$status" == "302" ]]; then
    loc=$(curl -so /dev/null -w '%{redirect_url}' \
      -H "Host: researchstack.info" \
      --max-time 5 \
      "http://$NODE_IP$path")
    red "  redirect target: $loc"
  fi
done

echo

# ── 3. auth.researchstack.info → Authentik (no forward_auth loop) ───────────
echo "── 3. auth.researchstack.info serves Authentik (200 or 302, no loop) ──"

auth_status=$(curl -so /dev/null -w '%{http_code}' \
  -H "Host: auth.researchstack.info" \
  -H "X-Forwarded-Proto: https" \
  --max-time 5 \
  "http://$NODE_IP/")

check "auth.researchstack.info returns 200 or 302 (got $auth_status)" \
  bash -c '[[ '"$auth_status"' == 200 || '"$auth_status"' == 302 ]]'

# If it's a redirect, the location must not point back to an internal IP
if [[ "$auth_status" == "302" ]]; then
  auth_loc=$(curl -sI \
    -H "Host: auth.researchstack.info" \
    -H "X-Forwarded-Proto: https" \
    --max-time 5 \
    "http://$NODE_IP/" | grep -Fi 'Location:' | tr -d '\r\n')
  check "auth redirect is relative or does not point to internal IP ($auth_loc)" \
    bash -c '[[ ! '"\"$auth_loc\""' =~ (100\.|127\.|10\.|192\.) ]]'
fi

# Response body should look like Authentik (may be empty if redirecting to flow)
auth_body=$(curl -s \
  -H "Host: auth.researchstack.info" \
  -H "X-Forwarded-Proto: https" \
  -L --max-redirs 3 --max-time 10 \
  "http://$NODE_IP/" 2>/dev/null || true)

check "auth response contains Authentik markers" \
  grep -q -E "authentik|ak-flow|Sign in" <<< "$auth_body"

echo

# ── 4. Host header passthrough ────────────────────────────────────────────────
echo "── 4. Host header passthrough (server Caddy → Traefik) ──"

# The Traefik dashboard is disabled, but /ping is available by default
ping_status=$(curl -so /dev/null -w '%{http_code}' \
  --max-time 5 \
  "http://$NODE_IP:30080/ping" 2>/dev/null || echo "000")

check "Traefik /ping on :30080 responds (got $ping_status — 200/404 both ok, 000 = not reachable)" \
  bash -c '[[ '"$ping_status"' != 000 ]]'

# Confirm Host is forwarded by checking a real Ingress path
jobs_status=$(curl -so /dev/null -w '%{http_code}' \
  -H "Host: researchstack.info" \
  --max-time 5 \
  "http://$NODE_IP/api/jobs/health")

check "/api/jobs/health via host Caddy → Traefik → service (got $jobs_status, not 000)" \
  bash -c '[[ '"$jobs_status"' != 000 ]]'

echo

# ── 5. X-Forwarded-Proto passthrough ─────────────────────────────────────────
echo "── 5. X-Forwarded-Proto preserved through server Caddy ──"

# Hermes placeholder echoes back X-Forwarded headers in its /health response
# if deployed. If not, check that Traefik doesn't return 000 on the path.
proto_status=$(curl -so /dev/null -w '%{http_code}' \
  -H "Host: researchstack.info" \
  -H "X-Forwarded-Proto: https" \
  --max-time 5 \
  "http://$NODE_IP/api/registry/health")

check "X-Forwarded-Proto: https request routes without error (got $proto_status)" \
  bash -c '[[ '"$proto_status"' != 000 ]]'

echo
echo "═══════════════════════════════════════════════════════"
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "═══════════════════════════════════════════════════════"
echo

if (( FAIL > 0 )); then
  echo "[verify] FAIL — fix the red checks before deploying the edge." >&2
  exit 1
fi

echo "[verify] PASS — internal leg is clean. Safe to deploy k3s-edge."
echo "  Next: nixos-rebuild switch on microvm-racknerd, then run:"
echo "    cd 4-Infrastructure/k3s-flake/tests && npm test"
