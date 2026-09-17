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
  :class:`PlantillaInvalidaError` BEFORE tokenising so the operator gets
  the same diagnostic at validation time and at render time.
- Strict on variable substitution: a missing placeholder renders as
  the literal ``{{ path }}`` (NOT silent omission) so the operator
  sees which field the legacy source forgot to provide.
- The tokeniser lives in :mod:`render_tokenize` and the condition
  evaluator in :mod:`render_condition` to keep the mutation-site
  budget per file under 250 (rule §33.4 + AGENTS.md §21).

Complexity note: the walk is a small dispatch table that delegates
to per-token-kind helpers; ``render_contrato`` itself carries only
the orchestration branching.
"""

from __future__ import annotations

from collections.abc import Callable

from app.modules.contratos.application.render_condition import (
    evaluate_condition,
    substitute,
)
from app.modules.contratos.application.render_tokenize import (
    KIND_IF_CLOSE,
    KIND_IF_OPEN,
    KIND_PLACEHOLDER,
    KIND_TEXT,
    _Token,
    tokenizar,
)
from app.modules.contratos.domain.plantilla import (
    Plantilla,
    PlantillaInvalidaError,
    validar_gramatica,
)
from app.modules.contratos.domain.solicitud import SolicitudContrato


def _render_text(token: _Token, _state: _WalkState) -> None:
    """Append a ``text`` token's body to the output buffer."""
    _state.output.append(token.text)


def _render_placeholder(token: _Token, state: _WalkState) -> None:
    """Append the resolved placeholder (or its literal fallback)."""
    state.output.append(substitute(token.text, state.variables))


def _open_conditional(token: _Token, state: _WalkState) -> None:
    """Evaluate the ``{% if %}`` guard; track whether to skip the block."""
    if state.skip_until_close > 0:
        state.skip_until_close += 1
        return
    truthy = evaluate_condition(token.text, state.variables)
    if not truthy:
        state.skip_until_close = 1


def _close_conditional(_token: _Token, state: _WalkState) -> None:
    """Exit the deepest ``{% if %}`` block currently being skipped."""
    if state.skip_until_close > 0:
        state.skip_until_close -= 1


class _WalkState:
    """Mutable state threaded through the token dispatch table.

    Kept as a small class so the orchestration function stays free of
    intermediate variables and each per-kind helper reads/writes
    only what it needs.
    """

    __slots__ = ("output", "skip_until_close", "variables")

    def __init__(self, variables: dict[str, str]) -> None:
        self.output: list[str] = []
        self.skip_until_close = 0
        self.variables = variables


#: Per-kind dispatch table. Each entry receives ``(token, state)``
#: and mutates ``state`` in place. ``text``/``placeholder`` append;
#: ``if_open``/``if_close`` adjust the skip counter.
_DISPATCH: dict[str, Callable[[_Token, _WalkState], None]] = {
    KIND_TEXT: _render_text,
    KIND_PLACEHOLDER: _render_placeholder,
    KIND_IF_OPEN: _open_conditional,
    KIND_IF_CLOSE: _close_conditional,
}


def render_contrato(plantilla: Plantilla, solicitud: SolicitudContrato) -> str:
    """Render ``plantilla`` against ``solicitud`` and return the body text.

    Order of operations:

    1. Validate the grammar (:func:`validar_gramatica`).
    2. Tokenise the body (:func:`tokenizar`).
    3. Walk the token stream through the dispatch table, expanding
       ``{% if %}`` blocks per the condition evaluation and
       substituting placeholders against the variable bundle.

    The return value is plain text. PDF generation is the storage
    adapter's concern (PR 2).
    """
    validar_gramatica(plantilla.cuerpo)
    tokens = tokenizar(plantilla.cuerpo)
    state = _WalkState(solicitud.variables)
    for token in tokens:
        if state.skip_until_close > 0 and token.kind not in (
            KIND_IF_OPEN,
            KIND_IF_CLOSE,
        ):
            continue
        handler = _DISPATCH.get(token.kind)
        if handler is not None:
            handler(token, state)
    return "".join(state.output)


# Re-export so legacy callers that imported these helpers from
# render_contrato keep working without churn.
__all__ = [
    "Plantilla",
    "PlantillaInvalidaError",
    "render_contrato",
    "validar_gramatica",
]
