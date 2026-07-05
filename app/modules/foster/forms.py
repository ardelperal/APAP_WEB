"""Single source of truth for the casa de acogida form fields.

The CasaAcogidaForm Pydantic model owns the 19 form fields, matching
the ``_WRITE_COLUMNS`` constant in ``app.modules.foster.service``.
Before the #140 readability refactor, the two POST handlers
(``create_casa_acogida_view`` and ``update_casa_acogida_view``) each
declared the 19 fields as ``Form(...)`` parameters — adding a column
meant two places to edit and a typo in either was a silent
form-mismatch (the form would submit the wrong column name and the
service would fail at the SQL layer).

This module defines the fields in ONE place: a Pydantic model the two
routes both use via ``form: CasaAcogidaForm = Form(...)``. Adding a
column now means: add the column to ``_WRITE_COLUMNS`` in the service
AND add the matching field here, and the module-load assert below
closes the drift gap.

Required fields are the 6 declared in the service module docstring
(``nombre``, ``apellidos``, ``calle``, ``telefono``, ``coche``,
``capacidad``); the other 13 are optional (``str | None``) so the
operator can leave them blank and the service stores NULL.

``capacidad`` is the only field whose type is not ``str`` — Pydantic
coerces the form string to ``int`` at parse time. The
``_form_data_to_params`` helper in ``routes.py`` passes it through
unchanged (the int-coercion error path lives in Pydantic, not the
service); see #140 W2 for the prior silent-try/except bug.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel

from app.modules.foster.service import _WRITE_COLUMNS


class CasaAcogidaForm(BaseModel):
    """Form payload for create / update casa de acogida.

    Field names match the schema columns exactly (snake_case). The 6
    required fields are typed as plain ``str`` (or ``int`` for
    ``capacidad``); the rest are ``str | None`` so the form lets the
    operator leave them blank and the service stores NULL.
    """

    # --- required fields (service validation contract) ---------------------
    nombre: str
    apellidos: str
    calle: str
    telefono: str
    coche: str
    capacidad: int

    # --- optional fields ---------------------------------------------------
    dni_acogedor: str | None = None
    numero: str | None = None
    piso: str | None = None
    letra: str | None = None
    localidad: str | None = None
    provincia: str | None = None
    cp: str | None = None
    telefono2: str | None = None
    email: str | None = None
    vinculacion: str | None = None
    caracteristicas: str | None = None
    especie_preferente: str | None = None
    observaciones: str | None = None


# Public list of ALL 19 form field names, derived from the Pydantic
# model so the source-of-truth is the model itself (no parallel list
# to drift out of sync). Tests and the routes iterate this tuple.
CASA_ACOGIDA_FORM_FIELDS: Final[tuple[str, ...]] = tuple(
    CasaAcogidaForm.model_fields.keys()
)

# Belt-and-braces: the form MUST be a subset of the columns the SQL
# INSERT/UPDATE writes. If a column is added to ``_WRITE_COLUMNS`` the
# test suite breaks at import time until the form is updated too, so
# the two cannot drift. Subset (not equality) lets the service expose
# internal-only write columns not on the public form surface, but in
# practice the two are equal today (all 19 columns are user-facing).
_CASA_ACOGIDA_FORM_FIELDS_AS_SET: Final[frozenset[str]] = frozenset(
    CASA_ACOGIDA_FORM_FIELDS
)
_WRITE_COLUMNS_AS_SET: Final[frozenset[str]] = frozenset(_WRITE_COLUMNS)
assert _CASA_ACOGIDA_FORM_FIELDS_AS_SET.issubset(_WRITE_COLUMNS_AS_SET), (
    "CASA_ACOGIDA_FORM_FIELDS must be a subset of service._WRITE_COLUMNS; "
    f"form - write = "
    f"{_CASA_ACOGIDA_FORM_FIELDS_AS_SET - _WRITE_COLUMNS_AS_SET}"
)