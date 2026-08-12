"""Pure-domain port of the legacy Access/VBA ``DameSituacion()`` cascade.

LIFECYCLE-03 (issue #33) PR-A. 6-level priority cascade, no I/O, no
transport imports (AGENTS.md §31/§33.4). The 11 parametrized cases in
``tests/test_lifecycle_state_cascade.py`` freeze this contract.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.modules.lifecycle.domain.constants import (
    _VALID_PRE_DEATH_STATES,
    PRE_DEATH_STATE_DESCONOCIDO,
    STATE_ACOGIDA,
    STATE_ADOPTADO,
    STATE_ALBERGUE,
    STATE_ENTREGADO,
    STATE_INCOHERENTE,
    STATE_PENDIENTE_ENTRADA,
    STATE_PENDIENTE_NUEVA_SITUACION,
)
from app.modules.lifecycle.domain.result import DerivationResult


class DerivationKind(StrEnum):
    """Categorical kind of the derived state (decoupled from the user-facing string)."""
    PENDIENTE_ENTRADA = "pendiente_entrada"
    PENDIENTE_NUEVA_SITUACION = "pendiente_nueva_situacion"
    ALBERGUE = "albergue"
    ACOGIDA = "acogida"
    ADOPTADO = "adoptado"
    ENTREGADO = "entregado"
    FALLECIDO = "fallecido"
    INCOHERENTE = "incoherente"


def calculate_state(
    ficha: dict[str, Any] | None,
    entradas: Iterable[dict[str, Any]],
    acogidas: Iterable[dict[str, Any]],
    adopciones: Iterable[dict[str, Any]],
) -> DerivationResult:
    """Pure derivation of an animal's current state from 4 collections.

    Replicates the VBA ``DameSituacion()`` priority cascade. ``ficha``
    may be ``None`` (treated as empty dict). Each priority level is
    evaluated in order by a dedicated helper; the orchestrator here
    stays linear (CC ≤ 5) to respect AGENTS.md §21 (cyclomatic-complexity
    budgets).
    """
    ficha = ficha if ficha is not None else {}
    entradas_list = list(entradas)
    active_intakes = [e for e in entradas_list if _is_null(e.get("FSalida"))]
    active_fosters = [a for a in acogidas if _is_null(a.get("FFinal"))]
    active_adoptions = [d for d in adopciones if _is_null(d.get("FDevolucion"))]
    has_death = _is_date(ficha.get("FDefuncion"))

    # P1 — Incoherente (multi-category, multiple-in-category, or death+active).
    if _is_incoherente(active_intakes, active_fosters, active_adoptions, has_death):
        return DerivationResult(
            state=STATE_INCOHERENTE, kind=DerivationKind.INCOHERENTE
        )

    # P2 — No active, no death.
    if not has_death and not active_intakes and not active_fosters and not active_adoptions:
        return _resolve_no_active_state(entradas_list)

    # P3 / P4 / P5 — single active placement.
    single = _resolve_single_active(active_intakes, active_fosters, active_adoptions)
    if single is not None:
        return single

    # P6 — Death (the only remaining branch once P1-P5 have all fallen through).
    if has_death:
        return _format_fallecido_result(ficha)

    # Defensive fallback (VBA defaults to "needs operator review").
    return DerivationResult(state=STATE_INCOHERENTE, kind=DerivationKind.INCOHERENTE)


def _is_incoherente(
    active_intakes: list[dict[str, Any]],
    active_fosters: list[dict[str, Any]],
    active_adoptions: list[dict[str, Any]],
    has_death: bool,
) -> bool:
    """P1 conflict detection: multi-category, multiple-in-category, or death+active."""
    return bool(
        len(active_intakes) > 1
        or len(active_fosters) > 1
        or len(active_adoptions) > 1
        or _has_cross_category(active_intakes, active_fosters, active_adoptions)
        or (has_death and (active_intakes or active_fosters or active_adoptions))
    )


def _resolve_no_active_state(entradas_list: list[dict[str, Any]]) -> DerivationResult:
    """P2 resolution: no actives, no death — choose Pendiente / Entregado."""
    if not entradas_list:
        return DerivationResult(
            state=STATE_PENDIENTE_ENTRADA,
            kind=DerivationKind.PENDIENTE_ENTRADA,
        )
    if _latest_FEntregaAPropietario(entradas_list) is None:  # noqa: N802 — legacy field name
        return DerivationResult(
            state=STATE_PENDIENTE_NUEVA_SITUACION,
            kind=DerivationKind.PENDIENTE_NUEVA_SITUACION,
        )
    return DerivationResult(state=STATE_ENTREGADO, kind=DerivationKind.ENTREGADO)


def _resolve_single_active(
    active_intakes: list[dict[str, Any]],
    active_fosters: list[dict[str, Any]],
    active_adoptions: list[dict[str, Any]],
) -> DerivationResult | None:
    """P3/P4/P5 resolution: exactly one active placement drives the state."""
    if len(active_intakes) == 1:
        intake = active_intakes[0]
        return DerivationResult(
            state=STATE_ALBERGUE,
            kind=DerivationKind.ALBERGUE,
            active_intake_id=_legacy_pk_as_str(intake, "IDEntrada"),
        )
    if len(active_fosters) == 1:
        foster = active_fosters[0]
        return DerivationResult(
            state=STATE_ACOGIDA,
            kind=DerivationKind.ACOGIDA,
            active_foster_id=_legacy_pk_as_str(foster, "IDAcogida"),
        )
    if len(active_adoptions) == 1:
        adoption = active_adoptions[0]
        return DerivationResult(
            state=STATE_ADOPTADO,
            kind=DerivationKind.ADOPTADO,
            active_adoption_id=_legacy_pk_as_str(adoption, "IDAdopcion"),
        )
    return None


def _format_fallecido_result(ficha: dict[str, Any]) -> DerivationResult:
    """P6 resolution: assemble the ``Fallecido ({pre})`` result."""
    pre = _resolve_pre_death_state(ficha)
    return DerivationResult(
        state=f"Fallecido ({pre})",
        kind=DerivationKind.FALLECIDO,
        pre_death_state=pre,
    )


def _is_null(value: Any) -> bool:
    """True when the value represents an empty end-date (None or ``""``)."""
    return value is None or value == ""


def _is_date(value: Any) -> bool:
    """True when the value is a non-empty date/datetime/string."""
    if value is None:
        return False
    if isinstance(value, datetime):
        return True
    if isinstance(value, str):
        return value != ""
    return False


def _has_cross_category(
    intakes: list[dict[str, Any]],
    fosters: list[dict[str, Any]],
    adoptions: list[dict[str, Any]],
) -> bool:
    """True when active placements span more than one category."""
    return (
        (bool(intakes) and (bool(fosters) or bool(adoptions)))
        or (bool(fosters) and (bool(intakes) or bool(adoptions)))
        or (bool(adoptions) and (bool(intakes) or bool(fosters)))
    )


def _legacy_pk_as_str(row: dict[str, Any], field: str) -> str | None:
    """Return the legacy primary key as ``str`` (or ``None`` when missing)."""
    raw = row.get(field)
    return None if raw is None else str(raw)


def _latest_FEntregaAPropietario(  # noqa: N802 — legacy field name; see migration/derivation.py:311 baseline
    entradas: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Latest entrada (by ``IDEntrada`` desc) with ``FEntregaAPropietario`` set.

    The uppercase name matches the legacy Access/VBA field
    (``FEntregaAPropietario``) for code-to-spec traceability — see
    ``migration/derivation.py::derive_estado_actual_animal`` for the
    canonical implementation.
    """
    with_date = [e for e in entradas if _is_date(e.get("FEntregaAPropietario"))]
    if not with_date:
        return None
    return max(with_date, key=lambda e: e.get("IDEntrada", 0) or 0)


# Captures the inner state of a derived "Fallecido (X)" string. Used by
# ``_resolve_pre_death_state`` to keep the helper idempotent against a
# cached ``Situacion`` that already carries a previously derived
# Fallecido string (VBA prioridad 6).
_FALLECIDO_PARENTHETICAL_RE = re.compile(r"^Fallecido \((.+)\)$")


def _resolve_pre_death_state(ficha: dict[str, Any]) -> str:
    """Compute the parenthetical for a ``Fallecido ({pre})`` state.

    Mirrors ``DameSituacion`` priority 6:
      - empty ``UltimoEstadoAntesDeFallecido`` + no Fallecido in cache
        -> Desconocido;
      - cache already carries ``Fallecido ({X})`` -> parse out ``X`` so
        the wrapper does not nest to ``Fallecido (Fallecido (X))``;
      - non-empty but invalid -> fall back to Desconocido.
    """
    pre = ficha.get("UltimoEstadoAntesDeFallecido") or ""
    situacion_anterior = ficha.get("Situacion") or ""
    if pre == "":
        if "Fallecido" not in situacion_anterior:
            return PRE_DEATH_STATE_DESCONOCIDO
        match = _FALLECIDO_PARENTHETICAL_RE.match(situacion_anterior)
        return match.group(1) if match is not None else PRE_DEATH_STATE_DESCONOCIDO
    if pre not in _VALID_PRE_DEATH_STATES:
        return PRE_DEATH_STATE_DESCONOCIDO
    return pre


__all__ = [
    "DerivationKind",
    "DerivationResult",
    "calculate_state",
]
