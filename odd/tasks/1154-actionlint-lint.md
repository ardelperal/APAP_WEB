# #1154 — actionlint in the lint job

## Goal

Gate the CI `lint` job on actionlint 1.7.12 across all workflows (operator decision 4 of the CI epic, handoff 2026-09-30 §3.4). actionlint validates the workflow schema, runs shellcheck over embedded scripts and checks `runs-on` labels against a declared config.

## Acceptance criteria

1. `Run actionlint (all workflows, pinned 1.7.12)` step in the `lint` job; any finding fails the job.
2. `.github/actionlint.yaml` declares the self-hosted fleet labels from `deploy.yml:296` (`self-hosted, Linux, ARM64, apap, oracle, coolify, noble`).
3. All findings fixed or declared with rationale comments.
4. `scripts/preflight.py` parity: the step is picked up automatically (no preflight.py change — dynamic `run:` extraction from #1145); locally `PASSED (20/20 steps)` with the step named and executed.
5. `tests/test_ci_workflow.py` pins: step present, version pin `1.7.12`, checksum-verified download, the three declared ignores, and the runner-label config covering every label `deploy.yml` uses.
6. The `lint` job stays green (verified: CI run 36741326730, `lint` pass 55s).

## Findings — fixed vs declared

Fixed in `ci.yml` (mechanical): SC2016 (`grep -q '[$][{]'`), SC2034 ×2 (throwaway loop counters → `_`), SC2129 (grouped `{ … } >> "$GITHUB_ENV"` redirect).

Declared in the step comments:
- `unexpected key "command" for "services" section` — belongs to open PR #900 (issue #894), which removes the whole `services.minio` block; remove the ignore when #900 merges.
- SC2129 + SC2086 in `deploy.yml` scripts — `deploy.yml` out of scope for this change; mechanical fixes belong to a dedicated `deploy.yml` change, then remove both ignores.

## Design notes

- Binary pinned to 1.7.12. Workstations use the system-wide install (handoff §5) so preflight runs the same step with no download; CI downloads the release tarball into `$RUNNER_TEMP` and verifies pinned SHA256 checksums (amd64 `8aca8db9…`, arm64 `325e971b…`). No third-party action involved (`rhysd/actionlint` ships no setup action; `raven-actions/actionlint` runs actionlint itself, which would break preflight parity).
- The version guard makes a stale local actionlint fail loud (download path), never silently use another version.

## Plan de validación (evidencia)

- `actionlint` (exact step invocation): exit 0 in the worktree and in CI (`lint` pass).
- `uv run python scripts/preflight.py`: `PASSED (20/20 steps)`, `PASS Run actionlint (all workflows, pinned 1.7.12)`.
- `uv run --extra dev pytest`: 5235 passed, 21 skipped (pre-existing Postgres skips).
- `python -m mypy` clean (377 files); `ruff check .` clean; vulture exit 0.

## Estado

Issue #1154 (rebuilt to the six-section contract after the `issue-spec` gate rejected the initial format; friction: the dictated issue format did not match `docs/codebase/issue-specifications.md`). PR #1157, branch `chore/1154-actionlint-lint`, auto-merge enabled.

**Merge blocker (base-wide, not this diff):** the `security` job fails with pip-audit `urllib3 2.7.0` CVE-2026-97687/97688/97689 (fix 2.8.0). `main`'s last `ci` push run (2026-09-28) predates the CVE publication, so any PR today hits it. Fix requires a `uv.lock` bump — out of scope here (dependency mutation needs explicit authorization). The `required` aggregator cascade is the same single root cause.
