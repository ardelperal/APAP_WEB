# Runbook — FOSTER-04 materiales: partial unique index failure recovery

## When to use this runbook

Trigger: `ensure_domain_schema` fails on application startup with the error:
```
relation "estancia_materiales" already exists
DETAIL: Key (estancia_id, material_id)=(...) is duplicated.
```

Or:
```
ERROR: could not create unique index "estancia_materiales_active_unique"
DETAIL: Key (estancia_id, material_id)=(...) is duplicated.
```

Both errors mean: the application cannot start because the partial unique index cannot be created due to pre-existing duplicate active rows in `estancia_materiales`.

## Pre-deploy checklist

Before deploying FOSTER-04 (#46) PR A schema to any environment that already has data in `estancia_materiales`:

- [ ] Confirm `estancia_materiales` has been audited for duplicate active `(estancia_id, material_id)` pairs.
- [ ] If duplicates exist, follow the "Deduplication procedure" below BEFORE the deploy.
- [ ] Run `python -m migration status --table estancia_materiales` (when issue #168 lands; until then, query InsForge directly via `psql` or the InsForge dashboard).
- [ ] Verify the `web_only_feature_shadow` table does NOT contain pending reconciliations (cleanup is a separate concern).

## Deploy steps

The schema migration itself is auto-applied by `ensure_domain_schema(client)` on first app boot (the function is called from the FastAPI `lifespan` in `app/main.py`). No manual SQL run is required.

```bash
# Deploy: merge PR B + PR C first, then this branch.
# On startup, ensure_domain_schema runs the 3 FOSTER-04 statements:
#   1. CREATE TABLE IF NOT EXISTS materiales
#   2. CREATE TABLE IF NOT EXISTS estancia_materiales
#   3. CREATE UNIQUE INDEX IF NOT EXISTS estancia_materiales_active_unique
```

If startup fails with the index error, the application does NOT start. Roll back by reverting the FOSTER-04 PR (or all of A + B + C) to the previous commit on `main`.

## Deduplication procedure (when index creation fails)

Step 1: list the duplicates in `estancia_materiales` (active rows only):

```sql
SELECT estancia_id, material_id, COUNT(*)
FROM public.estancia_materiales
WHERE activo = true
GROUP BY estancia_id, material_id
HAVING COUNT(*) > 1;
```

Step 2: for each duplicate pair, decide which row to keep:
- KEEP: the row with the most recent `fecha_alta`.
- SOFT-DELETE (`activo = false`): the other rows.

Step 3: apply soft-delete:

```sql
UPDATE public.estancia_materiales
SET activo = false, updated_at = now()
WHERE id IN (
  SELECT id FROM (
    SELECT id, ROW_NUMBER() OVER (
      PARTITION BY estancia_id, material_id
      ORDER BY fecha_alta DESC
    ) AS rn
    FROM public.estancia_materiales
    WHERE activo = true
  ) t
  WHERE rn > 1
);
```

Step 4: verify no duplicates remain:

```sql
SELECT COUNT(*) FROM (
  SELECT estancia_id, material_id
  FROM public.estancia_materiales
  WHERE activo = true
  GROUP BY estancia_id, material_id
  HAVING COUNT(*) > 1
) t;
-- Expected: 0
```

Step 5: restart the application. `ensure_domain_schema` will now succeed in creating the partial unique index.

## Verification

After the deduplication and restart:

- [ ] Application starts cleanly.
- [ ] `python -m migration status --table estancia_materiales` (when #168 lands) shows 0 pending reconciliations.
- [ ] Smoke: GET /materiales returns 200 with the list of materiales.
- [ ] Smoke: GET /acogidas/{id}/materiales (when PR C lands) returns 200 with the per-stay material list.

## Rollback

If the deduplication cannot be completed (e.g., the duplicates are intentional business data that the user wants to preserve):

1. **Do NOT** drop the partial unique index manually (it will be re-created on next startup).
2. **Do NOT** drop the `materiales` or `estancia_materiales` tables (the application depends on them).
3. **Revert the FOSTER-04 PRs A + B + C** (the partial unique index DDL is added in PR A; revert the merge commits on `main`).
4. Open a follow-up issue documenting the data conflict that blocked the deploy.
5. The user (operator) decides:
   - (a) Add a one-time data migration that merges the duplicates manually,
   - (b) Change the partial unique index to a non-unique index (loses the race-condition guard),
   - (c) Add a new domain concept (e.g. "material lot") that disambiguates the same (estancia, material) pair.

## Related

- PR #166 (FOSTER-04 PR A): the PR that introduced the partial unique index
- jd-judge-b BLOCKER-2 review comment on PR #166
- AGENTS.md §13 (Runbook for code requiring operator action)
- AGENTS.md §18 (web ↔ legacy mutual exclusion + mandatory sync)
- Issue #168 (migration/apply.py + bootstrap — pending follow-up that adds `migration status` command)
