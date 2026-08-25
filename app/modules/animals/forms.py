"""Single source of truth for the animal form fields.

The animal form has 24 fields, all matching the ``_INSERT_COLUMNS``
constant in ``app.modules.animals.domain.animal``. Before the refactor, the
two POST handlers (``create_animal_view`` and ``update_animal_view``)
each declared the 24 fields as ``Form(...)`` parameters — adding or
removing a column meant two places to edit, and a typo in either was
a silent form-mismatch (the form would submit the wrong column name
and the service would fail at the SQL layer).

This module defines the fields in ONE place: a Pydantic model the
two routes both use via ``Annotated[AnimalForm, Form()]``. Adding a
column now means: add the column to the domain ``_INSERT_COLUMNS``
AND add the matching field here, and the test suite
verifies the two stay in sync.

Required fields are defined as ``ANIMAL_FORM_REQUIRED_FIELDS``
below — they are the union of:

- **Access ``TbFichaAnimal.Required=True``** (D-05 fidelidad al legacy):
  ``NCHIP``, ``NombreAnimal``, ``Especie``, ``Sexo``, ``FNacimiento``,
  ``Terapia``.
- **``docs/discovery/feature-01-animal-lifecycle.md``** §"Required
  animal data" (campos marcados como datos requeridos de ficha en
  el dominio aunque el Access no los marque ``Required=True``):
  ``TraeNChip``, ``FImplantacionChip`` (web: ``FIMPLANTACIONCHIP``),
  ``Foto`` (web: ``NombreFoto``; el legacy ``TbFichaAnimal`` lo guarda
  como ``NombreFoto`` que es el nombre del archivo de foto del animal).

Los 19 restantes son opcionales (el form permite dejarlos en blanco
y el service guarda NULL). El numero de required crecio de 5 a 9 en
#129 para cerrar el gap con el legacy.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from app.modules.animals.domain.animal import _INSERT_COLUMNS


class AnimalForm(BaseModel):
    """Form payload for create / update animal.

    Field names match the schema columns exactly (legacy Access names
    kept verbatim per the migration spec). The 9 required fields (in
    ``ANIMAL_FORM_REQUIRED_FIELDS`` below) are typed as plain ``str``;
    the rest are ``str | None`` so the form lets the operator leave
    them blank and the service stores NULL.
    """

    NCHIP: str
    NombreAnimal: str
    Especie: str
    Sexo: str
    FNacimiento: str
    Terapia: str
    TraeNChip: str
    FIMPLANTACIONCHIP: str
    NombreFoto: str
    Raza: str | None = None
    Color: str | None = None
    Pelo: str | None = None
    Tamano: str | None = None
    Caracter: str | None = None
    FDefuncion: str | None = None
    Observaciones: str | None = None
    Cartilla: str | None = None
    Eutanasia: str | None = None
    RazaPPP: str | None = None
    Mestizo: str | None = None
    EutanasiaOtrasCausas: str | None = None
    EutanasiaEnfermedad: str | None = None
    UltimoEstadoAntesDeFallecido: str | None = None
    ComunicacionARIAC: str | None = None


# Type alias so the routes can write ``Annotated[AnimalForm, Form()]``
# without the verbose subscript on every signature.
AnimalFormPayload = Annotated[AnimalForm, "form"]

# Public list of required fields (used by tests and by the form
# template's required-attribute rendering). Single source of truth for
# what the animal form and service consider mandatory — adding or
# removing a field here forces the test suite and form template to
# update, closing the drift surfaced in #129.
ANIMAL_FORM_REQUIRED_FIELDS: tuple[str, ...] = (
    # Access TbFichaAnimal.Required=True
    "NCHIP",
    "NombreAnimal",
    "Especie",
    "Sexo",
    "FNacimiento",
    "Terapia",
    # Discovery feature-01-animal-lifecycle.md
    # §"Required animal data" (product-required even
    # if not Required=True in Access)
    "TraeNChip",
    "FIMPLANTACIONCHIP",  # discovery: FImplantacionChip
    "NombreFoto",  # discovery: Foto -> web NombreFoto
)

# Public list of ALL 24 form field names, derived from the Pydantic
# model. Tests assert this matches the domain ``_INSERT_COLUMNS``
# constant so the form and the SQL never drift.
ANIMAL_FORM_FIELDS: tuple[str, ...] = tuple(AnimalForm.model_fields.keys())

# Belt-and-braces: the form MUST carry the same 24 columns the SQL
# INSERT writes. If a column is added to ``_INSERT_COLUMNS`` the test
# suite breaks at import time until the form is updated too, so the
# two cannot drift.
_ANIMAL_FORM_FIELDS_AS_SET: frozenset[str] = frozenset(ANIMAL_FORM_FIELDS)
_INSERT_COLUMNS_AS_SET: frozenset[str] = frozenset(_INSERT_COLUMNS)
assert _ANIMAL_FORM_FIELDS_AS_SET == _INSERT_COLUMNS_AS_SET, (
    "ANIMAL_FORM_FIELDS and domain._INSERT_COLUMNS must agree on the "
    f"24 column names; got form - insert = "
    f"{_ANIMAL_FORM_FIELDS_AS_SET - _INSERT_COLUMNS_AS_SET}, "
    f"insert - form = "
    f"{_INSERT_COLUMNS_AS_SET - _ANIMAL_FORM_FIELDS_AS_SET}"
)
