"""11-cases regression test for the derivation engine
(PR 6/6, T6.5).

The 11 parametrized cases are the canonical enumeration from
``lifecycle-state-resolver-extraction.md`` section 4 (the discovery
doc the PR 2 derivation engine was built against). This regression
test freezes the contract: a future refactor of
``derive_estado_actual_animal`` MUST keep producing the same state
for each case.

This is the line of defense if someone accidentally drops a branch
from the priority cascade.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.local_backend.db import LocalPostgresExecutor

# --- helpers --------------------------------------------------------------


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _make_web_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> InsForgeClient:
    return InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(handler),
    )


def _capture_prompt(responses: list[str]) -> Callable[[str], str]:
    """Build a list-driven prompt reader."""

    def _read(_prompt: str) -> str:
        if not responses:
            raise AssertionError("prompt called more times than test expected")
        return responses.pop(0)

    return _read


def _needs_review_row(
    *,
    table_name: str = "animales",
    legacy_pk: str = "a-1",
    web_pk: str = "00000000-0000-0000-0000-000000000001",
    web_column: str = "current_state",
    preserved_value: Any = None,
    strategy: str = "derived",
    last_legacy_snapshot_at: str | None = "2026-06-20T12:00:00+00:00",
    last_reconciled_at: str | None = None,
    review_reasons: list[str] | None = None,
    reconciliation_status: str = "needs_review",
    # PR 5 follow-up additions
    derived_value: Any = None,
    derived_at: str | None = None,
) -> dict[str, Any]:
    """One row in the shape ``ShadowStateRepository.list_needs_review`` returns.

    Includes the new ``derived_value`` / ``derived_at`` columns added
    in PR 6 (PR 5 follow-up #1).
    """
    return {
        "id": "00000000-0000-0000-0000-000000000aaa",
        "table_name": table_name,
        "legacy_pk": legacy_pk,
        "web_pk": web_pk,
        "web_column": web_column,
        "preserved_value": json.dumps(preserved_value) if preserved_value is not None else None,
        "strategy": strategy,
        "last_legacy_snapshot_at": last_legacy_snapshot_at,
        "last_web_edit_at": None,
        "last_reconciled_at": last_reconciled_at,
        "reconciliation_status": reconciliation_status,
        "review_reasons": json.dumps(review_reasons or ["web_manual_override_detected"]),
        # PR 5 follow-up columns
        "derived_value": json.dumps(derived_value) if derived_value is not None else None,
        "derived_at": derived_at,
    }


def _shadow_state_mapping_with_current_state_derived():
    """Synthetic ``animales`` TableMapping with ``current_state`` as derived."""
    from migration.mappings import ColumnMapping, TableMapping

    return TableMapping(
        version="1.0",
        web_table="animales",
        legacy_table="TbFichaAnimal",
        key_field="NCHIP",
        legacy_key="NCHIP",
        date_fields=["FIMPLANTACIONCHIP", "FDefuncion"],
        columns=[
            ColumnMapping(
                web_column="NCHIP",
                legacy_column="NCHIP",
                transform="identity",
                nullable=False,
            ),
            ColumnMapping(
                web_column="current_state",
                legacy_column=None,
                transform="identity",
                nullable=True,
                web_only_strategy="derived",
            ),
        ],
        fk_lookups=[],
    )


def _voluntario_mapping_with_dni_preserve():
    """Synthetic ``voluntarios`` TableMapping with ``DNI`` as preserve."""
    from migration.mappings import ColumnMapping, TableMapping

    return TableMapping(
        version="1.0",
        web_table="voluntarios",
        legacy_table="TbVoluntariosParaAutorrellenables",
        key_field="Voluntario",
        legacy_key="Voluntario",
        date_fields=[],
        columns=[
            ColumnMapping(
                web_column="Voluntario",
                legacy_column="Voluntario",
                transform="identity",
                nullable=False,
            ),
            ColumnMapping(
                web_column="DNI",
                legacy_column=None,
                transform="identity",
                nullable=True,
                web_only_strategy="preserve",
            ),
        ],
        fk_lookups=[],
    )


def _empty_sync_state():
    from migration.sync_state import SyncState

    return SyncState()


# --- T6.1: Round-trip web->legacy->web preserves DNI ----------------------

# --- T6.5: derivation engine covers 11 cases ---------------------------


class TestDerivationElevenCasesRegression:
    """T6.5: explicit regression test that the derivation engine covers
    the 11 cases from ``lifecycle-state-resolver-extraction.md §4``.

    The fixture list is the canonical enumeration; each case produces
    the expected state. This is the line of defense if someone refactors
    the cascade and accidentally drops a branch.
    """

    @pytest.mark.parametrize(
        (
            "name",
            "ficha",
            "entradas",
            "acogidas",
            "adopciones",
            "expected_state",
        ),
        [
            (
                "01_pendiente_entrada",
                {
                    "NCHIP": "001",
                    "FDefuncion": None,
                    "Situacion": "",
                    "UltimoEstadoAntesDeFallecido": None,
                },
                [],
                [],
                [],
                "Pendiente de Entrada",
            ),
            (
                "02_pendiente_nueva_situacion",
                {
                    "NCHIP": "002",
                    "FDefuncion": None,
                    "Situacion": "",
                    "UltimoEstadoAntesDeFallecido": None,
                },
                [{"IDEntrada": 1, "FSalida": "2024-02-01", "FEntregaAPropietario": None}],
                [],
                [],
                "Pendiente de Nueva Situación",
            ),
            (
                "03_entregado",
                {
                    "NCHIP": "003",
                    "FDefuncion": None,
                    "Situacion": "",
                    "UltimoEstadoAntesDeFallecido": None,
                },
                [{"IDEntrada": 1, "FSalida": "2024-02-01", "FEntregaAPropietario": "2024-03-01"}],
                [],
                [],
                "Entregado",
            ),
            (
                "04_albergue",
                {
                    "NCHIP": "004",
                    "FDefuncion": None,
                    "Situacion": "",
                    "UltimoEstadoAntesDeFallecido": None,
                },
                [{"IDEntrada": 42, "FSalida": None, "FEntregaAPropietario": None}],
                [],
                [],
                "Albergue",
            ),
            (
                "05_acogida",
                {
                    "NCHIP": "005",
                    "FDefuncion": None,
                    "Situacion": "",
                    "UltimoEstadoAntesDeFallecido": None,
                },
                [],
                [{"IDAcogida": 7, "FFinal": None}],
                [],
                "Acogida",
            ),
            (
                "06_adoptado",
                {
                    "NCHIP": "006",
                    "FDefuncion": None,
                    "Situacion": "",
                    "UltimoEstadoAntesDeFallecido": None,
                },
                [],
                [],
                [{"IDAdopcion": 99, "FDevolucion": None}],
                "Adoptado",
            ),
            (
                "07_fallecido_albergue",
                {
                    "NCHIP": "007",
                    "FDefuncion": "2024-06-01",
                    "Situacion": "",
                    "UltimoEstadoAntesDeFallecido": "Albergue",
                },
                [{"IDEntrada": 1, "FSalida": "2024-05-01", "FEntregaAPropietario": None}],
                [],
                [],
                "Fallecido (Albergue)",
            ),
            (
                "08_fallecido_acogida",
                {
                    "NCHIP": "008",
                    "FDefuncion": "2024-06-01",
                    "Situacion": "",
                    "UltimoEstadoAntesDeFallecido": "Acogida",
                },
                [],
                [{"IDAcogida": 7, "FFinal": "2024-05-01"}],
                [],
                "Fallecido (Acogida)",
            ),
            (
                "09_fallecido_adoptado",
                {
                    "NCHIP": "009",
                    "FDefuncion": "2024-06-01",
                    "Situacion": "",
                    "UltimoEstadoAntesDeFallecido": "Adoptado",
                },
                [],
                [],
                [{"IDAdopcion": 99, "FDevolucion": "2024-05-01"}],
                "Fallecido (Adoptado)",
            ),
            (
                "10_fallecido_entregado",
                {
                    "NCHIP": "010",
                    "FDefuncion": "2024-06-01",
                    "Situacion": "",
                    "UltimoEstadoAntesDeFallecido": "Entregado",
                },
                [{"IDEntrada": 1, "FSalida": "2024-02-01", "FEntregaAPropietario": "2024-03-01"}],
                [],
                [],
                "Fallecido (Entregado)",
            ),
            (
                "11_incoherente_cross_category",
                {
                    "NCHIP": "011",
                    "FDefuncion": None,
                    "Situacion": "",
                    "UltimoEstadoAntesDeFallecido": None,
                },
                [{"IDEntrada": 1, "FSalida": None, "FEntregaAPropietario": None}],
                [],
                [{"IDAdopcion": 99, "FDevolucion": None}],
                "Incoherente",
            ),
        ],
        ids=[
            "01_pendiente_entrada",
            "02_pendiente_nueva_situacion",
            "03_entregado",
            "04_albergue",
            "05_acogida",
            "06_adoptado",
            "07_fallecido_albergue",
            "08_fallecido_acogida",
            "09_fallecido_adoptado",
            "10_fallecido_entregado",
            "11_incoherente_cross_category",
        ],
    )
    def test_derivation_covers_all_eleven_cases(
        self,
        name: str,  # noqa: ARG002
        ficha: dict[str, object],
        entradas: list[dict[str, object]],
        acogidas: list[dict[str, object]],
        adopciones: list[dict[str, object]],
        expected_state: str,
    ) -> None:
        from migration.derivation import derive_estado_actual_animal

        result = derive_estado_actual_animal(ficha, entradas, acogidas, adopciones)
        assert result.state == expected_state, (
            f"case {name!r}: expected state {expected_state!r}, got {result.state!r}"
        )
