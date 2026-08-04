"""Single source of truth for the cesion form fields.

Mirrors the pattern in ``app.modules.adopciones.forms`` (issue #337):
bind multiple ``Form(...)`` parameters into a single Pydantic model
the route uses via ``Annotated[CesionForm, Form()]``.

The cesión form has 22 fields covering the representative's identity,
address, and document references. Before the #388 PLR0913 refactor,
the POST handler declared all 22 as ``Form(...)`` parameters — adding
or removing a field meant touching two places.
"""

from __future__ import annotations

from pydantic import BaseModel


class CesionForm(BaseModel):
    """Form payload for create cesion.

    ``entrada_id`` and ``numero_contrato`` are required.
    The other 20 are optional so the operator can leave them blank
    and the service stores NULL.
    """

    # --- required fields -------------------------------------------------
    entrada_id: str
    numero_contrato: str

    # --- representative identity ----------------------------------------
    nombre_representante: str
    dni_representante: str | None = None

    # --- representative address ------------------------------------------
    fecha_cesion: str | None = None
    calle_representante: str | None = None
    numero_calle_representante: str | None = None
    piso_representante: str | None = None
    letra_representante: str | None = None
    localidad_representante: str | None = None
    provincia_representante: str | None = None
    cp_representante: str | None = None
    telefono_representante: str | None = None
    email_representante: str | None = None

    # --- document references ---------------------------------------------
    cartilla_sanitaria: str | None = None
    certificado_veterinario: str | None = None
    autorizacion_recogida: str | None = None
    fecha_vacuna_rabia: str | None = None
    numero_colegiado: str | None = None
    numero_colaborador: str | None = None
    hora_cesion: str | None = None
