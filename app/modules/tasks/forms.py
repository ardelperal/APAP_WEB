"""Single source of truth for the tarea form fields.

Mirrors the pattern in ``app.modules.adopciones.forms`` (issue #337):
bind multiple ``Form(...)`` parameters into a single Pydantic model
the route uses via ``Annotated[TareaForm, Form()]``.
"""

from __future__ import annotations

from pydantic import BaseModel


class TareaForm(BaseModel):
    """Form payload for create tarea.

    ``tipo`` is required. The other fields are optional with defaults
    matching the original Form() defaults.
    """

    tipo: str
    origen: str = "dashboard_manual"
    prioridad: str = "normal"
    vencimiento_at: str | None = None
    vinculo_tipo: str | None = None
    vinculo_id: str | None = None
