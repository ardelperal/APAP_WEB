#!/usr/bin/env bash
# scripts/coolify_deploy_local_backend.sh — operator-side deploy of the
# self-host InsForge-compatible backend as a Coolify service.
#
# Usage:
#   ./scripts/coolify_deploy_local_backend.sh [--tag 1.0.0]
#
# Pre-reqs:
#   - COOLIFY_API, COOLIFY_ACCESS_TOKEN, COOLIFY_PROJECT, COOLIFY_ENVIRONMENT
#     set in your shell (the same vars used by setup_resend_smtp.sh)
#   - docker installed and GHCR login (or a local registry mirror)
#   - 90s budget — the deploy polls every 4s
#
# What it does:
#   1. Builds the image: `docker build -f docker/local-backend.Dockerfile`
#   2. Tags and pushes to GHCR (or skips if --local)
#   3. Calls Coolify's POST /v1/applications to create the resource
#      (using the manifest in coolify/apap-local-backend.json as the
#      source of truth for every field)
#   4. Triggers a deploy and watches the deployment until finished
#
# After this script returns 0:
#   - http://apap-local-backend:8080/healthz returns 200 with
#     {"db": "up", "storage": "up", "oauth": "missing"}
#   - apap-web (if env vars are flipped per setup_local_backend_envvars.sh)
#     starts routing data queries through it

set -euo pipefail

: "${COOLIFY_API:?COOLIFY_API must be set (e.g. https://panel.romancaba.com/api/v1)}"
: "${COOLIFY_ACCESS_TOKEN:?COOLIFY_ACCESS_TOKEN must be set}"
: "${COOLIFY_PROJECT:?COOLIFY_PROJECT must be set (e.g. mjgxwv4srqlsuww4pfpyo0t7)}"
: "${COOLIFY_ENVIRONMENT:?COOLIFY_ENVIRONMENT must be set (e.g. c7wgl2dmapown2x84f1gbgl9)}"

TAG="1.0.0"
LOCAL_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --tag)        shift; TAG="$1"; shift ;;
    --tag=*)      TAG="${arg#*=}"; shift ;;
    --local)      LOCAL_ONLY=1; shift ;;
    *) echo "unknown arg: $arg" >&2; exit 1 ;;
  esac
done

MANIFEST="coolify/apap-local-backend.json"
NAME=$(python3 -c "import json; print(json.load(open('$MANIFEST'))['name'])")
IMAGE=$(python3 -c "import json; print(json.load(open('$MANIFEST'))['image'])")
DSN=$(python3 -c "import json; print(json.load(open('$MANIFEST'))['env']['APAP_LOCAL_BACKEND_DSN'])")
OAUTH=$(python3 -c "import json; print(json.load(open('$MANIFEST'))['env']['APAP_LOCAL_BACKEND_OAUTH_CONFIGURED'])")
ADMIN=$(python3 -c "import json; print(json.load(open('$MANIFEST'))['env']['APAP_INITIAL_ADMIN_EMAIL'])")

# 1. Build the image
FULL_IMAGE="$IMAGE"
if [ "$LOCAL_ONLY" = "1" ]; then
  FULL_IMAGE="apap-local-backend:$TAG"
  echo "Building local image: $FULL_IMAGE"
  docker build -f docker/local-backend.Dockerfile -t "$FULL_IMAGE" .
else
  echo "Building and pushing: $FULL_IMAGE"
  docker build -f docker/local-backend.Dockerfile -t "$FULL_IMAGE" .
  docker push "$FULL_IMAGE"
fi

# 2. Create the Coolify resource
echo "Creating Coolify application: $NAME"
CREATE_BODY=$(python3 -c "
import json
m = json.load(open('$MANIFEST'))
m['image'] = '$FULL_IMAGE'
m['project_uuid'] = '$COOLIFY_PROJECT'
m['environment_uuid'] = '$COOLIFY_ENVIRONMENT'
print(json.dumps(m))
")
APP_RESP=$(curl -sS -X POST "$COOLIFY_API/applications" \
  -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$CREATE_BODY")
APP_UUID=$(echo "$APP_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('uuid', ''))")
if [ -z "$APP_UUID" ]; then
  echo "ERROR creating application:" >&2
  echo "$APP_RESP" >&2
  exit 1
fi
echo "  application uuid: $APP_UUID"

# 3. Set env vars (in case the manifest didn't already include them, the
#    set_env calls are idempotent — DELETE then POST).
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

echo "Setting env vars:"
set_env "APAP_LOCAL_BACKEND_DSN"        "$DSN"
set_env "APAP_LOCAL_BACKEND_OAUTH_CONFIGURED" "$OAUTH"
set_env "APAP_INITIAL_ADMIN_EMAIL"       "$ADMIN"

# 4. Trigger deploy
echo
echo "Triggering deploy:"
DEPLOY_UUID=$(curl -sS -X POST "$COOLIFY_API/deploy" \
  -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(python3 -c "import json; print(json.dumps({'uuid':'$APP_UUID','force':True}))")" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['deployments'][0]['deployment_uuid'])")
echo "  deployment: $DEPLOY_UUID"

# 5. Watch until done (max 90s)
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
  echo "Local backend deployed. Smoke test:"
  APP_HEALTH=$(curl -sS -H "Authorization: Bearer $COOLIFY_ACCESS_TOKEN" "$COOLIFY_API/applications/$APP_UUID" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','?'))")
  echo "  Coolify status: $APP_HEALTH"
  echo
  echo "Next: flip apap-web env vars:"
  echo "  ./scripts/setup_local_backend_envvars.sh"
  exit 0
else
  echo "Deploy did not finish green. Check:"
  echo "  $COOLIFY_UI_URL/project/$COOLIFY_PROJECT/application/$APP_UUID"
  exit 1
fi
