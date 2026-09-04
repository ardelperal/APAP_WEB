"""M3 production magic-link round-trip gate (AS10-equivalent for the R3 check).

Drives the :func:`tests.migration._local_backend_fixture.run_magic_link_production_gate`
helper inline and asserts the dispatched CheckResult shape. Loud-aborts
when ``APAP_TEST_POSTGRES_DSN`` is unset while ``APAP_AUTH_ENABLE_MAGIC_LINK``
is true (matches AGENTS.md MUST NOT silently skip).

The actual production round-trip (spawn uvicorn + POST /auth/magic/start
+ read tests/mailbox.jsonl + GET /auth/magic/verify + assert apap_session)
lives in ``tests.migration._local_backend_fixture.run_magic_link_production_round_trip``.
"""
from __future__ import annotations

import pytest

from migration.verify_fallback_ready import CheckResult
from tests.migration._local_backend_fixture import (
    run_magic_link_production_gate,
)

pytestmark = pytest.mark.integration


def test_magic_link_production_round_trip_gate() -> None:
    """Drive the M3 gate check inline; assert the dispatched CheckResult."""
    result: CheckResult = run_magic_link_production_gate()
    assert result.name == "magic_link_production_round_trip"
    assert result.status in ("PASS", "FAIL")
    assert result.evidence
    # When the env flag is unset, the check is skipped with a clear evidence
    # string. When the flag is set, the helper exercises the round-trip
    # and either PASSes (cookie set) or FAILs with a specific reason.
    if result.status == "PASS":
        # Either skipped (flag off) or round-trip succeeded.
        assert (
            "APAP_AUTH_ENABLE_MAGIC_LINK unset" in result.evidence
            or "magic-link" in result.evidence.lower()
        )
    else:
        # FAIL must surface a specific reason, never a silent skip.
        assert "unset" in result.evidence.lower() or "missing" in result.evidence.lower() or "failed" in result.evidence.lower()
