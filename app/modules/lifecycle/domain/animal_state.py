"""Pure-domain port of the legacy Access/VBA ``DameSituacion()`` cascade.

LIFECYCLE-03 (issue #33) PR-A. Replicates the 6-level priority cascade
as a pure Python function so it can be reused by both the migration
layer (redirected in PR-C) and the web app's lifecycle writer
(rewired in PR-C). No I/O, no transport imports (AGENTS.md §31/§33.4).

Priority cascade:
  P1 Incoherente (multi-category active OR death + any active).
  P2 No active, no death -> Pendiente / Entregado.
  P3 Single active intake -> Albergue.
  P4 Single active foster -> Acogida.
  P5 Single active adoption -> Adoptado.
  P6 Death -> Fallecido (pre_death_state).

The 11 parametrized cases in tests/test_lifecycle_state_cascade.py
freeze this contract.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class DerivationKind(StrEnum):
    """Categorical kind of the derived state.

    Decoupled from the user-facing state string so callers can switch
    on category without parsing the localised string.
    """

    PENDIENTE_ENTRADA = "pendiente_entrada"
    PENDIENTE_NUEVA_SITUACION = "pendiente_nueva_situacion"
    ALBERGUE = "albergue"
    ACOGIDA = "acogida"
    ADOPTADO = "adoptado"
    ENTREGADO = "entregado"
    FALLECIDO = "fallecido"
    INCOHERENTE = "incoherente"


STATE_PENDIENTE_ENTRADA = "Pendiente de Entrada"
STATE_PENDIENTE_NUEVA_SITUACION = "Pendiente de Nueva Situación"
STATE_ALBERGUE = "Albergue"
STATE_ACOGIDA = "Acogida"
STATE_ADOPTADO = "Adoptado"
STATE_ENTREGADO = "Entregado"
STATE_INCOHERENTE = "Incoherente"
STATE_FALLECIDO_ALBERGUE = "Fallecido (Albergue)"
STATE_FALLECIDO_ACOGIDA = "Fallecido (Acogida)"
STATE_FALLECIDO_ADOPTADO = "Fallecido (Adoptado)"
STATE_FALLECIDO_ENTREGADO = "Fallecido (Entregado)"
STATE_FALLECIDO_DESCONOCIDO = "Fallecido (Desconocido)"

_VALID_PRE_DEATH_STATES: frozenset[str] = frozenset(
    {
        STATE_ALBERGUE,
        STATE_ACOGIDA,
        STATE_ADOPTADO,
        STATE_ENTREGADO,
    }
)

PRE_DEATH_STATE_DESCONOCIDO = "Desconocido"


@dataclass(frozen=True, slots=True)
class DerivationResult:
    """Output of :func:`calculate_state`.

    ``state`` is the literal value the spec writes to
    ``animal_current_state.current_state`` (matches the CHECK constraint
    in ``app/core/domain_lifecycle.py``). ``kind`` is the categorical
    enum used for branching in callers.

    ``pre_death_state`` is populated only when ``kind`` is ``FALLECIDO``
    (one of ``Albergue``, ``Acogida``, ``Adoptado``, ``Entregado``, or
    ``Desconocido``). ``active_*_id`` carry the legacy PK of the
    placement that produced the active state; all three are ``None``
    for terminal states and Incoherente.
    """

    state: str
    kind: DerivationKind
    pre_death_state: str | None = None
    active_intake_id: str | None = None
    active_foster_id: str | None = None
    active_adoption_id: str | None = None


def calculate_state(
    ficha: dict[str, Any] | None,
    entradas: Iterable[dict[str, Any]],
    acogidas: Iterable[dict[str, Any]],
    adopciones: Iterable[dict[str, Any]],
) -> DerivationResult:
    """Pure derivation of an animal's current state from 4 collections.

    Replicates the VBA ``DameSituacion()`` priority cascade. ``ficha``
    may be ``None`` — the function treats it as an empty dict and
    falls through to the no-active no-death branch, returning
    ``Pendiente de Entrada`` if there are no ``entradas`` either.
    """
    ficha = ficha if ficha is not None else {}
    entradas_list = list(entradas)
    acogidas_list = list(acogidas)
    adopciones_list = list(adopciones)

    active_intakes = [e for e in entradas_list if _is_null(e.get("FSalida"))]
    active_fosters = [a for a in acogidas_list if _is_null(a.get("FFinal"))]
    active_adoptions = [d for d in adopciones_list if _is_null(d.get("FDevolucion"))]
    has_death = _is_date(ficha.get("FDefuncion"))

    # P1 — Incoherente (multi-category, multiple-in-category, or death+active)
    if (
        len(active_intakes) > 1
        or len(active_fosters) > 1
        or len(active_adoptions) > 1
        or _has_cross_category(active_intakes, active_fosters, active_adoptions)
        or (has_death and (active_intakes or active_fosters or active_adoptions))
    ):
        return DerivationResult(state=STATE_INCOHERENTE, kind=DerivationKind.INCOHERENTE)

    # P2 — No active, no death
    if not has_death and not active_intakes and not active_fosters and not active_adoptions:
        if not entradas_list:
            return DerivationResult(
                state=STATE_PENDIENTE_ENTRADA,
                kind=DerivationKind.PENDIENTE_ENTRADA,
            )
        latest_with_propietario = _latest_FEntregaAPropietario(entradas_list)
        if latest_with_propietario is None:
            return DerivationResult(
                state=STATE_PENDIENTE_NUEVA_SITUACION,
                kind=DerivationKind.PENDIENTE_NUEVA_SITUACION,
            )
        return DerivationResult(state=STATE_ENTREGADO, kind=DerivationKind.ENTREGADO)

    # P3 / P4 / P5 — single active placement
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

    # P6 — Death
    if has_death:
        pre = _resolve_pre_death_state(ficha)
        return DerivationResult(
            state=f"Fallecido ({pre})",
            kind=DerivationKind.FALLECIDO,
            pre_death_state=pre,
        )

    # Defensive fallback: cascade above covers every input; defaults to
    # "needs operator review" to match VBA behaviour on edge cases.
    return DerivationResult(state=STATE_INCOHERENTE, kind=DerivationKind.INCOHERENTE)


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
    if raw is None:
        return None
    return str(raw)


def _latest_FEntregaAPropietario(
    entradas: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the latest entrada (by ``IDEntrada`` desc) with
    ``FEntregaAPropietario`` set, or ``None`` if no entrada carries it.

    Mirrors ``DameUltimaFEntregaAPropietario`` in
    ``Funciones Generales.bas:1639-1665``.
    """
    with_date = [e for e in entradas if _is_date(e.get("FEntregaAPropietario"))]
    if not with_date:
        return None
    return max(with_date, key=lambda e: e.get("IDEntrada", 0) or 0)


# Captures the inner state of a derived "Fallecido (X)" string. Used by
# ``_resolve_pre_death_state`` to make the helper idempotent against a
# cached ``Situacion`` that already carries a previously derived
# Fallecido string (VBA prioridad 6 — ``lifecycle-state-resolver-extraction.md``
# §10 Challenge #1).
_FALLECIDO_PARENTHETICAL_RE = re.compile(r"^Fallecido \((.+)\)$")


def _resolve_pre_death_state(ficha: dict[str, Any]) -> str:
    """Compute the parenthetical for a ``Fallecido ({pre})`` state.

    Mirrors ``DameSituacion`` priority 6:

      - If ``UltimoEstadoAntesDeFallecido`` is empty AND ``Situacion``
        does NOT already contain ``Fallecido``, returns ``Desconocido``.
      - If ``Situacion`` already carries ``Fallecido ({X})`` (the cache
        was overwritten by a previous apply), parses out ``X`` so the
        caller wraps it exactly once — idempotence rule, MUST NOT nest
        to ``Fallecido (Fallecido (X))``.
      - If ``UltimoEstadoAntesDeFallecido`` is set but not one of the
        four active states, falls back to ``Desconocido``.
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
    "PRE_DEATH_STATE_DESCONOCIDO",
    "STATE_ACOGIDA",
    "STATE_ADOPTADO",
    "STATE_ALBERGUE",
    "STATE_ENTREGADO",
    "STATE_FALLECIDO_ACOGIDA",
    "STATE_FALLECIDO_ADOPTADO",
    "STATE_FALLECIDO_ALBERGUE",
    "STATE_FALLECIDO_DESCONOCIDO",
    "STATE_FALLECIDO_ENTREGADO",
    "STATE_INCOHERENTE",
    "STATE_PENDIENTE_ENTRADA",
    "STATE_PENDIENTE_NUEVA_SITUACION",
    "calculate_state",
]
