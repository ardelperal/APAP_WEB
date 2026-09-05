#!/usr/bin/env bash
# scripts/setup_resend_smtp.sh — operator-side setup for Resend SMTP on Coolify.
#
# Usage:
#   ./scripts/setup_resend_smtp.sh <resend_api_key>
#
# What it does:
#   1. Sets the 5 APAP_SMTP_* env vars on the Coolify production app
#      (smtp.resend.com:465, user=resend, password=<api_key>,
#      from=noreply@romancaba.com).
#   2. Triggers a fresh deploy so the lifespan picks up the new SMTP
#      transport.
#
# Prereqs:
#   - Resend account created (https://resend.com).
#   - Domain romancaba.com verified in the Resend dashboard (SPF + DKIM
#     DNS records added and propagated). The from-address used here is
#     noreply@romancaba.com — change it via $APAP_SMTP_FROM env if you
#     want a different alias.
#   - Coolify env vars COOLIFY_API, COOLIFY_ACCESS_TOKEN, APP_UUID
#     (already in the operator's shell env or in scripts/.env).
set -euo pipefail

API_KEY="${1:?usage: $0 <resend_api_key>}"
: "${COOLIFY_API:?COOLIFY_API must be set (e.g. https://panel.romancaba.com/api/v1)}"
: "${COOLIFY_ACCESS_TOKEN:?COOLIFY_ACCESS_TOKEN must be set}"
: "${APP_UUID:?APP_UUID must be set (the apap-web resource uuid)}"
: "${SMTP_FROM:=noreply@romancaba.com}"

set_env() {
  local key="$1" value="$2"
  curl -sS -X POST "$COOLIFY_API/applications/$APP_UUID/envs" \
    -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$(printf '{"key":"%s","value":"%s","is_preview":false}' "$key" "$value")" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'  {d.get(\"key\", \"?\"):24} → {d.get(\"value\", \"?\")!r}  ({d.get(\"uuid\", \"?\")[:8]})')"
}

echo "Setting Resend SMTP env vars on app $APP_UUID:"
set_env "APAP_SMTP_HOST"     "smtp.resend.com"
set_env "APAP_SMTP_PORT"     "465"
set_env "APAP_SMTP_USER"     "resend"
set_env "APAP_SMTP_PASSWORD" "$API_KEY"
set_env "APAP_SMTP_FROM"     "$SMTP_FROM"

echo
echo "Triggering redeploy so the lifespan picks up the new SMTP transport:"
DEPLOY_UUID=$(curl -sS -X POST "$COOLIFY_API/deploy" \
  -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"uuid\":\"$APP_UUID\",\"force\":true}" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['deployments'][0]['deployment_uuid'])")
echo "  deployment: $DEPLOY_UUID"
echo
echo "Done. Wait for the deploy to finish (60-90s), then submit a magic-link"
echo "at https://apap.romancaba.com/login with your email — the link should"
echo "land in your inbox within a few seconds."
