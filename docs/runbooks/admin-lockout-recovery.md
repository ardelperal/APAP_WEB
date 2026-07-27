# Admin Lockout Recovery Runbook (issue #279)

Every active developer can be deactivated from `/admin`, and `deactivate_authorized_user` blocks deactivating the last active developer. After this fix ships, the application can no longer reach a state where no developer exists by deactivation alone. **This runbook covers the failure mode where the database is already locked out** — for example, an operator manually flipped the only developer's `activo = false`, a botched migration toggled every developer row, or the table was truncated. The fix in this PR is preventive; the runbook is the recovery path.

## When to trigger

Use this runbook when **local data is the only thing standing between the operators and a developer-less `usuarios_autorizados` table**:

- The single active developer has been deactivated (e.g. accidental click in the admin panel, before the fix shipped).
- `ensure_schema_and_seed` no longer re-seeds because the inactive developer row satisfies the old `WHERE rol = 'developer'` predicate (the only case the new `activo = true` filter addresses, but does not *recover from*).
- The database is reachable, but `GET /admin` returns 403 / redirects to `/unauthorized` for every operator email.
- The `APAP_INITIAL_ADMIN_EMAIL` env-var is set in Coolify but no active developer row exists with that email.

Do not use this runbook for application-level issues (CSRF, session, OAuth) — those have their own runbooks.

## What the operator sees

Two symptoms, both caused by the same root cause (no active developer):

1. **In `/admin`**: the deactivation button is greyed out for the last developer (the `DEACTIVATE_USER_SQL` guard from this PR). Once the last developer is gone, the page stops rendering for any operator because `require_developer_user_redirect` rejects every role except `developer`, and `GET /admin` redirects to `/unauthorized`.
2. **Across the app**: developer-only endpoints (admin panel, role assignments, anything guarded by `require_developer_user_redirect`) become unreachable. Reader and admin users retain their access; only developer-scoped paths are lost.

## Pre-deploy checklist

Before touching the database, confirm the following:

- [ ] Read this runbook end-to-end.
- [ ] Have the value of `APAP_INITIAL_ADMIN_EMAIL` ready (the operator email configured in Coolify).
- [ ] Have InsForge / Postgres admin shell access (via the `run-raw-sql` / `get-table-schema` MCP tools, or a direct `psql` connection with the database credentials stored in Coolify).
- [ ] Confirm the live Coolify deployment is on `main` and reachable. The recovery SQL targets the same database the running app talks to.
- [ ] Confirm no other operator is running a parallel bootstrap seed (must not happen — startup is gated by the active-developer filter; still worth confirming the container is not in the middle of a restart).
- [ ] Take a backup of the current `usuarios_autorizados` table before running the manual INSERT (`SELECT * FROM public.usuarios_autorizados` to a file).

## Deploy steps

The fix in this PR is the preventive safeguard. The manual recovery SQL below is the operator path for an already-locked database. Re-deploy is not part of the recovery — the production code only needs to be running with the new `DEACTIVATE_USER_SQL` if you want the guard to keep firing after recovery (it will, since the new code ships in `main` and the manual INSERT happens against the same table).

No re-deploy or restart is required to make the manual INSERT visible. The next authenticated request from the recovered developer will see the new row; the authorization cache miss is part of the normal invalidation path (issue #143, §29).

## Manual recovery SQL

Connect to the production Postgres database (InsForge) and run the following INSERT. The schema uses **Spanish column names** — `anadido_por` (NOT `added_by`), `fecha_alta` (NOT `created_at`). Using the wrong column name returned by a translation step will silently insert `NULL` or fail the statement.

```sql
INSERT INTO public.usuarios_autorizados
  (id, email, rol, activo, anadido_por, fecha_alta)
VALUES
  (gen_random_uuid(), '<APAP_INITIAL_ADMIN_EMAIL>', 'developer', true, 'recovery', now());
```

Substitutions:

- `<APAP_INITIAL_ADMIN_EMAIL>` — replace with the value of `APAP_INITIAL_ADMIN_EMAIL` from Coolify. Keep the email exact (case-sensitive in the SQL even though the app normalizes on read — issue #278 — so copy it as-is from the env var).

After the INSERT, **restart the application** so the bootstrap path re-evaluates. Both conditions matter:

- The new `SEED_ADMIN_SQL` filter (`activo = true` subquery) means the inserted active developer will not trigger a duplicate seed.
- If the new developer is the only active developer and the operator later deactivates them, the bootstrap re-seeds only if the inactive row is removed (the dormant row is still in the table). The recovery path is not for repeated use; it is the single-step unfreeze.

The bootstrap re-seed is automatically skipped when any active developer exists, so the restart is safe to run repeatedly.

## Verification

1. Confirm the recovered row is present:

   ```sql
   SELECT id, email, rol, activo, anadido_por, fecha_alta
     FROM public.usuarios_autorizados
    WHERE email = '<APAP_INITIAL_ADMIN_EMAIL>';
   ```

   Expect: one row with `rol = 'developer'`, `activo = true`, `anadido_por = 'recovery'`.

2. Hit the admin panel as the recovered developer:

   ```bash
   curl --fail --silent https://apap.romancaba.com/admin
   ```

   Expect: 200 OK with the users table rendered. If 302 → `/unauthorized`, the session cookie is not issued or the email normalisation diverged from the database value (issue #278 — re-check the email against the canonical form).

3. Confirm the guard is still active: try to deactivate another developer with `actor = recovered`. The UI must render the flash error `cannot deactivate the last active developer` because the recovered row is the only active developer (`/admin/users/<id>/deactivate` returns 200 with the error message, not 302).

4. Add a second developer from `/admin`, then deactivate one of the two. The deactivation succeeds and the remaining developer can still access `/admin`. This proves the guard differentiates between "last developer" and "not-last developer" correctly.

5. Inspect the application logs for the deactivate event — `log_safe` emits `auth.user.deactivated` with no PII (issue #287 redaction list covers email).

## Rollback

No rollback path. The recovery SQL is purely additive (it inserts a new developer row). The new developer can be deactivated later by an existing developer, returning the system to "only one developer exists" but never to "zero developers exist".

If the INSERT was run with the wrong email:

1. Run a targeted UPDATE to correct the email:

   ```sql
   UPDATE public.usuarios_autorizados
      SET email = '<correct_email>'
    WHERE anadido_por = 'recovery' AND activo = true;
   ```

2. Re-run the verification block above.

If the INSERT was run with a wrong role (e.g. `reader` instead of `developer`):

1. UPDATE the existing row to `rol = 'developer'` — do not insert a second recovery row:

   ```sql
   UPDATE public.usuarios_autorizados
      SET rol = 'developer'
    WHERE anadido_por = 'recovery' AND activo = true;
   ```

2. Re-verify.

## Related

- `app/core/auth.py` — `DEACTIVATE_USER_SQL`, `SEED_ADMIN_SQL`, `deactivate_authorized_user`, `ensure_schema_and_seed`.
- `app/main.py` — `admin_deactivate_user` route catching `ValueError` and re-rendering `admin.html` (issue #279).
- `templates/admin.html` — flash error rendering for `error_message`.
- `tests/test_auth.py` — 5 new cases: last-developer block, self-deactivate OK, SEED fires when only inactive devs exist, role-scope (reader/admin/key_user unaffected).
- `tests/test_admin.py` — 1 new case: route renders flash error when last developer deactivation fires.
- `AGENTS.md` §13 — runbook obligation for operator-facing recovery paths.
- `AGENTS.md` §6 — security defaults deny, not permit.
- `AGENTS.md` §32.P1 — perimeter blindness (the guard sits at the SQL boundary, the UI surfaces the migration path).
- `app/core/auth_cache.py` — `invalidate_auth(email)` reclaim invoked after a successful deactivation (issue #143, §29).
