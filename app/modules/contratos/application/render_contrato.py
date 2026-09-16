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
from app.modules.contratos.application.render_tokenize import tokenizar
from app.modules.contratos.domain.plantilla import (
    Plantilla,
    PlantillaInvalida,
    validar_gramatica,
)
from app.modules.contratos.domain.solicitud import SolicitudContrato


def render_contrato(plantilla: Plantilla, solicitud: SolicitudContrato) -> str:
    """Render ``plantilla`` against ``solicitud`` and return the body text.

    Order of operations:

    1. Validate the grammar (:func:`validar_gramatica`).
    2. Tokenise the body (:func:`tokenizar`).
    3. Walk the token stream, expanding ``{% if %}`` blocks per the
       condition evaluation and substituting placeholders against
       the variable bundle.

    The return value is plain text. PDF generation is the storage
    adapter's concern (PR 2).
    """
    validar_gramatica(plantilla.cuerpo)
    tokens = tokenizar(plantilla.cuerpo)
    output: list[str] = []
    skip_until_close = 0
    for token in tokens:
        if token.kind == "if_open":
            if skip_until_close > 0:
                skip_until_close += 1
                continue
            if not evaluate_condition(token.text, solicitud.variables):
                skip_until_close = 1
            continue
        if token.kind == "if_close":
            if skip_until_close > 0:
                skip_until_close -= 1
            continue
        if skip_until_close > 0:
            continue
        if token.kind == "text":
            output.append(token.text)
        elif token.kind == "placeholder":
            output.append(substitute(token.text, solicitud.variables))
    return "".join(output)


# Re-export so legacy callers that imported these helpers from
# render_contrato keep working without churn.
__all__ = [
    "Plantilla",
    "PlantillaInvalida",
    "render_contrato",
    "validar_gramatica",
]
