"""Positive fixture: integration test that covers build_foo.

The detector expects test_build_foo to exist here.
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_build_foo(ephemeral_postgres: object) -> None:
    """Covers build_foo from the queries module."""
    # This is a minimal stub — the detector only checks for existence.
    pass
