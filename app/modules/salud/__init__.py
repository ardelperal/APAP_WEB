"""Public surface of the ``salud`` module.

Provides CRUD for ``terapias`` and ``recomendaciones`` (HEALTH-04, issue #53).
"""

from app.modules.salud import service as salud_service

__all__ = ["salud_service"]
