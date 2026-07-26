# Startup Config Validation Runbook (issue #275)

APAP_WEB now validates critical secrets at startup: `APAP_SESSION_SECRET`
must be at least 32 characters and not the published development placeholder,
and `APAP_INSFORGE_SERVICE_KEY` must be non-empty. The validation gate
runs in the FastAPI lifespan **before** any InsForge connection is opened,
so a misconfigured deploy fails fast rather than silently signing sessions
with a known-secret placeholder.

## When to trigger

Use this runbook:

- before a first production deployment;
- after rotating `APAP_SESSION_SECRET` or `APAP_INSFORGE_SERVICE_KEY`;
- when a deploy fails with `StartupConfigError` in the application logs;
- before adding `APAP_DEBUG=true` to a production environment (do not do this).

## What the operator sees when the deploy fails

The application logs (JSON, stdout) contain an entry like:

```json
{
  "event": "startup.config_invalid",
  "level": "INFO",
  "_caller_fields": {
    "event": "startup.config_invalid",
    "env_var": "APAP_SESSION_SECRET",
    "reason": "placeholder"
  }
}
```

followed by a Python traceback ending with:

```
app.core.config.StartupConfigError: startup config error: APAP_SESSION_SECRET
is invalid (reason=placeholder); set a real value via the env var (or
APAP_DEBUG=true to bypass in local dev)
```

The application does not start. The health probe (`/healthz`) returns 503
or times out.

## Pre-deploy checklist

- [ ] `APAP_INSFORGE_SERVICE_KEY` is set to the real InsForge service key
      (not the empty default).
- [ ] `APAP_SESSION_SECRET` is set to a random string of **at least 32 characters**.
- [ ] `APAP_DEBUG` is **not** set to `true` in the production environment.
- [ ] You have tested the secret generation snippet below locally.

## Deploy steps

### Generate a safe secret

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

This prints a cryptographically random 32-character (256-bit) string.
Copy the output and set it as the value of `APAP_SESSION_SECRET`.

### Set secrets in Coolify

1. Open the Coolify application dashboard for `apap-web`.
2. Navigate to **Environment variables**.
3. Add or update `APAP_INSFORGE_SERVICE_KEY` with the real service key
   from the InsForge dashboard.
4. Add or update `APAP_SESSION_SECRET` with the generated secret.
5. Save and trigger a new deployment.

## Verification

1. Confirm the deploy is healthy:

   ```bash
   curl --fail --silent https://apap.romancaba.com/healthz
   ```

   Expected: `{"status":"ok","app":"APAP_WEB"}` with exit code 0.

2. Inspect the startup log for the validation event:

   ```bash
   # If your aggregator captures stdout JSON:
   grep "startup.config_invalid" /path/to/app.log
   # Should show: env_var="APAP_SESSION_SECRET", reason="placeholder" NOT present
   ```

3. A local startup guard can be verified without deploying:

   ```bash
   APAP_SESSION_SECRET="dev-only-change-me-in-production" \
     APAP_INSFORGE_SERVICE_KEY="ik_real_key" \
     python -c "from app.main import create_app; create_app()"
   ```

   Expected: non-zero exit with `StartupConfigError: ... reason=placeholder`.

## Rollback

If a previous working deployment used an empty `APAP_INSFORGE_SERVICE_KEY`
or the placeholder `APAP_SESSION_SECRET`:

1. Restore the previous values in Coolify environment variables.
2. Redeploy.
3. Confirm `curl https://apap.romancaba.com/healthz` returns 200.

**Warning**: A rollback to the placeholder secret means every session cookie
is signed with a value published in the repository. Any reader of the repo
could forge a session cookie. Prioritise setting a real secret and redeploy
rather than rolling back unless an incident is in progress.

## Related

- `app/core/config.py` — `StartupConfigError`, `_validate_secrets`, and
  `_PLACEHOLDER_SESSION_SECRET`.
- `app/main.py` — lifespan wiring: validator called between
  `configure_logging` and `InsForgeClient`.
- `docs/audits/secret-startup-validation-2026-Q3.md` — security audit.
- `AGENTS.md` §32.P2 — the anti-pattern this runbook closes.
