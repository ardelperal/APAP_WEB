"""Tests for the filesystem-backed template source (DOC-01, #1109).

Pins the CP-1 :class:`ContratosPlantillaPort` contract end-to-end:
the adapter loads every :class:`TipoContrato` value through the
canonical templates directory, the loaded body carries the
"pending-legacy" marker line so a future port from the legacy
``.docx`` corpus can be tracked by a single test diff, the body
passes :func:`validar_gramatica` (broken template files fail
loudly on CI, not at request time), unknown types and missing
files both surface as
:class:`PlantillaNoDisponibleError`, and the adapter satisfies the
Protocol structurally so a future DI swap stays hermetic.

Test classification (skills/apap-testing-strategy §3): application
unit (hexagonal) — the adapter is exercised against the canonical
template directory (read-only) and a temporary directory for the
sad-path cases; no DB, no HTTP, no S3, no FastAPI. Gate B does
not apply: this test does not touch SQL, FK enforcement or
constraints. Honours web-tdd-philosophy rules 1 (fixture gate),
2 (no humo), 3 (cardinality), 4 (three paths) and 8 (no
production mutation).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.contratos.adapters.filesystem.contratos_filesystem_plantillas import (
    FilesystemContratosPlantillas,
)
from app.modules.contratos.domain.plantilla import (
    Plantilla,
    PlantillaInvalidaError,
    PlantillaNoDisponibleError,
    validar_gramatica,
)
from app.modules.contratos.domain.tipos_contrato import TipoContrato
from app.modules.contratos.ports.contratos_plantilla_port import (
    ContratosPlantillaPort,
)

#: Exact marker line the portado-del-legacy follow-up will diff
#: against. Pinned here so a future port that drops the marker
#: breaks a single test, not the whole battery.
PENDING_LEGACY_MARKER = (
    "<!-- CONTRATO-PLANTILLA: TEXTO PENDIENTE DE PORTAR DEL LEGACY "
    "(issue #1109) -->"
)

#: Canonical templates directory shipped with the slice. Resolved
#: via the adapter so the test follows the same path-resolution
#: rules the production code uses.
CANONICAL_TEMPLATES_DIR = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "modules"
    / "contratos"
    / "templates"
)


# --- 1. Protocol conformance ----------------------------------------------


def test_adapter_satisfies_contratos_plantilla_port() -> None:
    """The filesystem adapter is a runtime ``ContratosPlantillaPort``.

    ``runtime_checkable`` lets the Protocol be checked via
    ``isinstance`` after the duck-typed method exists. The slice's
    DI root will rely on this assertion to keep the wiring honest.
    """
    adapter = FilesystemContratosPlantillas(templates_dir=CANONICAL_TEMPLATES_DIR)
    assert isinstance(adapter, ContratosPlantillaPort)


def test_adapter_exposes_obtener_plantilla() -> None:
    """The adapter exposes the single port method in domain vocabulary."""
    adapter = FilesystemContratosPlantillas(templates_dir=CANONICAL_TEMPLATES_DIR)
    assert callable(getattr(adapter, "obtener_plantilla", None))


# --- 2. Every TipoContrato loads through the adapter -----------------------


@pytest.mark.parametrize("tipo", list(TipoContrato), ids=lambda t: t.value)
def test_every_tipo_contrato_loads_through_adapter(tipo: TipoContrato) -> None:
    """All eight legacy contract types load via the canonical adapter.

    Pins the ``_SLUG_POR_TIPO`` mapping end-to-end: a regression
    that drops a slug (or mistypes it) fails this test before the
    render use case sees the gap.
    """
    adapter = FilesystemContratosPlantillas(templates_dir=CANONICAL_TEMPLATES_DIR)
    plantilla = adapter.obtener_plantilla(tipo=tipo.value)
    assert isinstance(plantilla, Plantilla)
    assert plantilla.tipo == tipo.value
    # Cardinality: the body is non-empty (operator-facing diagnostic
    # relies on the text after substitution).
    assert plantilla.cuerpo.strip(), (
        f"plantilla for {tipo.value!r} must not be blank"
    )


@pytest.mark.parametrize("tipo", list(TipoContrato), ids=lambda t: t.value)
def test_every_loaded_body_carries_pending_legacy_marker(tipo: TipoContrato) -> None:
    """Every body carries the exact pending-legacy marker.

    Pins the "no se inventan clausulas" contract: a future port
    from the legacy ``.docx`` corpus MUST either preserve the
    marker (with a follow-up issue to retire it) or remove it
    together with a test diff. No silent swap of legal text.
    """
    adapter = FilesystemContratosPlantillas(templates_dir=CANONICAL_TEMPLATES_DIR)
    plantilla = adapter.obtener_plantilla(tipo=tipo.value)
    assert PENDING_LEGACY_MARKER in plantilla.cuerpo, (
        f"plantilla for {tipo.value!r} must start with the "
        f"pending-legacy marker; got body[0:80]={plantilla.cuerpo[:80]!r}"
    )


@pytest.mark.parametrize("tipo", list(TipoContrato), ids=lambda t: t.value)
def test_every_loaded_body_passes_validar_gramatica(tipo: TipoContrato) -> None:
    """Every body passes the engine's grammar check.

    A broken template file is a hard error: the adapter validates
    on first load and raises
    :class:`PlantillaInvalidaError` with the engine's diagnostic.
    This test pins that the canonical 8 files all clear the
    validator; a regression that adds an unbalanced ``{% if %}``
    breaks here before the render use case sees it.
    """
    adapter = FilesystemContratosPlantillas(templates_dir=CANONICAL_TEMPLATES_DIR)
    plantilla = adapter.obtener_plantilla(tipo=tipo.value)
    # Must not raise.
    validar_gramatica(plantilla.cuerpo)


# --- 3. Unknown tipo raises the domain error -------------------------------


def test_unknown_tipo_raises_plantilla_no_disponible_error() -> None:
    """A ``tipo`` outside the :class:`TipoContrato` enum raises the port error.

    The error is the same class the adapter uses for missing files
    (see below): "no template available" is the port-level
    contract, regardless of why. The use case translates the
    message to a 404 / 422 at the HTTP boundary.
    """
    adapter = FilesystemContratosPlantillas(templates_dir=CANONICAL_TEMPLATES_DIR)
    with pytest.raises(PlantillaNoDisponibleError):
        adapter.obtener_plantilla(tipo="TipoInventado")


def test_unknown_tipo_message_names_the_offending_value() -> None:
    """The diagnostic names the offending ``tipo`` so the operator can act.

    The engine diagnostic pattern across the slice (see
    :class:`PlantillaInvalidaError`) puts the offending value in
    the message; this test keeps the port consistent with that
    convention.
    """
    adapter = FilesystemContratosPlantillas(templates_dir=CANONICAL_TEMPLATES_DIR)
    with pytest.raises(PlantillaNoDisponibleError, match="TipoInventado"):
        adapter.obtener_plantilla(tipo="TipoInventado")


# --- 4. Missing file raises the domain error -------------------------------


def test_missing_template_file_raises_domain_error(tmp_path: Path) -> None:
    """A missing template file raises :class:`PlantillaNoDisponibleError`.

    Simulates a future regression where a TipoContrato value
    exists in the enum and the slug mapping but the ``.md`` file
    is missing: the adapter must surface the absence as the
    port-level error, not as a raw ``FileNotFoundError``.
    """
    adapter = FilesystemContratosPlantillas(templates_dir=tmp_path)
    # tmp_path is empty, so any TipoContrato value misses its file.
    with pytest.raises(PlantillaNoDisponibleError):
        adapter.obtener_plantilla(tipo=TipoContrato.ENTRADA.value)


def test_missing_template_message_mentions_filename(tmp_path: Path) -> None:
    """The diagnostic names the missing file so CI points the operator.

    Same engine-style pattern as the unknown-tipo case: the
    message carries the filename so the operator does not have
    to guess which slug failed.
    """
    adapter = FilesystemContratosPlantillas(templates_dir=tmp_path)
    with pytest.raises(PlantillaNoDisponibleError, match="entrada.md"):
        adapter.obtener_plantilla(tipo=TipoContrato.ENTRADA.value)


# --- 5. Broken template file fails loudly ---------------------------------


def test_broken_template_file_raises_grammar_error(tmp_path: Path) -> None:
    """A template with an unbalanced ``{% if %}`` raises the grammar error.

    A regression that produces a syntactically invalid body must
    surface on first load, not at request time — the adapter
    validates on cache miss and the operator sees the engine's
    diagnostic on CI. ``PlantillaInvalidaError`` is the contract;
    the use case does NOT translate it (it is an internal
    "broken artifact" error, distinct from the port-level
    "missing artifact" error).
    """
    broken = (
        "<!-- CONTRATO-PLANTILLA: TEXTO PENDIENTE DE PORTAR DEL LEGACY "
        "(issue #1109) -->\n"
        "Contrato de entrada\n"
        "{% if animal.edad_meses >= 6 %}\n"  # missing {% endif %}
    )
    (tmp_path / "entrada.md").write_text(broken, encoding="utf-8")

    adapter = FilesystemContratosPlantillas(templates_dir=tmp_path)
    with pytest.raises(PlantillaInvalidaError):
        adapter.obtener_plantilla(tipo=TipoContrato.ENTRADA.value)


# --- 6. Cache contract -----------------------------------------------------


def test_repeated_calls_return_same_plantilla_instance() -> None:
    """The adapter caches the loaded body and returns the same object.

    The cache lives on the instance; a second call must NOT
    re-read the file (and would not, because bodies are versioned
    in the repo). This test pins the contract without asserting
    the cache key — a future implementation can switch to a
    LRU/TTL without breaking the public surface as long as the
    returned object is the same ``Plantilla``.
    """
    adapter = FilesystemContratosPlantillas(templates_dir=CANONICAL_TEMPLATES_DIR)
    first = adapter.obtener_plantilla(tipo=TipoContrato.ENTRADA.value)
    second = adapter.obtener_plantilla(tipo=TipoContrato.ENTRADA.value)
    assert first is second


def test_each_tipo_is_cached_independently() -> None:
    """A second ``tipo`` loads its own body and does not collide with the first.

    Pins the per-tipo cache key: a regression that uses a single
    shared cache slot would surface here as the first body leaking
    into the second call.
    """
    adapter = FilesystemContratosPlantillas(templates_dir=CANONICAL_TEMPLATES_DIR)
    entrada = adapter.obtener_plantilla(tipo=TipoContrato.ENTRADA.value)
    adopcion = adapter.obtener_plantilla(tipo=TipoContrato.ADOPCION.value)
    assert entrada.tipo == TipoContrato.ENTRADA.value
    assert adopcion.tipo == TipoContrato.ADOPCION.value
    assert entrada is not adopcion
    # And the bodies differ — the title line mirrors the contract type.
    assert "entrada" in entrada.cuerpo.lower()
    assert "adopcion" in adopcion.cuerpo.lower()


# --- 7. Slug mapping exhaustiveness ----------------------------------------


def test_slug_mapping_covers_every_tipo_contrato() -> None:
    """The private slug map exposes one entry per :class:`TipoContrato` value.

    Mirrors the contratos test strategy: a regression that drops
    a TipoContrato from the mapping (or adds one) breaks the
    adapter before the render use case sees the gap. The test
    is a guard, not the public contract — it reaches into the
    private dict intentionally to make the regression loud.
    """
    from app.modules.contratos.adapters.filesystem import (
        contratos_filesystem_plantillas as adapter_module,
    )

    assert set(adapter_module._SLUG_POR_TIPO) == {t.value for t in TipoContrato}
    # And every slug is ASCII-safe (no whitespace, no diacritics, no
    # punctuation) so the filename mapping is stable across locales.
    for slug in adapter_module._SLUG_POR_TIPO.values():
        assert slug == slug.lower()
        assert " " not in slug
        assert slug.isascii()
