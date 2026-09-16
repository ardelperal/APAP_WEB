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

_SUPPORTED_OPERATORS = (">=", "<=", "==", "!=", ">", "<")


def evaluate_condition(condition: str, variables: dict[str, str]) -> bool:
    """Evaluate a single ``{% if COND %}`` expression."""
    stripped = condition.strip()
    if not any(op in stripped for op in _SUPPORTED_OPERATORS):
        return bool(variables.get(stripped, "").strip())
    for op in _SUPPORTED_OPERATORS:
        if op in stripped:
            left, right = stripped.split(op, 1)
            left_value = variables.get(left.strip(), "")
            right_token = right.strip()
            return _string_op(left_value, right_token, op)
    return False  # pragma: no cover — unreachable


def _string_op(left: str, right_token: str, op: str) -> bool:
    """Compare ``left`` and ``right_token`` as strings per ``op``."""
    if op == "==":
        return left == right_token.strip("\"'")
    if op == "!=":
        return left != right_token.strip("\"'")
    try:
        ln, rn = float(left), float(right_token)
    except ValueError:
        return False
    if op == ">=":
        return ln >= rn
    if op == "<=":
        return ln <= rn
    if op == ">":
        return ln > rn
    if op == "<":
        return ln < rn
    return False  # pragma: no cover — unreachable


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
