"""Domain: a contract template (the DOC-01 PR 1 deliverable).

A ``Plantilla`` is a text body with placeholders and conditional
blocks. The render use case substitutes the placeholders with
variable values from the contract request and emits the rendered
text. The PDF adapter is layered on top of this — the domain does not
produce PDF.

Template syntax (mirrors the legacy Word mail-merge the
``RellenarContrato*`` family already produces — see
``docs/legacy-signed-contract-flow.md``):

- Placeholder: ``{{nombre.variable}}`` — replaced verbatim with the
  string representation of ``variables[nombre.variable]``.
- Conditional: ``{% if condition %}...{% endif %}`` — block included
  when the condition evaluates truthy. Conditions support the same
  ``{{nombre.variable}}`` interpolation inside their expression so a
  clause can be species- or sex-dependent.

Condition grammar (deliberately minimal for the template engine; richer
expression parsing is out of scope for PR 1):

- ``condición`` ::= ``nombre.variable`` | ``nombre.variable == literal``
                  | ``nombre.variable != literal`` | ``nombre.variable >= número``
                  | ``nombre.variable <= número`` | ``nombre.variable > número``
                  | ``nombre.variable < número``
- ``literal``   ::= ``"..."`` or ``'...'`` (single or double quoted, no
  escapes) or ``número`` (integer).

The grammar is checked by the use case and any unknown operator raises
:class:`PlantillaInvalida`. The render use case rejects the whole
template (not the variable) on a parse error so the operator sees the
broken template immediately rather than a half-filled contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class PlantillaInvalida(ValueError):
    """Raised when the template body fails the engine's grammar check.

    Subclasses :class:`ValueError` so legacy ``except ValueError``
    clauses keep working. The operator-facing message is the engine's
    best-effort diagnosis (line number, offending token).
    """


@dataclass(frozen=True, slots=True)
class Plantilla:
    """A contract template body keyed by ``TipoContrato``.

    Attributes:
        tipo: The contract type this template belongs to.
        cuerpo: The raw template body. Substitution is driven by this
            string and ``variables`` at render time. Stored verbatim
            so the storage adapter can persist the same text a
            operator would edit in Word.
    """

    tipo: str
    cuerpo: str


# Match ``{% if COND %}`` opener / ``{% endif %}`` closer. The pattern
# is intentionally narrow so the operator can keep using literal
# percent signs inside the template body without escaping them.
_IF_OPEN_RE = re.compile(r"\{%\s*if\s+(.+?)\s*%\}")
_ENDIF_RE = re.compile(r"\{%\s*endif\s*%\}")
# Match ``{{ variable.path }}`` placeholders.
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([\w]+(?:\.[\w]+)*)\s*\}\}")
# Match the supported operator tokens inside a condition expression.
_SUPPORTED_OPERATORS = (
    "==",
    "!=",
    ">=",
    "<=",
    ">",
    "<",
)


def validar_gramatica(cuerpo: str) -> None:
    """Raise :class:`PlantillaInvalida` if ``cuerpo`` is not well-formed.

    The validation is a static scan over the template body; it does
    NOT need any variable context. The render use case calls this
    before tokenising so a broken template is rejected with the
    operator's exact line number.

    Rules checked:

    - Every ``{% if COND %}`` opener has a matching ``{% endif %}``.
    - The conditional expression uses one of the supported operators
      or is a bare placeholder reference.
    - Placeholders inside the expression are well-formed ``{{ path }}``.

    The full token-by-token parser belongs to a future PR; this
    validation is the minimum that lets the render use case emit a
    useful diagnostic instead of a generic ``KeyError``.
    """
    if_blocks = _IF_OPEN_RE.findall(cuerpo)
    if not if_blocks:
        return
    opens = len(if_blocks)
    closes = len(_ENDIF_RE.findall(cuerpo))
    if opens != closes:
        raise PlantillaInvalida(  # noqa: TRY003 — operator-facing diagnostic
            f"plantilla invalida: {opens} '{{% if %}}' vs {closes} '{{% endif %}}'"
        )
    for condition in if_blocks:
        _validar_expresion_condicional(condition)


def _validar_expresion_condicional(condition: str) -> None:
    """Validate a single ``{% if COND %}`` expression.

    A bare placeholder reference (``{% if animal.sexo %}``) is valid
    and resolves to a truthy check at render time. An operator-bearing
    expression must use one of the supported operators and reference
    a known placeholder on the left side. The left operand may be
    either a bare dotted path (``animal.edad_meses``) or a fully
    wrapped ``{{ animal.edad_meses }}`` reference — both are accepted
    so the legacy Word mail-merge syntax (``{% if animal.edad_meses
    >= 6 %}``) renders without forcing operators on the operator.
    """
    if any(op in condition for op in _SUPPORTED_OPERATORS):
        for op in _SUPPORTED_OPERATORS:
            if op in condition:
                left, right = _split_on_operator(condition, op)
                bare = left.strip()
                wrapped_match = _PLACEHOLDER_RE.fullmatch(bare)
                bare_is_path = bool(bare) and "." in bare and re.fullmatch(
                    r"[\w]+(?:\.[\w]+)*", bare
                ) is not None
                if wrapped_match is None and not bare_is_path:
                    raise PlantillaInvalida(  # noqa: TRY003
                        f"plantilla invalida: lado izquierdo de '{op}' "
                        f"debe ser '{{{{ variable }}}}', recibio {bare!r}"
                    )
                if not _is_literal(right):
                    raise PlantillaInvalida(  # noqa: TRY003
                        f"plantilla invalida: lado derecho de '{op}' "
                        f"debe ser literal, recibio {right.strip()!r}"
                    )
                return
        raise PlantillaInvalida(  # noqa: TRY003 — defensive, never reached
            f"plantilla invalida: operador no soportado en {condition!r}"
        )


def _split_on_operator(expression: str, operator: str) -> tuple[str, str]:
    """Split ``expression`` on the first occurrence of ``operator``.

    Operator precedence is not modelled: the first operator in the
    string wins. The grammar disallows compound expressions
    (``a == b and c == d``) for the same reason — out of scope for PR 1.
    """
    idx = expression.index(operator)
    return expression[:idx], expression[idx + len(operator):]


def _is_literal(token: str) -> bool:
    """Return ``True`` if ``token`` is a quoted string or an integer."""
    stripped = token.strip()
    if not stripped:
        return False
    if (stripped.startswith('"') and stripped.endswith('"')) or (
        stripped.startswith("'") and stripped.endswith("'")
    ):
        return len(stripped) >= 2
    return stripped.lstrip("-").isdigit()


__all__ = ["Plantilla", "PlantillaInvalida", "validar_gramatica"]
