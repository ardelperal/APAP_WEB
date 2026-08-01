"""Grandfathered fixture for Detector 15 (integration test coverage).

This module has two build_ functions:
- build_foo: HAS a corresponding integration test (test_build_foo)
- build_baz: NO integration test BUT is in BASELINE_NO_INTEGRATION_TESTS

The detector should find NO violations for this fixture because:
- build_foo is covered by test_build_foo
- build_baz is grandfathered in BASELINE_NO_INTEGRATION_TESTS
"""

from __future__ import annotations

from typing import Any


def build_foo(param: str) -> tuple[str, list[Any]]:
    """Sample query builder covered by integration test."""
    return "SELECT id FROM test_table WHERE name = $1", [param]


def build_baz(param: str) -> tuple[str, list[Any]]:
    """Sample query builder NOT covered by integration test (grandfathered)."""
    return "SELECT id FROM test_table WHERE id = $1", [param]
