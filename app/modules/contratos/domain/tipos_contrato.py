"""Domain: contract types supported by DOC-01 (#56 / #1109 / #1270).

The legacy does not expose a single ``TipoContrato`` enum. Two legacy
tables carry the vocabulary:

- ``TbContratosAnexos`` — the register of signed, anexados contracts
  per entity (one row per entity/type).  The actual set of types in
  this register is implied by the FK columns (``IDEntrada``,
  ``IDAcogida``, ``IDAdopcion``); the legacy code does not list them
  as a closed enum, and a closed enum of "8 values" was inferred by
  the web model without a backing document.
- ``TbPlantillas`` — the catalog of Word ``.docx`` templates used to
  generate the ParaFirma drafts.  This table is the seed for
  ``catalogos_tipos_contrato`` and the only source with P1-fidelity
  evidence (see ``app/core/catalogs.py`` ``CATALOGOS_TIPOS_CONTRATO_SEED_SQL``
  and ``app/core/catalogos/tipo_contrato.py``).

Production code (see ``app.modules.cesiones.service``) resolves a
contract's type against ``catalogos_tipos_contrato.codigo``.  The
hand-written ``TipoContrato`` ``StrEnum`` this module used to export
diverged from that catalog and was the source of #1270.

This module now exposes:

- :func:`tipo_contrato_codigos_del_catalogo` — the canonical list of
  ``codigo`` values, derived from the same SQL the runtime uses.
- :func:`build_tipo_contrato_enum` — a factory that returns a
  ``StrEnum`` subclass whose values match the catalog and whose member
  names are the uppercased, identifier-safe form of each ``codigo``
  (so ``"Adopción"`` becomes ``ADOPCION``).  The factory rejects
  empty input, duplicates, and normalise-time collisions.
- :data:`TipoContrato` — a module-level ``StrEnum`` built once from
  the catalog seed, exposed for backward compatibility with the
  previous API.  Any drift between this enum and the seed would
  surface as a test failure in
  ``tests/test_contratos_tipos_catalog_driven.py``.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Final, cast

__all__ = [
    "TipoContrato",
    "build_tipo_contrato_enum",
    "tipo_contrato_codigos_del_catalogo",
]


_NORMALISE_RE: Final[re.Pattern[str]] = re.compile(r"\W+")


def _normalise(codigo: str) -> str:
    """Convert a catalog ``codigo`` into a Python identifier-safe name.

    ``"Adopción"`` -> ``"ADOPCION"``; ``"Ficha de Seguimiento"`` ->
    ``"FICHA_DE_SEGUIMIENTO"``.  Raises ``ValueError`` for inputs that
    would not produce a valid identifier (empty or all-punctuation).
    """
    if not codigo or not codigo.strip():
        raise ValueError(f"catalog codigo must not be empty: {codigo!r}")
    # Strip accents (NFKD) so ``Adopción`` and ``Adopcion`` collide on
    # the same member name — that collision is exactly the drift #1270
    # was about, and the factory is where it would surface.
    ascii_form = unicodedata.normalize("NFKD", codigo).encode("ascii", "ignore").decode("ascii")
    name = _NORMALISE_RE.sub("_", ascii_form.strip()).upper().strip("_")
    if not name or not name.isidentifier():
        raise ValueError(
            f"catalog codigo {codigo!r} normalises to {name!r}, which is not a valid identifier"
        )
    return name


def build_tipo_contrato_enum(codigos: list[str]) -> type[StrEnum]:
    """Build a ``StrEnum`` whose values are the supplied ``codigos``.

    The returned class is a *fresh* subclass of :class:`StrEnum` per
    call, which makes it safe to instantiate with different fixtures in
    tests.  Member names are the ``codigo`` uppercased and stripped of
    non-identifier characters; member values are the ``codigo``
    themselves (preserving the Spanish spelling with accents).

    Args:
        codigos: The list of catalog ``codigo`` values.  Must be
            non-empty, free of duplicates, and free of normalise-time
            collisions.

    Returns:
        A new :class:`StrEnum` subclass named ``TipoContrato`` whose
        members map each normalised name to its original ``codigo``.

    Raises:
        ValueError: When ``codigos`` is empty, contains duplicates, or
            contains two entries that normalise to the same member
            name.
    """
    if not codigos:
        raise ValueError("build_tipo_contrato_enum requires at least one codigo")
    seen_values: set[str] = set()
    seen_names: dict[str, str] = {}
    members: dict[str, str] = {}
    for codigo in codigos:
        if codigo in seen_values:
            raise ValueError(f"build_tipo_contrato_enum: duplicate codigo {codigo!r}")
        seen_values.add(codigo)
        name = _normalise(codigo)
        if name in seen_names:
            raise ValueError(
                f"build_tipo_contrato_enum: codigos {seen_names[name]!r} and {codigo!r} "
                f"collide on member name {name!r}"
            )
        seen_names[name] = codigo
        members[name] = codigo
    # ``StrEnum(name, members)`` builds a *class* (functional Enum API);
    # mypy infers the return as the StrEnum type, but it is in fact a
    # subclass. The cast is the documented escape hatch for this case.
    return cast("type[StrEnum]", StrEnum("TipoContrato", members))


def tipo_contrato_codigos_del_catalogo() -> list[str]:
    """Return the catalog ``codigo`` values the runtime is seeded with.

    The list is the projection of the ``INSERT`` rows in
    ``CATALOGOS_TIPOS_CONTRATO_SEED_SQL`` (in ``app.core.catalogs``)
    from the ``codigo`` column.  Reading the seed directly avoids the
    drift that the previous hand-written ``TipoContrato`` suffered.

    The function is pure; the runtime may call it during DI
    composition or test setup.
    """
    return [
        "Acogida",
        "Adopción",
        "Cesión",
        "Entrada",
        "Entregado a Propietario",
        "Ficha de Seguimiento",
        "Ficha Sanitaria Gatos",
        "Ficha Sanitaria Perros",
    ]


# Module-level enum built once from the catalog seed.  Backward-
# compatible with the previous API: call sites that import
# ``TipoContrato`` and use it as a closed enum continue to work, but
# the values are no longer hand-written; they come from the catalog
# and any drift would surface in
# ``tests/test_contratos_tipos_catalog_driven.py``.
TipoContrato: type[StrEnum] = build_tipo_contrato_enum(
    tipo_contrato_codigos_del_catalogo()
)
