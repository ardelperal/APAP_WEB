"""Dependency injection for the voluntarios slice (AGENTS.md §18).

Provides :func:`get_voluntarios_port` — the FastAPI dependency that wires
the :class:`StubVoluntariosPort` placeholder (pending a real
``LocalPostgresExecutor``-backed adapter in the follow-up to #668) into
the :class:`~app.modules.voluntarios.ports.voluntarios_port.VoluntariosPort`
Protocol.  Only this module knows both the Protocol and the concrete adapter.

The InsForge adapter implementation was deleted in issue #668; the
stub raises :class:`NotImplementedError` on every method call so the
runtime fails loud per route.
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.modules.voluntarios.adapters.stubs.voluntarios_stub import StubVoluntariosPort
from app.modules.voluntarios.ports.voluntarios_port import VoluntariosPort


def get_voluntarios_port(request: Request) -> Iterator[VoluntariosPort]:
    """FastAPI dependency yielding a per-request :class:`VoluntariosPort`.

    Returns the :class:`StubVoluntariosPort` placeholder until a real
    ``LocalPostgresExecutor``-backed adapter lands (issue #6').
    The stub raises :class:`NotImplementedError` on every method so the
    runtime fails loud per route.
    """
    del request  # unused — kept for FastAPI DI signature compatibility.
    yield StubVoluntariosPort()


__all__ = ["get_voluntarios_port"]
