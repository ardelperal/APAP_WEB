"""Positive fixture for Detector 15 (integration test coverage).

This module has a queries.py with one build_ function (build_foo) and a
corresponding integration test that covers it. The detector should find
NO violations for this fixture.
"""

from __future__ import annotations

from typing import Any


def build_foo(param: str) -> tuple[str, list[Any]]:
    """Sample query builder for Detector 15 positive fixture."""
    return "SELECT id FROM test_table WHERE name = $1", [param]
