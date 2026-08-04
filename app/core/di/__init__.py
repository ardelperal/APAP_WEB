"""FastAPI dependency-injection wiring for the catalog (reference-data) port.

The :func:`get_catalogos_port` dependency is the only entry point routes
and use cases need to consume the catalog layer. Future slices
(``app/core/di/animals_di.py``, ``app/core/di/voluntarios_di.py``,
etc.) will follow the same pattern.
"""


from __future__ import annotations

from app.core.di.catalogos_di import get_catalogos_port

__all__ = ["get_catalogos_port"]
