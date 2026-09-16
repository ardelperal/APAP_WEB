"""Template tokeniser for the contratos slice (DOC-01 PR 1).

Splits a template body into a flat list of
:class:`_Token` values for the render walk to consume. The
tokeniser assumes the body has already passed
:func:`app.modules.contratos.domain.plantilla.validar_gramatica`; the
two together form the parser half of the engine.

The tokeniser raises :class:`PlantillaInvalida` only on token-shape
errors (``{{`` / ``{%`` without the matching closer, or an unknown
tag). Grammar violations — unbalanced ``{% if %}`` blocks,
non-placeholder left operands — surface during validation so the
operator gets the diagnostic there, not at render time.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.contratos.domain.plantilla import PlantillaInvalida


@dataclass(frozen=True, slots=True)
class _Token:
    """A single token in the parsed template body.

    Private (``_`` prefix) — callers must use
    :func:`render_contrato` instead of importing it. The dataclass
    lives in its own module to keep this file under the mutation-site
    budget while keeping the public surface in
    ``render_contrato.py`` minimal.
    """

    kind: str  # "text" | "placeholder" | "if_open" | "if_close"
    text: str  # raw text for "text"; variable path for "placeholder"; condition for "if_open"
    line: int  # 1-indexed, for diagnostics


def tokenizar(cuerpo: str) -> list[_Token]:
    """Tokenise ``cuerpo`` into a stream of :class:`_Token` values.

    The grammar is intentionally narrow (no escaping, no nesting
    beyond simple ``{% if %}`` / ``{% endif %}``). The render use
    case rejects any grammar violation at validation time so the
    tokeniser can assume a well-formed body.
    """
    tokens: list[_Token] = []
    line = 1
    pos = 0
    while pos < len(cuerpo):
        next_open = cuerpo.find("{{", pos)
        next_tag = cuerpo.find("{%", pos)
        candidates = [x for x in (next_open, next_tag) if x != -1]
        candidate = min(candidates) if candidates else len(cuerpo)
        if candidate > pos:
            chunk = cuerpo[pos:candidate]
            line += chunk.count("\n")
            tokens.append(_Token(kind="text", text=chunk, line=line))
        if candidate == len(cuerpo):
            break
        if candidate == next_open:
            end = cuerpo.find("}}", candidate + 2)
            if end == -1:
                raise PlantillaInvalida(  # noqa: TRY003
                    f"plantilla invalida: '{{{{' sin '}}}}' en linea {line}"
                )
            path = cuerpo[candidate + 2:end].strip()
            tokens.append(_Token(kind="placeholder", text=path, line=line))
            pos = end + 2
            continue
        # ``{% ... %}``
        end = cuerpo.find("%}", candidate + 2)
        if end == -1:
            raise PlantillaInvalida(  # noqa: TRY003
                f"plantilla invalida: '{{%' sin '%}}' en linea {line}"
            )
        tag_body = cuerpo[candidate + 2:end].strip()
        if tag_body.startswith("if "):
            condition = tag_body[3:].strip()
            tokens.append(_Token(kind="if_open", text=condition, line=line))
        elif tag_body == "endif":
            tokens.append(_Token(kind="if_close", text="", line=line))
        else:
            raise PlantillaInvalida(  # noqa: TRY003
                f"plantilla invalida: etiqueta desconocida {tag_body!r} "
                f"en linea {line}"
            )
        pos = end + 2
    return tokens


__all__ = ["_Token", "tokenizar"]
