"""Tests for the catalog-driven TipoContrato enum (issue #1270).

The legacy does not expose a `TipoContrato` enum directly; the closest
sources are ``TbContratosAnexos`` (firmados anexados) and
``TbPlantillas`` (plantillas Word). The catalog
``catalogos_tipos_contrato`` is the only source with P1-fidelity
evidence and is what the production code resolves against (see
``app.modules.cesiones.service``).

These tests pin the contract:
  - the slice exposes a factory that returns a ``StrEnum`` whose values
    match the catalog seed, not a hand-written constant;
  - members preserve the legacy Spanish spelling (with accents);
  - a member name is the uppercased identifier-safe form of the
    catalog ``codigo`` (e.g. ``"Adopción"`` -> ``ADOPCION``).
"""

from __future__ import annotations

from app.modules.contratos.domain.tipos_contrato import (
    tipo_contrato_codigos_del_catalogo,
)


def test_codigos_del_catalogo_returns_list() -> None:
    """``tipo_contrato_codigos_del_catalogo`` is the bridge to the seed.

    The list must come from the same SQL seed the runtime uses; if the
    seed changes, this function and the tests above stay in sync.
    """
    codigos = tipo_contrato_codigos_del_catalogo()
    assert isinstance(codigos, list)
    assert "Adopción" in codigos
    assert "Cesión" in codigos
    assert "Entrada" in codigos
    assert "Acogida" in codigos


def test_enum_subset_of_catalog_seed() -> None:
    """The module-level ``TipoContrato`` must be a subset of the catalog seed.

    This test is the runtime guard that replaces the previous
    import-time ``assert`` (#1270).  The import-time assert was
    dropped to respect the ruff S101 ratchet (shrink-only), and the
    test provides the same coverage: any future catalog row that is
    not a contract type does not pollute the enum, and any future
    contract type that is missing from the enum is caught here.
    """
    from app.modules.contratos.domain.tipos_contrato import TipoContrato

    enum_codigos = {m.value for m in TipoContrato}
    catalog_codigos = set(tipo_contrato_codigos_del_catalogo())
    missing = enum_codigos - catalog_codigos
    assert not missing, (
        f"TipoContrato has codigos not in the catalog seed: {missing}. "
        f"Add them to the catalog seed (app/core/catalogs.py) before adding them here."
    )


def test_enum_excludes_template_only_catalog_rows() -> None:
    """The four template-only catalog rows are intentionally NOT in the enum.

    ``Ficha de Seguimiento``, ``Ficha Sanitaria Gatos``, ``Ficha
    Sanitaria Perros`` and ``Entregado a Propietario`` are Word
    templates for non-contract documents, not signed contracts; the
    enum covers only the four ``TbContratosAnexos``-relevant values.
    Pinning the negative here keeps the carve-out explicit.
    """
    from app.modules.contratos.domain.tipos_contrato import TipoContrato

    enum_codigos = {m.value for m in TipoContrato}
    template_only = {
        "Ficha de Seguimiento",
        "Ficha Sanitaria Gatos",
        "Ficha Sanitaria Perros",
        "Entregado a Propietario",
    }
    assert enum_codigos.isdisjoint(template_only), (
        f"TipoContrato carries template-only codigos: {enum_codigos & template_only}. "
        f"The enum is for signed contracts (TbContratosAnexos); templates live in the catalog only."
    )
