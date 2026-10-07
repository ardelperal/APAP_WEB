# #1218 — Repo half of team-skills#155 item 12: repo-root .env poisons the test env

## Goal

Isolate the test environment from the gitignored repo-root `.env`. `Settings` reads
`env_file=".env"` (`app/core/config.py:107`), so a developer `.env` with `APAP_*` leaks
into every `Settings` constructed without `_env_file=None`: 5 tests fail locally only
(green in CI, where no `.env` exists). Cost a full triage round on 2026-10-02 before the
environmental cause was found. The suite knows the hazard piecemeal — many tests opt in
with `Settings(_env_file=None)` (`tests/e2e_ci/conftest.py:106`,
`tests/test_magic_link_flag.py:86/95/108`, `tests/test_trusted_proxies.py:44`,
`tests/test_rawsql_auth.py:165`) — but `tests/conftest.py:36-53` does not neutralize the
dotenv at suite level.

## Scope

1. Suite-level isolation in `tests/conftest.py` (e.g. force `env_file=None` during test
   `Settings` construction, or the mechanism maintainers prefer).
2. Document the decision (conftest docstring or CONTRIBUTING).

Out of scope: app runtime config; tests that explicitly exercise dotenv reading
(`tests/test_verify_fallback_ready_cli.py:254`); existing `_env_file=None` opt-ins.

## Validation shape

1. Reproduce: temp `.env` with `APAP_*` at repo root → affected tests red (environmental
   RED).
2. Fix → same tests green with the `.env` present.
3. Full suite green with AND without a repo-root `.env` (guard against tests that silently
   depended on the local `.env`).

## Outcome (2026-10-03)

Implemented. `tests/conftest.py` pins the no-dotenv suite contract:
`Settings.model_config["env_file"] = None` right after the `APAP_MODE`/magic-link env
setup and before the `app.main` import. Mechanism chosen over per-test monkeypatching
because `Settings` construction happens at conftest import time (`app.main` module-level
`app`), where fixtures cannot reach.

Test-first evidence:

- RED: `tests/test_config.py::test_suite_settings_ignore_cwd_env_file` fails against
  clean `main` (`- APAP_WEB / + env-poison-probe`) via an isolated-CWD `.env`, without
  touching a real developer `.env`.
- GREEN: same test passes after the conftest pin.
- A real repo-root `.env` exists on this machine; the issue-named suites
  (test_config, test_magic_link_flag, test_trusted_proxies, test_rawsql_auth,
  test_startup_config_validation) run 83 passed with it present.
- Wide slice: `pytest tests/ --ignore=tests/e2e --ignore=tests/e2e_ci` →
  5319 passed, 21 skipped, 0 failed.
- Gates: ruff clean, `check_rules` clean, mypy 0 errors (377 files), module/route
  size OK, docstring coverage 87.31% (floor 73%), import cycles OK.

Incidental local finding (same "red only local" class, fixed on the spot):
`tests/test_repository_secrets_ignore.py::test_root_gitignore_ignores_atl_receipts_but_...
failed on clean main because an untracked, self-ignoring `.atl/.gitignore` (content `*`,
tool residue) shadowed the root `!.atl/skill-registry.md` exemption. Removed the local
residue; no repo change needed (root `.gitignore` already ignores the cache file).

## Cross-references

- Skill half: DysTelefonica/team-skills#155 (checklist item 12) — dual-issue directive
  2026-10-02. No prior repo issue covered this (searched `.env`/dotenv/conftest, all
  closed/unrelated).

## Status

Issue created 2026-10-02: https://github.com/ardelperal/APAP_WEB/issues/1218
(labels `status:approved` + `type:bug`; passes `issue_contract_errors` with 0 errors).
Implemented 2026-10-03 — see Outcome.
