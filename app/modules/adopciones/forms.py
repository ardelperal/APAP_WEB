"""Single source of truth for the adopcion form fields.

The adopcion form has 13 fields, all matching the ``ADOPCION_WRITE_COLUMNS``
constant in ``app.modules.adopciones.queries``. Before the #337 refactor,
the two POST handlers (``create_adopcion_view`` and ``update_adopcion_view``)
each declared the 13 fields as ``Form(...)`` parameters — adding or
removing a field meant two places to edit, and a typo in either was
a silent form-mismatch (the form would submit the wrong field name
and the service would fail at the SQL layer).

This module defines the fields in ONE place: a Pydantic model the
two routes both use via ``Annotated[AdopcionForm, Form()]``. Adding a
field now means: add the field to ``ADOPCION_WRITE_COLUMNS`` in the
queries module AND add the matching field here, and the module-load
assert below closes the drift gap.

Required fields are the 4 declared in the service's ``_required_text``
calls (``animal_id``, ``fecha_adopcion``, ``nombre_adoptante``,
plus ``tipo_adopcion`` which defaults to ``"regular"``);
the other 9 are optional (``str | None``) so the operator can
leave them blank and the service stores NULL.
"""

from __future__ import annotations

from pydantic import BaseModel


class AdopcionForm(BaseModel):
    """Form payload for create / update adopcion.

    Field names match the schema columns exactly (snake_case).
    The 4 required fields are typed as plain ``str``; the rest are
    ``str | None`` so the form lets the operator leave them blank
    and the service stores NULL. ``donativo_preadopcion`` and
    ``donativo_adopcion`` are stored as float by the service's
    ``_optional_numeric`` helper — they arrive here as strings from
    the form and the service coerces them.
    """

    # --- required fields (service validation contract) ---------------------
    animal_id: str
    fecha_adopcion: str
    nombre_adoptante: str
    tipo_adopcion: str = "regular"

    # --- optional fields -------------------------------------------------
    voluntario_seguimiento_id: str | None = None
    fecha_devolucion: str | None = None
    donativo_preadopcion: str | None = None
    donativo_adopcion: str | None = None
    dni_adoptante: str | None = None
    telefono_adoptante: str | None = None
    email_adoptante: str | None = None
    entrada_origen_id: str | None = None
    observaciones: str | None = None
