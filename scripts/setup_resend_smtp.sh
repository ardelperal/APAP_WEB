#!/usr/bin/env bash
# scripts/setup_resend_smtp.sh — operator-side setup for Resend SMTP on Coolify.
#
# Usage:
#   ./scripts/setup_resend_smtp.sh <resend_api_key>
#
# What it does:
#   1. Replaces the 5 APAP_SMTP_* env vars on the Coolify production app
#      (smtp.resend.com:465, user=resend, password=<api_key>,
#      from=onboarding@resend.dev for instant testability).
#   2. Triggers a fresh deploy so the lifespan picks up the new SMTP
#      transport.
#
# Prereqs:
#   - Resend account created (https://resend.com).
#   - API key copied from Settings → API Keys (starts with `re_`).
#   - Coolify env vars COOLIFY_API, COOLIFY_ACCESS_TOKEN, APP_UUID
#     set in the operator's shell.
#
# Note on `from`:
#   By default this script sets APAP_SMTP_FROM=onboarding@resend.dev.
#   This is the test from-address Resend ships with every account — no
#   DNS required. The recipient sees the email come from
#   "onboarding@resend.dev" (fine for internal E2E).
#
#   Once you verify romancaba.com in the Resend dashboard (Domains →
#   Add Domain → paste the SPF + DKIM records into your DNS), change
#   `from` to `noreply@romancaba.com` (or whatever alias you prefer):
#
#       ENV_UUID=$(curl -sS -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN" \
#         "$COOLIFY_API/applications/$APP_UUID/envs" \
#         | python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(e["uuid"] for e in d if e["key"]=="APAP_SMTP_FROM" and not e["is_preview"]))')
#       curl -sS -X DELETE "$COOLIFY_API/applications/$APP_UUID/envs/$ENV_UUID" \
#         -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN"
#       curl -sS -X POST "$COOLIFY_API/applications/$APP_UUID/envs" \
#         -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN" \
#         -H "Content-Type: application/json" \
#         -d '{"key":"APAP_SMTP_FROM","value":"noreply@romancaba.com","is_preview":false}'
#
#   Then redeploy.
set -euo pipefail

API_KEY="${1:?usage: $0 <resend_api_key>}"
: "${COOLIFY_API:?COOLIFY_API must be set (e.g. https://panel.romancaba.com/api/v1)}"
: "${COOLIFY_ACCESS_TOKEN:?COOLIFY_ACCESS_TOKEN must be set}"
: "${APP_UUID:?APP_UUID must be set (the apap-web resource uuid)}"
: "${SMTP_FROM:=onboarding@resend.dev}"

# 1. Enumerate existing APAP_SMTP_* env vars in production (is_preview=false).
#    Coolify v4 doesn't accept PATCH on /envs/{uuid} (returns 404), so we
#    delete+recreate to atomically replace the value.
existing_uuids=$(curl -sS -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN" \
  "$COOLIFY_API/applications/$APP_UUID/envs" \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(' '.join(e['uuid'] for e in d
              if e['key'].startswith('APAP_SMTP_')
              and not e['is_preview']))
")

for uuid in $existing_uuids; do
  curl -sS -X DELETE "$COOLIFY_API/applications/$APP_UUID/envs/$uuid" \
    -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN" > /dev/null
done
echo "Deleted $(echo "$existing_uuids" | wc -w) old APAP_SMTP_* entries."

# 2. POST fresh values.
post_env() {
  local key="$1" value="$2"
  curl -sS -X POST "$COOLIFY_API/applications/$APP_UUID/envs" \
    -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$(printf '{"key":"%s","value":"%s","is_preview":false}' "$key" "$value")" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'  {d.get(\"key\", \"?\"):24} = {d.get(\"value\", \"?\")!r}')"
}

echo "Setting Resend SMTP env vars on app $APP_UUID:"
post_env "APAP_SMTP_HOST"     "smtp.resend.com"
post_env "APAP_SMTP_PORT"     "465"
post_env "APAP_SMTP_USER"     "resend"
post_env "APAP_SMTP_PASSWORD" "$API_KEY"
post_env "APAP_SMTP_FROM"     "$SMTP_FROM"

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
