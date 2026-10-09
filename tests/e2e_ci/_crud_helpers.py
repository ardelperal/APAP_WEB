"""Shared helpers for the failing-closed CRUD batteries (issue #1095).

Issue #1095 (slice 1) ports the ``tests/e2e/test_animales_crud.py``
battery into ``tests/e2e_ci/`` so the CI browser gate actually
exercises business flows instead of six form-less smoke tests. The
remaining batteries — entradas, adopciones, acogidas, cesiones,
sanidad — each inline the same helpers (e2e_secret, csrf helper,
animal_form_data, animal_id_factory, species/sex constants, Spanish
error fragments). This module is the single source of truth so the
five follow-up porting slices do not duplicate them again.

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
