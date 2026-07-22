# Auth Cache: Multi-Worker Deployment Runbook (issue #262)

## Purpose

The auth cache backing `require_authorized_user`
(`app/core/auth_cache.py`, original issue #143) is **per-worker**: each
uvicorn/gunicorn worker process holds its own in-memory cache. When an
admin deactivates a user via `/admin/users/{id}/deactivate`, the cache
invalidation (`invalidate_auth(email)`) only reaches the worker that
called it. Other workers keep serving the stale verdict until their TTL
expires (default `APAP_AUTH_CACHE_TTL_SECONDS=300`, 5 minutes) or the
worker restarts.

This runbook gives operators a deterministic playbook for the
multi-worker case:

- Lowering `APAP_AUTH_CACHE_TTL_SECONDS` to `0` for immediate
  cluster-wide revocation (cheap, one extra `SELECT` per request).
- Switching to the shared Redis backend once the follow-up PR wires it
  (cluster-wide revocation in ~1 RTT, requires Redis).
- Documenting the per-worker scope of the default in-process backend so
  the limitation is not surprising.

The structural seam is in `app/core/auth_cache.py` (issue #262, see
the module docstring). The Redis backend class exists as a stub today
(`RedisAuthCache`); the wire-up to a real Redis client is the follow-up
PR.

## When to read this runbook

- **Incident**: a deactivated user can still hit `/admin/*` for up to
  `APAP_AUTH_CACHE_TTL_SECONDS` per worker. Read this runbook; pick
  remediation (drop TTL to `0`, or deploy a Redis backend if available).
- **Capacity planning**: a new uvicorn/gunicorn deployment runs more
  than 1 worker. Read this runbook; decide TTL vs Redis before going
  live.
- **Pre-prod review**: the issue #262 acceptance criteria mention this
  doc as the operator-facing remediation.

## Pre-deploy checklist

- [ ] Worker count confirmed (Coolify → Application → Deploy → the
      `--workers N` argument in the start command, or gunicorn
      `workers = N`).
- [ ] If switching to Redis: Redis reachable from the app container
      (Coolify → Networking → Service); TLS or VPC peering configured
      per environment policy.
- [ ] `APAP_AUTH_CACHE_BACKEND` decided: keep `"in_process"` (default)
      or set to `"redis"` (after the follow-up PR wires the real
      client).
- [ ] `APAP_AUTH_CACHE_TTL_SECONDS` decided: keep `300` (default,
      single-process acceptable; multi-worker waits up to TTL per
      worker), drop to `60` (faster worker-local staleness, 1 extra
      SELECT per user per minute), or drop to `0` (immediate revocation,
      1 extra SELECT per request).
- [ ] Plan for rollback captured: previous env values + the deploy
      strategy (`recreate` on Coolify).

## Decision matrix

| Deployment | Backend | TTL | Worst-case staleness per worker |
|---|---|---|---|
| Single worker (dev, hobby) | `in_process` (default) | 300 | TTL |
| Multi-worker, accept up to 5 min | `in_process` (default) | 300 | TTL |
| Multi-worker, accept up to 1 min | `in_process` (default) | 60 | TTL |
| Multi-worker, want immediate revocation, no Redis | `in_process` | 0 | 0 (one extra SELECT per request) |
| Multi-worker, want immediate revocation, have Redis | `redis` (follow-up PR) | any | ~1 RTT |

## Deploy steps

### Option A: drop TTL to `0` (no new dep, immediate revocation)

1. Coolify → Application → Environment → edit
   `APAP_AUTH_CACHE_TTL_SECONDS=0`.
2. Click "Save" + "Redeploy" (atomic, recreate strategy).
3. Verify (below).

Effect: one extra `SELECT FROM usuarios_autorizados WHERE email = $1`
per authenticated request. Per the architecture doc's quality bar, this
is acceptable; the same SELECT was already issued unconditionally
before issue #143 added the cache. Cost: query budget increases
linearly with concurrent users; the deactivation budget stays bounded
by network round-trip to InsForge.

### Option B: switch to the Redis backend (follow-up PR required)

1. Ensure `pip install '.[cache-redis]'` (or the equivalent extra) is
   wired into the production image. This is NOT done in this slice —
   the follow-up PR adds the `redis` dep under an optional extra.
2. Coolify → Application → Environment → set
   `APAP_AUTH_CACHE_BACKEND=redis`.
3. Set `APAP_REDIS_URL` (or equivalent; the follow-up PR specifies the
   exact name) to a real Redis instance.
4. Click "Save" + "Redeploy".

Effect: `invalidate_auth(email)` propagates to every worker in ~1 RTT.
The cluster-wide staleness window drops to one network round trip.

NOTE: this slice ships only the structural seam. Setting
`APAP_AUTH_CACHE_BACKEND=redis` without the follow-up PR wired raises
`NotImplementedError` at the first cache operation — fail-loud, not
silent.

### Option C: keep the default (single-process or TTL tolerance)

If your deployment runs a single worker, OR if up to
`APAP_AUTH_CACHE_TTL_SECONDS` per-worker staleness is acceptable, leave
the defaults:

```bash
APAP_AUTH_CACHE_BACKEND=in_process   # default; not required
APAP_AUTH_CACHE_TTL_SECONDS=300      # default; not required
```

Document the limit in the operator handoff so the next person is not
surprised.

## Verification

After the deploy, verify the cache behavior matches the chosen option.

### Smoke (any option)

```bash
curl -i https://<env>.apap.local/healthz   # 200 OK in <60s
```

### Verify TTL=0 disables the cache

```bash
# Authenticate as a known user, observe InsForge query log shows
# one SELECT FROM usuarios_autorizados per request (not per TTL window).
tail -f /var/log/apap/queries.log | grep "usuarios_autorizados"
```

Expected with `TTL=0`: a SELECT per authenticated request.

### Verify Redis backend (after the follow-up PR wires it)

```bash
# Worker A:
redis-cli -h <redis-host> SET apap:auth_cache:<email>:generation 0

# Worker B reads:
redis-cli -h <redis-host> GET apap:auth_cache:<email>:generation
# Expected: 0 (workers share the version counter)
```

Follow-up PR will pin the exact key layout.

### Verify per-worker staleness is bounded by TTL (default)

1. Spin two workers (`--workers 2`).
2. Log in as `test@example.com` on worker 1 → 302 redirect to
   `/login` (no session yet).
3. Authenticate; the session cookie is now valid for worker 1.
4. Send the same request to worker 2 (round-robin / different
   instance). If the cache hits on worker 2, you'll see no DB query.
5. From worker 1, deactivate the user.
6. Hit any authenticated route on worker 2.
7. Expected with TTL=300: the request STILL succeeds for up to 300s
   (per-worker staleness). This is the documented limit.
8. Set TTL=0 and repeat: the request is denied on the next hit on
   worker 2.

## Rollback

If the new TTL or backend misbehaves:

1. Coolify → Application → Environment → restore the previous value
   of `APAP_AUTH_CACHE_TTL_SECONDS` / `APAP_AUTH_CACHE_BACKEND`.
2. Click "Redeploy".
3. Re-run the smoke verification.

Effect: the cache behavior reverts to the previous value on the next
deploy; no persistent state to clean up (the in-process cache is wiped
on restart anyway; Redis state, once wired, persists by design).

## Related

- `app/core/auth_cache.py` — the seam (Protocol + InProcessAuthCache +
  RedisAuthCache stub + factory).
- `app/core/config.py` — `auth_cache_backend` and
  `auth_cache_ttl_seconds` settings.
- `app/core/auth_dependencies.py:198-221` — `require_authorized_user`,
  the only consumer of the cache.
- `AGENTS.md` Rule 12 (audit doc) and Rule 13 (this runbook).
- `docs/audits/auth-cache-shared-2026-Q3.md` — the audit doc that
  accompanies this runbook.
- `docs/audits/auth-revalidation-2026-Q3.md` — the issue #143 audit
  doc; this runbook is the multi-worker follow-up.
- `tests/test_auth_cache_backend.py` — the test suite that pins the
  seam + scope documentation.
