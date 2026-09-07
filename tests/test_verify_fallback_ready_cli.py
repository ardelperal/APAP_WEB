"""Tests for ``migration.verify_fallback_ready`` and the
``migration.cli_verify_fallback_ready`` standalone entry point.

These tests cover the gate's surface (which checks, exit codes,
output format) without spinning up the full migration pipeline. The
real migration E2E is in ``tests/migration/test_e2e_legacy_postgres.py``;
here we just verify the gate logic in isolation.
"""

from __future__ import annotations

from pathlib import Path

from migration.verify_fallback_ready import (
    ALL_CHECKS,
    CI_CHECKS,
    CheckResult,
    check_operator_signature,
    check_pii_audit_verdict,
    check_round_trip_test,
    format_receipt,
    run_gate,
)


def _patched_results(monkeypatch, *results: CheckResult) -> None:
    """Patch every CI check to return the given results in order.

    The order matches ``CI_CHECKS``: round_trip_test, pii_audit_verdict,
    web_to_legacy_check_only. If fewer than three results are given,
    the extra checks fall through to the real (file-based) check.
    """
    import migration.verify_fallback_ready as _vfb

    pairs = [
        ("check_round_trip_test", results[0] if len(results) > 0 else None),
        ("check_pii_audit_verdict", results[1] if len(results) > 1 else None),
        ("check_web_to_legacy_check_only", results[2] if len(results) > 2 else None),
        ("check_operator_signature", results[3] if len(results) > 3 else None),
    ]
    for name, result in pairs:
        if result is not None:
            # Replace the function in the module so CI_CHECKS / ALL_CHECKS
            # (which captured the function by reference at import time)
            # see the patched version when iterated.
            monkeypatch.setattr(_vfb, name, lambda *a, _r=result, **kw: _r)


# --- Pure-logic checks ----------------------------------------------------


def test_run_gate_passes_when_every_check_passes(monkeypatch) -> None:
    """All checks return PASS → gate exits 0 in both CI and full mode."""
    results = [
        CheckResult(name="round_trip_test", status="PASS", evidence="ok"),
        CheckResult(name="pii_audit_verdict", status="PASS", evidence="ok"),
        CheckResult(name="web_to_legacy_check_only", status="PASS", evidence="ok"),
        CheckResult(name="operator_signature", status="PASS", evidence="ok"),
    ]
    _patched_results(monkeypatch, *results)
    code_ci, _ = run_gate(ci_only=True)
    code_full, _ = run_gate(ci_only=False)
    assert code_ci == 0
    assert code_full == 0


def test_run_gate_fails_when_one_ci_check_fails(monkeypatch) -> None:
    """A FAIL on a CI-runnable check exits 1 in both modes."""
    results = [
        CheckResult(name="round_trip_test", status="PASS", evidence="ok"),
        CheckResult(name="pii_audit_verdict", status="FAIL", evidence="audit doc missing"),
        CheckResult(name="web_to_legacy_check_only", status="PASS", evidence="ok"),
        CheckResult(name="operator_signature", status="PASS", evidence="ok"),
    ]
    _patched_results(monkeypatch, *results)
    code_ci, _ = run_gate(ci_only=True)
    code_full, _ = run_gate(ci_only=False)
    assert code_ci == 1
    assert code_full == 1


def test_run_gate_ci_only_treats_pending_as_pass(monkeypatch) -> None:
    """Operator-attested checks return PENDING in CI mode; that does
    not fail the gate. The full mode treats PENDING as fail (the
    operator must have signed the report before claiming fallback-ready).
    """
    results = [
        CheckResult(name="round_trip_test", status="PASS", evidence="ok"),
        CheckResult(name="pii_audit_verdict", status="PASS", evidence="ok"),
        CheckResult(name="web_to_legacy_check_only", status="PASS", evidence="ok"),
        CheckResult(name="operator_signature", status="PENDING", evidence="missing"),
    ]
    _patched_results(monkeypatch, *results)
    code_ci, _ = run_gate(ci_only=True)
    code_full, _ = run_gate(ci_only=False)
    assert code_ci == 0  # PENDING counts as PASS in CI mode
    assert code_full == 1  # PENDING counts as not-OK in full mode


# --- Receipt formatting ---------------------------------------------------


def test_format_receipt_lists_every_check() -> None:
    """The receipt has one line per check, regardless of status."""
    results = [
        CheckResult(name="a", status="PASS", evidence="ok"),
        CheckResult(name="b", status="FAIL", evidence="bad"),
        CheckResult(name="c", status="PENDING", evidence="missing"),
    ]
    receipt = format_receipt(results, ci_only=True)
    assert "[PASS   ] a" in receipt
    assert "[FAIL   ] b" in receipt
    assert "[PENDING] c" in receipt


def test_format_receipt_includes_missing_ci_condition_lines() -> None:
    """Failed CI conditions surface as ``missing_ci_condition=<name>``
    lines so the CI runner can grep them.
    """
    results = [
        CheckResult(name="round_trip_test", status="FAIL", evidence="boom"),
        CheckResult(name="pii_audit_verdict", status="PASS", evidence="ok"),
    ]
    receipt = format_receipt(results, ci_only=True)
    assert "missing_ci_condition=round_trip_test" in receipt
    assert "FAILED: 1 CI condition(s) not met" in receipt


# --- Real-disk checks (no DB) --------------------------------------------


def test_pii_audit_check_passes_when_verdict_is_pass() -> None:
    """``check_pii_audit_verdict`` parses the PR4b audit doc and
    returns PASS when the verdict is PASS.
    """
    result = check_pii_audit_verdict()
    assert result.name == "pii_audit_verdict"
    assert result.status == "PASS", (
        f"PR4b audit doc is the single source of truth for the gate. "
        f"If this fails, the audit verdict regressed. Got: {result.evidence}"
    )


def test_round_trip_test_passes_against_fakelocal_backend() -> None:
    """``check_round_trip_test`` runs the existing PR6 round-trip
    test suite, which uses FakeSqlExecutor and does not need a real
    backend. It must pass green for the gate to be CI-clean.
    """
    result = check_round_trip_test()
    assert result.name == "round_trip_test"
    assert result.status == "PASS", (
        f"Round-trip test (PR6) regressed. The E2E atom is the M2 closure. "
        f"Got: {result.evidence}"
    )


# --- Operator signature (full mode only) ---------------------------------


def test_operator_signature_check_passes_with_valid_file(
    tmp_path: Path, monkeypatch
) -> None:
    """A signature file with all required keys returns PASS."""
    import json

    from migration import verify_fallback_ready

    sig = tmp_path / "migration_report_signature.json"
    sig.write_text(json.dumps({
        "operator_id": "ana",
        "sha256_of_report": "deadbeef" * 8,
        "signed_at": "2026-08-31T12:00:00+00:00",
    }))

    monkeypatch.setattr(verify_fallback_ready, "OPERATOR_SIGNATURE_PATH", sig)
    result = check_operator_signature()
    assert result.status == "PASS"
    assert "ana" in result.evidence


def test_operator_signature_check_returns_pending_when_missing(
    monkeypatch,
) -> None:
    """No signature file → PENDING (the operator hasn't run a real cycle yet)."""
    from migration import verify_fallback_ready

    monkeypatch.setattr(
        verify_fallback_ready, "OPERATOR_SIGNATURE_PATH",
        verify_fallback_ready.REPO_ROOT / "this_does_not_exist.json",
    )
    result = check_operator_signature()
    assert result.status == "PENDING"


# --- Module structure ----------------------------------------------------


def test_ci_checks_excludes_operator_signature() -> None:
    """The CI-runnable subset must NOT include the operator-attested check.
    The orchestrator would otherwise fail CI runs that have no operator
    signature (which is always the case in CI).
    """
    assert check_operator_signature not in CI_CHECKS


def test_all_checks_includes_operator_signature() -> None:
    """The full mode runs every check, including the operator-attested one."""
    assert check_operator_signature in ALL_CHECKS
