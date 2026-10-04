"""Template source port for the contratos slice (DOC-01 CP1, issue #1109).

The render use case (``application/render_contrato.py``, CP-1) needs
a :class:`~app.modules.contratos.domain.plantilla.Plantilla` per
:class:`~app.modules.contratos.domain.tipos_contrato.TipoContrato`.
The source of that template is intentionally kept out of the
domain — the legacy Word mail-merge texts live in `.docx` files
on the workstation of the Access operator, the modern port loads
versioned plain-text bodies from
``app/modules/contratos/templates/<slug>.md``, and a future adapter
could fetch them from an external corpus. This Protocol is the
adapter-agnostic surface the use case calls.

The Protocol takes the contract type as a plain string
(``TipoContrato`` is a ``StrEnum`` so its values compare equal to
their string form) and returns a fully populated
:class:`Plantilla`. When the source has no body for the requested
type — unknown type, missing file, or slug mapping without a
backing file — the port raises
:class:`~app.modules.contratos.domain.plantilla.PlantillaNoDisponibleError`
so the use case can translate that to a 404 / 422 at the HTTP
boundary without leaking transport vocabulary.

The template body is loaded once per :class:`TipoContrato` and
reused for every subsequent call (the bodies are versioned files
that change only through Git); the cache lives in the adapter
implementation, not in this Protocol.

No transport import is allowed here — the architectural pin test
(``tests/test_slice_contratos_architecture.py``, AGENTS.md §33.4)
enforces this.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.modules.contratos.domain.plantilla import Plantilla


@runtime_checkable
class ContratosPlantillaPort(Protocol):
    """Backend-agnostic source of contract template bodies.

    The :class:`TipoContrato` value drives both the body's
    metadata (``Plantilla.tipo``) and the filename under the
    adapter's source directory; the port is a thin facade that
    keeps the engine domain-vocabulary-only.
    """

    def obtener_plantilla(self, *, tipo: str) -> Plantilla:
        """Return the :class:`Plantilla` for the given contract ``tipo``.

        ``tipo`` is a :class:`TipoContrato` value passed as its
        string form (``"Adopcion"``, ``"Acogida Judicial"``, …).
        The returned :class:`Plantilla` carries the same ``tipo``
        plus the loaded body — the engine (``render_contrato``) is
        the only consumer of the body and assumes it has already
        passed :func:`validar_gramatica`.

        Raises:
            PlantillaNoDisponibleError: when no template body is
                available for ``tipo`` (unknown type, missing
                file, or slug mapping without a backing file).
        """


__all__ = ["ContratosPlantillaPort"]
