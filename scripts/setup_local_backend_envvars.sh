#!/usr/bin/env bash
# scripts/setup_local_backend_envvars.sh — operator-side flip of the
# apap-web env vars so the data layer routes through apap-local-backend.
#
# Usage:
#   ./scripts/setup_local_backend_envvars.sh
#
# Pre-reqs:
#   - apap-local-backend is already deployed (run
#     scripts/coolify_deploy_local_backend.sh first)
#   - COOLIFY_API, COOLIFY_ACCESS_TOKEN, APP_UUID (the apap-web resource
#     uuid) set in your shell
#
# What it does:
#   1. DELETEs existing APAP_LOCAL_BACKEND and APAP_INSFORGE_URL env vars
#      on apap-web (Coolify v4's PATCH endpoint returns 404 for updates,
#      so delete+post is the reliable path)
#   2. POSTs the new values:
#         APAP_LOCAL_BACKEND=true
#         APAP_INSFORGE_URL=http://apap-local-backend:8080/api
#   3. Triggers a fresh apap-web deploy
#
# After this returns 0:
#   - /admin, /animales, /voluntarios, /salud stop returning 500
#   - The 8 dashboard counter cards populate from the local Postgres
#   - The magic-link flow still works (cookie trust chain unchanged)

set -euo pipefail

: "${COOLIFY_API:?COOLIFY_API must be set (e.g. https://panel.romancaba.com/api/v1)}"
: "${COOLIFY_ACCESS_TOKEN:?COOLIFY_ACCESS_TOKEN must be set}"
: "${APP_UUID:?APP_UUID must be set (the apap-web resource uuid)}"

set_env() {
  local key="$1" value="$2"
  local existing
  existing=$(curl -sS -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN" "$COOLIFY_API/applications/$APP_UUID/envs" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(next((e['uuid'] for e in d if e['key']=='$key' and not e['is_preview']), ''))")
  if [ -n "$existing" ]; then
    curl -sS -X DELETE "$COOLIFY_API/applications/$APP_UUID/envs/$existing" \
      -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN" > /dev/null
  fi
  curl -sS -X POST "$COOLIFY_API/applications/$APP_UUID/envs" \
    -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json; print(json.dumps({'key':'$key','value':'$value','is_preview':False}))")" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'  {d.get(\"key\")} = {d.get(\"value\")!r}')"
}

echo "Setting apap-web env vars to route through apap-local-backend:"
set_env "APAP_LOCAL_BACKEND"      "true"
set_env "APAP_INSFORGE_URL"       "http://apap-local-backend:8080/api"

echo
echo "Triggering apap-web redeploy:"
DEPLOY_UUID=$(curl -sS -X POST "$COOLIFY_API/deploy" \
  -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(python3 -c "import json; print(json.dumps({'uuid':'$APP_UUID','force':True}))")" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['deployments'][0]['deployment_uuid'])")
echo "  deployment: $DEPLOY_UUID"

for i in $(seq 1 22); do
  status=$(curl -sS -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN" "$COOLIFY_API/deployments/$DEPLOY_UUID" \
    | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    if isinstance(d,list):
        for x in d:
            s=x.get('status','')
            if s in ('finished','failed','error','cancelled'): print(s); break
        else: print('ip')
    else: print(d.get('status','?'))
except: print('err')
" 2>&1)
  echo "[$i] $status"
  if echo "$status" | grep -qE "finished|failed|error|cancelled"; then break; fi
  sleep 4
done

if [ "$status" = "finished" ]; then
  echo
  echo "apap-web now routes through apap-local-backend. Verify:"
  echo "  curl -sf https://apap.romancaba.com/admin   # should render the user table"
  echo "  curl -sf https://apap.romancaba.com/animales  # should render the animals list"
  echo "  bash scripts/smoke_local_backend.sh  # full smoke"
fi
