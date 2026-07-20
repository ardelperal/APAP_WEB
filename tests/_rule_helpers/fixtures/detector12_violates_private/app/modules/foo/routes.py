"""Positive fixture for Detector 12 (Rule 27), failure mode (b):
importing an underscore-prefixed 'private' name across module
boundaries, mirroring ``app/modules/entradas/batch_service.py``'s
private-helper import pattern (issue #232) but across modules."""

from __future__ import annotations

from app.modules.bar import _private_helper


def use_it() -> str | None:
    return _private_helper()
