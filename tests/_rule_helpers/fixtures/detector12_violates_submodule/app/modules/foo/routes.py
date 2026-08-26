"""Positive fixture for Detector 12 (Rule 27), failure mode (a):
``from app.modules.bar import service`` reaches into the ``service``
submodule directly instead of going through ``bar``'s public API,
mirroring the cross-module submodule import removed by issue #231."""

from __future__ import annotations

from app.modules.bar import service as bar_service


def use_service() -> str:
    return bar_service.do_thing()
