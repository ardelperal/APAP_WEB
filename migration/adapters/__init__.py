"""Adapters for the migration package.

Concrete implementations of the :mod:`migration.ports` Protocols.
Each subpackage is one adapter family (LocalBackend, legacy DAO, ...).
Adapters are the ONLY place that imports transport clients — the
:mod:`migration.application` use cases never see
:class:`~app.core.local_backend.LocalPostgresExecutor` or the legacy DAO
client directly.

§18 (web ↔ legacy mutual exclusion): the migration package is the
ONLY package allowed to read both backends. Adapter subpackages keep
each backend's I/O in its own module so a single import path can
never accidentally cross streams.
"""

from __future__ import annotations
