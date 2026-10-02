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

## Cross-references

- Skill half: DysTelefonica/team-skills#155 (checklist item 12) — dual-issue directive
  2026-10-02. No prior repo issue covered this (searched `.env`/dotenv/conftest, all
  closed/unrelated).

## Status

Issue created 2026-10-02: https://github.com/ardelperal/APAP_WEB/issues/1218
(labels `status:approved` + `type:bug`; passes `issue_contract_errors` with 0 errors).
Not started.
