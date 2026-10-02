# 1222 — dual issue: deploy lane falls on runner tooling gap (gettext-base/envsubst)

Issue: #1222 (type:bug + status:approved). Skill half: DysTelefonica/team-skills#155, comment `5957451916` (checklist item 16).
Fiction origin: deploy run 37037386528 (2026-10-02, `main@ee1f0c89`), failed at step 9 «Install Cosign» with `envsubst: command not found` (exit 127); steps 10-16 skipped; production untouched at `9816c974`.

## Verified facts (2026-10-02)
- Log: job `deploy`, `Runner name: 'apap-coolify-noble-2'`, workspace `/data/runners/apap-2/_work/`; error line `/data/runners/apap-2/_work/_temp/ab27b243-…sh: line 3: envsubst: command not found`, `##[error]Process completed with exit code 127`.
- Positive finding: the pool-wide deploy lane works — the dispatch routed to `-2` and the job ran to the tooling-dependent step; routing/registration are not the defect.
- Readonly fleet probe (`command -v envsubst / gettext`, image `ghcr.io/actions/actions-runner:latest`, Ubuntu 24.04.4):
  - `apap-coolify-noble-2` (served the deploy): envsubst MISSING, gettext MISSING.
  - `apap-coolify-noble-3`: envsubst MISSING, gettext MISSING.
  - `apap-coolify-noble`: envsubst present (`/usr/bin/envsubst`), gettext present.
- Fix options stated in the issue: (a) install `gettext-base` in the runner service provisioning/entrypoint — recommended; (b) repo-side pinned direct download of cosign or a fail-loud tooling preflight.

## Operator observation folded into #1222 (no third issue)
`GET /api/v1/applications/cxm5x2f489eos8nr8e1qv1c6/envs` returns TWO rows for `APAP_E2E_AUTH_SECRET`: one `is_preview: false`, one `is_preview: true` (`is_build_time` absent on both; no secret values read). Same duplication pattern for most `APAP_*` keys (base row + preview row). Operator owns the Coolify cleanup; the reliable read path during the battery was the server-side `.env`.

## Progress / evidence
- Issue created and read back: #1222 OPEN, labels `status:approved`, `type:bug`.
- team-skills#155 comment read back: `issue_url` resolves to DysTelefonica/team-skills/issues/155.
