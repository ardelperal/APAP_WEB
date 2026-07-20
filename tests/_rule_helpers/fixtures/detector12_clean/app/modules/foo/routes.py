"""Clean fixture for Detector 12 (Rule 27): importing a name from the
target module's package (__init__.py) — not a submodule path, not a
private name."""

from __future__ import annotations

from app.modules.bar import helper


def use_helper() -> str:
    return helper()
