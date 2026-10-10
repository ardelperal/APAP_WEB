"""Domain: contract types supported by DOC-01 (#56 / #1109 / #1270).

The legacy does not expose a single ``TipoContrato`` enum. Two legacy
tables carry the vocabulary and they describe **different things**:

- ``TbContratosAnexos`` — the register of *signed, anexados* contracts
  per entity (one row per entity/type).  The actual set of types in
  this register is implied by the FK columns (``IDEntrada``,
  ``IDAcogida``, ``IDAdopcion``); the legacy code does not list them
  as a closed enum, and a closed enum of "8 values" was inferred by
  the web model without a backing document.  These are the **types of
  contract that get PDF-generated and stored in object storage**.
- ``TbPlantillas`` — the catalog of Word ``.docx`` *templates* used
  to generate the ParaFirma drafts.  This table is the seed for
  ``catalogos_tipos_contrato`` and the only source with P1-fidelity
  evidence.  It includes four entries that are not signed contracts
  (``Ficha de Seguimiento``, ``Ficha Sanitaria Gatos``, ``Ficha
  Sanitaria Perros``, ``Entregado a Propietario``) — they are
  *template* documents, not contract types.

The :class:`TipoContrato` ``StrEnum`` below enumerates **only the
contract types that get PDF-generated**, i.e. the four
``TbContratosAnexos``-relevant values.  The catalog remains the
broader source of templates; :func:`tipo_contrato_codigos_del_catalogo`
returns the full eight-row seed.  The subset relationship
(``TipoContrato`` ⊆ catalog seed) is asserted by the test
``test_enum_subset_of_catalog_seed`` in
``tests/test_contratos_tipos_catalog_driven.py`` — it runs on every
pytest invocation and is the guard that replaces the import-time
assert of the previous iteration (the assert triggered the S101
ruff ratchet, which is shrink-only and forbids new top-level
asserts; the test is the same coverage, with the ratchet respected).

The :func:`build_tipo_contrato_enum` factory is the dynamic-API
entry point used by tests and any caller that needs a ``StrEnum``
over a narrower or wider subset of the catalog.
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
        raise ValueError(f"catalog codigo must not be empty: {codigo!r}")  # noqa: TRY003
    # Strip accents (NFKD) so ``Adopción`` and ``Adopcion`` collide on
    # the same member name — that collision is exactly the drift #1270
    # was about, and the factory is where it would surface.
    ascii_form = unicodedata.normalize("NFKD", codigo).encode("ascii", "ignore").decode("ascii")
    name = _NORMALISE_RE.sub("_", ascii_form.strip()).upper().strip("_")
    if not name or not name.isidentifier():
        raise ValueError(  # noqa: TRY003
            f"catalog codigo {codigo!r} normalises to {name!r}, which is not a valid identifier"
        )
    return name


def build_tipo_contrato_enum(codigos: list[str]) -> type[StrEnum]:
    """Build a ``StrEnum`` whose values are the supplied ``codigos``.

    Useful for tests and for any caller that needs a ``StrEnum`` over
    a narrower or wider subset of the catalog.  The returned class is
    a *fresh* subclass of :class:`StrEnum` per call, which makes it
    safe to instantiate with different fixtures in tests.  Member
    names are the ``codigo`` uppercased and stripped of
    non-identifier characters (accents via NFKD); member values are
    the ``codigo`` themselves (preserving the Spanish spelling).

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
        raise ValueError("build_tipo_contrato_enum requires at least one codigo")  # noqa: TRY003
    seen_values: set[str] = set()
    seen_names: dict[str, str] = {}
    members: dict[str, str] = {}
    for codigo in codigos:
        if codigo in seen_values:
            raise ValueError(f"build_tipo_contrato_enum: duplicate codigo {codigo!r}")  # noqa: TRY003
        seen_values.add(codigo)
        name = _normalise(codigo)
        if name in seen_names:
            raise ValueError(  # noqa: TRY003
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
    from the ``codigo`` column.  The catalog is the *template* catalog
    (``TbPlantillas``), not the *signed-contract* register
    (``TbContratosAnexos``); see the module docstring for why the
    enum is a subset of the catalog.
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


class TipoContrato(StrEnum):
    """Contract types whose PDF the slice generates and stores.

    Members cover the four ``TbContratosAnexos``-relevant values
    (signed contracts that get anexados per entity).  The other four
    catalog ``codigo`` rows (``Ficha de Seguimiento``,
    ``Ficha Sanitaria Gatos``, ``Ficha Sanitaria Perros``,
    ``Entregado a Propietario``) are template documents, not signed
    contracts; they live in the catalog so the future template engine
    can resolve them, but they are intentionally absent from this
    enum.  The subset relationship is asserted in
    ``tests/test_contratos_tipos_catalog_driven.py``
    (``test_enum_subset_of_catalog_seed``).
    """

    ACOGIDA = "Acogida"
    ADOPCION = "Adopción"
    CESION = "Cesión"
    ENTRADA = "Entrada"
