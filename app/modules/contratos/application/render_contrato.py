"""Use case: render one contract template (DOC-01 PR 1).

The render use case is the only public surface that touches a
:class:`Plantilla`. It validates the grammar, tokenises the body,
substitutes placeholders against the request variables, and resolves
conditionals. The output is plain text — the PDF adapter in PR 2
turns that text into a PDF; the storage adapter in PR 2 writes the
PDF to object storage.

Design notes:

- Pure: no I/O, no globals, no ``print``. The route layer (PR 3)
  delegates here and never holds a reference to the engine.
- Strict on grammar: a broken template raises
  :class:`PlantillaInvalida` BEFORE tokenising so the operator gets
  the same diagnostic at validation time and at render time.
- Strict on variable substitution: a missing placeholder renders as
  the literal ``{{ path }}`` (NOT silent omission) so the operator
  sees which field the legacy source forgot to provide.
- The tokeniser lives in :mod:`render_tokenize` and the condition
  evaluator in :mod:`render_condition` to keep the mutation-site
  budget per file under 250 (rule §33.4 + AGENTS.md §21).
"""

from __future__ import annotations

from app.modules.contratos.application.render_condition import (
    evaluate_condition,
    substitute,
)
from app.modules.contratos.application.render_tokenize import Token, tokenizar
from app.modules.contratos.domain.plantilla import (
    Plantilla,
    PlantillaInvalida,
    validar_gramatica,
)
from app.modules.contratos.domain.solicitud import SolicitudContrato


def render_contrato(plantilla: Plantilla, solicitud: SolicitudContrato) -> str:
    """Render ``plantilla`` against ``solicitud`` and return the body text."""
    validar_gramatica(plantilla.cuerpo)
    return _render_tokens(tokenizar(plantilla.cuerpo), solicitud.variables)


def _render_tokens(tokens: list[Token], variables: dict[str, str]) -> str:
    """Walk ``tokens`` and return the rendered string.

    ``{% if %}`` blocks are tracked by a depth counter
    (``skip_depth``): opening an ``if`` inside an already-skipped
    block increments the counter, and only ``{% endif %}`` decrements
    it back to zero, restoring regular expansion.
    """
    output: list[str] = []
    skip_depth = 0
    for token in tokens:
        skip_depth, chunk = _step(token, variables, skip_depth)
        if chunk:
            output.append(chunk)
    return "".join(output)


def _step(token: Token, variables: dict[str, str], skip_depth: int) -> tuple[int, str]:
    """Advance the walker by one token; return ``(new_skip, chunk)``."""
    if token.kind == "if_open":
        return _step_open(token.text, variables, skip_depth)
    if token.kind == "if_close":
        return _step_close(skip_depth)
    if skip_depth > 0:
        return skip_depth, ""
    return skip_depth, _render_token(token, variables)


def _step_open(condition: str, variables: dict[str, str], skip_depth: int) -> tuple[int, str]:
    """Enter an ``{% if %}`` block; bump depth if it's truthy-false."""
    if skip_depth > 0 or not evaluate_condition(condition, variables):
        return skip_depth + 1, ""
    return skip_depth, ""


def _step_close(skip_depth: int) -> tuple[int, str]:
    """Exit an ``{% endif %}`` block; decrement depth if nested."""
    if skip_depth > 0:
        return skip_depth - 1, ""
    return skip_depth, ""


def _render_token(token: Token, variables: dict[str, str]) -> str:
    """Render a single non-control token into the output buffer."""
    if token.kind == "text":
        return token.text
    if token.kind == "placeholder":
        return substitute(token.text, variables)
    return ""  # pragma: no cover — only text/placeholder reach here


# Re-export so legacy callers that imported these helpers from
# render_contrato keep working without churn.
__all__ = [
    "Plantilla",
    "PlantillaInvalida",
    "render_contrato",
    "validar_gramatica",
]
