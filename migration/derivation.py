"""Derivation engine for ``animal_current_state``.

Thin wrapper around the lifecycle slice's domain cascade
(``app.modules.lifecycle.domain.animal_state.calculate_state``).
The migration layer used to carry its own copy of the VBA
``DameSituacion()`` priority cascade; LIFECYCLE-03 (issue #33) PR-C
redirects the migration layer to import the pure domain function so
the two implementations cannot drift (AGENTS.md §22 single-seam rule).

The migration layer's contract is unchanged: ``derive_estado_actual_animal``
takes the 4 legacy-shape collections (``tb_ficha``, ``tb_entradas``,
``tb_acogidas``, ``tb_adopciones``) and returns a ``DerivationResult``
carrying the derived state string + the categorical kind + the active
placement IDs (legacy PKs). The domain function consumes the same
field names (``FSalida`` / ``FFinal`` / ``FDevolucion`` /
``FDefuncion`` / ``UltimoEstadoAntesDeFallecido``), so no
``_legacy_to_web_row`` mapper is needed — the projection happens in
the LocalBackend adapter's SQL (``entradas.id AS "IDEntrada"`` etc.) and
the migration layer reads the legacy-shape rows directly.

The companion comparator ``compare_derived_to_stored`` implements the
post-application Q2 rule (matched / divergent / needs_review /
pending) and is the building block the applier hook uses to populate
``animal_current_state.reconciliation_status``.

Permission to import the domain layer is granted by the
``PURE_ALLOWED_SUBPACKAGES`` allowlist in
``scripts/migration_boundaries_policy.py`` — the domain is pure
(Protocol-typed, no I/O, no transport), and the import is symmetric
with the existing ``app.core.data_access.SqlExecutor`` Protocol-import
pattern at line 50-51 of that same file.

Re-exports
----------

``DerivationKind`` and ``DerivationResult`` are re-exported from the
domain so existing migration callers (``reconcile.py``,
``semantic_events.py``, the 11-case regression suite, etc.) continue
to import them from ``migration.derivation`` without change. The
domain's ``DerivationResult`` is structurally compatible (same field
names + defaults); only the static ``kind`` annotation differs
(``DerivationKind`` locally vs ``object`` in the domain to avoid a
module-load cycle). The migration's ``compare_derived_to_stored``
reads ``derived.state`` (a ``str``) so the annotation change is
invisible at runtime.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from app.modules.lifecycle.domain.animal_state import (
    DerivationKind,
    DerivationResult,
    calculate_state,
)
from migration.reconcile import ReconciliationStatus

# --- State value constants -----------------------------------------------
#
# Re-exported from the domain so the comparator and downstream callers
# can keep importing them from ``migration.derivation``. The full set
# (including the 5 ``STATE_FALLECIDO_*`` variants) is in the domain's
# ``constants.py``; the migration layer only references the 8 core
# states plus ``STATE_FALLECIDO_DESCONOCIDO`` (used by older code
# paths that hard-coded the parenthetical).
STATE_PENDIENTE_ENTRADA = "Pendiente de Entrada"
STATE_PENDIENTE_NUEVA_SITUACION = "Pendiente de Nueva Situación"
STATE_ALBERGUE = "Albergue"
STATE_ACOGIDA = "Acogida"
STATE_ADOPTADO = "Adoptado"
STATE_ENTREGADO = "Entregado"
STATE_INCOHERENTE = "Incoherente"
STATE_FALLECIDO_DESCONOCIDO = "Fallecido (Desconocido)"


# --- Derivation entry point ----------------------------------------------


def derive_estado_actual_animal(
    tb_ficha: dict[str, Any] | None,
    tb_entradas: Iterable[dict[str, Any]],
    tb_acogidas: Iterable[dict[str, Any]],
    tb_adopciones: Iterable[dict[str, Any]],
) -> DerivationResult:
    """Pure derivation of an animal's current state from 4 legacy collections.

    Thin wrapper around
    :func:`app.modules.lifecycle.domain.animal_state.calculate_state`.
    The function preserves the migration layer's pre-PR-C public
    contract (same name, same signature, same return type) so the 11
    parametrized cases in ``tests/test_derivation_11cases.py`` and
    the callers in ``migration/reconcile.py`` +
    ``migration/semantic_events.py`` continue to work unchanged.

    The domain function implements the P1-P6 priority cascade:

      P1 — Incoherente (multi-category active OR death+active).
      P2 — No active, no death → Pendiente / Entregado.
      P3 — Single active intake → Albergue.
      P4 — Single active foster → Acogida.
      P5 — Single active adoption → Adoptado.
      P6 — Death → Fallecido (pre_death_state).

    The function is deterministic for a given input. ``tb_ficha``
    may be ``None`` (animal record not yet loaded) — the domain
    cascade treats it as an empty dict and falls through to the
    no-active no-death branch, returning ``Pendiente de Entrada``
    if there are no ``tb_entradas`` either.
    """
    return calculate_state(
        ficha=tb_ficha,
        entradas=tb_entradas,
        acogidas=tb_acogidas,
        adopciones=tb_adopciones,
    )


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
