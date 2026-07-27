# Auth Email Normalization Runbook (issue #277 + #278)

`fix/issue-277-278-ghost-users` closes two defects at the auth boundary:

- **#277** — `admin_add_user` raised an unhandled `InsForgeError` (500) when a
  duplicate email slipped past the pre-insert check; the route now surfaces the
  duplicate (or any other validation failure) back to the admin page as a
  flash message.
- **#278** — emails were compared case-sensitively against
  `usuarios_autorizados.email`, so `Maria.Lopez@Example.COM` and
  `maria.lopez@example.com` were two distinct users (the *ghost user*
  anti-pattern). Every auth boundary now passes through
  `app.core.auth_helpers.normalize_email` (strip + lowercase), the per-email
  cache key is case-folded, and `invalidate_auth` sweeps all case variants.

The application code is already shipped; this runbook covers the **operator
follow-up** for any rows that already exist in `usuarios_autorizados` with
mixed casing.

## When to trigger

Run this runbook:

- **after** deploying `fix/issue-277-278-ghost-users` to production;
- **before** the next backup restore (so the new code reads from clean data);
- whenever a user reports "I can't log in" and you suspect their email was
  inserted twice with different casing by the legacy code path;
- as a one-shot hygiene pass: even if no users are currently broken, the
  ghost rows will eventually surface as duplicate-render glitches in the admin
  panel (the `LIST_USERS_SQL` ORDER BY shows both variants).

This is a one-time migration for each environment. After it completes, the new
code prevents new ghosts from being created.

## What the operator sees

The pre-fix behaviour let `usuarios_autorizados` accumulate rows whose
`email` columns differ only in case. The new code treats them as duplicates of
the canonical lowercased form, so an admin who tries to re-add `John@Example.com`
will hit the "email already authorized" flash even though the table holds
`john@example.com`.

The duplicate-detection SQL is the canonical way to find these rows before any
new write lands:

```sql
-- Find rows where the lowercased email appears more than once (mixed-case duplicates)
SELECT LOWER(email) AS normalized, COUNT(*) AS n, array_agg(email) AS variants
FROM public.usuarios_autorizados
GROUP BY LOWER(email)
HAVING COUNT(*) > 1;
```

A clean table returns **zero rows**. Any row this query returns is a ghost
group that the new code would either silently shadow or reject on the next
add.

If your Postgres role does not have `array_agg`, the equivalent without it is:

```sql
SELECT LOWER(email) AS normalized, COUNT(*) AS n,
       string_agg(email, ' | ' ORDER BY email) AS variants
FROM public.usuarios_autorizados
GROUP BY LOWER(email)
HAVING COUNT(*) > 1;
```

## Pre-deploy checklist

- [ ] Read this runbook end-to-end.
- [ ] Notify the team in `#apap-ops` that the dedupe migration is about to
      happen; capture who is on call.
- [ ] Have the duplicate-detection SQL above ready to paste into
      `psql` / the InsForge query surface.
- [ ] Confirm you can read `usuarios_autorizados` with the operator role that
      will run the dedupe.
- [ ] Confirm the deployed commit hash for `fix/issue-277-278-ghost-users`
      includes `f41e717` (or a successor) — see `git log --oneline main`.
- [ ] Decide the rename target for losing rows in each duplicate group (see
      step 2 of the dedupe procedure below).
- [ ] Snapshot the table before the dedupe so the migration is reversible:

      ```sql
      CREATE TABLE usuarios_autorizados__pre_email_dedupe AS
      SELECT * FROM public.usuarios_autorizados;
      ```

## Deploy steps

1. **Confirm the code is already on `main`.** This runbook does not deploy
   anything; `fix/issue-277-278-ghost-users` merged to `main` as PR #308 and
   the Coolify deploy job (gated on `ci.yml`) picks it up automatically. The
   first thing the runbook expects is that the running pod already has commit
   `f41e717` (or a successor). If not, merge via CI first:

   ```bash
   git fetch origin
   git log --oneline origin/main | head -5
   ```

   The commit subject you want is
   `feat(auth): normalize_email helper + add_authorized_user validation + cache case-folding + admin error rendering (issue #277, #278)`.

2. **Run the duplicate-detection SQL** (from §"What the operator sees") against
   the production table. Capture the output as
   `users_ghost_groups_pre_dedupe.csv` for the audit trail.

3. **Execute the dedupe procedure** (§"Dedupe procedure" below).

4. **Re-run the duplicate-detection SQL**. It must return zero rows.

5. **Verify the application** (§"Verification" below).

## Dedupe procedure

For every group the duplicate-detection SQL returns:

1. **Run the duplicate-detection SQL above** and capture the group list.

2. **For each duplicate group, manually decide which row to keep.** Typical
   heuristics, in order of preference:
   - The row the user actually uses to log in (their live `email`).
   - The most recently active row (use `fecha_alta` + any `last_login` evidence
     the admin panel exposes).
   - The oldest row if neither side has activity signal (preserve the audit
     trail of who was added first).

   Document the choice in the migration log so the audit can trace it back.

3. **Update the loser's email** to a unique placeholder that can never match
   the canonical form:

   ```sql
   -- For each losing row in group <N>
   UPDATE public.usuarios_autorizados
   SET email = 'disabled + ' || to_char(now() AT TIME ZONE 'UTC',
                                       'YYYY-MM-DD"T"HH24:MI:SS"Z"') || '@archive.local'
   WHERE id = '<loser-uuid>';
   ```

   The `disabled + <timestamp>@archive.local` form is intentional:
   - `disabled + ...` keeps the row visible to the operator as a tombstone.
   - The `@archive.local` TLD guarantees no real client could ever resolve it,
     so the cache cannot accidentally re-attach the loser to a future live
     user.
   - The timestamp disambiguates if you run the dedupe again.

   If the table has a UNIQUE constraint on `email`, the placeholder must be
   unique per row. The timestamp above already guarantees that.

4. **Re-run the duplicate-detection SQL.** It must return **zero rows**.

5. **After all duplicates are resolved, the normal migration is complete.** The
   new code (already deployed) now sees a clean canonical table. No further
   manual steps are required.

If a duplicate group is genuinely two distinct users (e.g. a typo created two
real accounts), keep both rows and rename the loser to a real alternative
address owned by that person instead of the tombstone form. The new code will
accept both rows as long as their lowercased forms are unique.

## Verification

1. **Duplicate-detection SQL returns zero rows:**

   ```sql
   SELECT LOWER(email) AS normalized, COUNT(*) AS n, array_agg(email) AS variants
   FROM public.usuarios_autorizados
   GROUP BY LOWER(email)
   HAVING COUNT(*) > 1;
   ```

   Expected: 0 rows.

2. **Application health check:**

   ```bash
   curl --fail --silent https://apap.romancaba.com/healthz
   ```

   Expected: `{"status":"ok"}` (or whatever the existing `/healthz` payload is).

3. **Admin panel renders without ghost rows.** Log in as a developer-role user,
   navigate to `/admin`, and confirm the user table shows each email once at
   its canonical (lowercased) form. If any row still shows mixed casing, the
   dedupe missed a group — re-run the detection SQL.

4. **Re-add test:** pick one of the tombstoned loser rows in the admin panel,
   confirm the form rejects re-adding the original email with a flash error
   (`email already authorized: <canonical>`), and that re-adding a NEW email
   for the same person succeeds.

5. **Cache smoke check (optional):** in the running pod, hit
   `GET /admin/users` twice in quick succession and inspect the application
   logs for one `auth.cache_hit` per email per TTL window — `invalidate_auth`
   was called on the loser during the dedupe, so its next request should miss
   and re-fetch.

## Rollback

The application change is **non-destructive**: PR #308 only changes how the
app *reads* and *writes* the table — it does not mutate existing rows on its
own. Reverting the code leaves the table in whatever state the dedupe left it.

- **If you have not yet run the dedupe:** rollback is a no-op. Revert the
  deploy and the table is untouched.
- **If you have run the dedupe:** the tombstoned losers (`disabled +
  <timestamp>@archive.local`) are recoverable from the
  `usuarios_autorizados__pre_email_dedupe` snapshot you created in §"Pre-deploy
  checklist". The recovery is a `pg_dump`/`pg_restore` of the snapshot, or a
  per-row `UPDATE` if the snapshot is large. The application does not need a
  code rollback in either case — it tolerates both old and new states
  identically.

If the deploy itself must be rolled back (rare — only if the new code regresses
an unrelated path), use the standard Coolify redeploy workflow against the
previous `main` HEAD. The migration lock is a thing you hold during the
dedupe (§"Pre-deploy checklist" snapshot), not during the code deploy.

## Related

- `app/core/auth_helpers.py` — `normalize_email` + `validate_email_format`
  (single source of truth, AGENTS.md §4 + §25).
- `app/core/auth.py` — `add_authorized_user` pre-check + defense-in-depth
  `InsForgeError` mapping (issue #277) and `normalize_email` plumbing
  (issue #278).
- `app/core/auth_cache.py` — `invalidate_auth` case-variant sweep
  (`_case_variants`) and case-folded cache key (issue #278).
- `app/core/admin_helpers.py` — flash-message helpers `_pop_flash` /
  `_redirect_with_flash` (issue #277).
- `app/main.py` — `admin_add_user` handler with `_add_user_or_error` and the
  post-success render path.
- `tests/test_auth.py`, `tests/test_auth_cache.py`, `tests/test_auth_helpers.py`,
  `tests/test_admin.py` — TDD safety net.
- `docs/audits/ghost-users-audit-2026-Q3.md` — defect audit for #277 + #278.
- `docs/runbooks/auth-cache-multi-worker.md` — companion runbook for the
  cache worker-scope semantics that issue #278 interacts with.
- Issues: #277 (partial exception handling — §32.P4), #278 (perimeter
  blindness — §32.P1 example).
- AGENTS.md §4 (one source of truth per domain concept), §12 (audit doc
  requirement), §13 (runbook requirement), §25 (no duplicated helper
  functions), §32.P1 (perimeter blindness), §32.P4 (partial exception
  handling).