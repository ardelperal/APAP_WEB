"""Single source of truth for the material form fields.

Mirrors the pattern in ``app.modules.adopciones.forms`` (issue #337):
bind multiple ``Form(...)`` parameters into a single Pydantic model
the route uses via ``Annotated[MaterialForm, Form()]``.
"""

from __future__ import annotations

from pydantic import BaseModel


class MaterialForm(BaseModel):
    """Form payload for create / update material.

    ``material``, ``tamano``, and ``color`` are required (natural key).
    ``observaciones`` is optional.
    """

    material: str
    tamano: str
    color: str
    observaciones: str | None = None
