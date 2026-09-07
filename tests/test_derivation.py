"""Tests for the derivation engine + comparator (PR 2/6, T2.1+T2.2+T2.3).

Replicates the VBA ``DameSituacion()`` priority cascade documented in
``docs/discovery/lifecycle-state-resolver-extraction.md §3``. The 11
parametrized cases come from §4 and tasks.md T2.3:

  1. Pendiente de Entrada
  2. Pendiente de Nueva Situación
  3. Entregado
  4. Albergue
  5. Acogida
  6. Adoptado
  7. Fallecido (Albergue)
  8. Fallecido (Acogida)
  9. Fallecido (Adoptado)
 10. Fallecido (Entregado)
 11. Incoherente

Plus 5 tests for the Q2 comparator (``compare_derived_to_stored``).
"""

from __future__ import annotations

import pytest

from migration.derivation import DerivationKind

# --- helpers --------------------------------------------------------------


def _ficha(**overrides: object) -> dict[str, object]:
    """Build a minimal ``TbFichaAnimal`` row.

    Defaults represent a healthy animal with no death and no cached
    ``UltimoEstadoAntesDeFallecido``. Tests override what they need.
    """
    base: dict[str, object] = {
        "NCHIP": "001",
        "FDefuncion": None,
        "Situacion": "",
        "UltimoEstadoAntesDeFallecido": None,
    }
    base.update(overrides)
    return base


def _entrada(
    *,
    identrada: int = 1,
    fentrada: object = "2024-01-01",
    fsalida: object | None = None,
    fentrega_propietario: object | None = None,
) -> dict[str, object]:
    return {
        "IDEntrada": identrada,
        "NChip": "001",
        "FEntrada": fentrada,
        "FSalida": fsalida,
        "FEntregaAPropietario": fentrega_propietario,
    }


def _acogida(
    *,
    idacogida: int = 1,
    ffinal: object | None = None,
) -> dict[str, object]:
    return {
        "IDAcogida": idacogida,
        "Nchip": "001",
        "FInicio": "2024-01-01",
        "FFinal": ffinal,
    }


def _adopcion(
    *,
    idadopcion: int = 1,
    fdevolucion: object | None = None,
) -> dict[str, object]:
    return {
        "IDAdopcion": idadopcion,
        "NCHIP": "001",
        "FAdopcion": "2024-01-01",
        "FDevolucion": fdevolucion,
    }


# --- TestDerivationEngine ------------------------------------------------


class TestDerivationEngine:
    """Pure-function tests for ``derive_estado_actual_animal``.

    Each parametrized case is a complete legacy snapshot for ONE animal;
    the function is pure and deterministic, so identical inputs MUST
    produce identical outputs (no DB, no clock, no global state).
    """

    @pytest.mark.parametrize(
        (
            "name",
            "ficha",
            "entradas",
            "acogidas",
            "adopciones",
            "expected_state",
            "expected_kind",
            "expected_pre_death_state",
            "expected_active",
        ),
        [
            # 1. Pendiente de Entrada — ficha exists, no FDefuncion, no entradas at all.
            (
                "pendiente_entrada",
                lambda: _ficha(),
                [],
                [],
                [],
                "Pendiente de Entrada",
                DerivationKind.PENDIENTE_ENTRADA,
                None,
                {"intake": None, "foster": None, "adoption": None},
            ),
            # 2. Pendiente de Nueva Situación — closed intake, no owner return.
            (
                "pendiente_nueva_situacion",
                lambda: _ficha(),
                [_entrada(fsalida="2024-02-01", fentrega_propietario=None)],
                [],
                [],
                "Pendiente de Nueva Situación",
                DerivationKind.PENDIENTE_NUEVA_SITUACION,
                None,
                {"intake": None, "foster": None, "adoption": None},
            ),
            # 3. Entregado — latest intake has FEntregaAPropietario set (terminal).
            (
                "entregado",
                lambda: _ficha(),
                [_entrada(fsalida="2024-02-01", fentrega_propietario="2024-03-01")],
                [],
                [],
                "Entregado",
                DerivationKind.ENTREGADO,
                None,
                {"intake": None, "foster": None, "adoption": None},
            ),
            # 4. Albergue — single active intake (FSalida null).
            (
                "albergue",
                lambda: _ficha(),
                [_entrada(identrada=42, fsalida=None)],
                [],
                [],
                "Albergue",
                DerivationKind.ALBERGUE,
                None,
                {"intake": "42", "foster": None, "adoption": None},
            ),
            # 5. Acogida — single active foster (FFinal null).
            (
                "acogida",
                lambda: _ficha(),
                [],
                [_acogida(idacogida=7, ffinal=None)],
                [],
                "Acogida",
                DerivationKind.ACOGIDA,
                None,
                {"intake": None, "foster": "7", "adoption": None},
            ),
            # 6. Adoptado — single active adoption (FDevolucion null).
            (
                "adoptado",
                lambda: _ficha(),
                [],
                [],
                [_adopcion(idadopcion=99, fdevolucion=None)],
                "Adoptado",
                DerivationKind.ADOPTADO,
                None,
                {"intake": None, "foster": None, "adoption": "99"},
            ),
            # 7. Fallecido (Albergue) — death + UltimoEstadoAntesDeFallecido="Albergue"
            # AND the foster already closed. Cascade P6 fires (no active records).
            (
                "fallecido_albergue",
                lambda: _ficha(FDefuncion="2024-06-01", UltimoEstadoAntesDeFallecido="Albergue"),
                [_entrada(fsalida="2024-05-01")],  # closed intake
                [],
                [],
                "Fallecido (Albergue)",
                DerivationKind.FALLECIDO,
                "Albergue",
                {"intake": None, "foster": None, "adoption": None},
            ),
            # 8. Fallecido (Acogida) — closed foster, pre_death_state="Acogida".
            (
                "fallecido_acogida",
                lambda: _ficha(FDefuncion="2024-06-01", UltimoEstadoAntesDeFallecido="Acogida"),
                [],
                [_acogida(idacogida=7, ffinal="2024-05-01")],
                [],
                "Fallecido (Acogida)",
                DerivationKind.FALLECIDO,
                "Acogida",
                {"intake": None, "foster": None, "adoption": None},
            ),
            # 9. Fallecido (Adoptado) — closed adoption, pre_death_state="Adoptado".
            (
                "fallecido_adoptado",
                lambda: _ficha(FDefuncion="2024-06-01", UltimoEstadoAntesDeFallecido="Adoptado"),
                [],
                [],
                [_adopcion(idadopcion=99, fdevolucion="2024-05-01")],
                "Fallecido (Adoptado)",
                DerivationKind.FALLECIDO,
                "Adoptado",
                {"intake": None, "foster": None, "adoption": None},
            ),
            # 10. Fallecido (Entregado) — closed owner-return, pre_death_state="Entregado".
            (
                "fallecido_entregado",
                lambda: _ficha(FDefuncion="2024-06-01", UltimoEstadoAntesDeFallecido="Entregado"),
                [_entrada(fsalida="2024-02-01", fentrega_propietario="2024-03-01")],
                [],
                [],
                "Fallecido (Entregado)",
                DerivationKind.FALLECIDO,
                "Entregado",
                {"intake": None, "foster": None, "adoption": None},
            ),
            # 11. Incoherente — cross-category active records (intake + adoption).
            (
                "incoherente_cross_category",
                lambda: _ficha(),
                [_entrada(fsalida=None)],
                [],
                [_adopcion(fdevolucion=None)],
                "Incoherente",
                DerivationKind.INCOHERENTE,
                None,
                {"intake": None, "foster": None, "adoption": None},
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
    def test_priority_cascade(
        self,
        name: str,  # noqa: ARG002  (param id used for readable pytest output)
        ficha: object,
        entradas: list[dict[str, object]],
        acogidas: list[dict[str, object]],
        adopciones: list[dict[str, object]],
        expected_state: str,
        expected_kind: object,
        expected_pre_death_state: str | None,
        expected_active: dict[str, str | None],
    ) -> None:
        """One parametrized test per cascade branch (11 cases).

        Each fixture is a complete legacy snapshot for ONE animal; the
        function is pure and deterministic, so identical inputs MUST
        produce identical outputs (no DB, no clock, no global state).
        The 4 ``ficha``/``entradas``/``acogidas``/``adopciones``
        arguments accept callables (for the ficha) and literals so
        pytest parametrize can render them in the test ID.
        """
        from migration.derivation import derive_estado_actual_animal

        ficha_value = ficha() if callable(ficha) else ficha  # type: ignore[arg-type]
        result = derive_estado_actual_animal(ficha_value, entradas, acogidas, adopciones)
        assert result.state == expected_state, (
            f"case {name!r}: expected state {expected_state!r}, got {result.state!r}"
        )
        assert result.kind is expected_kind, (
            f"case {name!r}: expected kind {expected_kind!r}, got {result.kind!r}"
        )
        assert result.pre_death_state == expected_pre_death_state
        assert result.active_intake_id == expected_active["intake"]
        assert result.active_foster_id == expected_active["foster"]
        assert result.active_adoption_id == expected_active["adoption"]

    def test_incoherente_death_plus_active_records(self) -> None:
        """Death + active intake triggers P1 (Incoherente), NOT Fallecido (Albergue).

        Documents the VBA priority-1 conflict detector: when the
        animal has both a death date AND an active record, the state
        is ``Incoherente`` regardless of ``UltimoEstadoAntesDeFallecido``.
        See ``lifecycle-state-resolver-extraction.md`` §3 P1.
        """
        from migration.derivation import (
            DerivationKind,
            derive_estado_actual_animal,
        )

        result = derive_estado_actual_animal(
            _ficha(FDefuncion="2024-06-01", UltimoEstadoAntesDeFallecido="Albergue"),
            [_entrada(identrada=42, fsalida=None)],
            [],
            [],
        )
        assert result.state == "Incoherente"
        assert result.kind is DerivationKind.INCOHERENTE


# --- TestPreDeathStateIdempotence (P1 #1 regression) ----------------------


class TestPreDeathStateIdempotence:
    """P1 #1 regression: ``_resolve_pre_death_state`` must be idempotent.

    The legacy cache ``TbFichaAnimal.Situacion`` is overwritten with the
    derived state after the first apply. If the second apply reads that
    cached value as ``Situacion`` AND ``UltimoEstadoAntesDeFallecido``
    is empty (typical for the "first death registration" pass), the
    derived state MUST NOT nest as ``"Fallecido (Fallecido (Albergue))"``.

    The chosen fix parses the parenthetical out of the cached
    ``Situacion`` so the caller wraps it exactly once. These tests
    freeze the contract: ``derive_estado_actual_animal`` is idempotent
    on the pre-death parenthetical even when the cache carries the
    previous derived value.
    """

    def test_no_nesting_when_situacion_already_fallecido_known_state(self) -> None:
        """``Situacion='Fallecido (Albergue)'`` + empty pre-state field stays single.

        The cached ``Situacion`` carries a previously derived
        ``Fallecido (Albergue)`` string. With ``UltimoEstadoAntesDeFallecido``
        empty (the common case for the first death pass) the function
        MUST surface ``Albergue`` so the caller wraps it once. Nesting
        like ``Fallecido (Fallecido (Albergue))`` is a regression of
        the VBA priority-6 idempotence rule (see
        ``lifecycle-state-resolver-extraction.md §10`` Challenge #1).
        """
        from migration.derivation import derive_estado_actual_animal

        result = derive_estado_actual_animal(
            _ficha(
                FDefuncion="2024-06-01",
                Situacion="Fallecido (Albergue)",
                UltimoEstadoAntesDeFallecido=None,
            ),
            [],
            [],
            [],
        )
        assert result.state == "Fallecido (Albergue)"
        assert result.pre_death_state == "Albergue"

    def test_no_nesting_when_situacion_already_fallecido_desconocido(self) -> None:
        """``Situacion='Fallecido (Desconocido)'`` + empty pre-state stays single.

        Mirror of the above for the ``Desconocido`` fallback: the cache
        carries ``Fallecido (Desconocido)``; re-derivation MUST yield
        ``Fallecido (Desconocido)`` again, never nest.
        """
        from migration.derivation import derive_estado_actual_animal

        result = derive_estado_actual_animal(
            _ficha(
                FDefuncion="2024-06-01",
                Situacion="Fallecido (Desconocido)",
                UltimoEstadoAntesDeFallecido=None,
            ),
            [],
            [],
            [],
        )
        assert result.state == "Fallecido (Desconocido)"
        assert result.pre_death_state == "Desconocido"

    def test_idempotent_on_cached_situacion_without_pre_state(self) -> None:
        """Calling twice with the second input caching the first output returns the same state.

        End-to-end idempotence contract: the legacy ``Situacion`` is
        written after the first apply with the derived value. The
        second apply MUST read that cached value and produce the SAME
        state — never ``Fallecido (Fallecido (Desconocido))``.
        """
        from migration.derivation import derive_estado_actual_animal

        ficha_first = _ficha(
            FDefuncion="2024-06-01",
            Situacion="",
            UltimoEstadoAntesDeFallecido=None,
        )
        result_first = derive_estado_actual_animal(ficha_first, [], [], [])

        # Simulate the legacy cache being written with the derived state.
        ficha_second = {**ficha_first, "Situacion": result_first.state}
        result_second = derive_estado_actual_animal(ficha_second, [], [], [])

        assert result_first.state == result_second.state
        assert result_first.pre_death_state == result_second.pre_death_state
        # Hard guard against the original regression: explicit no-nesting.
        assert "(Fallecido (Fallecido" not in result_second.state


# --- TestComparator ------------------------------------------------------


class TestDerivationComparator:
    """Q2 rule: derive → MATCHED / DIVERGENT / NEEDS_REVIEW / PENDING.

    Verdict matrix:

    - ``stored_state is None`` → PENDING (initial; never derived).
    - ``derived == stored`` → MATCHED (no operator action).
    - ``derived != stored`` AND ``web_updated_at > last_legacy_snapshot_at``
      (operator overrode the web value after the last sync) → NEEDS_REVIEW
      (operator decision required).
    - ``derived != stored`` otherwise → DIVERGENT (info-only; the applier
      has already overwritten the stored value with the derived one).
    """

    def test_matched_when_derived_equals_stored(self) -> None:
        """Derived value equals the stored web value → MATCHED."""
        from datetime import UTC, datetime

        from migration.derivation import compare_derived_to_stored
        from migration.reconcile import ReconciliationStatus

        verdict = compare_derived_to_stored(
            derived_state="Albergue",
            stored_state="Albergue",
            web_updated_at=datetime(2026, 6, 21, 10, 0, tzinfo=UTC),
            last_legacy_snapshot_at=datetime(2026, 6, 20, 10, 0, tzinfo=UTC),
        )
        assert verdict is ReconciliationStatus.MATCHED

    def test_pending_when_stored_is_none(self) -> None:
        """Initial state (``stored_state is None``) → PENDING."""
        from datetime import UTC, datetime

        from migration.derivation import compare_derived_to_stored
        from migration.reconcile import ReconciliationStatus

        verdict = compare_derived_to_stored(
            derived_state="Albergue",
            stored_state=None,
            web_updated_at=datetime(2026, 6, 21, 10, 0, tzinfo=UTC),
            last_legacy_snapshot_at=datetime(2026, 6, 20, 10, 0, tzinfo=UTC),
        )
        assert verdict is ReconciliationStatus.PENDING

    def test_needs_review_when_web_overrode_after_sync(self) -> None:
        """Derived ≠ stored AND web was edited AFTER the last sync → NEEDS_REVIEW.

        Q2 path: operator manually overrode the web value, so the
        applier does NOT overwrite it; surfaces in the CLI.
        """
        from datetime import UTC, datetime

        from migration.derivation import compare_derived_to_stored
        from migration.reconcile import ReconciliationStatus

        verdict = compare_derived_to_stored(
            derived_state="Adoptado",
            stored_state="Acogida",  # web was manually set to Acogida
            web_updated_at=datetime(2026, 6, 21, 12, 0, tzinfo=UTC),  # AFTER sync
            last_legacy_snapshot_at=datetime(2026, 6, 21, 10, 0, tzinfo=UTC),
        )
        assert verdict is ReconciliationStatus.NEEDS_REVIEW

    def test_divergent_when_no_web_override(self) -> None:
        """Derived ≠ stored AND no recent web edit → DIVERGENT.

        Info-only verdict: the applier has already overwritten the
        stored value with the derived one. The operator does not need
        to act (the case appears in ``needs_review`` count for
        visibility but does NOT block the run).
        """
        from datetime import UTC, datetime

        from migration.derivation import compare_derived_to_stored
        from migration.reconcile import ReconciliationStatus

        verdict = compare_derived_to_stored(
            derived_state="Adoptado",
            stored_state="Acogida",
            web_updated_at=datetime(2026, 6, 20, 9, 0, tzinfo=UTC),  # BEFORE sync
            last_legacy_snapshot_at=datetime(2026, 6, 21, 10, 0, tzinfo=UTC),
        )
        assert verdict is ReconciliationStatus.DIVERGENT

    def test_needs_review_takes_priority_over_divergent(self) -> None:
        """When timestamps are equal, the comparator errs on the side of NEEDS_REVIEW.

        Conservative rule: if the web update is at-or-after the last
        legacy snapshot, the operator may have intentionally overridden
        the value; flag for review instead of silently overwriting.
        """
        from datetime import UTC, datetime

        from migration.derivation import compare_derived_to_stored
        from migration.reconcile import ReconciliationStatus

        ts = datetime(2026, 6, 21, 10, 0, tzinfo=UTC)
        verdict = compare_derived_to_stored(
            derived_state="Adoptado",
            stored_state="Acogida",
            web_updated_at=ts,
            last_legacy_snapshot_at=ts,
        )
        assert verdict is ReconciliationStatus.NEEDS_REVIEW


# --- Mutation-killer cases (issue #433) -----------------------------------
#
# Targeted table-driven cases to kill the 38 surviving mutants measured by
# cosmic-ray on 2026-08-06. Each case pins a specific input/output tuple that
# distinguishes one or more of the surviving mutation families: boolean
# (``or``→``and``), comparison (``==``→``is``, ``!=``→``>``, ``>``→``>=``),
# number replacement (``1``→``0``), or ``AddNot``.
#
# Conventions:
#   - Multi-clause boolean predicates get one case per clause with the other
#     clauses held false, so a flipped connective causes a wrong verdict.
#   - Identity comparisons (``is``) are flipped by passing a value equal to
#     the constant by content but NOT identical to it (a non-interned
#     ``"".join([])`` or a fresh string built via list comprehension).
#   - Boundary literals (``> 1``, ``== 1``, ``!= ""``, ``0``) get an explicit
#     case at each side of the boundary.


def _non_interned(s: str) -> str:
    """Return a string equal to ``s`` but NOT identical to the literal.

    ``"".join([<chars>])`` and list-comprehension-built strings return
    fresh objects whose identity differs from the canonical literal for
    *non-empty* inputs. CPython always interns empty strings regardless
    of how they are constructed, so this helper is only effective for
    non-empty inputs.

    Note: on CPython, empty strings are always interned (``""  is  ""``
    is True), so any ``== ""`` → ``is ""`` mutation cannot be killed
    by feeding an empty string here. The helper exists to provide a
    non-interned string for non-empty comparisons (e.g.,
    ``"Albergue"``), which IS non-interned after this round-trip.
    """
    # Reverse then reverse back: round-trips via ``"".join``, which
    # returns a fresh string for non-empty inputs.
    return "".join([c for c in s])

