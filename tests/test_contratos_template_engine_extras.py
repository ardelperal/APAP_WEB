"""Coverage atoms for the contratos template engine (DOC-01 PR 1).

The base :mod:`tests.test_contratos_template_engine` pins the public
contract (the eight enum values, the grammar validator, the render
substitution and conditional expansion). This companion module
targets the internal branches that the public contract does not
reach but the 85% coverage floor requires:

- malformed ``{{ ...`` / ``{% ...`` tokens that survive validation
  (e.g. line-based diagnostics when the body has no validation-passed
  structure but the tokeniser runs on a hand-built grammar-bypass).
- nested ``{% if %}`` blocks (the engine supports ``if`` over ``if``
  via the ``skip_until_close`` counter).
- numeric comparisons whose right side parses as an integer.
- equality / inequality with quoted string literals.
- missing placeholder fallback to the literal ``{{ path }}`` form.

Hard rules honoured (web-tdd-philosophy):

- Rule 1 (fixture gate): no fixtures; template strings are literals.
- Rule 4 (no humo): every assertion pins a specific branch — the
  expansion result, the substitution literal, or the failure class.
"""

from __future__ import annotations

import pytest

from app.modules.contratos.application.render_condition import (
    evaluate_condition as _evaluate_condition,
)
from app.modules.contratos.application.render_condition import (
    substitute as _substitute,
)
from app.modules.contratos.application.render_contrato import render_contrato
from app.modules.contratos.application.render_tokenize import tokenizar as _tokenizar
from app.modules.contratos.domain.plantilla import (
    Plantilla,
    PlantillaInvalida,
)
from app.modules.contratos.domain.solicitud import SolicitudContrato
from app.modules.contratos.domain.tipos_contrato import TipoContrato

# --- 1. Tokeniser error branches -----------------------------------

def test_tokenizar_raises_when_placeholder_opener_is_unterminated() -> None:
    """``{{ path`` without ``}}`` raises PlantillaInvalida at tokenise time."""
    with pytest.raises(PlantillaInvalida, match=r"plantilla invalida: '{{' sin '}}'"):
        _tokenizar("hola {{ path")


def test_tokenizar_raises_when_tag_opener_is_unterminated() -> None:
    """``{% if x`` without ``%}`` raises at tokenise time."""
    with pytest.raises(PlantillaInvalida, match=r"plantilla invalida: '{%' sin '%}'"):
        _tokenizar("hola {% if x")


def test_tokenizar_raises_on_unknown_tag() -> None:
    """Tags other than ``if`` / ``endif`` are rejected at tokenise time."""
    with pytest.raises(PlantillaInvalida, match="etiqueta desconocida"):
        _tokenizar("hola {% for x in xs %}adios{% endfor %}")


# --- 2. _evaluate_condition branches --------------------------------

def test_evaluate_condition_string_equality_true() -> None:
    """Quoted-string equality with matching value resolves truthy."""
    assert _evaluate_condition("animal.sexo == 'Macho'", {"animal.sexo": "Macho"})


def test_evaluate_condition_string_equality_false() -> None:
    """Quoted-string equality with different value resolves falsy."""
    assert not _evaluate_condition(
        "animal.sexo == 'Macho'", {"animal.sexo": "Hembra"}
    )


def test_evaluate_condition_string_inequality() -> None:
    """Quoted-string inequality mirrors equality's semantics."""
    assert _evaluate_condition(
        "animal.sexo != 'Macho'", {"animal.sexo": "Hembra"}
    )
    assert not _evaluate_condition(
        "animal.sexo != 'Macho'", {"animal.sexo": "Macho"}
    )


def test_evaluate_condition_numeric_greater_than() -> None:
    """Numeric ``>`` comparison uses float coercion."""
    assert _evaluate_condition(
        "animal.edad_meses > 6", {"animal.edad_meses": "12"}
    )
    assert not _evaluate_condition(
        "animal.edad_meses > 6", {"animal.edad_meses": "3"}
    )


def test_evaluate_condition_numeric_less_than() -> None:
    """Numeric ``<`` comparison uses float coercion."""
    assert _evaluate_condition(
        "animal.edad_meses < 6", {"animal.edad_meses": "3"}
    )
    assert not _evaluate_condition(
        "animal.edad_meses < 6", {"animal.edad_meses": "12"}
    )


def test_evaluate_condition_numeric_greater_or_equal() -> None:
    """Numeric ``>=`` boundary value is inclusive."""
    assert _evaluate_condition(
        "animal.edad_meses >= 6", {"animal.edad_meses": "6"}
    )


def test_evaluate_condition_numeric_less_or_equal() -> None:
    """Numeric ``<=`` boundary value is inclusive."""
    assert _evaluate_condition(
        "animal.edad_meses <= 6", {"animal.edad_meses": "6"}
    )


def test_evaluate_condition_missing_value_is_falsy_for_bare_path() -> None:
    """A bare ``{% if path %}`` resolves falsy when the value is missing."""
    assert not _evaluate_condition("animal.esterilizado", {})


def test_evaluate_condition_missing_value_is_falsy_for_comparison() -> None:
    """A comparison whose LHS is missing resolves falsy (not exception)."""
    assert not _evaluate_condition(
        "animal.edad_meses >= 6", {}
    )


def test_evaluate_condition_invalid_number_resolves_falsy() -> None:
    """A non-numeric LHS against a numeric operator resolves falsy."""
    assert not _evaluate_condition(
        "animal.edad_meses >= 6", {"animal.edad_meses": "not-a-number"}
    )


# --- 3. _substitute fallback ----------------------------------------

def test_substitute_returns_literal_placeholder_when_missing() -> None:
    """A missing variable renders as ``{{ path }}`` rather than silently omitting it."""
    assert _substitute("animal.nombre", {}) == "{{ animal.nombre }}"


def test_substitute_returns_value_when_present() -> None:
    """A present variable renders as its stringified form."""
    assert _substitute("animal.nombre", {"animal.nombre": "Luna"}) == "Luna"


# --- 4. Nested conditional block ------------------------------------

def test_render_contrato_nested_if_inside_true_block_is_evaluated() -> None:
    """An ``{% if %}`` inside another ``{% if %}`` uses the nested counter.

    The legacy Adopcion template has ``{% if animal.sexo == 'Macho' %}
    {% if animal.esterilizado %}`` chains; the engine must expand both
    blocks when both conditions hold and skip the inner one cleanly
    when the outer is false.
    """
    cuerpo = (
        "{% if animal.sexo == 'Macho' %}"
        "Macho. {% if animal.esterilizado %}Esterilizado{% endif %}"
        "{% endif %}\n"
    )
    plantilla = Plantilla(tipo=TipoContrato.ADOPCION, cuerpo=cuerpo)

    macho_esterilizado = render_contrato(
        plantilla,
        SolicitudContrato(
            variables={
                "animal.sexo": "Macho",
                "animal.esterilizado": "si",
            },
            tipo=TipoContrato.ADOPCION,
        ),
    )
    assert "Macho. Esterilizado" in macho_esterilizado

    macho_no_esterilizado = render_contrato(
        plantilla,
        SolicitudContrato(
            variables={
                "animal.sexo": "Macho",
                "animal.esterilizado": "",
            },
            tipo=TipoContrato.ADOPCION,
        ),
    )
    assert "Macho." in macho_no_esterilizado
    assert "Esterilizado" not in macho_no_esterilizado

    hembra = render_contrato(
        plantilla,
        SolicitudContrato(
            variables={
                "animal.sexo": "Hembra",
                "animal.esterilizado": "si",
            },
            tipo=TipoContrato.ADOPCION,
        ),
    )
    assert "Macho" not in hembra
    assert "Esterilizado" not in hembra
