"""Template tokeniser for the contratos slice (DOC-01 PR 1).

Splits a template body into a flat list of
:class:`Token` values for the render walk to consume. The
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
class Token:
    """A single token in the parsed template body.

    Public so callers writing custom render walks can type their
    helpers against :class:`Token` rather than the private
    implementation detail. The dataclass lives in its own module to
    keep this file under the mutation-site budget while keeping the
    public surface in ``render_contrato.py`` minimal.
    """

    kind: str  # "text" | "placeholder" | "if_open" | "if_close"
    text: str  # raw text for "text"; variable path for "placeholder"; condition for "if_open"
    line: int  # 1-indexed, for diagnostics


def tokenizar(cuerpo: str) -> list[Token]:
    """Tokenise ``cuerpo`` into a stream of :class:`Token` values.

    The grammar is intentionally narrow (no escaping, no nesting
    beyond simple ``{% if %}`` / ``{% endif %}``). The render use
    case rejects any grammar violation at validation time so the
    tokeniser can assume a well-formed body.
    """
    tokens: list[Token] = []
    line, pos = 1, 0
    while pos < len(cuerpo):
        candidate = _next_boundary(cuerpo, pos)
        if candidate > pos:
            line = _emit_text(tokens, cuerpo[pos:candidate], line)
        if candidate == len(cuerpo):
            break
        pos = _emit_at(tokens, cuerpo, candidate, line)
    return tokens


def _next_boundary(cuerpo: str, pos: int) -> int:
    """Return the index of the next ``{{`` / ``{%`` opener, or ``len(cuerpo)``."""
    candidates = [x for x in (cuerpo.find("{{", pos), cuerpo.find("{%", pos)) if x != -1]
    return min(candidates) if candidates else len(cuerpo)


def _emit_text(tokens: list[Token], chunk: str, line: int) -> int:
    """Append a text token and return the updated line count."""
    tokens.append(Token(kind="text", text=chunk, line=line))
    return line + chunk.count("\n")


def _emit_at(tokens: list[Token], cuerpo: str, candidate: int, line: int) -> int:
    """Emit the token at ``candidate`` and return the new scan position."""
    if cuerpo[candidate:candidate + 2] == "{{":
        return _emit_placeholder(tokens, cuerpo, candidate, line)
    return _emit_tag(tokens, cuerpo, candidate, line)


def _emit_placeholder(
    tokens: list[Token], cuerpo: str, candidate: int, line: int
) -> int:
    """Tokenise ``{{ path }}`` at ``candidate``."""
    end = cuerpo.find("}}", candidate + 2)
    if end == -1:
        raise PlantillaInvalida(  # noqa: TRY003
            f"plantilla invalida: '{{{{' sin '}}}}' en linea {line}"
        )
    tokens.append(Token(kind="placeholder", text=cuerpo[candidate + 2:end].strip(), line=line))
    return end + 2


def _emit_tag(tokens: list[Token], cuerpo: str, candidate: int, line: int) -> int:
    """Tokenise ``{% if COND %}`` or ``{% endif %}`` at ``candidate``."""
    end = cuerpo.find("%}", candidate + 2)
    if end == -1:
        raise PlantillaInvalida(  # noqa: TRY003
            f"plantilla invalida: '{{%' sin '%}}' en linea {line}"
        )
    kind, text = _classify_tag(cuerpo[candidate + 2:end].strip(), line)
    tokens.append(Token(kind=kind, text=text, line=line))
    return end + 2


def _classify_tag(tag_body: str, line: int) -> tuple[str, str]:
    """Translate the raw ``{%...%}`` body into ``(kind, text)``."""
    if tag_body.startswith("if "):
        return "if_open", tag_body[3:].strip()
    if tag_body == "endif":
        return "if_close", ""
    raise PlantillaInvalida(  # noqa: TRY003
        f"plantilla invalida: etiqueta desconocida {tag_body!r} "
        f"en linea {line}"
    )


__all__ = ["Token", "tokenizar"]
