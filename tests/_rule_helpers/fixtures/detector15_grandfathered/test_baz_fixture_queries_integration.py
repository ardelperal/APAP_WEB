"""Grandfathered fixture: integration test covers build_foo only.

build_baz is NOT covered here but is in BASELINE_NO_INTEGRATION_TESTS,
so Detector 15 must NOT flag it.
"""

from __future__ import annotations


def test_build_foo() -> None:
    # Minimal stub — the detector only checks for existence of this function.
    pass
