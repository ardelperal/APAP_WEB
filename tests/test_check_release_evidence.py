"""Behaviour tests for scripts/check_release_evidence.py (issue #1082).

The evaluator decides whether the production e2e evidence recorded as the
``release/e2e-production`` commit status belongs to the revision being
released. It must never let evidence for one revision approve another one.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_release_evidence as cre  # noqa: E402

SHA = "a" * 40
OTHER_SHA = "b" * 40
CTX = "release/e2e-production"


def _status(
    state: str, description: str = "", created_at: str = "2026-09-29T10:00:00Z", context: str = CTX
) -> dict[str, str]:
    return {
        "context": context,
        "state": state,
        "description": description,
        "target_url": "https://github.com/ardelperal/APAP_WEB/actions/runs/1",
        "created_at": created_at,
    }


def _payload(*statuses: dict[str, str], sha: str = SHA) -> dict[str, object]:
    return {"sha": sha, "statuses": list(statuses)}


def test_success_for_the_right_sha_passes() -> None:
    verdict = cre.evaluate(_payload(_status("success", "e2e green")), SHA)

    assert verdict.ok is True
    assert verdict.code == "success"
    assert SHA in verdict.message


def test_evidence_for_another_sha_never_approves() -> None:
    verdict = cre.evaluate(_payload(_status("success"), sha=OTHER_SHA), SHA)

    assert verdict.ok is False
    assert verdict.code == "wrong-sha"
    assert SHA in verdict.message
    assert OTHER_SHA in verdict.message


def test_absent_evidence_fails_closed_naming_the_sha() -> None:
    verdict = cre.evaluate(_payload(_status("success", context="ci/other")), SHA)

    assert verdict.ok is False
    assert verdict.code == "absent"
    assert SHA in verdict.message
    assert CTX in verdict.message


def test_empty_statuses_fail_closed() -> None:
    verdict = cre.evaluate(_payload(), SHA)

    assert (verdict.ok, verdict.code) == (False, "absent")


def test_pending_evidence_fails() -> None:
    verdict = cre.evaluate(_payload(_status("pending", "awaiting runbook validation")), SHA)

    assert verdict.ok is False
    assert verdict.code == "pending"
    assert SHA in verdict.message


def test_failure_evidence_fails_and_points_to_rollback() -> None:
    verdict = cre.evaluate(_payload(_status("failure", "suite red")), SHA)

    assert verdict.ok is False
    assert verdict.code == "failure"
    assert "deploy-rollback" in verdict.message


def test_error_state_is_treated_as_failure() -> None:
    verdict = cre.evaluate(_payload(_status("error")), SHA)

    assert (verdict.ok, verdict.code) == (False, "failure")


def test_bypass_with_reason_passes_for_that_sha_only() -> None:
    bypass = _status("success", "skipped:prod window closed")

    ok = cre.evaluate(_payload(bypass), SHA)
    other = cre.evaluate(_payload(bypass, sha=OTHER_SHA), SHA)

    assert ok.ok is True
    assert ok.code == "bypass"
    assert "prod window closed" in ok.message
    assert SHA in ok.message
    assert other.ok is False


def test_bypass_without_reason_is_not_accepted() -> None:
    verdict = cre.evaluate(_payload(_status("success", "skipped:   ")), SHA)

    assert verdict.ok is False
    assert verdict.code == "bypass-without-reason"


def test_pending_bypass_text_does_not_pass() -> None:
    verdict = cre.evaluate(_payload(_status("pending", "skipped:reason")), SHA)

    assert (verdict.ok, verdict.code) == (False, "pending")


def test_latest_status_wins_over_older_ones() -> None:
    older_success = _status("success", created_at="2026-09-29T09:00:00Z")
    newer_failure = _status("failure", created_at="2026-09-29T11:00:00Z")

    verdict = cre.evaluate(_payload(older_success, newer_failure), SHA)

    assert (verdict.ok, verdict.code) == (False, "failure")


def test_pending_after_success_reopens_the_gate() -> None:
    old = _status("success", created_at="2026-09-29T09:00:00Z")
    new = _status("pending", created_at="2026-09-29T11:00:00Z")

    assert cre.evaluate(_payload(new, old), SHA).code == "pending"


@pytest.mark.parametrize("payload", [None, [], "x", {"sha": SHA}, {"sha": SHA, "statuses": "x"}])
def test_malformed_payload_fails_closed(payload: object) -> None:
    verdict = cre.evaluate(payload, SHA)  # type: ignore[arg-type]

    assert verdict.ok is False
    assert verdict.code in {"malformed", "absent"}


def test_unknown_state_fails_closed() -> None:
    verdict = cre.evaluate(_payload(_status("weird")), SHA)

    assert (verdict.ok, verdict.code) == (False, "malformed")


def test_cli_exit_codes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_payload(_status("success")))))
    assert cre.main(["--sha", SHA]) == 0

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_payload(_status("pending")))))
    assert cre.main(["--sha", SHA]) == 1
    assert "::error::" in capsys.readouterr().out

    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert cre.main(["--sha", SHA]) == 2


SMOKE = "release/smoke-production"


def test_custom_context_is_evaluated_and_named_in_messages() -> None:
    payload = _payload(_status("success", "smoke ok", context=SMOKE))

    ok = cre.evaluate(payload, SHA, context=SMOKE)
    assert (ok.ok, ok.code) == (True, "success")

    pending = cre.evaluate(_payload(_status("pending", context=SMOKE)), SHA, context=SMOKE)
    assert pending.code == "pending"
    assert SMOKE in pending.message
    assert SHA in pending.message


def test_bypass_and_success_messages_name_the_evaluated_context() -> None:
    """Issue #1221: smoke-context verdicts must not read as e2e verdicts.

    The bypass mechanism is context-agnostic, but the messages hardcoded
    "e2e validation skipped" / "production e2e validation recorded"; a
    smoke bypass printed an e2e claim, muddying the audit trail.
    """
    bypass = cre.evaluate(
        _payload(
            _status(
                "success",
                "skipped:bootstrap - deployed before smoke existed (#1133)",
                context=SMOKE,
            )
        ),
        SHA,
        context=SMOKE,
    )
    assert (bypass.ok, bypass.code) == (True, "bypass")
    assert "e2e" not in bypass.message.lower()
    assert SMOKE in bypass.message

    success = cre.evaluate(
        _payload(_status("success", "smoke ok", context=SMOKE)), SHA, context=SMOKE
    )
    assert (success.ok, success.code) == (True, "success")
    assert "e2e" not in success.message.lower()
    assert SMOKE in success.message


def test_status_of_another_context_is_ignored() -> None:
    payload = _payload(_status("success"))  # only release/e2e-production

    verdict = cre.evaluate(payload, SHA, context=SMOKE)

    assert (verdict.ok, verdict.code) == (False, "absent")
    assert SMOKE in verdict.message
    assert CTX not in verdict.message


def test_default_context_ignores_a_successful_custom_context() -> None:
    verdict = cre.evaluate(_payload(_status("success", context=SMOKE)), SHA)

    assert (verdict.ok, verdict.code) == (False, "absent")
    assert CTX in verdict.message


def test_newest_status_of_the_requested_context_wins() -> None:
    old = _status("success", created_at="2026-09-29T09:00:00Z", context=SMOKE)
    new = _status("failure", created_at="2026-09-29T11:00:00Z", context=SMOKE)
    newer_other = _status("success", created_at="2026-09-29T12:00:00Z")

    verdict = cre.evaluate(_payload(old, new, newer_other), SHA, context=SMOKE)

    assert verdict.code == "failure"


def test_cli_context_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps(_payload(_status("success", context=SMOKE)))
    monkeypatch.setattr(sys, "stdin", io.StringIO(body))
    assert cre.main(["--sha", SHA, "--context", SMOKE]) == 0

    monkeypatch.setattr(sys, "stdin", io.StringIO(body))
    assert cre.main(["--sha", SHA]) == 1


def test_cli_accepts_only_the_two_known_contexts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI context is a closed allow-list: a typo must not read as 'absent'."""
    payload = json.dumps(_payload(_status("success", context=SMOKE)))

    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert cre.main(["--sha", SHA, "--context", SMOKE]) == 0

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_payload(_status("success")))))
    assert cre.main(["--sha", SHA, "--context", CTX]) == 0

    for bad in ("release/smoke-prod", "ci / required", ""):
        monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
        assert cre.main(["--sha", SHA, "--context", bad]) == cre.EXIT_USAGE_ERROR
    capsys.readouterr()


def test_allowed_contexts_are_exactly_the_two_release_statuses() -> None:
    assert frozenset({CTX, SMOKE}) == cre.ALLOWED_CONTEXTS
