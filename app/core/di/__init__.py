"""FastAPI dependency-injection wiring for the application's port layer.

Each slice exposes its own ``get_<slice>_port`` dependency here:

- :func:`get_catalogos_port` (catalog slice)
- :func:`get_schema_bootstrap_port` (schema-bootstrap slice)

Future slices (``app/core/di/animals_di.py``, ``app/core/di/
voluntarios_di.py``, etc.) follow the same pattern.
"""


from __future__ import annotations

from app.core.di.catalogos_di import get_catalogos_port
from app.core.di.schema_bootstrap_di import get_schema_bootstrap_port

__all__ = ["get_catalogos_port", "get_schema_bootstrap_port"]
