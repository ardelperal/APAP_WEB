# RawSQL shared-secret runbook (issue #680)

## What

``POST /api/database/advance/rawsql`` is the LocalBackend compatibility endpoint that mirrors LocalBackend's upstream. Every request must carry ``Authorization: Bearer <APAP_RAWSQL_AUTH_TOKEN>``; the handler rejects every other presentation with 401 before touching the executor.

Production must set the env var explicitly. An empty / weak token refuses to boot the service (``_validate_secrets`` raises ``StartupConfigError``).

## When

The token is required for:

- Any future caller of the LocalBackend compatibility HTTP surface (e.g. an admin script, a back-office tool).
- Any new mount of ``app.core.local_backend.app:create_app`` that wants to use the rawsql endpoint.

The token is not required for:

- Production traffic served by ``app.main:app`` (the main app does not mount the rawsql router).
- Migration CLI runs (``python -m migration apply`` / ``reconcile``), which use ``LocalPostgresExecutor`` in-process and never hit HTTP.
- ``tests/integration/test_local_backend.py`` round-trip suite (the fixture provisions its own test token).

## How

### Provision the token

```bash
# Generate a 44-char random token (openssl or python secrets).
python -c 'import secrets; print(secrets.token_urlsafe(32))' > .rawsql_token
export APAP_RAWSQL_AUTH_TOKEN="$(cat .rawsql_token)"
chmod 600 .rawsql_token
```

Minimum length is 32 characters (enforced by ``Settings.shared_secret_min_length``). The token must be stored outside the repo (Coolify secrets, Vault, etc.).

### Wire into Coolify

In the Coolify app configuration, add ``APAP_RAWSQL_AUTH_TOKEN`` to the environment variables. The value comes from your secret store.

### Wire into the verifier subprocess

``migration/verify_fallback_*.py`` call the executor directly today. If a future verifier switches to the HTTP surface, it must:

1. Set ``APAP_RAWSQL_AUTH_TOKEN`` in the env before launching the local backend.
2. Pass ``Authorization: Bearer <token>`` on every ``client.post(...)``.

## Verify

After deployment, confirm:

```bash
# Empty / weak token refuses to boot.
unset APAP_RAWSQL_AUTH_TOKEN
python -c 'from app.main import create_app; create_app()'
# StartupConfigError: APAP_RAWSQL_AUTH_TOKEN is invalid (reason=empty)

# Correct token boots.
export APAP_RAWSQL_AUTH_TOKEN="<correct-token>"
python -c 'from app.main import create_app; create_app()'
# (no error)
```

Smoke test the endpoint from inside the Coolify container:

```bash
curl -fsS http://localhost:8000/api/database/advance/rawsql \
  -H "Authorization: Bearer $APAP_RAWSQL_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT 1", "params": []}'
# {"rows": [{"?column?": 1}], "rowCount": 1}

curl -i http://localhost:8000/api/database/advance/rawsql \
  -H "Authorization: Bearer WRONG" \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT 1", "params": []}'
# HTTP/1.1 401 Unauthorized
```

## Rotate

1. Generate a new token (see "Provision").
2. Set the new value in Coolify / your secret store and restart the app.
3. Update every caller to use the new token.
4. Revoke the old token by setting ``APAP_RAWSQL_AUTH_TOKEN=""`` in the secret store (the next restart will refuse to boot).

There is no overlap window — the handler validates the exact string with ``hmac.compare_digest``, so partial matches never succeed.

## Rollback

To temporarily re-enable the open endpoint (incident response only):

1. Set ``APAP_RAWSQL_AUTH_TOKEN`` to a known token and restart.
2. Or temporarily set ``Settings.rawsql_auth_token`` to a non-empty placeholder that passes ``_validate_secrets``. (Do NOT lower the ``shared_secret_min_length`` floor — that would weaken the production posture.)

For a deeper rollback (back to no auth at all):

1. Revert the helper in ``app/core/local_backend/rawsql.py`` and remove the dependency on ``Settings.rawsql_auth_token``.
2. Remove the new validation block in ``app/core/config.py::_validate_secrets``.
3. Drop the unit tests in ``tests/test_rawsql_auth.py``.
4. Open a follow-up issue explaining the rollback and what new threat triggered it.
