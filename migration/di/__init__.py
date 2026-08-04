"""DI helpers for the migration package.

Constructors that bind the :mod:`migration.ports` Protocols to a
concrete adapter implementation. Tests override the binding by
replacing the executor with an in-memory fake — the use cases never
see the difference.
"""

from __future__ import annotations
