# #1221 — release-e2e-gate blocks every deploy: wrong-revision smoke requirement

## Goal

Unblock deploys and remove the two structural defects of the `release-e2e-gate` job in
`.github/workflows/deploy.yml`:

1. The "previous revision" is selected from the Actions runs search index
   (`[0].head_sha` of the most recent successful run), a non-transactional index that
   already returned the third-most-recent revision once (run 37028750019 chose
   `460c56f1` while production serves `9816c974`). The gate must resolve the revision
   that actually serves traffic: `vars.APAP_DEPLOY_HEALTH_URL` → `/healthz` →
   `.revision` (the same source `scripts/verify_deployment.py` uses post-deploy).
2. Bootstrap asymmetry: `release/e2e-production` got its `skipped:bootstrap` bypass
   during the #1082 rollout, but `release/smoke-production` (added in #1133) has no
   bootstrap path — `production-smoke` only runs after a successful deploy, so no
   pre-#1133 revision can ever obtain the verdict automatically. Symmetrize: the
   bypass mechanism in `scripts/check_release_evidence.py` is already context-agnostic
   (`BYPASS_PREFIX`); document the smoke bootstrap path in the runbook and make the
   script's verdict messages context-aware (today a smoke bypass prints "e2e
   validation skipped").

## Scope

- `deploy.yml` gate step: select `previous_sha` from the serving revision's `/healthz`
  (`.revision`); drop the Actions runs-index query (and the now-unneeded
  `actions: read` permission if nothing else uses it); fail closed when the health
  endpoint is unreachable or returns no revision; keep an explicit notice-only escape
  for the not-configured-URL bootstrap (first deploy) documented in the workflow.
- `scripts/check_release_evidence.py`: context-aware verdict messages; tests extended.
- `docs/runbooks/e2e-production.md`: document the symmetric smoke bootstrap
  (`skipped:bootstrap ...` status on pre-#1133 revisions).
- Pins in `tests/test_deploy_workflow.py` updated to the new contract, shift-agnostic
  (no SHA pinned).

Out of scope: the authenticated e2e battery content, the rollback path, Coolify/runner
infra, recording the `9816c974` e2e verdict (operator action per the runbook, tracked
while the fix lands).

## Validation shape

1. RED: rewritten gate pins (healthz selection, no runs-index in the section,
   fail-closed on unreachable health endpoint) + context-aware bypass message test.
2. GREEN after implementation; full deploy/release-evidence suites + ratchets.
3. End-to-end: merge to `main` → full `deploy.yml` cycle green
   (acceptance criterion c).

## Status

Implemented 2026-10-03: the gate resolves `previous_sha` from the serving
revision's `/healthz` (`.revision`), dropping the Actions runs-index query and its
`actions: read` scope; fail-closed on an unreachable endpoint or a payload without a
revision; the only notice-only escape is the not-configured health URL (first-deploy
bootstrap). `check_release_evidence.py` verdict messages are now context-aware, and the
runbook documents the gate's new selection source (the smoke bootstrap path already
existed in the runbook — acceptance (b) via the documented route). RED observed on both
rewritten gate pins and the context-aware message test.
