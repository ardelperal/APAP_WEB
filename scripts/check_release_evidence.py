"""Evaluate the per-revision production e2e evidence (issue #1082).

After a successful deploy, ``deploy.yml`` (job ``release-e2e-record``) sets the
commit status ``release/e2e-production`` to ``pending`` on the deployed SHA.
The operator then records the runbook verdict on that same SHA
(``docs/runbooks/e2e-production.md``): ``success`` with the run URL, ``failure``
(which triggers the digest rollback path), or a bypass recorded as ``success``
with the description ``skipped:<reason>``.

This module holds the pure decision over a statuses payload so any audit job or
operator can reuse it. It fails closed: anything that is not clear evidence for
exactly the requested SHA is a refusal, and the message always names that SHA.

Usage::

    gh api repos/OWNER/REPO/commits/SHA/status | \\
        python scripts/check_release_evidence.py --sha SHA [--context CONTEXT]

``--context`` selects the commit-status context (default ``release/e2e-production``;
the only other accepted value is ``release/smoke-production``, anything else is a
usage error).

The payload is the combined-status document (``{"sha": ..., "statuses": [...]}``).

Exit codes:
    0 - valid evidence (success or a bypass with a reason) for the SHA
    1 - evidence missing, pending, failed, or bound to another SHA
    2 - usage error (including an unknown --context) or unreadable JSON input

Tests: ``tests/test_check_release_evidence.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

STATUS_CONTEXT = "release/e2e-production"
SMOKE_CONTEXT = "release/smoke-production"
#: Closed allow-list for ``--context``: a typo must be a usage error, never an
#: "absent" verdict that reads like missing evidence.
ALLOWED_CONTEXTS = frozenset({STATUS_CONTEXT, SMOKE_CONTEXT})
BYPASS_PREFIX = "skipped:"
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE_ERROR = 2
KNOWN_STATES = frozenset({"success", "pending", "failure", "error"})
RUNBOOK = "docs/runbooks/e2e-production.md"
ROLLBACK_RUNBOOK = "docs/runbooks/deploy-rollback.md"


@dataclass(frozen=True)
class Verdict:
    """Outcome of the evidence check for one revision."""

    ok: bool
    code: str
    message: str


def _refuse(code: str, message: str) -> Verdict:
    return Verdict(ok=False, code=code, message=message)


def _latest_status(
    statuses: Sequence[object], context: str = STATUS_CONTEXT
) -> Mapping[str, object] | None:
    """Return the newest status for ``context``, or None.

    The GitHub API lists newest first; ``created_at`` breaks ties explicitly so
    the decision does not depend on the ordering of the payload.
    """
    matching = [
        item for item in statuses if isinstance(item, Mapping) and item.get("context") == context
    ]
    if not matching:
        return None
    return max(matching, key=lambda item: str(item.get("created_at", "")))


def evaluate(payload: object, sha: str, context: str = STATUS_CONTEXT) -> Verdict:
    """Decide whether ``payload`` holds valid evidence in ``context`` for ``sha``.

    ``context`` defaults to the production e2e context; slice 2 of issue #1131
    reuses the same fail-closed logic for ``release/smoke-production``. Statuses
    of any other context are ignored.
    """
    if not isinstance(payload, Mapping):
        return _refuse("malformed", f"statuses payload for {sha} is not a JSON object.")
    payload_sha = payload.get("sha")
    if payload_sha != sha:
        return _refuse(
            "wrong-sha",
            f"evidence is bound to {payload_sha!r}, not to the revision {sha}; "
            f"evidence for one revision never approves another. Record "
            f"{context} on {sha} per {RUNBOOK}.",
        )
    statuses = payload.get("statuses")
    if not isinstance(statuses, list):
        return _refuse("malformed", f"statuses payload for {sha} has no statuses list.")

    latest = _latest_status(statuses, context)
    if latest is None:
        return _refuse(
            "absent",
            f"no {context} status recorded for {sha}. Validate production "
            f"and record the verdict on that SHA per {RUNBOOK}.",
        )

    state = latest.get("state")
    description = str(latest.get("description") or "").strip()
    if state not in KNOWN_STATES:
        return _refuse("malformed", f"{context} on {sha} has unknown state {state!r}.")
    if state == "pending":
        return _refuse(
            "pending",
            f"{context} on {sha} is still pending: production validation "
            f"has not been recorded. Follow {RUNBOOK}.",
        )
    if state in {"failure", "error"}:
        return _refuse(
            "failure",
            f"{context} on {sha} is {state}: the revision failed production "
            f"validation. Fix forward or roll back per {ROLLBACK_RUNBOOK}.",
        )
    if description.startswith(BYPASS_PREFIX):
        reason = description[len(BYPASS_PREFIX) :].strip()
        if not reason:
            return _refuse(
                "bypass-without-reason",
                f"bypass on {sha} records no reason; use skipped:<reason>.",
            )
        return Verdict(
            ok=True,
            code="bypass",
            # Issue #1221: name the evaluated context — a smoke bypass must
            # not read as an e2e verdict in the audit trail.
            message=f"{context} validation skipped for {sha}: {reason}",
        )
    return Verdict(
        ok=True, code="success", message=f"{context} validation recorded for {sha}."
    )


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Read a combined-status JSON document from stdin and print the verdict."""
    _pin_output_encoding()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sha", required=True, help="revision the evidence must be bound to")
    parser.add_argument(
        "--context",
        default=STATUS_CONTEXT,
        choices=sorted(ALLOWED_CONTEXTS),
        help=f"commit-status context to evaluate (default: {STATUS_CONTEXT})",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE_ERROR
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        print(f"::error::statuses input is not valid JSON: {error}")
        return EXIT_USAGE_ERROR

    verdict = evaluate(payload, args.sha, args.context)
    if verdict.ok:
        print(f"::notice::{verdict.message}")
        return EXIT_OK
    print(f"::error::{verdict.message}")
    return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
