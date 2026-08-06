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


class TestMutationKillersLine149:
    """Decide each clause of ``derivation.py:149`` independently.

    The priority-cascade's first conflict detector is

        ``len(active_intakes) > 1 or len(active_fosters) > 1
         or len(active_adoptions) > 1``

    Existing tests only walk cross-category cases (one row in two different
    lists); they never hold each ``len() > 1`` independently true with the
    other two clauses false. Five mutants survive that gap. This class
    adds one parametrized case per clause direction plus the boundary at
    exactly one row so ``> 1`` vs ``>= 1`` is pinned.
    """

    @pytest.mark.parametrize(
        (
            "intake_rows",
            "foster_rows",
            "adoption_rows",
            "expected_state",
        ),
        [
            # --- All clauses false ---
            (
                [_entrada(identrada=1, fsalida=None)],
                [],
                [],
                "Albergue",
            ),
            # --- intake clause true alone ---
            (
                [
                    _entrada(identrada=1, fsalida=None),
                    _entrada(identrada=2, fsalida=None),
                ],
                [],
                [],
                "Incoherente",
            ),
            # --- foster clause true alone ---
            (
                [],
                [
                    _acogida(idacogida=1, ffinal=None),
                    _acogida(idacogida=2, ffinal=None),
                ],
                [],
                "Incoherente",
            ),
            # --- adoption clause true alone ---
            (
                [],
                [],
                [
                    _adopcion(idadopcion=1, fdevolucion=None),
                    _adopcion(idadopcion=2, fdevolucion=None),
                ],
                "Incoherente",
            ),
            # --- All three clauses true ---
            (
                [
                    _entrada(identrada=1, fsalida=None),
                    _entrada(identrada=2, fsalida=None),
                ],
                [
                    _acogida(idacogida=1, ffinal=None),
                    _acogida(idacogida=2, ffinal=None),
                ],
                [
                    _adopcion(idadopcion=1, fdevolucion=None),
                    _adopcion(idadopcion=2, fdevolucion=None),
                ],
                "Incoherente",
            ),
            # --- Boundary: exactly 1 per category → NOT incoherente,
            # but rather cross_category triggers (intake + adoption) ---
            (
                [_entrada(identrada=1, fsalida=None)],
                [],
                [_adopcion(idadopcion=2, fdevolucion=None)],
                "Incoherente",
            ),
        ],
        ids=[
            "single_intake_no_conflict",
            "two_active_intakes_only",
            "two_active_fosters_only",
            "two_active_adoptions_only",
            "all_three_categories_overflow",
            "one_each_cross_category",
        ],
    )
    def test_multiple_in_same_category_each_clause_independent(
        self,
        intake_rows: list[dict[str, object]],
        foster_rows: list[dict[str, object]],
        adoption_rows: list[dict[str, object]],
        expected_state: str,
    ) -> None:
        """Each ``len(...) > 1`` is decided in isolation.

        A mutation that flips one of the three ``or`` connectives to ``and``
        would require ALL three lists to overflow before returning
        ``Incoherente``; the single-clause cases above make that wrong.
        A mutation that changes ``> 1`` to ``>= 1`` would make the
        ``two_active_intakes_only`` case still pass (since 2 >= 1) but
        ALSO start returning Incoherente for a single intake; the
        ``single_intake_no_conflict`` case pins the lower boundary.
        """
        from migration.derivation import derive_estado_actual_animal

        result = derive_estado_actual_animal(
            _ficha(), intake_rows, foster_rows, adoption_rows
        )
        assert result.state == expected_state


class TestMutationKillersLine153:
    """Decide each inner clause of ``derivation.py:153`` independently.

    The cross-category clause for fosters reads

        ``(active_fosters and (active_intakes or active_adoptions))``

    Existing tests only hit the foster+intake path. The adoptions-only
    half of the inner ``or`` is unasserted, and the outer ``and`` is
    unverified in isolation. This class adds the missing axes.
    """

    @pytest.mark.parametrize(
        ("foster_rows", "intake_rows", "adoption_rows", "expected_state"),
        [
            # only fosters, nothing else → not cross-category, just ACOGIDA
            (
                [_acogida(idacogida=7, ffinal=None)],
                [],
                [],
                "Acogida",
            ),
            # fosters + intakes (inner-or's first half alone)
            (
                [_acogida(idacogida=7, ffinal=None)],
                [_entrada(identrada=1, fsalida=None)],
                [],
                "Incoherente",
            ),
            # fosters + adoptions (inner-or's second half alone)
            (
                [_acogida(idacogida=7, ffinal=None)],
                [],
                [_adopcion(idadopcion=99, fdevolucion=None)],
                "Incoherente",
            ),
            # fosters + intakes + adoptions
            (
                [_acogida(idacogida=7, ffinal=None)],
                [_entrada(identrada=1, fsalida=None)],
                [_adopcion(idadopcion=99, fdevolucion=None)],
                "Incoherente",
            ),
        ],
        ids=[
            "fosters_only_is_not_cross_category",
            "fosters_and_intakes_cross_category",
            "fosters_and_adoptions_cross_category",
            "fosters_with_intake_and_adoption",
        ],
    )
    def test_fosters_cross_category_inner_or_each_half_independent(
        self,
        foster_rows: list[dict[str, object]],
        intake_rows: list[dict[str, object]],
        adoption_rows: list[dict[str, object]],
        expected_state: str,
    ) -> None:
        """The ``or`` inside the foster cross-category clause has two halves.

        A mutation that flips ``or`` to ``and`` between ``active_intakes``
        and ``active_adoptions`` would only fire when BOTH are present;
        each half alone in the parametrization above makes a flipped
        connective produce a wrong verdict.
        """
        from migration.derivation import derive_estado_actual_animal

        result = derive_estado_actual_animal(
            _ficha(), intake_rows, foster_rows, adoption_rows
        )
        assert result.state == expected_state


class TestMutationKillersLine184Eq1:
    """Boundary: ``len(active_X) == 1`` exactly vs higher vs zero.

    Lines 184, 193, 202 each carry a literal ``== 1`` comparison:
        ``if len(active_intakes) == 1``,
        ``if len(active_fosters) == 1``,
        ``if len(active_adoptions) == 1``.
    Existing tests cover the single-row happy path; they never pin
    the boundary at exactly one row vs zero rows vs two rows. A
    ``== 1`` → ``== 0`` mutation would silently reroute the cascade
    and pick the wrong PK (or none).
    """

    def test_zero_active_intakes_is_not_albergue(self) -> None:
        """Zero intakes + zero other actives → Pendiente de Entrada (not Albergue).

        The branch on line 184 is False, so the cascade falls through
        to P2. A mutation ``== 1`` → ``== 0`` would call this branch
        True (an empty list, length 0, satisfies ``== 0``) and return
        ALBERGUE with ``active_intake_id=None``. Pinning ``Pendiente
        de Entrada`` here kills that mutation.
        """
        from migration.derivation import derive_estado_actual_animal

        result = derive_estado_actual_animal(_ficha(), [], [], [])
        assert result.state == "Pendiente de Entrada"

    def test_two_active_intakes_does_not_satisfy_eq_1(self) -> None:
        """Two intakes must NOT be selected by ``len == 1``: Incoherente takes over.

        P1's multiple-in-same-category detector still fires under
        ``== 1`` → ``== 2`` (both versions reject length 1), but under
        ``== 1`` → ``== 0`` the len=0 case stays at P2 while the
        len=2 case would also miss line 184 and reach P3 via the
        overflow branch. The simpler pin: assert Incoherente is the
        unambiguous outcome whenever two intakes overflow, regardless
        of how the cascade fires.
        """
        from migration.derivation import derive_estado_actual_animal

        result = derive_estado_actual_animal(
            _ficha(),
            [
                _entrada(identrada=1, fsalida=None),
                _entrada(identrada=2, fsalida=None),
            ],
            [],
            [],
        )
        assert result.state == "Incoherente"

    def test_single_active_intake_satisfies_eq_1(self) -> None:
        """Exactly one active intake → ALBERGUE with the right PK.

        A mutation ``== 1`` → ``== 0`` would let the branch skip an
        empty list (no PK) AND skip the single-row case, so pin that
        the PK is preserved exactly when the count is 1.
        """
        from migration.derivation import derive_estado_actual_animal

        result = derive_estado_actual_animal(
            _ficha(),
            [_entrada(identrada=42, fsalida=None)],
            [],
            [],
        )
        assert result.state == "Albergue"
        assert result.active_intake_id == "42"

    def test_single_active_foster_satisfies_eq_1(self) -> None:
        """Exactly one active foster → ACOGIDA with the right PK.

        Mirrors the intake case at line 193: ``len(active_fosters) ==
        1`` must select the foster branch. Pinned here so a
        ``== 1`` → ``== 0`` mutation on the foster branch is caught.
        """
        from migration.derivation import derive_estado_actual_animal

        result = derive_estado_actual_animal(
            _ficha(),
            [],
            [_acogida(idacogida=7, ffinal=None)],
            [],
        )
        assert result.state == "Acogida"
        assert result.active_foster_id == "7"

    def test_single_active_adoption_satisfies_eq_1(self) -> None:
        """Exactly one active adoption → ADOPTADO with the right PK.

        Mirrors the intake and foster cases at line 202:
        ``len(active_adoptions) == 1`` must select the adoption branch.
        """
        from migration.derivation import derive_estado_actual_animal

        result = derive_estado_actual_animal(
            _ficha(),
            [],
            [],
            [_adopcion(idadopcion=99, fdevolucion=None)],
        )
        assert result.state == "Adoptado"
        assert result.active_adoption_id == "99"


class TestMutationKillersLine266:
    """Pinned distinctions for ``compare_derived_to_stored`` line 266.

    Surviving mutants are ``==`` → ``is`` and ``==`` → ``is not``: for
    string literals the CPython interpreter interning means
    ``"Albergue" is "Albergue"`` is True at module scope, so the
    existing MATCHED test passes under mutation. We force a non-interned
    equal string in stored_state and assert the contract holds anyway.
    """

    def test_matched_when_stored_is_non_interned_equal(self) -> None:
        """``derived_state == stored_state`` returns MATCHED even when
        ``is`` would say False: a non-interned equal string.
        """
        from datetime import UTC, datetime

        from migration.derivation import compare_derived_to_stored
        from migration.reconcile import ReconciliationStatus

        verdict = compare_derived_to_stored(
            derived_state="Albergue",
            stored_state=_non_interned("Albergue"),
            web_updated_at=datetime(2026, 6, 21, 10, 0, tzinfo=UTC),
            last_legacy_snapshot_at=datetime(2026, 6, 20, 10, 0, tzinfo=UTC),
        )
        assert verdict is ReconciliationStatus.MATCHED

    def test_divergent_when_strings_lie_in_different_ordering_buckets(self) -> None:
        """``derived_state != stored_state`` returns DIVERGENT.

        Kills any ``==`` → ``>=`` or ``==`` → ``<=`` survival: when the
        two strings are unequal, ``>=`` and ``<=`` still evaluate against
        lexicographic order, and a numeric lucky match would flip the
        verdict. Pinning derived='Z-state' vs stored='A-other' makes
        both ``>=`` and ``<=`` return True under certain operator
        mutations, while the original ``==`` is unambiguously False.
        """
        from datetime import UTC, datetime

        from migration.derivation import compare_derived_to_stored
        from migration.reconcile import ReconciliationStatus

        verdict = compare_derived_to_stored(
            derived_state="Z-state",
            stored_state="A-other",
            web_updated_at=datetime(2026, 6, 20, 9, 0, tzinfo=UTC),
            last_legacy_snapshot_at=datetime(2026, 6, 21, 10, 0, tzinfo=UTC),
        )
        assert verdict is ReconciliationStatus.DIVERGENT


class TestMutationKillersLine283:
    """Table-driven cases for ``_is_null`` (``derivation.py:283``).

    Surviving mutants: ``is None`` → ``== None`` (an instance with a
    permissive ``__eq__``), ``== ""`` → ``is ""`` (a non-interned equal
    string), and ``or`` → ``and`` (an empty-list falsy value). The
    parametrization walks each combination that distinguishes one
    surviving mutation from the original.
    """

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            # Boundary: None is empty.
            (None, True),
            # Boundary: empty string is empty.
            ("", True),
            # Non-interned empty string — same value, different identity.
            ("".join([]), True),
            # Non-empty string is NOT empty.
            ("x", False),
            # Falsy non-empty values are NOT empty.
            (0, False),
            (False, False),
            # Non-string / non-empty compound.
            ([], False),
            ([1], False),
        ],
        ids=[
            "none_is_empty",
            "interned_empty_is_empty",
            "non_interned_empty_is_empty",
            "non_empty_string",
            "zero_int",
            "false_bool",
            "empty_list",
            "non_empty_list",
        ],
    )
    def test_is_null_distinguishes_each_input(self, value: object, expected: bool) -> None:
        """Pin the empty/non-empty contract on ``_is_null``.

        The non-interned-empty case (``"".join([])``) is the load-bearing
        one: under ``==`` → ``is`` the function would return False for
        it (identity check fails), so pinning True here kills that
        surviving mutation. The integer and list cases pin the falsy-
        but-not-empty behavior that ``or`` → ``and`` would also break:
        ``0 and 0`` is 0 (falsy) so the ``and`` mutant would return
        False for None-OR-empty cases that are True under ``or``.
        """
        from migration.derivation import _is_null

        assert _is_null(value) is expected


class TestMutationKillersLine299:
    """Boundary cases for ``_is_date`` (``derivation.py:299``).

    Surviving mutations on the string branch are mostly
    ``!=`` → ``>=``, ``!=`` → ``<=`` (same for non-empty strings, but
    True vs False for the empty case) and ``!=`` → ``is not`` (False
    for interned ``""`` but True for a non-interned equal). The empty
    string and the non-interned empty are the cases that flip.
    """

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            # Boundary: interned empty string is NOT a date.
            ("", False),
            # Non-interned equal empty is NOT a date (kills ``!=`` → ``is not``).
            ("".join([]), False),
            # Non-empty strings ARE dates.
            ("x", True),
            ("2024-06-01", True),
            # Non-string types follow the existing branches.
            (None, False),
            (0, False),
            (False, False),
        ],
        ids=[
            "interned_empty_is_not_a_date",
            "non_interned_empty_is_not_a_date",
            "single_char_string",
            "iso_date_string",
            "none",
            "integer_pk",
            "false_bool",
        ],
    )
    def test_is_date_string_branch(self, value: object, expected: bool) -> None:
        """Pin the string-branch of ``_is_date``.

        ``"" >= ""`` is True and ``"" <= ""`` is True, while
        ``"" != ""`` is False: a mutated ``!=`` → ``>=`` would return
        True for the empty string where the original returns False,
        so each empty-string case below catches a flipped operator.
        The non-interned empty catches ``!=`` → ``is not`` (which
        returns True for ``"".join([]) is not ""`` even though the
        strings are content-equal).
        """
        from datetime import datetime

        from migration.derivation import _is_date

        assert _is_date(value) is expected
        # Sanity: a datetime instance must still satisfy the contract
        # even though it bypasses the string branch.
        assert _is_date(datetime(2024, 6, 1)) is True


class TestMutationKillersLine327:
    """Cases for ``_latest_FEntregaAPropietario`` (``derivation.py:327``).

    The expression is ``max(with_date, key=lambda e: e.get("IDEntrada",
    0) or 0)``. Surviving mutants target:

      1. ``max`` → ``min`` (pick the lowest IDEntrada instead of the
         highest).
      2. ``or`` → ``and`` (truthy IDEntrada would be replaced by the
         second ``0`` instead of the first).
      3. Number replacements on each ``0`` (default arg of ``get``,
         and the right-hand side of the ``or``).

    Each parametrized case below holds a different mix of present /
    missing / falsy IDEntrada to flip one or more of these mutations.
    """

    @staticmethod
    def _row(identrada: object, owner_return: str = "2024-03-01") -> dict[str, object]:
        return {
            "IDEntrada": identrada,
            "NChip": "001",
            "FEntrada": "2024-01-01",
            "FSalida": "2024-02-01",
            "FEntregaAPropietario": owner_return,
        }

    def test_picks_highest_IDEntrada_among_multiple(self) -> None:
        """Two rows with owner-return; max IDEntrada wins (kills ``min`` mutation).

        Under ``max`` → ``min`` the function would return the row with
        IDEntrada=5 instead of IDEntrada=10. Under ``or`` → ``and``
        both rows would receive key=0 (since ``x and 0`` is 0 for any
        truthy ``x``) and tie-break arbitrarily — pinning the
        ``IDEntrada=10`` outcome kills that flip as well.
        """
        from migration.derivation import _latest_FEntregaAPropietario

        entradas = [
            self._row(5),
            self._row(10),
        ]
        result = _latest_FEntregaAPropietario(entradas)
        assert result == self._row(10)

    def test_handles_missing_IDEntrada_key(self) -> None:
        """A row without ``IDEntrada`` still resolves to that row when alone.

        Pinned because the cascade falls to P5→Acogida / P3→Albergue
        only if the lookup returns a row: a mutation on
        ``get("IDEntrada", 0)``'s default that breaks the lookup would
        change P2's choice between ``Entregado`` and ``Pendiente de
        Nueva Situación``. Here we directly invoke the helper to keep
        the test local.
        """
        from migration.derivation import _latest_FEntregaAPropietario

        entradas: list[dict[str, object]] = [
            self._row(None),  # missing key
        ]
        result = _latest_FEntregaAPropietario(entradas)
        assert result == self._row(None)

    def test_picks_truthy_IDEntrada_over_missing_key(self) -> None:
        """Truthy ``IDEntrada`` wins over a missing-key tie.

        Under ``or`` → ``and`` the truthy row would receive key=0 (since
        ``truthy and 0`` is 0) just like the missing-key row, making the
        tie arbitrary; pinning the truthy-IDEntrada outcome here kills
        the ``or`` → ``and`` mutation.
        """
        from migration.derivation import _latest_FEntregaAPropietario

        entradas: list[dict[str, object]] = [
            self._row(None),  # missing key → key=0
            self._row(7),     # truthy key=7
        ]
        result = _latest_FEntregaAPropietario(entradas)
        assert result == self._row(7)

    def test_falsy_zero_IDEntrada_loses_to_truthy_IDEntrada(self) -> None:
        """Row with ``IDEntrada=0`` (falsy) is correctly ranked below truthy rows.

        Under ``or`` → ``and`` both rows would receive key=0 again;
        this case (truthy=7, falsy=0) pins the truthy winner. Under
        any ``0`` → ``1`` mutation on the trailing ``or 0``, the
        falsy-zero row would receive key=1, which still loses to 7 but
        might beat other rows — this test only catches the ``or`` flip,
        which is the surviving mutation of interest.
        """
        from migration.derivation import _latest_FEntregaAPropietario

        entradas: list[dict[str, object]] = [
            self._row(0),
            self._row(7),
        ]
        result = _latest_FEntregaAPropietario(entradas)
        assert result == self._row(7)


class TestMutationKillersLine364:
    """Boundary cases for ``_resolve_pre_death_state`` (``derivation.py:364``).

    Surviving mutants target ``pre == ""`` (e.g., ``==`` → ``is`` on the
    empty string) and ``pre is None``. The function normalizes ``pre``
    via ``ficha.get("UltimoEstadoAntesDeFallecido") or ""`` so most
    mutations on the empty-string identity check are unreachable; we
    still pin each branch of the resulting control flow so an
    ``or`` → ``and``
    flip on line 364 (which would skip the death-default branch for
    no-pre-but-cached-Situacion cases) cannot regress silently.
    """

    @pytest.mark.parametrize(
        ("ultimo_estado", "situacion", "expected_pre"),
        [
            # None + clean empty cache → "Desconocido" (P6 fallback).
            (None, "", "Desconocido"),
            # None + cached Fallecido (...) → unparsed inner state.
            (None, "Fallecido (Albergue)", "Albergue"),
            (None, "Fallecido (Acogida)", "Acogida"),
            (None, "Fallecido (Desconocido)", "Desconocido"),
            # Cache with malformed Fallecido line falls back to "Desconocido".
            (None, "Fallecido (not-closed-paren", "Desconocido"),
            # Valid pre-state passes through the second branch.
            ("Albergue", "", "Albergue"),
            ("Acogida", "", "Acogida"),
            ("Adoptado", "", "Adoptado"),
            ("Entregado", "", "Entregado"),
            # Invalid pre-state values fall back to "Desconocido".
            ("Invalid", "", "Desconocido"),
            ("fallECIDO", "", "Desconocido"),
        ],
        ids=[
            "none_no_cache",
            "none_cached_albergue",
            "none_cached_acogida",
            "none_cached_desconocido",
            "none_cached_malformed",
            "pre_albergue",
            "pre_acogida",
            "pre_adoptado",
            "pre_entregado",
            "pre_invalid_unknown",
            "pre_invalid_fallecido_casing",
        ],
    )
    def test_resolve_pre_death_state_pins_each_branch(
        self,
        ultimo_estado: str | None,
        situacion: str,
        expected_pre: str,
    ) -> None:
        """Walk every branch of ``_resolve_pre_death_state``.

        The ``None``-and-cache cases exercise the line-364 path; an
        ``or`` → ``and`` mutation on line 364 would skip the cache
        parsing branch when ``pre == ""`` is True and ``pre is None`` is
        False (which is exactly the situation after ``... or ""``
        coerces None), so any test where ``expected_pre`` is NOT
        ``"Desconocido"`` while pre-empty=True and the inner ``"Fallecido"
        in situacion_anterior`` is True will fail under the flipped
        connective. The valid-state and invalid-state cases pin the
        downstream branch.
        """
        from migration.derivation import _resolve_pre_death_state

        ficha: dict[str, object] = {
            "UltimoEstadoAntesDeFallecido": ultimo_estado,
            "Situacion": situacion,
        }
        assert _resolve_pre_death_state(ficha) == expected_pre
