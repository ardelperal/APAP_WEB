"""Single source of truth for the salud form fields.

Mirrors the pattern in ``app.modules.adopciones.forms`` (issue #337):
bind multiple ``Form(...)`` parameters into a single Pydantic model
the route uses via ``Annotated[TerapiaForm, Form()]`` and
``Annotated[RecomendacionForm, Form()]``.
"""

from __future__ import annotations

from pydantic import BaseModel


class TerapiaForm(BaseModel):
    """Form payload for create / update terapia.

    ``animal_id``, ``voluntario_id``, and ``fecha`` are required.
    ``descripcion`` is optional.
    """

    animal_id: str
    voluntario_id: str
    fecha: str
    descripcion: str | None = None


class RecomendacionForm(BaseModel):
    """Form payload for create recomendacion.

    ``fecha`` and ``texto`` are required.
    """

    fecha: str
    texto: str
