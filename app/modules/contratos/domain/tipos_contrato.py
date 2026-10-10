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
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "TipoContrato",
    "tipo_contrato_codigos_del_catalogo",
]


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
