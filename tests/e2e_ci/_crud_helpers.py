"""Shared helpers for the failing-closed CRUD batteries (issue #1095).

Issue #1095 (slice 1) ports the ``tests/e2e/test_animales_crud.py``
battery into ``tests/e2e_ci/`` so the CI browser gate actually
exercises business flows instead of six form-less smoke tests. Slice 2
adds the ``tests/e2e/test_entradas_crud.py`` and
``tests/e2e/test_cesiones_crud.py`` batteries. The remaining batteries
— adopciones, acogidas, sanidad — each inline the same helpers
(e2e_secret, csrf helper, animal_form_data, animal_id_factory,
species/sex constants, Spanish error fragments). This module is the
single source of truth so the follow-up porting slices do not duplicate
them again.

The helpers are read verbatim from the inlined originals; only the
visibility is widened (drop the leading underscore) so other
batteries can import them. Behaviour is intentionally unchanged.
"""

from __future__ import annotations

import os
import uuid

from playwright.sync_api import Page

# --- shared constants -----------------------------------------------------

# Header carrying the e2e login secret. The route /e2e/login is the
# OAuth mock that mints a developer session when this header is set.
E2E_SECRET_HEADER = "X-E2E-Secret"

# Header that ``CsrfMiddleware`` requires for non-form-encoded
# non-safe methods (PATCH, JSON POST, etc.). Form-encoded POSTs
# include the token through the hidden input rendered by the form.
CSRF_HEADER = "X-CSRFToken"

# Species + sex are domain enums (Especie.CANINA, Sexo.M) — the legacy
# form carries them as uppercase strings. The species / sex selectors
# in the animales form are dropdowns with option values "CANINA" /
# "FELINA" and "M" / "H" respectively (per
# ``app/modules/animals/domain/animal.py``).
SPECIES_CANINA = "CANINA"
SPECIES_FELINA = "FELINA"
SEX_MACHO = "M"
SEX_HEMBRA = "H"

# Spanish / English fragments preserved through the FK-validation
# 422 response. ``adopciones`` and ``sanidad`` share the same canonical
# value; ``entradas`` uses ``animal_id does not reference`` with no
# "active" qualifier — both are pinned in their respective 422 atoms.
NONEXISTENT_ANIMAL_SPANISH = "animal_id does not reference"

#: Sanidad answers with the lifecycle gate's Spanish message, not the FK
#: pre-check copy the other modules produce (issue #1298): the guard lives in
#: ``_raise_validation_error`` and names the animal, so the operator sees a
#: different sentence than ``NONEXISTENT_ANIMAL_SPANISH``.
SANIDAD_NONEXISTENT_ANIMAL_SPANISH = "debe apuntar a un animal activo"

# Slice 2 — ``/entradas`` 422 path. The form template renders the
# error panel header as ``"No se pudo guardar la entrada"``; both the
# create and update routes go through the same panel.
ENTRADA_SAVE_FAILED_SPANISH = "No se pudo guardar la entrada"

# Slice 2 — ``/cesiones`` 422 path. The form template renders the
# header as ``"No se pudo guardar la cesión"`` (accented); the original
# test asserts the non-accented substring (see the regression-comment
# at ``tests/e2e/test_cesiones_crud.py:482``). Preserving that
# substring verbatim is the whole point of porting the assertions
# exactly — if the test currently fails against the live form the
# mismatch is the finding, not the test.
CESION_SAVE_FAILED_SPANISH = "No se pudo guardar la cesion"

# Slice 2 — regression sentinel for the ``/cesiones/new`` form h1.
# The template renders ``"Nueva cesión por propietario"``; the
# original battery asserts ``h1.lower()`` contains the substring
# ``"cesión"`` so an accidental page swap ("Nueva adopción", "Editar
# contrato", ...) is loud.
CESION_FORM_H1_LOWER_FRAGMENT = "cesión"

# Slice 3 — ``/adopciones`` list-page h1. The list template at
# ``app/templates/adopciones/list.html`` renders an
# ``<h1 id="main-title">Adopciones</h1>`` at the top of the page; the
# slice-3 battery pins this exact string as a regression sentinel so
# the route is rendered (not an error page).
ADOPCIONES_LIST_TITLE = "Adopciones"

# Slice 3 — Spanish error header for the ``/adopciones`` 422/409
# branch. The route's create/update handlers wrap the underlying
# ``ValueError`` / ``AdopcionConflictError`` under
# ``"No se pudo guardar la adopción: ..."``; the form template ALSO
# renders the bare ``"No se pudo guardar la adopción"`` inside the
# error panel header (``app/templates/adopciones/form.html:15``),
# so the body carries the substring either way. The FK validation
# surfaces ``"animal_id does not reference ..."`` (the existing
# ``NONEXISTENT_ANIMAL_SPANISH`` constant).
ADOPCION_SAVE_FAILED_SPANISH = "No se pudo guardar la adopción"

# Slice 3 — Spanish error header for the ``/sanidad`` 422/503
# branch. Same shape as the entradas / adopciones / cesiones panels:
# the form template (``app/templates/sanidad/form.html:16``) renders
# the bare ``"No se pudo guardar la actuación"`` inside the error
# panel header and the route prepends
# ``"No se pudo guardar la actuación: ..."`` to the underlying
# ``ValueError`` / ``BackendError`` text.
SANIDAD_SAVE_FAILED_SPANISH = "No se pudo guardar la actuación"

# Slice 2 — ``/entradas`` list-page h1.
ENTRADAS_LIST_TITLE = "Entradas"

# Slice 2 — P1-fidelity list of every ``name="..."`` the cesión form
# must render. There are 21 inputs (one per legacy column plus the
# ``hora_cesion`` time field) — preserved 1:1 from the original
# ``tests/e2e/test_cesiones_crud.py:285-309`` so the slice-2 port
# keeps the same fidelity check.
CESION_LEGACY_FIELDS: tuple[str, ...] = (
    "entrada_id",
    "numero_contrato",
    "nombre_representante",
    "dni_representante",
    "fecha_cesion",
    "calle_representante",
    "numero_calle_representante",
    "piso_representante",
    "letra_representante",
    "localidad_representante",
    "provincia_representante",
    "cp_representante",
    "telefono_representante",
    "email_representante",
    "cartilla_sanitaria",
    "certificado_veterinario",
    "autorizacion_recogida",
    "fecha_vacuna_rabia",
    "numero_colegiado",
    "numero_colaborador",
    "hora_cesion",
)


# --- helpers --------------------------------------------------------------


def e2e_secret() -> str | None:
    """Return the test-suite shared secret, or ``None`` if unset.

    Mirrors the inlined ``_e2e_secret()`` helpers in
    ``tests/e2e/test_animales_crud.py`` and the five sibling
    batteries. Read from the environment because the OAuth mock
    resolves it server-side from the same variable.
    """
    return os.environ.get("APAP_E2E_AUTH_SECRET")


def unique_chip() -> str:
    """Generate a unique chip string (uuid hex, max 15 chars).

    Mirrors ``tests/e2e/test_animales_crud.py::_unique_chip``. The
    legacy ``NCHIP`` column carries a unique constraint and the
    UUID-derived suffix keeps sibling tests from colliding.
    """
    return uuid.uuid4().hex[:15]


def csrf_token_from_form(page: Page) -> str:
    """Read the csrf_token hidden input rendered on the current page.

    Every form page (animales, entradas, batch, ...) renders the
    token as ``<input type="hidden" name="csrf_token" value="...">``.
    This helper also acts as the regression sentinel: every form
    page MUST render a non-empty token (otherwise ``CsrfMiddleware``
    rejects every POST and the whole slice breaks).

    Mirrors ``tests/e2e/test_animales_crud.py::_csrf_token_from_form``.
    The "page, path" rendering in the task description refers to
    ``_visit_animal_form(page, base_url, animal_id)`` which navigates
    first and then calls this helper — the helper itself only needs
    the page.
    """
    token = page.locator('input[name="csrf_token"]').first.get_attribute("value")
    assert token, "every form page must render a non-empty csrf_token hidden input"
    return token


def animal_form_data(suffix: str) -> dict[str, str]:
    """Build a valid AnimalForm payload (9 required + 2 optionals).

    Mirrors the inner factory of
    ``tests/e2e/test_animales_crud.py::make_animal_form_data`` and
    the parallel ``_animal_form_data`` helpers in
    ``tests/e2e/test_adopciones_crud.py`` and
    ``tests/e2e/test_sanidad_crud.py``. Each call uses a unique
    chip so multiple ``/animales`` POSTs in the same session do
    not collide on the UNIQUE constraint.

    Field names follow the Pydantic model in
    ``app/modules/animals/forms.py::AnimalForm``.
    """
    chip = unique_chip()
    return {
        "NCHIP": chip,
        "NombreAnimal": f"Test-{suffix}",
        "Especie": SPECIES_CANINA,
        "Sexo": SEX_MACHO,
        "FNacimiento": "2024-01-15",
        "TraeNChip": "Si",
        "FIMPLANTACIONCHIP": "2024-01-16",
        "NombreFoto": "",
        "Terapia": "No",
        "Raza": "Mestizo",
        "Color": "Negro",
    }


def entrada_form_data(
    animal_id: str,
    fecha_entrada: str,
    *,
    origen: str = "",
    motivo: str = "",
    observaciones: str = "",
    voluntario_entrada_id: str = "",
) -> dict[str, str]:
    """Build a valid ``EntradaForm`` payload (2 required + 4 optionals).

    Mirrors ``tests/e2e/test_entradas_crud.py::_fill_entrada_form``
    (slice 2 adapts the inlined DOM-fill helper into a form-data
    builder that pairs with ``page.request.post(...)`` instead of
    click-driven browser submission — the slice-1 animales port
    established the same pattern). The four optional fields
    default to empty strings so the form posts the minimum valid
    intake-entry.

    Field names follow the Pydantic model in
    ``app/modules/entradas/forms.py::EntradaForm``.
    """
    return {
        "animal_id": animal_id,
        "fecha_entrada": fecha_entrada,
        "voluntario_entrada_id": voluntario_entrada_id,
        "origen": origen,
        "motivo": motivo,
        "observaciones": observaciones,
    }


def cesion_form_data(
    *,
    entrada_id: str,
    numero_contrato: str,
    nombre_representante: str,
    **overrides: str,
) -> dict[str, str]:
    """Build a valid ``CesionForm`` payload (3 required + 18 optionals).

    Mirrors ``tests/e2e/test_cesiones_crud.py::_cesion_form_data``
    (slice 2 adopts it verbatim into the shared module so the cesión
    battery can import it). The 18 optional fields default to empty
    string (the route's ``_opt`` helper converts blanks to ``None``
    so the service writes ``NULL`` to the DB rather than ``""``).
    Calls can override individual fields via ``**overrides`` — used
    by the blank-``nombre_representante`` 422 atom.

    Field names follow the Pydantic model in
    ``app/modules/cesiones/forms.py::CesionForm``.
    """
    data: dict[str, str] = {
        "entrada_id": entrada_id,
        "numero_contrato": numero_contrato,
        "nombre_representante": nombre_representante,
        "dni_representante": "",
        "fecha_cesion": "",
        "calle_representante": "",
        "numero_calle_representante": "",
        "piso_representante": "",
        "letra_representante": "",
        "localidad_representante": "",
        "provincia_representante": "",
        "cp_representante": "",
        "telefono_representante": "",
        "email_representante": "",
        "cartilla_sanitaria": "",
        "certificado_veterinario": "",
        "autorizacion_recogida": "",
        "fecha_vacuna_rabia": "",
        "numero_colegiado": "",
        "numero_colaborador": "",
        "hora_cesion": "",
    }
    data.update(overrides)
    return data


def adopcion_form_data(
    *,
    animal_id: str,
    fecha_adopcion: str,
    nombre_adoptante: str,
    tipo_adopcion: str = "regular",
    telefono_adoptante: str = "",
    email_adoptante: str = "",
    dni_adoptante: str = "",
    observaciones: str = "",
    voluntario_seguimiento_id: str = "",
    fecha_devolucion: str = "",
    donativo_preadopcion: str = "",
    donativo_adopcion: str = "",
    entrada_origen_id: str = "",
) -> dict[str, str]:
    """Build a valid ``AdopcionForm`` payload (4 required + 9 optionals).

    Mirrors ``tests/e2e/test_adopciones_crud.py::_adopcion_form_data``
    (slice 3 promotes it into the shared module so the adopcion
    battery can import it). The 4 required fields are
    ``animal_id``, ``fecha_adopcion``, ``nombre_adoptante``, and
    ``tipo_adopcion`` (the latter defaults to ``"regular"``). The 9
    optional fields default to empty strings so the form posts the
    minimum valid adoption payload.

    Field names follow the Pydantic model in
    ``app/modules/adopciones/forms.py::AdopcionForm``.
    """
    return {
        "animal_id": animal_id,
        "voluntario_seguimiento_id": voluntario_seguimiento_id,
        "fecha_adopcion": fecha_adopcion,
        "fecha_devolucion": fecha_devolucion,
        "donativo_preadopcion": donativo_preadopcion,
        "donativo_adopcion": donativo_adopcion,
        "nombre_adoptante": nombre_adoptante,
        "dni_adoptante": dni_adoptante,
        "telefono_adoptante": telefono_adoptante,
        "email_adoptante": email_adoptante,
        "entrada_origen_id": entrada_origen_id,
        "observaciones": observaciones,
        "tipo_adopcion": tipo_adopcion,
    }


def actuacion_form_data(
    *,
    animal_id: str,
    fecha: str,
    tipo_actuacion_id: str = "",
    voluntario_id: str = "",
    veterinario: str = "",
    observaciones: str = "",
    material_utilizado: str = "",
) -> dict[str, str]:
    """Build a valid ``ActuacionForm`` payload (2 required + 5 optionals).

    Mirrors ``tests/e2e/test_sanidad_crud.py::_actuacion_form_data``
    (slice 3 promotes it into the shared module so the sanidad
    battery can import it). The 2 required fields are ``animal_id``
    and ``fecha``; the 5 optional fields default to empty strings
    so the form posts the minimum valid actuacion payload, and the
    ``tipo_actuacion_id`` deliberately defaults to ``""`` so the
    operator / test can leave the dropdown on "Sin clasificar" and
    the service writes NULL to the DB (mirroring the original
    ``tests/e2e/test_sanidad_crud.py`` convention, which avoids
    assuming the ``catalogos_pruebas`` seed is populated).

    Field names follow the Pydantic model in
    ``app/modules/sanidad/forms.py::ActuacionForm``.
    """
    return {
        "animal_id": animal_id,
        "voluntario_id": voluntario_id,
        "fecha": fecha,
        "tipo_actuacion_id": tipo_actuacion_id,
        "veterinario": veterinario,
        "observaciones": observaciones,
        "material_utilizado": material_utilizado,
    }
