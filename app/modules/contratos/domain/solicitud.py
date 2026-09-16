"""Domain: variable bundle for rendering one contract template.

The render use case receives a :class:`SolicitudContrato` and uses its
``variables`` dict to substitute ``{{ ... }}`` placeholders. The
dict keys are dotted paths (``animal.nombre``, ``propietario.dni``)
that match the legacy ``RellenarContrato*`` family. The dataclass
itself is just a typed envelope around the dict; the dict is the
authoritative contract surface.

The dataclass is frozen so callers cannot mutate the variables
between grammar validation and render — that would be a race the
engine could not debug. The dataclass does NOT model "sección" or
"formato"; the legacy ``FormatoContrato`` enum and the
``RellenarContrato*`` helpers stay in the legacy layer and become a
future PR's adapter concern.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SolicitudContrato:
    """The variable bundle for one contract render.

    Attributes:
        variables: Mapping ``dotted.path -> value``. Values are
            stringified for substitution; numeric literals in
            conditions compare against the same stringified form
            (the render engine does not coerce types — the use case
            does, see ``application/render_contrato.py``).
        tipo: The :class:`TipoContrato` of the contract. Lets the
            storage adapter compute the object path and the route
            handler pick the right template without an extra lookup.
    """

    variables: dict[str, str] = field(default_factory=dict)
    tipo: str = ""


__all__ = ["SolicitudContrato"]
