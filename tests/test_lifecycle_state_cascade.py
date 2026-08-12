"""Domain-level port of the 11 derivation cases from
``tests/test_derivation_11cases.py`` (LIFECYCLE-03, PR-A work-unit A1).

The 11 parametrized cases are the canonical enumeration from
``docs/discovery/lifecycle-state-resolver-extraction.md`` §4 — they
freeze the contract for the P1-P6 priority cascade that the legacy
Access/VBA ``DameSituacion()`` function implements. The pure domain
function in ``app/modules/lifecycle/domain/animal_state.py::calculate_state``
MUST produce the same output for each case.

This file is the RED baseline for the new domain cascade. It exercises
the same input shapes as ``tests/test_derivation_11cases.py`` (the
migration-layer copy); PR-C will redirect the migration layer to call
this domain function so the two implementations cannot drift.

This is the line of defense if someone refactors the cascade and
accidentally drops a branch.
"""

from __future__ import annotations

from typing import Any

import pytest


# --- 11 RED parametrized cases -------------------------------------------


class TestLifecycleStateCascadeElevenCases:
    """Domain-level port of the 11 derivation cases.

    The fixture list is the canonical enumeration; each case produces
    the expected state. Same shape as ``tests/test_derivation_11cases.py``
    but the call goes to ``app.modules.lifecycle.domain.animal_state``
    (pure domain), not ``migration.derivation``.
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
    def test_cascade_matches_derivation_11cases(
        self,
        name: str,  # noqa: ARG002
        ficha: dict[str, object],
        entradas: list[dict[str, object]],
        acogidas: list[dict[str, object]],
        adopciones: list[dict[str, object]],
        expected_state: str,
    ) -> None:
        from app.modules.lifecycle.domain.animal_state import calculate_state

        result = calculate_state(ficha, entradas, acogidas, adopciones)
        assert result.state == expected_state, (
            f"case {name!r}: expected state {expected_state!r}, got {result.state!r}"
        )


# --- Architectural pin: domain depends on no transport --------------------


class TestLifecycleDomainPurity:
    """Domain layer must not import transport types (AGENTS.md §31/§33.4)."""

    def test_domain_module_does_not_import_insforge(self) -> None:
        import ast
        import pathlib

        src = pathlib.Path("app/modules/lifecycle/domain/animal_state.py")
        assert src.exists(), "domain module must exist before cascade can run"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "InsForge" not in alias.name, (
                        f"domain module imports transport type: {alias.name}"
                    )
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "InsForge" not in module, (
                    f"domain module imports from transport: {module}"
                )
                for alias in node.names:
                    assert "InsForge" not in alias.name, (
                        f"domain module imports transport symbol: {alias.name}"
                    )
