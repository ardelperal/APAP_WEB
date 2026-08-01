"""Single import surface for the FastAPI domain router chain (issue #204).

Extracted from ``app/main.py`` as part of issue #204. The
``register_routers`` function is the only place that calls
``app.include_router(...)`` for the domain modules; ``app/main.py``
imports it and calls it once during ``create_app``. The ordering of
``include_router`` calls MUST be kept stable — multiple routers have
overlapping dynamic paths and rely on declaration order to take
precedence (see the inline comments in the pre-refactor
``app/main.py:641-684``).
"""

from __future__ import annotations

from fastapi import FastAPI

from app.modules.acogidas.routes import router as acogidas_router
from app.modules.adopciones.routes import router as adopciones_router
from app.modules.animals.routes import router as animals_router
from app.modules.cesiones.routes import router as cesiones_router
from app.modules.entradas.batch_routes import router as entradas_batch_router
from app.modules.entradas.routes import router as entradas_router
from app.modules.foster.assignment_routes import (
    router as foster_assignment_router,
)
from app.modules.foster.routes import router as foster_router
from app.modules.materiales.acogida_routes import (
    router as materiales_acogida_router,
)
from app.modules.materiales.routes import router as materiales_router
from app.modules.sanidad.batch_routes import router as sanidad_batch_router
from app.modules.sanidad.routes import router as sanidad_router
from app.modules.sanidad.terapia_routes import router as terapia_router
from app.modules.tasks.routes import router as tareas_router
from app.modules.voluntarios.routes import router as voluntarios_router


def register_routers(app: FastAPI) -> None:
    """Include every domain router on ``app`` in the same order as
    pre-refactor ``app/main.py``.

    Ordering notes (preserved from ``app/main.py:641-684``):

    - FOSTER-03 (#45) — foster_assignment_router mounted AFTER
      foster_router so its more specific paths (``/{casa_id}/asignar``,
      ``/{casa_id}/overrides``) take precedence over
      foster_router's dynamic ``/{casa_id}`` for those exact paths.
    - FOSTER-02 (#44) — acogidas_router mounted AFTER foster_router
      because the FK from ``acogidas`` -> ``casas_acogida`` requires
      the foster module to already be loaded.
    - ADOPT-01 (#47) — adopciones_router mounted near the end so its
      ``/{adopcion_id}`` dynamic path does not shadow more specific
      ``/{adopcion_id}/edit`` siblings.
    - HEALTH-01 (#50) — sanidad_router mounted AFTER adopciones for
      stable insertion order alongside other domain routers.
    - HEALTH-02 (#51) — sanidad_batch_router mounted AFTER
      sanidad_router because both routers declare paths under the
      ``/sanidad`` prefix. The single-record CRUD lives in
      ``sanidad/routes.py`` and the batch endpoint lives in
      ``sanidad/batch_routes.py``; mounting the batch router last
      guarantees the dynamic batch POST ``/sanidad/actuaciones/batch``
      takes precedence over the single-record POST ``/sanidad`` when
      both could match (they do not in practice — different paths —
      but the order keeps FastAPI's router chain unambiguous).
    - FOSTER-04 (#46) — materiales_router and
      materiales_acogida_router mounted LAST (catalog and per-estancia
      junction respectively); the junction router declares absolute
      paths under ``/acogidas/...`` so the catalog's
      ``{material_id}``-shaped paths must come first.
    - TASKS-01 (#7) — tareas_router mounted before materiales_router
      so the ``/tareas`` prefix is unambiguous.
    """
    app.include_router(animals_router)
    app.include_router(entradas_router)
    app.include_router(entradas_batch_router)
    app.include_router(foster_router)
    app.include_router(foster_assignment_router)
    app.include_router(acogidas_router)
    app.include_router(cesiones_router)
    app.include_router(voluntarios_router)
    app.include_router(adopciones_router)
    app.include_router(sanidad_router)
    app.include_router(sanidad_batch_router)
    app.include_router(terapia_router)
    app.include_router(tareas_router)
    app.include_router(materiales_router)
    app.include_router(materiales_acogida_router)
