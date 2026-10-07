# 1223 — dual issue: gate runbook assumed e2e@apap.local seeded, production had lost the row

Issue: #1223 (type:bug + status:approved). Skill half: DysTelefonica/team-skills#155, comment `5957452247` (checklist item 17).
Lesson: a gate runbook cannot assume DB state — either seed it or verify it fail-loud.

## Verified facts (2026-10-02)
- Runbook premise: `docs/runbooks/e2e-production.md` precondition 6 (the #1073 update) states `e2e@apap.local` (rol `developer`) "is confirmed seeded" in production.
- Reality during the battery: the row was MISSING from production `usuarios_autorizados`; the worker re-inserted it (`INSERT INTO usuarios_autorizados (email, rol, activo) VALUES ('e2e@apap.local','developer',true)`).
- Read-only post-check against the production DSN (backend container DSN → `apap-pg-test` Postgres): the row now exists exactly once as `(e2e@apap.local, developer, t)` — the re-insert took effect.
- Drift timeline: no issue/PR in the trail documents a production DB reset or a restore; hypothesis (reset after #1073 closed 2026-09-30) unconfirmed — issue criterion (c) covers documenting it if confirmed.
- Impact: with #1073 live, a missing row makes `/e2e/login` answer 400, so the production e2e gate (#909) breaks silently at the next run.

## Progress / evidence

Outcome (2026-10-03): implemented the fail-loud preflight route of acceptance (a).
Rationale: automated seeding of production converts a precondition fix into a data
migration with PII-adjacent risk and requires production credentials in automation;
the preflight converts the silent 400 into signal with zero new privileges.

- `scripts/check_e2e_seed.py`: read-only preflight — exit 0 (exactly one active
  developer row), exit 1 (precondition unmet: missing / inactive / wrong role /
  duplicated, message names the fix and the runbook), exit 2 (no DSN or DB error).
- `docs/runbooks/e2e-production.md` precondition 6: premise corrected — the row is
  mutable production state, no automation guarantees it, the 2026-10-02 drift is
  recorded with its timeline explicitly unconfirmed (acceptance c, honest state).
- Tests RED→GREEN: `tests/test_check_e2e_seed.py` (6 tests, decision logic + CLI exit
  codes with an injected `fetch_rows`; no DB required).
- Issue created and read back: #1223 OPEN, labels `status:approved`, `type:bug`.
- team-skills#155 comment read back: `issue_url` resolves to DysTelefonica/team-skills/issues/155.
