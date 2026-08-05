"""Single source of truth for the sanidad form fields.

Mirrors the pattern in ``app.modules.adopciones.forms`` (issue #337):
bind multiple ``Form(...)`` parameters into a single Pydantic model
the route uses via ``Annotated[ActuacionForm, Form()]``.
"""

from __future__ import annotations

from pydantic import BaseModel


class ActuacionForm(BaseModel):
    """Form payload for create / update actuacion sanitaria.

    ``animal_id`` and ``fecha`` are required.
    The other 5 are optional so the operator can leave them blank
    and the service stores NULL.
    """

    animal_id: str
    fecha: str
    voluntario_id: str | None = None
    tipo_actuacion_id: str | None = None
    veterinario: str | None = None
    observaciones: str | None = None
    material_utilizado: str | None = None
