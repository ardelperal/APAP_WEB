"""Adapter layer of the hexagonal architecture.

Each backend (InsForge, future legacy Access, future Redis cache,
etc.) owns a sub-package here. The adapter is the only layer that
imports the concrete backend client and the only layer that shapes
SQL strings.
"""


from __future__ import annotations

__all__: list[str] = []
