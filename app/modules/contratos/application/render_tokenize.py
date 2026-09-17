"""Template tokeniser for the contratos slice (DOC-01 PR 1).

Splits a template body into a flat list of :class:`_Token` values for
the render walk to consume. The tokeniser assumes the body has
already passed :func:`app.modules.contratos.domain.plantilla
.validar_gramatica`; the two together form the parser half of the
engine.

The tokeniser raises :class:`PlantillaInvalidaError` only on token-shape
errors (``{{`` / ``{%`` without the matching closer, or an unknown
tag). Grammar violations — unbalanced ``{% if %}`` blocks,
non-placeholder left operands — surface during validation so the
operator gets the diagnostic there, not at render time.

Complexity note: the loop is intentionally flat. Each branch is a
helper so the dispatch table never grows past a single
``if``/``elif``/``else`` chain, keeping the cyclomatic complexity
under the CRAP-grade-A ceiling (rule §19, AGENTS.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.contratos.domain.plantilla import PlantillaInvalidaError

#: Marker kinds emitted by the tokeniser.
KIND_TEXT = "text"
KIND_PLACEHOLDER = "placeholder"
KIND_IF_OPEN = "if_open"
KIND_IF_CLOSE = "if_close"


@dataclass(frozen=True, slots=True)
class _Token:
    """A single token in the parsed template body.

    Private (``_`` prefix) — callers must use
    :func:`render_contrato` instead of importing it. The dataclass
    lives in its own module to keep this file under the mutation-site
    budget while keeping the public surface in
    ``render_contrato.py`` minimal.
    """

    kind: str  # one of KIND_TEXT, KIND_PLACEHOLDER, KIND_IF_OPEN, KIND_IF_CLOSE
    text: str  # raw text for text; variable path for placeholder; condition for if_open
    line: int  # 1-indexed, for diagnostics


def _find_marker(cuerpo: str, pos: int) -> tuple[int, str]:
    """Return ``(position, marker_kind)`` of the next ``{{`` or ``{%``.

    ``marker_kind`` is one of ``"{{"`` / ``"{%"`` / ``""`` (EOF).
    When the body has no further marker the position equals its
    length so the caller can emit the trailing text chunk.
    """
    next_open = cuerpo.find("{{", pos)
    next_tag = cuerpo.find("{%", pos)
    candidates = (p for p in (next_open, next_tag) if p != -1)
    position = min(candidates, default=len(cuerpo))
    if position == next_open:
        return position, "{{"
    if position == next_tag:
        return position, "{%"
    return position, ""


def _emit_text_chunk(cuerpo: str, start: int, end: int, line: int) -> tuple[_Token, int]:
    """Emit the text token spanning ``cuerpo[start:end]`` and return next line.

    Carriage returns in the chunk advance the line counter so the
    next token's diagnostic line number is correct.
    """
    chunk = cuerpo[start:end]
    next_line = line + chunk.count("\n")
    return _Token(kind=KIND_TEXT, text=chunk, line=line), next_line


def _emit_placeholder(cuerpo: str, marker_pos: int, line: int) -> tuple[_Token | None, int]:
    """Emit a placeholder token; raise on missing ``}}`` closer.

    Returns ``(token, next_pos)``. ``token is None`` when the body
    is exhausted before the closer is found; the caller surfaces the
    diagnostic with the current ``line``.
    """
    end = cuerpo.find("}}", marker_pos + 2)
    if end == -1:
        raise PlantillaInvalidaError(  # noqa: TRY003
            f"plantilla invalida: '{{{{' sin '}}}}' en linea {line}"
        )
    path = cuerpo[marker_pos + 2 : end].strip()
    return _Token(kind=KIND_PLACEHOLDER, text=path, line=line), end + 2


def _emit_tag(cuerpo: str, marker_pos: int, line: int) -> tuple[_Token | None, int]:
    """Emit an ``{% if %}`` / ``{% endif %}`` token; raise on shape errors.

    Returns ``(token, next_pos)``. ``token is None`` when the body
    is exhausted before the ``%}`` closer is found.
    """
    end = cuerpo.find("%}", marker_pos + 2)
    if end == -1:
        raise PlantillaInvalidaError(  # noqa: TRY003
            f"plantilla invalida: '{{%' sin '%}}' en linea {line}"
        )
    tag_body = cuerpo[marker_pos + 2 : end].strip()
    token = _classify_tag(tag_body, line)
    return token, end + 2


def _classify_tag(tag_body: str, line: int) -> _Token | None:
    """Translate a stripped tag body into the matching token or raise."""
    if tag_body.startswith("if "):
        return _Token(kind=KIND_IF_OPEN, text=tag_body[3:].strip(), line=line)
    if tag_body == "endif":
        return _Token(kind=KIND_IF_CLOSE, text="", line=line)
    raise PlantillaInvalidaError(  # noqa: TRY003
        f"plantilla invalida: etiqueta desconocida {tag_body!r} en linea {line}"
    )


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
        marker_pos, marker = _find_marker(cuerpo, pos)
        line = _append_text_chunk(cuerpo, pos, marker_pos, line, tokens)
        if marker == "":
            break
        pos = _advance_marker(cuerpo, marker_pos, marker, line, tokens)
    return tokens


def _append_text_chunk(
    cuerpo: str,
    start: int,
    end: int,
    line: int,
    tokens: list[_Token],
) -> int:
    """Emit the text chunk ``cuerpo[start:end]`` and return next line."""
    if end <= start:
        return line
    chunk_token, next_line = _emit_text_chunk(cuerpo, start, end, line)
    tokens.append(chunk_token)
    return next_line


def _advance_marker(
    cuerpo: str,
    marker_pos: int,
    marker: str,
    line: int,
    tokens: list[_Token],
) -> int:
    """Emit the marker token and return the next ``pos`` past it."""
    if marker == "{{":
        token, pos = _emit_placeholder(cuerpo, marker_pos, line)
    else:
        token, pos = _emit_tag(cuerpo, marker_pos, line)
    if token is not None:
        tokens.append(token)
    return pos


__all__ = ["_Token", "tokenizar"]
