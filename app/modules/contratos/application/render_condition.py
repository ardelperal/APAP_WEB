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

Complexity note: each comparison is dispatched through a small
operator table so neither ``evaluate_condition`` nor
:meth:`_compare` carries more than a handful of branches; the
table itself is constant data.
"""

from __future__ import annotations

from collections.abc import Callable

_SUPPORTED_OPERATORS: tuple[str, ...] = (">=", "<=", "==", "!=", ">", "<")

#: Operator dispatch table. Each entry is the operator's
#: ``(left, right) -> bool`` callable. Equality and inequality
#: operate on the stripped string literal so a quoted ``"Macho"``
#: compares equal to the unquoted ``Macho``.
_NUMERIC_OPS: dict[str, Callable[[float, float], bool]] = {}


def _strip_quotes(token: str) -> str:
    """Remove a single matched pair of surrounding ``"`` or ``'``."""
    return token.strip("\"'")


def _try_pair(left: str, right: str) -> tuple[float, float] | None:
    """Return ``(left, right)`` as floats if both parse, else ``None``."""
    try:
        return float(left), float(right)
    except ValueError:
        return None


def evaluate_condition(condition: str, variables: dict[str, str]) -> bool:
    """Evaluate a single ``{% if COND %}`` expression."""
    stripped = condition.strip()
    if not any(op in stripped for op in _SUPPORTED_OPERATORS):
        return bool(variables.get(stripped, "").strip())
    op = _first_operator(stripped)
    if op is None:
        return False
    left, right = stripped.split(op, 1)
    return _compare(variables.get(left.strip(), ""), right.strip(), op)


def _first_operator(stripped: str) -> str | None:
    """Return the first supported operator that appears in ``stripped``."""
    for op in _SUPPORTED_OPERATORS:
        if op in stripped:
            return op
    return None


def _compare(left: str, right_token: str, op: str) -> bool:
    """Compare ``left`` and ``right_token`` per ``op``.

    Equality and inequality operate on the stripped string literal so a
    quoted ``"Macho"`` compares equal to the unquoted ``Macho``.
    Ordering operators require both operands to parse as floats; if
    either fails to parse, the comparison is ``False``.
    """
    if op in ("==", "!="):
        equal = left == _strip_quotes(right_token)
        return equal if op == "==" else not equal
    pair = _try_pair(left, right_token)
    if pair is None:
        return False
    ln, rn = pair
    fn = _NUMERIC_OPS.get(op)
    return bool(fn and fn(ln, rn))


# Populate the dispatch tables after the callables are defined so the
# table reads as data at module top.
_NUMERIC_OPS.update(
    {
        ">=": lambda ln, rn: ln >= rn,
        "<=": lambda ln, rn: ln <= rn,
        ">": lambda ln, rn: ln > rn,
        "<": lambda ln, rn: ln < rn,
    }
)


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
