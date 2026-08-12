"""Pure-domain port of the legacy Access/VBA ``DameSituacion()`` cascade.

LIFECYCLE-03 (issue #33) PR-A work-unit A2+A3. Implements the 6-level
priority cascade as a pure Python function so the cascade can be reused
by both the migration layer (``migration/derivation.py`` — redirected in
PR-C) and the web app's lifecycle writer
(``app/modules/animals/lifecycle_events.py`` — rewired in PR-C). No I/O,
no transport imports (AGENTS.md §31/§33.4): the function takes plain
dicts / lists and returns a ``DerivationResult``.

Priority cascade (mirrors ``docs/legacy-lifecycle-transition-rules.md``):

  P1 — Incoherente (multi-category active OR death + any active).
  P2 — No active, no death → Pendiente / Entregado.
  P3 — Single active intake → Albergue.
  P4 — Single active foster → Acogida.
  P5 — Single active adoption → Adoptado.
  P6 — Death → Fallecido (pre_death_state).

The 11 parametrized cases in
``tests/test_lifecycle_state_cascade.py`` (ported from
``tests/test_derivation_11cases.py:178-345``) freeze this contract.
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
    on category without parsing the localised string. The state string
    (``DerivationResult.state``) is what the spec writes to
    ``animal_current_state.current_state`` and is constrained by the
    CHECK enum in ``app/core/domain_lifecycle.py``.
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
# Centralised so the cascade and the future applier (PR-B) reference the
# same canonical strings. Mirrors the CHECK enum in
# ``app/core/domain_lifecycle.py::ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL``.

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

# Valid values for the ``Fallecido (X)`` parenthetical. Mirrors
# ``migration/derivation.py::_VALID_PRE_DEATH_STATES`` (lines 70-72).
_VALID_PRE_DEATH_STATES: frozenset[str] = frozenset(
    {
        STATE_ALBERGUE,
        STATE_ACOGIDA,
        STATE_ADOPTADO,
        STATE_ENTREGADO,
    }
)

# Sentinel for the parenthetical when ``UltimoEstadoAntesDeFallecido`` is
# empty / not in the valid set. The cascade writes it inside the
# ``Fallecido (...)`` wrapper.
PRE_DEATH_STATE_DESCONOCIDO = "Desconocido"


@dataclass(frozen=True, slots=True)
class DerivationResult:
    """Output of ``calculate_state``.

    ``state`` is the literal value the spec writes to
    ``animal_current_state.current_state`` (matches the CHECK constraint
    in ``app/core/domain_lifecycle.py``). ``kind`` is the categorical
    enum used for branching in callers.

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


# --- Cascade entry point -------------------------------------------------


def calculate_state(
    ficha: dict[str, Any] | None,
    entradas: Iterable[dict[str, Any]],
    acogidas: Iterable[dict[str, Any]],
    adopciones: Iterable[dict[str, Any]],
) -> DerivationResult:
    """Pure derivation of an animal's current state from 4 collections.

    Replicates the VBA ``DameSituacion()`` priority cascade as a pure
    Python function (no DB I/O, no events). The applier (PR-B) is
    responsible for plumbing the four web collections into the call and
    for persisting the resulting ``DerivationResult`` into
    ``animal_current_state``.

    ``ficha`` may be ``None`` (animal record not yet loaded) — the
    function treats it as an empty dict and falls through to the
    no-active no-death branch, returning ``Pendiente de Entrada`` if
    there are no ``entradas`` either.
    """
    ficha = _normalise_ficha(ficha)
    entradas_list = list(entradas)
    acogidas_list = list(acogidas)
    adopciones_list = list(adopciones)

    active_intakes = _select_active(entradas_list, "FSalida")
    active_fosters = _select_active(acogidas_list, "FFinal")
    active_adoptions = _select_active(adopciones_list, "FDevolucion")
    has_death = _is_date(ficha.get("FDefuncion"))

    # --- P1: Incoherente (conflict detection) -------------------------
    incoherente_reason = _detect_incoherence(
        active_intakes, active_fosters, active_adoptions, has_death
    )
    if incoherente_reason is not None:
        return DerivationResult(state=STATE_INCOHERENTE, kind=DerivationKind.INCOHERENTE)

    # --- P2: No active, no death --------------------------------------
    pendiente_result = _resolve_p2_pendiente(
        entradas_list,
        active_fosters=active_fosters,
        active_adoptions=active_adoptions,
        has_death=has_death,
    )
    if pendiente_result is not None:
        return pendiente_result

    # --- P3 / P4 / P5: single active placement ------------------------
    placement_result = _resolve_single_active(
        active_intakes, active_fosters, active_adoptions
    )
    if placement_result is not None:
        return placement_result

    # --- P6: Death ----------------------------------------------------
    if has_death:
        pre = _resolve_pre_death_state(ficha)
        return DerivationResult(
            state=_format_fallecido(pre),
            kind=DerivationKind.FALLECIDO,
            pre_death_state=pre,
        )

    # Defensive fallback — the cascade above should cover every input.
    # Returning ``Incoherente`` keeps the function total (no exceptions
    # surface into the applier) and matches the VBA behaviour of
    # defaulting to a "needs operator review" verdict on edge cases.
    return DerivationResult(state=STATE_INCOHERENTE, kind=DerivationKind.INCOHERENTE)


# --- Pure helpers (named to make the cascade self-documenting) ----------


def _normalise_ficha(ficha: dict[str, Any] | None) -> dict[str, Any]:
    """Return a dict regardless of ``None`` input (so the cascade can
    treat a missing ``ficha`` as empty without a guard at every callsite).
    """
    return ficha if ficha is not None else {}


def _select_active(
    rows: list[dict[str, Any]], end_date_field: str
) -> list[dict[str, Any]]:
    """Return the rows whose end-date column is empty (NULL/None/``""``).

    The legacy VBA check ``IsDate(FSalida) = False AND IsNull(FSalida) = True``
    maps to Python ``None`` and the empty string in the snapshot.
    Centralising the predicate means the cascade stays consistent if a
    future helper changes the definition of "active".
    """
    return [row for row in rows if _is_null(row.get(end_date_field))]


def _is_null(value: Any) -> bool:
    """True when the value represents an empty end-date (NULL/None/``""``).

    Mirrors the migration copy at ``migration/derivation.py::_is_null``.
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


def _detect_incoherence(
    active_intakes: list[dict[str, Any]],
    active_fosters: list[dict[str, Any]],
    active_adoptions: list[dict[str, Any]],
    has_death: bool,
) -> str | None:
    """P1 conflict detection.

    Returns a non-empty string naming the conflict when the animal is
    incoherent (multi-category active records, multiple active records
    in the same category, or death + any active). Returns ``None`` when
    the cascade should fall through to P2. The string is informational
    only; the cascade always returns ``STATE_INCOHERENTE``.

    VBA priority 1 (Funciones Generales.bas:1116+): any combination of
    cross-category active records OR death + any active record →
    ``Incoherente``. Also fires on multiple active records within a
    single category (legacy signals this with a ``#`` separator in the
    IDs; we detect it by length).
    """
    multiple_in_same_category = (
        len(active_intakes) > 1
        or len(active_fosters) > 1
        or len(active_adoptions) > 1
    )
    cross_category = (
        bool(active_intakes)
        and (bool(active_fosters) or bool(active_adoptions))
    ) or (
        bool(active_fosters)
        and (bool(active_intakes) or bool(active_adoptions))
    ) or (
        bool(active_adoptions)
        and (bool(active_intakes) or bool(active_fosters))
    )
    death_plus_active = has_death and bool(
        active_intakes or active_fosters or active_adoptions
    )
    if multiple_in_same_category:
        return "multiple_active_in_same_category"
    if cross_category:
        return "cross_category_active"
    if death_plus_active:
        return "death_plus_active"
    return None


def _resolve_p2_pendiente(
    entradas: list[dict[str, Any]],
    *,
    active_fosters: list[dict[str, Any]],
    active_adoptions: list[dict[str, Any]],
    has_death: bool,
) -> DerivationResult | None:
    """P2 — return the ``Pendiente de Entrada`` / ``Nueva Situación`` /
    ``Entregado`` verdict when the animal has no active placement of any
    kind and has not died. Returns ``None`` when the cascade should fall
    through to P3-P5 (the caller has already established at least one
    active record at this point).
    """
    if has_death:
        # P1 already handled death + active. Death alone falls through to
        # P6 below.
        return None
    if entradas and _any_empty_end_date(entradas, "FSalida"):
        # An active intake exists; P3 will handle it. P2 only applies
        # when every entrada is closed (or there are no entradas at all).
        return None
    if active_fosters or active_adoptions:
        # An active foster or adoption exists; P4 or P5 will handle it.
        return None

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


def _any_empty_end_date(rows: list[dict[str, Any]], field: str) -> bool:
    """True when any row carries an empty end-date in ``field``."""
    return any(_is_null(row.get(field)) for row in rows)


def _resolve_single_active(
    active_intakes: list[dict[str, Any]],
    active_fosters: list[dict[str, Any]],
    active_adoptions: list[dict[str, Any]],
) -> DerivationResult | None:
    """P3-P5 — return the active-placement verdict (Albergue/Acogida/Adoptado)
    when exactly one placement category is active. Returns ``None`` when
    the cascade should fall through to P6 (death) or the defensive
    fallback. P1 has already eliminated multi-active cases above.
    """
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


def _legacy_pk_as_str(row: dict[str, Any], field: str) -> str | None:
    """Return the legacy primary key as a ``str`` (or ``None`` when missing).
    Centralised so the cascade does not repeat the ``str(...)`` pattern
    in three places.
    """
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
    with_date = [
        e for e in entradas if _is_date(e.get("FEntregaAPropietario"))
    ]
    if not with_date:
        return None
    return max(with_date, key=lambda e: e.get("IDEntrada", 0) or 0)


# Matches a derived "Fallecido (X)" string (single level, no nesting).
# Group 1 captures the inner state (e.g. "Albergue", "Desconocido").
# Used by ``_resolve_pre_death_state`` to make the helper idempotent
# against a cached ``Situacion`` that already carries a previously
# derived Fallecido string (VBA prioridad 6 — see
# ``docs/legacy-lifecycle-transition-rules.md`` §10 Challenge #1).
_FALLECIDO_PARENTHETICAL_RE = re.compile(r"^Fallecido \((.+)\)$")


def _resolve_pre_death_state(ficha: dict[str, Any]) -> str:
    """Compute the parenthetical for a ``Fallecido ({pre})`` state.

    Mirrors the VBA logic in ``DameSituacion`` priority 6:

      - If ``UltimoEstadoAntesDeFallecido`` is empty AND the previous
        ``Situacion`` does NOT already contain ``Fallecido``, the
        parenthetical is ``Desconocido``.
      - If the previous ``Situacion`` already carries a single-level
        ``Fallecido ({X})`` string (the death was registered and the
        cache was overwritten with the derived value), parse out ``X``
        so the caller wraps it exactly once. This is the idempotence
        rule: re-deriving MUST NOT nest to
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
            return PRE_DEATH_STATE_DESCONOCIDO
        # Cached ``Situacion`` already carries a Fallecido ({X}) string
        # from a previous apply. Parse out the inner state so the caller
        # wraps it exactly once. If the cache is somehow not a clean
        # ``Fallecido (...)`` shape (e.g. legacy typo), fall back to
        # ``Desconocido`` instead of silently echoing the bad value.
        match = _FALLECIDO_PARENTHETICAL_RE.match(situacion_anterior)
        if match is not None:
            return match.group(1)
        return PRE_DEATH_STATE_DESCONOCIDO

    if pre not in _VALID_PRE_DEATH_STATES:
        return PRE_DEATH_STATE_DESCONOCIDO

    return pre


def _format_fallecido(pre: str) -> str:
    """Compose the canonical ``Fallecido ({pre})`` string.

    Centralised so the cascade produces the wrapped form consistently
    (the 5 variants are the only strings the CHECK enum allows).
    """
    return f"Fallecido ({pre})"


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
