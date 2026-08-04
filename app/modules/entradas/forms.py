"""Single source of truth for the entrada form fields.

Mirrors the pattern in ``app.modules.adopciones.forms`` (issue #337):
bind multiple ``Form(...)`` parameters into a single Pydantic model
the route uses via ``Annotated[EntradaForm, Form()]``.
"""

from __future__ import annotations

from pydantic import BaseModel


class EntradaForm(BaseModel):
    """Form payload for create / update entrada.

    ``animal_id`` and ``fecha_entrada`` are required.
    The other 5 are optional so the operator can leave them blank
    and the service stores NULL.
    """

    animal_id: str
    fecha_entrada: str
    voluntario_entrada_id: str | None = None
    origen: str | None = None
    motivo: str | None = None
    observaciones: str | None = None
