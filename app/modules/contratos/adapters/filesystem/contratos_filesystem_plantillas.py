"""Filesystem-backed template source for the contratos slice (DOC-01, #1109).

Implements the CP-1
:class:`~app.modules.contratos.ports.contratos_plantilla_port.ContratosPlantillaPort`
by reading versioned plain-text bodies from
``app/modules/contratos/templates/<slug>.md``. The bodies are
versioned in the repo so they follow the same review/CI flow as the
code that consumes them. NOTE: the legacy Word mail-merge texts
(``RellenarContrato*`` family, ``Plantillas/*.docx``) have not been
ported verbatim yet — every body currently starts with the
``TEXTO PENDIENTE DE PORTAR DEL LEGACY`` marker, pinned by test, and
must be replaced with the ported legacy text in a future change
(issue #1109, ADR d-45).

The adapter owns the :class:`TipoContrato` value → ASCII-safe slug
mapping and a per-tipo cache. Every body is run through
:func:`app.modules.contratos.domain.plantilla.validar_gramatica`
on first load; a broken template file is a hard error
(``PlantillaInvalidaError``) so the operator catches the typo on
CI, not at request time. Unknown contract types and missing files
both surface as
:class:`~app.modules.contratos.domain.plantilla.PlantillaNoDisponibleError`
so the use case can translate the absence into a 404 / 422 at the
HTTP boundary.

Construction:

- ``templates_dir`` defaults to ``<repo>/app/modules/contratos/templates``
  (resolved from this file). Tests override it with a temporary
  directory so they can pin broken / missing template files
  without touching the canonical location.
- ``client`` is NOT injected: the canonical adapter reads from the
  local filesystem directly. The slice-completeness gate
  (``tests/test_slice_contratos_architecture.py``) enforces the
  import surface; this module is the only place in the slice that
  imports :mod:`pathlib`.
"""

from __future__ import annotations

from pathlib import Path

from app.modules.contratos.domain.plantilla import (
    Plantilla,
    PlantillaInvalidaError,
    PlantillaNoDisponibleError,
    validar_gramatica,
)
from app.modules.contratos.domain.tipos_contrato import TipoContrato

#: Default templates directory. Resolved from this file so the adapter
#: works regardless of the process's current working directory; tests
#: override it with a temporary directory.
_DEFAULT_TEMPLATES_DIR: Path = (
    Path(__file__).resolve().parents[2] / "templates"
)

#: ASCII-safe slug for every :class:`TipoContrato` value. Slugs are
#: derived by lower-casing and replacing whitespace with ``_`` so the
#: mapping is stable, no surprises with diacritics, and every legacy
#: value has a single canonical filename.
_SLUG_POR_TIPO: dict[str, str] = {
    TipoContrato.ENTRADA.value: "entrada",
    TipoContrato.ACOGIDA.value: "acogida",
    TipoContrato.ACOGIDA_JUDICIAL.value: "acogida_judicial",
    TipoContrato.ADOPCION.value: "adopcion",
    TipoContrato.PREADOPCION.value: "preadopcion",
    TipoContrato.CESION.value: "cesion",
    TipoContrato.RESERVA.value: "reserva",
    TipoContrato.ENTREGA.value: "entrega",
}


def _resolve_slug(tipo: str) -> str:
    """Return the ASCII slug for ``tipo`` or raise
    :class:`PlantillaNoDisponibleError`."""
    slug = _SLUG_POR_TIPO.get(tipo)
    if slug is None:
        raise PlantillaNoDisponibleError(  # noqa: TRY003 — operator-facing diagnostic
            f"no hay plantilla disponible para el tipo de contrato {tipo!r}"
        )
    return slug


def _read_template(templates_dir: Path, slug: str) -> str:
    """Read ``<templates_dir>/<slug>.md`` and return its UTF-8 body.

    Raises:
        PlantillaNoDisponibleError: when the file is absent. The
            error is the port-level contract for "no template
            available" and lets the use case translate to a 404.
    """
    path = templates_dir / f"{slug}.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PlantillaNoDisponibleError(  # noqa: TRY003 — operator-facing diagnostic
            f"no se encontro la plantilla {path.name} en {templates_dir}"
        ) from exc


class FilesystemContratosPlantillas:
    """Concrete :class:`ContratosPlantillaPort` backed by versioned
    ``.md`` files.

    The adapter is read-only by design: template bodies are versioned
    in the repo and follow the standard code review flow (no operator
    action at runtime mutates them). The per-tipo cache lives on the
    instance, so a single adapter instance reused across the request
    lifecycle amortises the file read.
    """

    def __init__(
        self,
        templates_dir: Path | str | None = None,
    ) -> None:
        """Wire the adapter to ``templates_dir`` (default: the canonical
        location under ``app/modules/contratos/templates``)."""
        if templates_dir is None:
            self._templates_dir = _DEFAULT_TEMPLATES_DIR
        else:
            self._templates_dir = Path(templates_dir)
        self._cache: dict[str, Plantilla] = {}

    @property
    def templates_dir(self) -> Path:
        """The directory the adapter reads template bodies from."""
        return self._templates_dir

    def obtener_plantilla(self, *, tipo: str) -> Plantilla:
        """Return the cached or freshly-loaded :class:`Plantilla` for
        ``tipo``."""
        cached = self._cache.get(tipo)
        if cached is not None:
            return cached
        slug = _resolve_slug(tipo)
        body = _read_template(self._templates_dir, slug)
        try:
            validar_gramatica(body)
        except PlantillaInvalidaError:
            # Surface the diagnostic verbatim: a broken template file
            # is a hard error and the operator must see the engine
            # diagnostic (line number, offending token) on CI.
            raise
        plantilla = Plantilla(tipo=tipo, cuerpo=body)
        self._cache[tipo] = plantilla
        return plantilla


__all__ = ["FilesystemContratosPlantillas"]
