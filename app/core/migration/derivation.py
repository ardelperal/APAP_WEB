"""Derivation engine for ``animal_current_state``.

PR 2 of ``web-only-feature-preservation``. Replicates the VBA
``DameSituacion()`` priority cascade as a pure Python function so the
web DB can compute an animal's current state from the legacy tables
without round-tripping back to Access.

The implementation matches
``docs/discovery/lifecycle-state-resolver-extraction.md`` §3
step-by-step. The 11 parametrized cases (tasks.md T2.3) come from §4.

The function is PURE: it does not read from the DB, does not write
events, and has no side effects. The applier (PR 4) is responsible for
plumbing the four legacy collections into the call and for persisting
the resulting ``DerivationResult`` into ``animal_current_state``.

Companion comparator ``compare_derived_to_stored`` implements the
post-application Q2 rule (matched / divergent / needs_review /
pending) and is the building block the applier hook (PR 4) uses to
populate ``animal_current_state.reconciliation_status``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.core.migration.reconcile import ReconciliationStatus


class DerivationKind(StrEnum):
    """Categorical kind of the derived state.

    Decoupled from the user-facing state string so callers can switch
    on category without parsing the localised string. The state string
    (``DerivationResult.state``) is what the spec writes to
    ``animal_current_state.current_state`` and is constrained by the
    CHECK enum in ``app/core/domain.py``.
    """

    PENDIENTE_ENTRADA = "pendiente_entrada"
    PENDIENTE_NUEVA_SITUACION = "pendiente_nueva_situacion"
    ALBERGUE = "albergue"
    ACOGIDA = "acogida"
    ADOPTADO = "adoptado"
    ENTREGADO = "entregado"
    FALLECIDO = "fallecido"
    INCOHERENTE = "incoherente"


# --- State value constants -----------------------------------------------
#
# Centralised so the comparator and the applier (PR 4) reference the
# same canonical strings. Mirrors the CHECK enum in
# ``app/core/domain.py::ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL``.

STATE_PENDIENTE_ENTRADA = "Pendiente de Entrada"
STATE_PENDIENTE_NUEVA_SITUACION = "Pendiente de Nueva Situación"
STATE_ALBERGUE = "Albergue"
STATE_ACOGIDA = "Acogida"
STATE_ADOPTADO = "Adoptado"
STATE_ENTREGADO = "Entregado"
STATE_INCOHERENTE = "Incoherente"
STATE_FALLECIDO_DESCONOCIDO = "Fallecido (Desconocido)"

_VALID_PRE_DEATH_STATES = frozenset(
    {STATE_ALBERGUE, STATE_ACOGIDA, STATE_ADOPTADO, STATE_ENTREGADO}
)


@dataclass(frozen=True, slots=True)
class DerivationResult:
    """Output of ``derive_estado_actual_animal``.

    ``state`` is the literal value the spec writes to
    ``animal_current_state.current_state`` (matches the CHECK constraint
    in ``app/core/domain.py``). ``kind`` is the categorical enum used
    for branching in the comparator and the CLI.

    ``pre_death_state`` is populated only when ``kind`` is
    ``FALLECIDO``; it carries the ``UltimoEstadoAntesDeFallecido``
    value (one of ``Albergue``, ``Acogida``, ``Adoptado``, ``Entregado``)
    or ``"Desconocido"`` when the legacy record lacks it.

    ``active_intake_id``, ``active_foster_id``, ``active_adoption_id``
    carry the legacy PKs of the records that produced the active
    placement (exactly one is set for Albergue / Acogida / Adoptado;
    all three are ``None`` for terminal states and Incoherente).
    """

    state: str
    kind: DerivationKind
    pre_death_state: str | None = None
    active_intake_id: str | None = None
    active_foster_id: str | None = None
    active_adoption_id: str | None = None


# --- Derivation entry point ----------------------------------------------


def derive_estado_actual_animal(
    tb_ficha: dict[str, Any] | None,
    tb_entradas: Iterable[dict[str, Any]],
    tb_acogidas: Iterable[dict[str, Any]],
    tb_adopciones: Iterable[dict[str, Any]],
) -> DerivationResult:
    """Pure derivation of an animal's current state from 4 legacy collections.

    Implements the priority cascade from
    ``lifecycle-state-resolver-extraction.md §3``:

      P1 — Incoherente (multi-category active OR death+active).
      P2 — No active, no death → Pendiente / Entregado.
      P3 — Single active intake → Albergue.
      P4 — Single active foster → Acogida.
      P5 — Single active adoption → Adoptado.
      P6 — Death → Fallecido (pre_death_state).

    The function is deterministic for a given input. ``tb_ficha`` may
    be ``None`` (animal record not yet loaded) — the function treats
    it as an empty dict and falls through to the no-active no-death
    branch, returning ``Pendiente de Entrada`` if there are no
    ``tb_entradas`` either.
    """
    ficha = tb_ficha or {}
    entradas = list(tb_entradas)
    acogidas = list(tb_acogidas)
    adopciones = list(tb_adopciones)

    has_death = _is_date(ficha.get("FDefuncion"))

    active_intakes = [e for e in entradas if _is_null(e.get("FSalida"))]
    active_fosters = [a for a in acogidas if _is_null(a.get("FFinal"))]
    active_adoptions = [d for d in adopciones if _is_null(d.get("FDevolucion"))]

    # --- P1: Incoherente (conflict detection) -------------------------
    #
    # VBA priority 1: any combination of cross-category active records
    # OR death + any active record → Incoherente. Also fires on
    # multiple active records within a single category (legacy signals
    # this with a `#` separator in the IDs; we detect it by length).

    multiple_in_same_category = (
        len(active_intakes) > 1 or len(active_fosters) > 1 or len(active_adoptions) > 1
    )
    cross_category = (
        (active_intakes and (active_fosters or active_adoptions))
        or (active_fosters and (active_intakes or active_adoptions))
        or (active_adoptions and (active_intakes or active_fosters))
    )
    death_plus_active = has_death and (active_intakes or active_fosters or active_adoptions)

    if multiple_in_same_category or cross_category or death_plus_active:
        return DerivationResult(state=STATE_INCOHERENTE, kind=DerivationKind.INCOHERENTE)

    # --- P2: No active, no death --------------------------------------
    #
    # VBA priority 2: ficha present + no FDefuncion + empty active sets
    # → check whether the animal has ever had an intake. If never
    # entered → Pendiente de Entrada. If entered and the latest
    # ``FEntregaAPropietario`` is set → Entregado. Otherwise →
    # Pendiente de Nueva Situación.

    if not has_death and not active_intakes and not active_fosters and not active_adoptions:
        if not entradas:
            return DerivationResult(
                state=STATE_PENDIENTE_ENTRADA,
                kind=DerivationKind.PENDIENTE_ENTRADA,
            )
        latest_with_propietario = _latest_FEntregaAPropietario(entradas)
        if latest_with_propietario is None:
            return DerivationResult(
                state=STATE_PENDIENTE_NUEVA_SITUACION,
                kind=DerivationKind.PENDIENTE_NUEVA_SITUACION,
            )
        return DerivationResult(state=STATE_ENTREGADO, kind=DerivationKind.ENTREGADO)

    # --- P3: Single active intake -------------------------------------
    if len(active_intakes) == 1:
        intake = active_intakes[0]
        return DerivationResult(
            state=STATE_ALBERGUE,
            kind=DerivationKind.ALBERGUE,
            active_intake_id=_legacy_pk_as_str(intake, "IDEntrada"),
        )

    # --- P4: Single active foster -------------------------------------
    if len(active_fosters) == 1:
        foster = active_fosters[0]
        return DerivationResult(
            state=STATE_ACOGIDA,
            kind=DerivationKind.ACOGIDA,
            active_foster_id=_legacy_pk_as_str(foster, "IDAcogida"),
        )

    # --- P5: Single active adoption -----------------------------------
    if len(active_adoptions) == 1:
        adoption = active_adoptions[0]
        return DerivationResult(
            state=STATE_ADOPTADO,
            kind=DerivationKind.ADOPTADO,
            active_adoption_id=_legacy_pk_as_str(adoption, "IDAdopcion"),
        )

    # --- P6: Death ----------------------------------------------------
    #
    # VBA priority 6: death overrides all. The parenthetical carries
    # the ``UltimoEstadoAntesDeFallecido`` value (one of the four
    # active states or "Desconocido" when the legacy record lacks it).
    # The VBA also preserves an existing ``Fallecido`` string when the
    # state was already set; we replicate that to avoid producing
    # ``Fallecido (Fallecido (Albergue))`` if called twice.

    if has_death:
        pre = _resolve_pre_death_state(ficha)
        return DerivationResult(
            state=f"Fallecido ({pre})",
            kind=DerivationKind.FALLECIDO,
            pre_death_state=pre,
        )

    # Defensive fallback — the cascade above should cover every input.
    # Returning ``Incoherente`` keeps the function total (no exceptions
    # surface into the applier) and matches the VBA behaviour of
    # defaulting to a "needs operator review" verdict on edge cases.
    return DerivationResult(state=STATE_INCOHERENTE, kind=DerivationKind.INCOHERENTE)


# --- Comparator (T2.2) --------------------------------------------------


def compare_derived_to_stored(
    *,
    derived_state: str,
    stored_state: str | None,
    web_updated_at: datetime | None,
    last_legacy_snapshot_at: datetime | None,
) -> ReconciliationStatus:
    """Comparador post-aplicación (regla Q2).

    Verdict matrix:

    - ``stored_state is None`` → ``PENDING`` (initial; never derived).
    - ``derived_state == stored_state`` → ``MATCHED`` (no operator action).
    - ``derived_state != stored_state`` AND
      ``web_updated_at >= last_legacy_snapshot_at`` → ``NEEDS_REVIEW``
      (operator manually overrode the web value; applier preserves
      stored value; case surfaces in the CLI).
    - ``derived_state != stored_state`` otherwise → ``DIVERGENT``
      (info-only; the applier has already overwritten the stored
      value with the derived one).

    The conservative ``>=`` boundary treats equal timestamps as a
    potential override (the operator may have edited the value
    concurrently with the sync). This keeps the comparator aligned
    with the spec REQ-Hook scenario where ``updated_at > last_sync``
    is the explicit signal of a manual override.
    """
    if stored_state is None:
        return ReconciliationStatus.PENDING
    if derived_state == stored_state:
        return ReconciliationStatus.MATCHED
    if web_updated_at is not None and last_legacy_snapshot_at is not None:
        if web_updated_at >= last_legacy_snapshot_at:
            return ReconciliationStatus.NEEDS_REVIEW
    return ReconciliationStatus.DIVERGENT


# --- helpers -------------------------------------------------------------


def _is_null(value: Any) -> bool:
    """True when the value represents an empty end-date (NULL/None/``""``).

    The legacy VBA check ``IsDate(FSalida) = False AND IsNull(FSalida) = True``
    maps to Python ``None`` and the empty string in the snapshot.
    """
    return value is None or value == ""


def _is_date(value: Any) -> bool:
    """True when the value is a non-empty date.

    VBA's ``IsDate()`` returns True for any non-empty date/datetime. In
    Python we accept ``datetime`` instances and non-empty strings. A
    numeric value is treated as a non-date so an accidental integer
    PK never silently satisfies the death check.
    """
    if value is None:
        return False
    if isinstance(value, datetime):
        return True
    if isinstance(value, str):
        return value != ""
    return False


def _legacy_pk_as_str(row: dict[str, Any], field: str) -> str | None:
    """Return the legacy primary key as a ``str`` (or ``None`` when missing)."""
    raw = row.get(field)
    if raw is None:
        return None
    return str(raw)


def _latest_FEntregaAPropietario(
    entradas: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the latest entrada (by ``IDEntrada`` desc) with
    ``FEntregaAPropietario`` set, or ``None`` if no entrada carries a
    return-to-owner date.

    Replicates the semantics of ``DameUltimaFEntregaAPropietario`` in
    ``Funciones Generales.bas:1639-1665`` — the latest entry that has
    the owner-return date set determines whether the animal is
    ``Entregado`` (terminal) or ``Pendiente de Nueva Situación`` (still
    awaiting placement).
    """
    with_date = [e for e in entradas if _is_date(e.get("FEntregaAPropietario"))]
    if not with_date:
        return None
    return max(with_date, key=lambda e: e.get("IDEntrada", 0) or 0)


# Matches a derived "Fallecido (X)" string (single level, no nesting).
# Group 1 captures the inner state (e.g. "Albergue", "Desconocido").
# Used by ``_resolve_pre_death_state`` to make the helper idempotent
# against a cached ``Situacion`` that already carries a previously
# derived Fallecido string (regla de VBA prioridad 6 — ver
# ``lifecycle-state-resolver-extraction.md`` §10 Challenge #1).
_FALLECIDO_PARENTHETICAL_RE = re.compile(r"^Fallecido \((.+)\)$")


def _resolve_pre_death_state(ficha: dict[str, Any]) -> str:
    """Compute the parenthetical for a ``Fallecido ({pre})`` state.

    Mirrors the VBA logic in ``DameSituacion`` priority 6 (lines
    1270-1284):

      - If ``UltimoEstadoAntesDeFallecido`` is empty AND the previous
        ``Situacion`` does NOT already contain ``Fallecido``, the
        parenthetical is ``Desconocido``.
      - If the previous ``Situacion`` already carries a single-level
        ``Fallecido ({X})`` string (the death was registered and the
        cache was overwritten with the derived value), parse out ``X``
        so the caller wraps it exactly once. This is the
        idempotence rule: re-deriving MUST NOT nest to
        ``Fallecido (Fallecido (X))``.
      - If ``UltimoEstadoAntesDeFallecido`` is set but is NOT one of
        the four active states, fall back to ``Desconocido``.

    The function is pure and idempotent: feeding it the same
    ``Situacion`` cache that was previously emitted produces the
    same pre-state, never a deeper nest.
    """
    pre = ficha.get("UltimoEstadoAntesDeFallecido") or ""
    situacion_anterior = ficha.get("Situacion") or ""

    if pre == "" or pre is None:
        if "Fallecido" not in situacion_anterior:
            return "Desconocido"
        # Cached ``Situacion`` already carries a Fallecido ({X}) string
        # from a previous apply. Parse out the inner state so the caller
        # wraps it exactly once. If the cache is somehow not a clean
        # ``Fallecido (...)`` shape (e.g. legacy typo), fall back to
        # ``Desconocido`` instead of silently echoing the bad value.
        match = _FALLECIDO_PARENTHETICAL_RE.match(situacion_anterior)
        if match is not None:
            return match.group(1)
        return "Desconocido"

    if pre not in _VALID_PRE_DEATH_STATES:
        return "Desconocido"

    return pre


__all__ = [
    "DerivationKind",
    "DerivationResult",
    "STATE_ACOGIDA",
    "STATE_ADOPTADO",
    "STATE_ALBERGUE",
    "STATE_ENTREGADO",
    "STATE_FALLECIDO_DESCONOCIDO",
    "STATE_INCOHERENTE",
    "STATE_PENDIENTE_ENTRADA",
    "STATE_PENDIENTE_NUEVA_SITUACION",
    "compare_derived_to_stored",
    "derive_estado_actual_animal",
]
