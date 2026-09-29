"""Integration tests: chip-change saga against the REAL provisioned schema (issue #916, A-04).

The pre-#916 cascade ran ``UPDATE <table> SET chip = $1 WHERE chip = $2``
on ``entradas``, ``acogidas``, ``adopciones``, ``actuaciones_sanitarias``
and ``terapias``. None of those tables has a ``chip`` column — chips live
only on ``animales.nchip`` — and ``actuaciones_sanitarias`` is not even a
table (the real one is ``actuacion_sanitaria``). The first dependent UPDATE
failed with ``UndefinedColumn`` in production. The saga also faked a
transaction by sending ``BEGIN``/``COMMIT``/``ROLLBACK`` through
``execute_sql``, which opens a NEW connection per call and protects nothing.

Decision (orchestrator, P2 ladder verified): the web schema references the
animal by the surrogate FK ``animal_id UUID REFERENCES animales(id)``
(``app/core/domain_entradas.py:38``, ``domain_adopciones.py:40``,
``domain_foster.py:42``, ``domain_terapias.py:11``, ``domain_salud.py:35``).
Legacy Access propagated NCHIP because NCHIP was the legacy join key
(``docs/discovery/feature-01-animal-lifecycle.md:217``,
``docs/discovery/data-model-notes.md:123``); the FK replaced that join key,
so the dependent-table cascade UPDATEs are unnecessary.

The saga now keeps only: preflight uniqueness + current-chip checks, one
guarded ``UPDATE animales SET nchip``, and the ``CHIP_CHANGED`` lifecycle
event — all inside a real ``transaction()`` (pattern of
``app/modules/adopciones/service.py::create_adopcion`` after issue #914).

These atoms run through ``LocalPostgresExecutor`` on the real domain
schema provisioned by the integration conftest, following the
fault-injection style of ``test_create_altas_atomic.py``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.modules.acogidas import service as acogidas_service
from app.modules.adopciones import service as adopciones_service
from app.modules.animals.adapters.local_backend.animals_local_backend_chip_cascade import (
    AnimalsLocalBackendChipCascade,
)
from tests.integration.conftest import _EphemeralPostgres
from tests.integration.test_lifecycle_created_by_actor import (
    ACTOR,
    _acogida_params,
    _adopcion_params,
    _count,
    _executor,
    _seed_animal,
)

pytestmark = pytest.mark.integration

_CASCADE_MODULE = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "modules"
    / "animals"
    / "adapters"
    / "local_backend"
    / "animals_local_backend_chip_cascade.py"
)

# Tables the old cascade falsely assumed carry a ``chip`` column. The
# health table's REAL name is ``actuacion_sanitaria`` (singular) — the old
# cascade targeted the nonexistent ``actuaciones_sanitarias``.
_DEPENDENT_TABLES = (
    "entradas",
    "acogidas",
    "adopciones",
    "actuacion_sanitaria",
    "terapias",
)


def _seed_actuacion_sanitaria(ep: _EphemeralPostgres, animal_id: str) -> None:
    """Insert one active health action for the animal (minimal NOT NULL set)."""
    ep.execute(
        "INSERT INTO actuacion_sanitaria (animal_id, fecha) "
        "VALUES (%s, %s) RETURNING id",
        [animal_id, date.today().isoformat()],
    )


def _nchip(ep: _EphemeralPostgres, animal_id: str) -> str:
    rows = ep.execute(
        "SELECT nchip FROM animales WHERE id = %s", [animal_id]
    )
    return str(rows[0]["nchip"])


def _event_count(ep: _EphemeralPostgres, animal_id: str) -> int:
    return _count(ep, "animal_lifecycle_events", animal_id)


def _cascade(ep: _EphemeralPostgres) -> AnimalsLocalBackendChipCascade:
    return AnimalsLocalBackendChipCascade(_executor(ep))


def _change_params(old_chip: str, new_chip: str) -> dict[str, str]:
    return {
        "old_chip": old_chip,
        "new_chip": new_chip,
        "reason": "chip reimplantado",
        "operador_user_id": ACTOR,
    }


def test_chip_change_succeeds_with_related_entities_active(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """(a) The saga commits when adopcion + acogida + health action exist,
    and (b) the related entities still resolve the animal via ``animal_id``.
    """
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep)
    old_chip = _nchip(ep, animal_id)
    new_chip = f"{old_chip}-NEW"

    adopciones_service.create_adopcion(
        _executor(ep), _adopcion_params(animal_id), actor_user_id=ACTOR
    )
    acogidas_service.create_acogida(
        _executor(ep), _acogida_params(animal_id), actor_user_id=ACTOR
    )
    _seed_actuacion_sanitaria(ep, animal_id)

    result = _cascade(ep).change_animal_chip(
        animal_id=animal_id, **_change_params(old_chip, new_chip)
    )

    assert result.success is True, result.error
    assert result.updated_tables == {"animals": 1}
    assert _nchip(ep, animal_id) == new_chip

    # (b) The dependent rows never carried a chip copy: they reference the
    # animal through animal_id and keep resolving to the same animal.
    assert _count(ep, "adopciones", animal_id) == 1
    assert _count(ep, "acogidas", animal_id) == 1
    assert _count(ep, "actuacion_sanitaria", animal_id) == 1

    # The CHIP_CHANGED audit event records the transition.
    events = ep.execute(
        "SELECT event_type, metadata FROM animal_lifecycle_events "
        "WHERE animal_id = %s AND event_type = 'CHIP_CHANGED'",
        [animal_id],
    )
    assert len(events) == 1
    metadata = events[0]["metadata"]
    if isinstance(metadata, str):  # JSON column (not JSONB) arrives as str
        metadata = json.loads(metadata)
    assert metadata["old_chip"] == old_chip
    assert metadata["new_chip"] == new_chip


def test_forced_failure_after_animales_update_rolls_back_to_original_chip(
    ephemeral_postgres: _EphemeralPostgres,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(c) A failure AFTER the animales UPDATE rolls back to the original
    chip — a REAL rollback via transaction(), not a per-call connection.
    """

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("forced CHIP_CHANGED event failure (issue #916)")

    monkeypatch.setattr(AnimalsLocalBackendChipCascade, "_record_event", _boom)

    ep = ephemeral_postgres
    animal_id = _seed_animal(ep)
    old_chip = _nchip(ep, animal_id)
    new_chip = f"{old_chip}-NEW"

    result = _cascade(ep).change_animal_chip(
        animal_id=animal_id, **_change_params(old_chip, new_chip)
    )

    assert result.success is False
    assert "forced CHIP_CHANGED event failure" in str(result.error)
    # The animales UPDATE was undone by the real transaction rollback.
    assert _nchip(ep, animal_id) == old_chip
    # No CHIP_CHANGED event leaked from the failed saga.
    assert _event_count(ep, animal_id) == 0
    assert result.updated_tables == {}


def test_dependent_tables_have_no_chip_column(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """The schema reality that made the old cascade impossible still holds:
    none of the five dependent tables declares a ``chip`` column."""
    ep = ephemeral_postgres
    for table in _DEPENDENT_TABLES:
        cols = ep.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s",
            [ep.schema, table],
        )
        column_names = {str(r["column_name"]) for r in cols}
        assert "chip" not in column_names, (
            f"{table} unexpectedly declares a 'chip' column; the cascade "
            "removal rationale (issue #916) no longer holds — investigate."
        )


def test_cascade_source_has_no_chip_column_writes_or_fake_transaction() -> None:
    """(d) The saga source no longer writes a nonexistent ``chip`` column
    and no longer sends BEGIN/COMMIT/ROLLBACK through execute_sql — the
    atomic unit comes from ``transaction()`` instead.
    """
    source = _CASCADE_MODULE.read_text(encoding="utf-8")

    assert "SET chip" not in source, (
        "The cascade still writes a nonexistent 'chip' column on a "
        "dependent table (issue #916 regression)."
    )
    for fake_tx in ('"BEGIN"', '"COMMIT"', '"ROLLBACK"', "'BEGIN'", "'COMMIT'", "'ROLLBACK'"):
        assert fake_tx not in source, (
            f"The cascade still sends {fake_tx} through execute_sql; "
            "that opens a NEW connection per call and protects nothing "
            "(issue #916 regression). Use transaction() instead."
        )
    assert "transaction()" in source, (
        "The saga must execute its unit of work inside a real "
        "transaction() (pattern of create_adopcion, issue #914)."
    )
