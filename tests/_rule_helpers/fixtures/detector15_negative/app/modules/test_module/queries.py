"""Negative fixture for Detector 15 (integration test coverage).

This module has a queries.py with one build_ function (build_bar) but NO
corresponding integration test. The detector should produce a violation.
"""

from __future__ import annotations

from typing import Any


def build_bar(param: str) -> tuple[str, list[Any]]:
    """Sample query builder for Detector 15 negative fixture."""
    return "SELECT id FROM test_table WHERE name = $1", [param]
