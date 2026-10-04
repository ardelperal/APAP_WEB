"""Behaviour tests for scripts/check_e2e_seed.py (issue #1223).

The production e2e gate mints its session for ``e2e@apap.local`` against
``usuarios_autorizados``; when the row drifts away (as it did on
2026-10-02), ``/e2e/login`` answers ``400`` and the battery fails as an
opaque "credential rejected". The preflight must fail loudly naming the
precondition instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_e2e_seed as ces  # noqa: E402


def _row(rol: str = "developer", activo: bool = True) -> dict[str, object]:
    return {"rol": rol, "activo": activo}


def test_present_active_developer_row_passes() -> None:
    verdict = ces.evaluate([_row()])

    assert verdict.ok is True
    assert ces.EMAIL in verdict.message


def test_missing_row_fails_naming_the_precondition() -> None:
    verdict = ces.evaluate([])

    assert verdict.ok is False
    assert ces.EMAIL in verdict.message
    assert "not seeded" in verdict.message
    assert "/e2e/login" in verdict.message, "the message must name the downstream symptom"
    assert "docs/runbooks/e2e-production.md" in verdict.message


def test_inactive_row_fails_naming_the_state() -> None:
    verdict = ces.evaluate([_row(activo=False)])

    assert verdict.ok is False
    assert "not active" in verdict.message


def test_wrong_role_row_fails_naming_the_expected_role() -> None:
    verdict = ces.evaluate([_row(rol="key_user")])

    assert verdict.ok is False
    assert "key_user" in verdict.message
    assert ces.EXPECTED_ROLE in verdict.message


def test_duplicated_rows_fail_as_ambiguous() -> None:
    verdict = ces.evaluate([_row(), _row()])

    assert verdict.ok is False
    assert "more than one" in verdict.message


def test_cli_exit_codes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APAP_LOCAL_DB_URL", "postgresql://fake")
    monkeypatch.setattr(ces, "fetch_rows", lambda dsn: [_row()])
    assert ces.main([]) == 0

    monkeypatch.setattr(ces, "fetch_rows", lambda dsn: [])
    assert ces.main([]) == 1
    assert ces.EMAIL in capsys.readouterr().out

    monkeypatch.delenv("APAP_LOCAL_DB_URL")
    assert ces.main([]) == 2, "a missing DSN is a usage error, never a silent pass"
