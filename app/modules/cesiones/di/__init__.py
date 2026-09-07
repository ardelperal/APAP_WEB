"""Composition root — Cesiones slice DI.

Wires ``CesionesPort`` -> ``StubCesionesPort`` (pending a real
``LocalPostgresExecutor``-backed adapter in the follow-up to #668).
The InsForge adapter implementation was deleted in issue #668; the
stub raises :class:`NotImplementedError` on every method call so the
runtime fails loud per route.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.modules.cesiones.adapters.stubs.cesiones_stub import StubCesionesPort
from app.modules.cesiones.ports.cesiones_port import CesionesPort


def get_cesiones_port(
    request: Request,
) -> Iterator[CesionesPort]:
    """Yield a :class:`CesionesPort` backed by the stub placeholder.

    Returns the :class:`StubCesionesPort` placeholder until a real
    ``LocalPostgresExecutor``-backed adapter lands (issue #6').
    The stub raises :class:`NotImplementedError` on every method so the
    runtime fails loud per route.
    """
    del request  # unused — kept for FastAPI DI signature compatibility.
    yield StubCesionesPort()


__all__ = ["get_cesiones_port"]
