"""Tests for the DOC-01 contratos template engine (issue #56, PR 1).

The template engine is the ZERO-IO heart of the contratos slice: it
parses a template body, validates its grammar, and renders the body
against a variable bundle. The PDF adapter sits on top of this in a
later PR; this RED pins the engine itself.

Hard rules honoured (web-tdd-philosophy):

- Rule 1 (fixture gate): the only fixtures are the test-local literal
  template strings. No I/O. No DB. No network.
- Rule 2 (no humo): every assertion pins one observable contract — the
  rendered text, the exception class, or the enum membership.
- Rule 4 (no production mutation): the engine is pure; the tests
  exercise the public use case surface only.
- Rule 8 (no production mutation): no fixtures hit a database or
  filesystem.

Test layout mirrors :mod:`tests.test_materiales`: pure-domain atoms
that do not need an HTTP client, a LocalBackend executor, or a
database. The integration atoms live in
``tests/integration/test_contratos_*.py`` (lands in PR 2 with the
storage adapter).
"""

from __future__ import annotations

import pytest

from app.modules.contratos.application.render_contrato import render_contrato
from app.modules.contratos.domain.plantilla import (
    Plantilla,
    PlantillaInvalidaError,
    validar_gramatica,
)
from app.modules.contratos.domain.solicitud import SolicitudContrato
from app.modules.contratos.domain.tipos_contrato import TipoContrato

# --- 1. TipoContrato enum coverage ------------------------------------

def test_tipo_contrato_enum_covers_eight_legacy_types() -> None:
    """TipoContrato must expose exactly the eight legacy contract types.

    Mirrors the eight ``TbContratosAnexos`` enum values documented in
    ``docs/legacy-signed-contract-flow.md`` §4. Removing any value is
    a breaking change to the storage adapter (orphaned object paths);
    adding one is a breaking change to the DB enum. The exhaustive
    list is the single source of truth.
    """
    assert {t.value for t in TipoContrato} == {
        "Entrada",
        "Acogida",
        "Acogida Judicial",
        "Adopcion",
        "PreAdopcion",
        "Cesion",
        "Reserva",
        "Entrega",
    }


def test_tipo_contrato_str_mixin_supports_legacy_string_equality() -> None:
    """TipoContrato values compare equal to plain legacy strings.

    The legacy ``RellenarContrato*`` family keys off plain strings
    (``"Adopcion"``, ``"Acogida Judicial"``, etc.). The ``str`` mix-in
    on the enum is what lets the storage adapter and the route layer
    pass a legacy string into ``SolicitudContrato`` without an
    explicit enum conversion. Pins the JSON serialisation contract.
    """
    assert TipoContrato.ADOPCION == "Adopcion"
    assert TipoContrato.ACOGIDA_JUDICIAL == "Acogida Judicial"


# --- 2. Grammar validation ------------------------------------------

def test_validar_gramatica_accepts_placeholder_only_body() -> None:
    """A body with only placeholders is well-formed and accepted."""
    validar_gramatica("Hola {{animal.nombre}}.")


def test_validar_gramatica_accepts_balanced_conditional_block() -> None:
    """Balanced ``{% if %}`` / ``{% endif %}`` blocks are accepted."""
    cuerpo = (
        "Nombre: {{animal.nombre}}\n"
        "{% if animal.sexo == 'Macho' %}\n"
        "Esterilizado: si\n"
        "{% endif %}\n"
    )
    validar_gramatica(cuerpo)


def test_validar_gramatica_accepts_bare_placeholder_condition() -> None:
    """``{% if path %}`` without an operator is a truthy check on the value.

    The legacy ``RellenarContrato*`` family treats a bare ``{% if
    variable %}`` as a boolean coercion of the variable. PR 1 of
    #56 mirrors that behaviour.
    """
    validar_gramatica("{% if animal.esterilizado %}Esterilizado{% endif %}")


def test_validar_gramatica_rejects_unbalanced_if_block() -> None:
    """A missing ``{% endif %}`` raises :class:`PlantillaInvalidaError`.

    The render use case cannot recover from an unbalanced block — it
    has no way to know where the block was supposed to end. The
    diagnostic names the opens vs. closes count so the operator can
    locate the gap without re-reading the whole template.
    """
    with pytest.raises(PlantillaInvalidaError, match="1 '{% if %}' vs 0 '{% endif %}'"):
        validar_gramatica("{% if animal.sexo %}Esterilizado")


def test_validar_gramatica_rejects_non_placeholder_left_operand() -> None:
    """A comparison with a literal on the LEFT of an operator is rejected.

    Only ``{{ variable }}`` references may stand on the left side of
    ``==`` / ``!=`` / ``>=`` / ``<=`` / ``>`` / ``<``. Pinning the
    left-operand rule keeps the grammar auditable — every comparison
    is ``{{ variable }} op literal`` and never the other way around.
    """
    with pytest.raises(PlantillaInvalidaError, match="lado izquierdo"):
        validar_gramatica("{% if 'Macho' == animal.sexo %}{% endif %}")


def test_validar_gramatica_accepts_numeric_right_operand() -> None:
    """Numeric literals on the right side of comparison operators are valid.

    The legacy ``RellenarContratoAdopcion`` clause uses
    ``{% if animal.edad_meses >= 6 %}`` to gate the sterilisation
    paragraph; that condition must validate under the engine grammar.
    """
    validar_gramatica(
        "{% if animal.edad_meses >= 6 %}Esterilizado: si{% endif %}"
    )


# --- 3. Render use case --------------------------------------------

def test_render_contrato_substitutes_simple_placeholder() -> None:
    """``{{ variable }}`` is replaced with the stringified value."""
    plantilla = Plantilla(
        tipo=TipoContrato.ENTRADA,
        cuerpo="Hola {{animal.nombre}}.",
    )
    solicitud = SolicitudContrato(
        variables={"animal.nombre": "Luna"},
        tipo=TipoContrato.ENTRADA,
    )
    resultado = render_contrato(plantilla, solicitud)
    assert resultado == "Hola Luna."


def test_render_contrato_substitutes_multiple_placeholders() -> None:
    """Multiple placeholders in the same body each resolve."""
    plantilla = Plantilla(
        tipo=TipoContrato.ADOPCION,
        cuerpo=(
            "Fecha: {{solicitud.fecha}}\n"
            "Adoptante: {{persona.nombre}} {{persona.apellidos}}\n"
            "Animal: {{animal.nombre}} ({{animal.chip}})\n"
        ),
    )
    solicitud = SolicitudContrato(
        variables={
            "solicitud.fecha": "2026-09-16",
            "persona.nombre": "Marta",
            "persona.apellidos": "García",
            "animal.nombre": "Toby",
            "animal.chip": "987000000123456",
        },
        tipo=TipoContrato.ADOPCION,
    )
    resultado = render_contrato(plantilla, solicitud)
    assert resultado == (
        "Fecha: 2026-09-16\n"
        "Adoptante: Marta García\n"
        "Animal: Toby (987000000123456)\n"
    )


def test_render_contrato_includes_block_when_condition_is_true() -> None:
    """A block gated by ``{% if animal.edad_meses >= 6 %}`` is included."""
    plantilla = Plantilla(
        tipo=TipoContrato.ADOPCION,
        cuerpo=(
            "Animal: {{animal.nombre}}\n"
            "{% if animal.edad_meses >= 6 %}"
            "Cláusula de esterilización obligatoria.\n"
            "{% endif %}"
        ),
    )
    solicitud = SolicitudContrato(
        variables={"animal.nombre": "Toby", "animal.edad_meses": "12"},
        tipo=TipoContrato.ADOPCION,
    )
    resultado = render_contrato(plantilla, solicitud)
    assert "Cláusula de esterilización obligatoria." in resultado
    assert "Animal: Toby" in resultado


def test_render_contrato_omits_block_when_condition_is_false() -> None:
    """A block gated by a false condition is removed from the output."""
    plantilla = Plantilla(
        tipo=TipoContrato.ADOPCION,
        cuerpo=(
            "Animal: {{animal.nombre}}\n"
            "{% if animal.edad_meses >= 6 %}"
            "Cláusula de esterilización obligatoria.\n"
            "{% endif %}"
        ),
    )
    solicitud = SolicitudContrato(
        variables={"animal.nombre": "Bimba", "animal.edad_meses": "3"},
        tipo=TipoContrato.ADOPCION,
    )
    resultado = render_contrato(plantilla, solicitud)
    assert "Cláusula" not in resultado
    assert "Animal: Bimba" in resultado


def test_render_contrato_handles_bare_placeholder_truthy() -> None:
    """``{% if path %}`` without operator treats the value as truthy.

    Mirrors the legacy Word mail-merge behaviour: ``{% if
    animal.esterilizado %}`` evaluates ``animal.esterilizado`` as a
    boolean — empty string and missing key are false, anything else
    is true.
    """
    plantilla = Plantilla(
        tipo=TipoContrato.ACOGIDA,
        cuerpo=(
            "{% if animal.esterilizado %}Esterilizado{% endif %}\n"
            "{% if animal.vacunado %}Vacunado{% endif %}\n"
        ),
    )
    solicitud = SolicitudContrato(
        variables={"animal.esterilizado": "si"},
        tipo=TipoContrato.ACOGIDA,
    )
    resultado = render_contrato(plantilla, solicitud)
    assert "Esterilizado" in resultado
    assert "Vacunado" not in resultado


def test_render_contrato_rejects_unbalanced_template() -> None:
    """A template with unbalanced ``{% if %}`` blocks raises at render.

    The use case validates the grammar before tokenising so the
    operator gets a clear diagnostic instead of a half-rendered
    contract.
    """
    plantilla = Plantilla(
        tipo=TipoContrato.ENTRADA,
        cuerpo="Hola {% if animal.sexo %}Macho",
    )
    solicitud = SolicitudContrato(
        variables={"animal.sexo": "Macho"},
        tipo=TipoContrato.ENTRADA,
    )
    with pytest.raises(PlantillaInvalidaError):
        render_contrato(plantilla, solicitud)


# --- 4. Conditional clause contracts --------------------------------

def test_adopcion_clauses_include_sterilisation_over_six_months() -> None:
    """DOC-01 acceptance: Adopcion gate sterilisation on age > 6 months.

    Pins the conditional clause from the legacy
    ``RellenarContratoAdopcion`` template. The engine must render the
    sterilisation paragraph for an adult animal and omit it for a
    puppy / kitten.
    """
    cuerpo = (
        "Animal: {{animal.nombre}}, {{animal.edad_meses}} meses.\n"
        "{% if animal.edad_meses >= 6 %}"
        "El adoptante se compromete a mantener al animal esterilizado.\n"
        "{% endif %}"
    )
    plantilla = Plantilla(tipo=TipoContrato.ADOPCION, cuerpo=cuerpo)

    adulto = render_contrato(
        plantilla,
        SolicitudContrato(
            variables={"animal.nombre": "Toby", "animal.edad_meses": "24"},
            tipo=TipoContrato.ADOPCION,
        ),
    )
    assert "esterilizado" in adulto.lower()

    cachorro = render_contrato(
        plantilla,
        SolicitudContrato(
            variables={"animal.nombre": "Bimba", "animal.edad_meses": "4"},
            tipo=TipoContrato.ADOPCION,
        ),
    )
    assert "esterilizado" not in cachorro.lower()
