"""Condition evaluator for ``{% if %}`` blocks (DOC-01 PR 1).

Supports two expression shapes:

- bare ``{{ path }}`` -> truthy check on ``variables[path]``.
- ``{{ path }} op literal`` where ``op`` is one of ``==``, ``!=``,
  ``>=``, ``<=``, ``>``, ``<`` and the literal is a quoted string
  or integer.

Compound expressions (``a == b and c == d``) are out of scope and
rejected at validation time by
:func:`app.modules.contratos.domain.plantilla.validar_gramatica`.

The evaluator lives in its own module to keep the mutation-site
budget per file under 250 while keeping the public surface in
``render_contrato.py`` minimal.
"""

from __future__ import annotations

_OPERATORS = ("==", "!=", ">=", "<=", ">", "<")


def evaluate_condition(condition: str, variables: dict[str, str]) -> bool:
    """Evaluate a single ``{% if COND %}`` expression."""
    stripped = condition.strip()
    operator = _first_operator(stripped)
    if operator is None:
        return bool(variables.get(stripped, "").strip())
    left, right = stripped.split(operator, 1)
    return _compare(variables.get(left.strip(), ""), right.strip(), operator)


def _first_operator(expression: str) -> str | None:
    """Return the first operator in ``expression`` or ``None``."""
    for op in _OPERATORS:
        if op in expression:
            return op
    return None


def _compare(left: str, right_token: str, operator: str) -> bool:
    """Compare ``left`` against ``right_token`` per ``operator``."""
    if operator == "==":
        return left == _unquote(right_token)
    if operator == "!=":
        return left != _unquote(right_token)
    return _compare_numeric(left, right_token, operator)


def _compare_numeric(left: str, right_token: str, operator: str) -> bool:
    """Compare ``left`` and ``right_token`` as floats per ``operator``."""
    try:
        ln, rn = float(left), float(right_token)
    except ValueError:
        return False
    if operator == ">=":
        return ln >= rn
    if operator == "<=":
        return ln <= rn
    if operator == ">":
        return ln > rn
    return ln < rn


def _unquote(token: str) -> str:
    """Strip surrounding quotes from a string literal token."""
    stripped = token.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "'\"":
        return stripped[1:-1]
    return stripped


def substitute(placeholder_path: str, variables: dict[str, str]) -> str:
    """Return ``variables[path]`` literally, with a literal ``{{ path }}``
    fallback when the key is missing.

    The fallback is deliberate: silent omission would let a missing
    variable produce a valid-looking contract with a missing field,
    which is a fidelity bug. A literal placeholder keeps the gap
    visible until the operator populates the source.
    """
    if placeholder_path not in variables:
        return "{{ " + placeholder_path + " }}"
    return variables[placeholder_path]


__all__ = ["evaluate_condition", "substitute"]
