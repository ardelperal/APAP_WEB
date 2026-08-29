"""Domain-level port of the 11 derivation cases from
``tests/test_derivation_11cases.py`` (LIFECYCLE-03, PR-A).

The 11 parametrized cases freeze the P1-P6 priority cascade contract
that ``DameSituacion()`` implements. The pure domain function in
``app/modules/lifecycle/domain/animal_state.py::calculate_state`` MUST
produce the same output for each case.
"""

from __future__ import annotations

import pytest

CASES: list[tuple[str, dict[str, object], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], str]] = [
    (
        "01_pendiente_entrada",
        {"NCHIP": "001", "FDefuncion": None, "Situacion": "", "UltimoEstadoAntesDeFallecido": None},
        [], [], [],
        "Pendiente de Entrada",
    ),
    (
        "02_pendiente_nueva_situacion",
        {"NCHIP": "002", "FDefuncion": None, "Situacion": "", "UltimoEstadoAntesDeFallecido": None},
        [{"IDEntrada": 1, "FSalida": "2024-02-01", "FEntregaAPropietario": None}],
        [], [],
        "Pendiente de Nueva Situación",
    ),
    (
        "03_entregado",
        {"NCHIP": "003", "FDefuncion": None, "Situacion": "", "UltimoEstadoAntesDeFallecido": None},
        [{"IDEntrada": 1, "FSalida": "2024-02-01", "FEntregaAPropietario": "2024-03-01"}],
        [], [],
        "Entregado",
    ),
    (
        "04_albergue",
        {"NCHIP": "004", "FDefuncion": None, "Situacion": "", "UltimoEstadoAntesDeFallecido": None},
        [{"IDEntrada": 42, "FSalida": None, "FEntregaAPropietario": None}],
        [], [],
        "Albergue",
    ),
    (
        "05_acogida",
        {"NCHIP": "005", "FDefuncion": None, "Situacion": "", "UltimoEstadoAntesDeFallecido": None},
        [], [{"IDAcogida": 7, "FFinal": None}], [],
        "Acogida",
    ),
    (
        "06_adoptado",
        {"NCHIP": "006", "FDefuncion": None, "Situacion": "", "UltimoEstadoAntesDeFallecido": None},
        [], [], [{"IDAdopcion": 99, "FDevolucion": None}],
        "Adoptado",
    ),
    (
        "07_fallecido_albergue",
        {"NCHIP": "007", "FDefuncion": "2024-06-01", "Situacion": "", "UltimoEstadoAntesDeFallecido": "Albergue"},
        [{"IDEntrada": 1, "FSalida": "2024-05-01", "FEntregaAPropietario": None}],
        [], [],
        "Fallecido (Albergue)",
    ),
    (
        "08_fallecido_acogida",
        {"NCHIP": "008", "FDefuncion": "2024-06-01", "Situacion": "", "UltimoEstadoAntesDeFallecido": "Acogida"},
        [], [{"IDAcogida": 7, "FFinal": "2024-05-01"}], [],
        "Fallecido (Acogida)",
    ),
    (
        "09_fallecido_adoptado",
        {"NCHIP": "009", "FDefuncion": "2024-06-01", "Situacion": "", "UltimoEstadoAntesDeFallecido": "Adoptado"},
        [], [], [{"IDAdopcion": 99, "FDevolucion": "2024-05-01"}],
        "Fallecido (Adoptado)",
    ),
    (
        "10_fallecido_entregado",
        {"NCHIP": "010", "FDefuncion": "2024-06-01", "Situacion": "", "UltimoEstadoAntesDeFallecido": "Entregado"},
        [{"IDEntrada": 1, "FSalida": "2024-02-01", "FEntregaAPropietario": "2024-03-01"}],
        [], [],
        "Fallecido (Entregado)",
    ),
    (
        "11_incoherente_cross_category",
        {"NCHIP": "011", "FDefuncion": None, "Situacion": "", "UltimoEstadoAntesDeFallecido": None},
        [{"IDEntrada": 1, "FSalida": None, "FEntregaAPropietario": None}],
        [], [{"IDAdopcion": 99, "FDevolucion": None}],
        "Incoherente",
    ),
]

TERMINAL_CASES = [
    case
    for case in CASES
    if case[0]
    in {
        "03_entregado",
        "07_fallecido_albergue",
        "09_fallecido_adoptado",
        "11_incoherente_cross_category",
    }
]


@pytest.mark.parametrize(
    ("name", "ficha", "entradas", "acogidas", "adopciones", "expected_state"),
    CASES,
    ids=[c[0] for c in CASES],
)
def test_cascade_matches_derivation_11cases(
    name: str,  # noqa: ARG001
    ficha: dict[str, object],
    entradas: list[dict[str, object]],
    acogidas: list[dict[str, object]],
    adopciones: list[dict[str, object]],
    expected_state: str,
) -> None:
    from app.modules.lifecycle.domain.animal_state import calculate_state

    result = calculate_state(ficha, entradas, acogidas, adopciones)
    assert result.state == expected_state, (
        f"case {name!r}: expected {expected_state!r}, got {result.state!r}"
    )


@pytest.mark.parametrize(
    ("name", "ficha", "entradas", "acogidas", "adopciones", "expected_state"),
    TERMINAL_CASES,
    ids=[case[0] for case in TERMINAL_CASES],
)
def test_terminal_states_have_no_placement_ids(
    name: str,  # noqa: ARG001
    ficha: dict[str, object],
    entradas: list[dict[str, object]],
    acogidas: list[dict[str, object]],
    adopciones: list[dict[str, object]],
    expected_state: str,
) -> None:
    from app.modules.lifecycle.domain.animal_state import calculate_state

    result = calculate_state(ficha, entradas, acogidas, adopciones)

    assert result.state == expected_state
    assert result.active_intake_id is None
    assert result.active_foster_id is None
    assert result.active_adoption_id is None


def test_domain_module_does_not_import_insforge() -> None:
    """Domain module must not import transport types (AGENTS.md §31/§33.4)."""
    import ast
    import pathlib

    src = pathlib.Path("app/modules/lifecycle/domain/animal_state.py")
    assert src.exists(), "domain module must exist before this pin can run"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "InsForge" not in alias.name, (
                    f"domain module imports transport type: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "InsForge" not in module, (
                f"domain module imports from transport: {module}"
            )
            for alias in node.names:
                assert "InsForge" not in alias.name, (
                    f"domain module imports transport symbol: {alias.name}"
                )
