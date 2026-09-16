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

- ``condición`` ::= ``nombre.variable`` | ``nombre.variable op literal``
- ``op``       ::= ``==`` | ``!=`` | ``>=`` | ``<=`` | ``>`` | ``<``
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


_IF_OPEN_RE = re.compile(r"\{%\s*if\s+(.+?)\s*%\}")
_ENDIF_RE = re.compile(r"\{%\s*endif\s*%\}")
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([\w]+(?:\.[\w]+)*)\s*\}\}")
_BARE_PATH_RE = re.compile(r"[\w]+(?:\.[\w]+)*")
_OPERATORS = ("==", "!=", ">=", "<=", ">", "<")


def validar_gramatica(cuerpo: str) -> None:
    """Raise :class:`PlantillaInvalida` if ``cuerpo`` is not well-formed."""
    bloques_if = _IF_OPEN_RE.findall(cuerpo)
    if not bloques_if:
        return
    if len(bloques_if) != len(_ENDIF_RE.findall(cuerpo)):
        raise PlantillaInvalida(  # noqa: TRY003
            f"plantilla invalida: {len(bloques_if)} '{{% if %}}' vs "
            f"{len(_ENDIF_RE.findall(cuerpo))} '{{% endif %}}'"
        )
    for condition in bloques_if:
        _validar_expresion_condicional(condition)


def _validar_expresion_condicional(condition: str) -> None:
    """Validate a single ``{% if COND %}`` expression.

    A bare placeholder reference (``{% if animal.sexo %}``) is valid
    and resolves to a truthy check at render time. An operator-bearing
    expression must use one of the supported operators with a known
    placeholder on the left side. The left operand may be either a
    bare dotted path (``animal.edad_meses``) or a fully wrapped
    ``{{ animal.edad_meses }}`` reference.
    """
    operator = _buscar_operador(condition)
    if operator is None:
        return
    left, right = _split_on_operator(condition, operator)
    _validar_operando_izquierdo(left.strip(), operator)
    _validar_operando_derecho(right.strip(), operator)


def _buscar_operador(condition: str) -> str | None:
    """Return the first supported operator in ``condition`` or ``None``.

    Iterates the operators in order so ``>=`` is preferred over ``>``.
    A bare placeholder reference (``{% if path %}``) returns ``None``
    and the caller treats the expression as a truthy check.
    """
    for op in _OPERATORS:
        if op in condition:
            return op
    return None


def _validar_operando_izquierdo(left: str, operator: str) -> None:
    """Reject a left operand that is neither a bare path nor ``{{ path }}``."""
    if _PLACEHOLDER_RE.fullmatch(left) or _BARE_PATH_RE.fullmatch(left):
        return
    raise PlantillaInvalida(  # noqa: TRY003
        f"plantilla invalida: lado izquierdo de '{operator}' "
        f"debe ser '{{{{ variable }}}}', recibio {left!r}"
    )


def _validar_operando_derecho(right: str, operator: str) -> None:
    """Reject a right operand that is neither a quoted string nor an integer."""
    if _is_literal(right):
        return
    raise PlantillaInvalida(  # noqa: TRY003
        f"plantilla invalida: lado derecho de '{operator}' "
        f"debe ser literal, recibio {right!r}"
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
    if _is_quoted_string(token):
        return True
    return token.lstrip("-").isdigit()


def _is_quoted_string(token: str) -> bool:
    """Return ``True`` if ``token`` is a single- or double-quoted string."""
    if len(token) < 2:
        return False
    quote = token[0]
    if token[-1] != quote:
        return False
    return quote in "'\""


__all__ = ["Plantilla", "PlantillaInvalida", "validar_gramatica"]
