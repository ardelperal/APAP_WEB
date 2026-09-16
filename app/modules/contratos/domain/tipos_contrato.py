"""Domain: the eight contract types supported by DOC-01 (#56).

Mirrors the legacy ``TbContratosAnexos`` enum that the legacy
``RellenarContrato*`` family uses (see ``docs/legacy-signed-contract-flow.md``).
Eight values, exact spellings of the legacy keys.

Each value is the natural identifier of the contract type as it
appears in ``TbContratosAnexos`` and in the template filename under
``legacy/templates/contratos/``. The render use case keys template
selection off this enum; the storage adapter keys the object path off
this enum; the route handler renders a human label off this enum.

Adding a value is a breaking change to the schema (new contract type
requires new template + new DB enum value). Removing a value is a
breaking change to the storage adapter (old object paths become
orphans). The exhaustive list below is the single source of truth.
"""

from __future__ import annotations

from enum import StrEnum


class TipoContrato(StrEnum):
    """The eight contract types supported by DOC-01.

    Values mirror the legacy ``TbContratosAnexos`` enum
    (``docs/legacy-signed-contract-flow.md`` §4). ``str`` mix-in gives
    JSON-friendly serialisation and direct equality with the legacy
    string keys.
    """

    ENTRADA = "Entrada"
    ACOGIDA = "Acogida"
    ACOGIDA_JUDICIAL = "Acogida Judicial"
    ADOPCION = "Adopcion"
    PREADOPCION = "PreAdopcion"
    CESION = "Cesion"
    RESERVA = "Reserva"
    ENTREGA = "Entrega"


__all__ = ["TipoContrato"]
