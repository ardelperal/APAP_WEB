# Archive Report: m3-1-magic-link-e2e

**Change**: `m3-1-magic-link-e2e`
**Archived on**: 2026-09-05
**Artifact store mode**: `openspec`
**Branch**: `feat/641-self-host-backend-coolify`
**Archive status**: wip — partial; awaiting `M3.4` (magic-link wiring + `SMTPMailTransport`)

## Summary

The `m3-1-magic-link-e2e` change was archived as **wip** (partial). The slice shipped its scaffolding and unit tests, but the round-trip E2E test it was designed to enable cannot pass yet because the M3 backend wiring it exercises is not in the codebase:

- The routes `POST /auth/magic/start` and `GET /auth/magic/verify` are not registered anywhere. `app/core/auth_flow.py` only exposes `/login`, `/auth/google`, `/auth/callback`, and `/logout`.
- `SMTPMailTransport` is not implemented. `grep -rn 'send_magic_link\|SMTPMailTransport' app/` returns zero hits. `Settings` has no `APAP_SMTP_HOST/PORT/USER/...` fields.

Both gaps are tracked as a single follow-up issue, the **M3.4** slice, in `docs/roadmap/transversales.md` under "Issues pendientes de crear".

## Task Completion Gate

Archived `tasks.md` shows 2/3 tasks landed and 1 task explicitly skipped:

| Task | Status | Evidence |
|---|---|---|
| T1 — RED: write the Playwright E2E test (failing first) | landed + skipped | `tests/e2e/test_magic_link_e2e.py` exists but is gated by `pytest.mark.skip` with a reason that names M3.4 |
| T2 — GREEN: write the MailDev helper | landed | `tests/e2e/_maildev_helper.py` — 44 LOC |
| T3 — `conftest.py` with `maildev_url` fixture | already tracked | `tests/e2e/conftest.py` was committed in `ec99037 feat(ui): apply real APAP Alcala design tokens + Playwright E2E coverage (#108)` and required no delta |

Companion unit tests at `tests/test_maildev_helper.py` (192 LOC) cover the helper's pure logic — 13/13 green under 1.5s in the default suite, with `httpx` mocked and `time.sleep` neutralised by `monkeypatch`.

## Verification Gate

The verification verdict is **WIP — cannot round-trip**. The unit tests are green; the E2E test is skipped with a reason that names the missing backend:

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest tests/test_maildev_helper.py -v` | ✅ 13 passed in 1.21s |
| `.venv/bin/python -m pytest tests/e2e/test_magic_link_e2e.py -v` | ⏭️ 1 skipped (reason: M3 backend missing) |
| `.venv/bin/python -m ruff check tests/test_maildev_helper.py tests/e2e/_maildev_helper.py` | ✅ All checks passed |
| `.venv/bin/python -m mypy tests/test_maildev_helper.py` | ✅ Success: no issues found |

No CRITICAL verification issues; the partial state is the slice's own design (scaffolding + unit tests land now, round-trip E2E un-skips when M3.4 closes).

## Implementation commits

| Commit | Work unit | SDD tasks | Verification |
|---|---|---|---|
| `1ac15e3` | `chore(m3-1): land helper + unit tests as wip; skip round-trip e2e` | T2 + companion unit tests + skip on T1 | Focused `pytest tests/test_maildev_helper.py` 13/13 green; `ruff check .` clean; `mypy` clean |
| `b406b68` | `fix(insforge): restore app/core/insforge_url.py lost from working tree` | enables any pytest run (conftest import path) | Verbatim copy from `main` (no functional change) |
| `8a64628` | `docs(roadmap): add self-host backend section to transversales; update integrations inventory` | updates the roadmap to list M3.4 as pending | n/a (doc only) |
| `7b9f953` | `chore(skill-registry): refresh after move to Oracle VPS` | housekeeping | n/a (auto-generated metadata) |

All listed commits are reachable from `feat/641-self-host-backend-coolify` via `git merge-base --is-ancestor`.

## Runtime verification evidence

The MailDev HTTP API on `apap-smtp-dev:8025` returns "Empty reply" — pre-existing breakage tracked separately. The helper is correct (unit-tested) but cannot read from MailDev in its current state; once M3.4 wires `SMTPMailTransport` to a working SMTP backend (Resend in production, MailDev locally), the helper can be repointed.

## Specs synced

Delta specs were **not** promoted to `openspec/specs/`. The M3.1 specs describe a verification target that the round-trip E2E does not currently exercise. Promoting them would mislead a future reader into believing the round-trip is verified. The specs remain in this archive folder for traceability; promotion to `openspec/specs/` is a precondition of the M3.4 archive (which will close the verification loop end-to-end).

## Follow-up

- **M3.4** (`feat(m3-4): magic-link wiring + SMTPMailTransport en local_backend/app.py`): 1 router, 1 SMTP transport class, 2 endpoints, settings + DI. Scope ~150 LOC. The round-trip E2E in this archive un-skips when M3.4 lands.
- **Phase 3** (#648): Coolify deploy manifest + `.accdb` legacy migration + runbook operador. Independent of M3.4.
- **Phase 5** (#647): separate deploy step from lifespan bootstrap. Independent.
- **Hygiene** (#646): pre-existing ruff errors + failing e2e (paralelo).
