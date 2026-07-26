# Auth Cache Multi-Worker Runbook (issue #287)

APAP_WEB now supports one authorization-cache backend: the worker-local
`in_process` cache. This resolves the old Redis selector, which was configurable
but never implemented. `APAP_AUTH_CACHE_BACKEND=redis` and every unknown value
now fail settings validation during application startup, before traffic is
served.

## Current production state

Confirmed on 2026-07-25 from the live Coolify application details and the
repository Dockerfile:

| Setting | Confirmed value |
|---|---|
| Coolify application | `apap-web` |
| Build pack | `dockerfile` |
| Coolify start-command override | none (`start_command=null`) |
| Application replicas | 1 (`swarm_replicas=1`) |
| Image command | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| Uvicorn `--workers` argument | absent |
| Effective auth-cache scope today | one process, one cache |

The current deployment therefore does not need cross-worker invalidation.
`invalidate_auth(email)` invalidates the only process-local cache immediately.
The semantics remain worker-local: adding workers or replicas creates independent
caches, each of which can retain a verdict until its TTL expires.

## When to trigger

Use this runbook:

- before adding `--workers N` where `N > 1`;
- before increasing the Coolify application replica count above 1;
- when a deactivated user remains authorized on another worker;
- when changing `APAP_AUTH_CACHE_TTL_SECONDS` or
  `APAP_AUTH_CACHE_BACKEND`.

## Pre-deploy checklist

- [ ] Confirm the live Coolify application still has one replica.
- [ ] Confirm no start-command override adds `--workers`.
- [ ] Confirm `APAP_AUTH_CACHE_BACKEND` is unset or exactly `in_process`.
- [ ] If the target has multiple workers or replicas, set
      `APAP_AUTH_CACHE_TTL_SECONDS=0` before scaling.
- [ ] Record the previous worker count, replica count, backend value, and TTL.
- [ ] Confirm the expected query increase is acceptable when TTL is zero: one
      authorization `SELECT` per authenticated request.

## Deploy steps

### Keep the current single-worker deployment

1. Leave the Coolify replica count at 1.
2. Leave the application start-command override empty so the Dockerfile `CMD`
   remains authoritative.
3. Remove `APAP_AUTH_CACHE_BACKEND` or set it to `in_process`.
4. Keep the chosen TTL (`300` by default).
5. Redeploy and complete the verification below.

### Scale to multiple workers or replicas

1. Set `APAP_AUTH_CACHE_TTL_SECONDS=0` in Coolify and save it.
2. Ensure `APAP_AUTH_CACHE_BACKEND` is unset or `in_process`.
3. Redeploy with TTL zero while the application still has one worker.
4. Increase the Uvicorn worker count or Coolify replica count.
5. Redeploy again and complete the verification below.

TTL zero makes every cache lookup stale, so each authenticated request consults
`usuarios_autorizados`. This preserves immediate revocation across independent
workers without claiming cluster-wide invalidation.

## Verification

1. Confirm the deploy is healthy:

   ```bash
   curl --fail --silent https://apap.romancaba.com/healthz
   ```

2. In Coolify, confirm the application status is `running:healthy`, the intended
   replica count is active, and the start-command override matches the plan.
3. In the application container, inspect the Uvicorn process arguments:

   ```bash
   ps -ef | grep '[u]vicorn'
   ```

   For the current deployment, expect one Uvicorn process without `--workers`.
4. Confirm startup logs contain no Pydantic validation error for
   `auth_cache_backend`.
5. For a multi-worker deployment, deactivate a test user and send authenticated
   requests across repeated load-balanced connections. With TTL zero, every
   request after deactivation must be denied after the in-flight request ends.

A local startup guard can be checked without deploying:

```bash
APAP_AUTH_CACHE_BACKEND=redis python -c "from app.core.config import get_settings; get_settings()"
```

Expected: non-zero exit with a validation error naming `auth_cache_backend`.
The app must never start and then fail with `NotImplementedError` on a request.

## Rollback

If TTL zero causes unacceptable query load:

1. Reduce the deployment to one Uvicorn worker and one Coolify replica first.
2. Restore the previous positive `APAP_AUTH_CACHE_TTL_SECONDS` value.
3. Ensure `APAP_AUTH_CACHE_BACKEND` remains unset or `in_process`.
4. Redeploy.
5. Re-run the health and process-count checks.

Do not restore a positive TTL while multiple workers remain active unless the
per-worker staleness window is explicitly accepted. There is no persistent cache
state to clean up; every deploy starts the process-local cache empty.

## Related

- `app/core/auth_cache.py` — worker-local cache, generation guard, and facades.
- `app/core/config.py` — TTL plus the `in_process` compatibility guard.
- `AGENTS.md` §29 — deployment contract.
- `docs/audits/auth-cache-in-process-audit-2026-Q3.md` — #287 security audit.
- `tests/test_auth_cache_backend.py` — backend and settings contracts.
- `tests/test_lifespan.py` — startup rejection for stale Redis configuration.
