"""Single source of truth for the acogida form fields.

Mirrors the pattern in ``app.modules.adopciones.forms`` (issue #337):
bind multiple ``Form(...)`` parameters into a single Pydantic model
the route uses via ``Annotated[AcogidaForm, Form()]``. Adding a field
now means one place to edit, and the form model stays in sync with
the service layer's column expectations.
"""

from __future__ import annotations

from pydantic import BaseModel


class AcogidaForm(BaseModel):
    """Form payload for create / update estancia de acogida.

    Field names match the schema columns exactly (snake_case).
    Required fields (``animal_id``, ``fecha_inicio``) are plain ``str``.
    The other 13 are optional (``str | None``) so the operator can
    leave them blank and the service stores NULL.
    """

    # --- required fields -------------------------------------------------
    animal_id: str
    fecha_inicio: str

    # --- optional fields -------------------------------------------------
    casa_acogida_id: str | None = None
    voluntario_acogida_id: str | None = None
    voluntario_seguimiento1_id: str | None = None
    voluntario_seguimiento2_id: str | None = None
    voluntario_sanitario_id: str | None = None
    fecha_final: str | None = None
    entrada_origen_id: str | None = None
    direccion: str | None = None
    telefono: str | None = None
    observaciones: str | None = None
