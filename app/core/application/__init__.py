"""Application layer of the hexagonal architecture.

Each feature owns a sub-package here (e.g.
:mod:`app.core.application.catalogos`,
:mod:`app.core.application.schema_bootstrap`,
:mod:`app.core.application.auth`) that exposes one use case per
module. The application layer is the only place that depends on the
port (Protocol) and the domain entities; it never touches the
adapter or any concrete backend.
"""


from __future__ import annotations

__all__: list[str] = []
