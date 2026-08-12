"""Branch coverage tests for the private helpers in
``app.modules.lifecycle.domain.animal_state``.

These tests target the four helpers whose CRAP score would otherwise
exceed the grade-A threshold (CRAP < 6) per ``scripts/check_crap.py``:
``_is_incoherente``, ``_has_cross_category``, ``_resolve_pre_death_state``,
``calculate_state``. By exercising every short-circuit branch, the
CRAP score drops below the threshold without lowering the function
complexity.

The cascade-level behaviour is already frozen by the 11 parametrized
cases in ``test_lifecycle_state_cascade.py``; this module is purely
about closing the remaining branch-coverage gaps on the helpers.

Refs #33 (PR-A)
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.modules.lifecycle.domain.animal_state import (
    _has_cross_category,
    _is_incoherente,
    _is_null,
    _resolve_pre_death_state,
)

# ---------------------------------------------------------------------------
# _is_null — covered in isolation so the cascade-level test suite doesn't have
# to. Branches: None, empty string, anything-else (returns False).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, True),
        ("", True),
        ("2024-02-01", False),
        (datetime(2024, 2, 1), False),
    ],
)
def test__is_null_branches(value: object, expected: bool) -> None:
    assert _is_null(value) is expected


# ---------------------------------------------------------------------------
# _has_cross_category — three OR branches; at least one is taken when both
# sides of the cross are non-empty. Exercising all three forces every
# boolean combination.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "intakes,fosters,adoptions,expected",
    [
        ([], [], [], False),
        ([{"IDEntrada": 1}], [], [], False),
        ([{"IDEntrada": 1}], [{"IDAcogida": 2}], [], True),   # intakes + fosters
        ([{"IDEntrada": 1}], [], [{"IDAdopcion": 3}], True),  # intakes + adoptions
        ([], [{"IDAcogida": 2}], [{"IDAdopcion": 3}], True),  # fosters + adoptions
    ],
)
def test__has_cross_category_branches(
    intakes: list[dict[str, object]],
    fosters: list[dict[str, object]],
    adoptions: list[dict[str, object]],
    expected: bool,
) -> None:
    assert _has_cross_category(intakes, fosters, adoptions) is expected


# ---------------------------------------------------------------------------
# _is_incoherente — five OR sub-conditions. The cascade covers the typical
# cases; this module adds the corner-cases (death with no actives, multi-
# intake without cross-category, etc.).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "intakes,fosters,adoptions,has_death,expected",
    [
        ([], [], [], False, False),
        # Death with no actives — not Incoherente.
        ([], [], [], True, False),
        # Death with one active — Incoherente.
        ([{"IDEntrada": 1, "FSalida": None}], [], [], True, True),
        # Two intakes (no cross-category) — Incoherente.
        (
            [{"IDEntrada": 1, "FSalida": None}, {"IDEntrada": 2, "FSalida": None}],
            [], [], False, True,
        ),
        # One intake + one foster — Incoherente (cross-category).
        (
            [{"IDEntrada": 1, "FSalida": None}],
            [{"IDAcogida": 2, "FFinal": None}],
            [],
            False,
            True,
        ),
        # Two fosters (no cross-category) — Incoherente.
        (
            [],
            [{"IDAcogida": 1, "FFinal": None}, {"IDAcogida": 2, "FFinal": None}],
            [],
            False,
            True,
        ),
        # One intake + one adoption — Incoherente (cross-category).
        (
            [{"IDEntrada": 1, "FSalida": None}],
            [],
            [{"IDAdopcion": 2, "FDevolucion": None}],
            False,
            True,
        ),
        # Two adoptions (no cross-category) — Incoherente.
        (
            [],
            [],
            [
                {"IDAdopcion": 1, "FDevolucion": None},
                {"IDAdopcion": 2, "FDevolucion": None},
            ],
            False,
            True,
        ),
    ],
)
def test__is_incoherente_branches(
    intakes: list[dict[str, object]],
    fosters: list[dict[str, object]],
    adoptions: list[dict[str, object]],
    has_death: bool,
    expected: bool,
) -> None:
    assert _is_incoherente(intakes, fosters, adoptions, has_death) is expected


# ---------------------------------------------------------------------------
# _resolve_pre_death_state — five branches (empty vs non-empty pre, with
# various cache contents).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ficha,expected",
    [
        # Empty pre, no Fallecido in cache → Desconocido.
        ({"UltimoEstadoAntesDeFallecido": None, "Situacion": ""}, "Desconocido"),
        # Empty pre, valid Fallecido in cache → parse out the parenthetical.
        (
            {"UltimoEstadoAntesDeFallecido": None, "Situacion": "Fallecido (Albergue)"},
            "Albergue",
        ),
        # Empty pre, malformed Fallecido in cache → Desconocido fallback.
        (
            {"UltimoEstadoAntesDeFallecido": None, "Situacion": "Fallecido (X"},
            "Desconocido",
        ),
        # Non-empty valid pre → passthrough.
        (
            {"UltimoEstadoAntesDeFallecido": "Acogida", "Situacion": ""},
            "Acogida",
        ),
        # Non-empty invalid pre → Desconocido fallback.
        (
            {"UltimoEstadoAntesDeFallecido": "Inventado", "Situacion": ""},
            "Desconocido",
        ),
    ],
)
def test__resolve_pre_death_state_branches(
    ficha: dict[str, object], expected: str
) -> None:
    assert _resolve_pre_death_state(ficha) == expected


# ---------------------------------------------------------------------------
# calculate_state — the defensive fallback branch is mathematically
# unreachable through any input + monkey-patch combination (every
# priority level returns a DerivationResult before the fallback is
# reached). The branch is preserved as a defensive guard per VBA's
# "needs operator review" default; its line coverage gap is reported by
# the CRAP ratchet and is intentional. PR-C will narrow this gap when
# the close/can_delete use cases force additional code paths.
# ---------------------------------------------------------------------------
