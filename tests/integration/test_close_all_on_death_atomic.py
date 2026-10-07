"""Integration tests: close_all_on_death is atomic (issue #915, A-03).

``close_all_on_death`` inserts ``DEATH_RECORDED`` and then walks the
active entradas/acogidas/adopciones emitting one closing event each,
every statement committing on its own connection before A-03. A
failure in a middle closing event left the animal recorded as dead
with placements still open in the event log — exactly the invariant
the module declares.

These tests force a failure in the second closing event (after
``DEATH_RECORDED`` and the first closing event already ran) and
assert nothing from that call persists. Real Postgres, following the
fault-injection pattern of ``test_create_altas_atomic.py`` (A-02).
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

import pytest

from app.modules.lifecycle.application import close_all_on_death as death_module
from app.modules.lifecycle.application.close_all_on_death import close_all_on_death
from tests.integration.conftest import _EphemeralPostgres
from tests.integration.test_lifecycle_created_by_actor import (
    ACTOR,
    _count,
    _executor,
    _seed_animal,
)

pytestmark = pytest.mark.integration


def _seed_active_entrada(ep: _EphemeralPostgres, animal_id: str) -> str:
    entrada_id = str(uuid4())
    ep.execute(
        "INSERT INTO entradas (id, animal_id, fecha_entrada, motivo) "
        "VALUES (%s, %s, CURRENT_DATE, 'test intake') RETURNING id",
        [entrada_id, animal_id],
    )
    return entrada_id


def _seed_active_adopcion(ep: _EphemeralPostgres, animal_id: str) -> str:
    adopcion_id = str(uuid4())
    ep.execute(
        "INSERT INTO adopciones (id, animal_id, fecha_adopcion, tipo_adopcion, nombre_adoptante) "
        "VALUES (%s, %s, CURRENT_DATE, 'regular', 'Test Adopter') RETURNING id",
        [adopcion_id, animal_id],
    )
    return adopcion_id


def _force_second_close_event_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wrap the per-row closing-event emitter with a raiser on call 2.

    Call 1 (first active placement) succeeds, so ``DEATH_RECORDED``
    and one closing event are already written when the failure hits —
    the exact half-written state A-03 describes.
    """
    original = death_module._close_event
    calls = {"n": 0}

    def _flaky(*args: Any, **kwargs: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("forced second closing-event failure (issue #915)")
        original(*args, **kwargs)

    monkeypatch.setattr(death_module, "_close_event", _flaky)


def test_close_all_on_death_failure_in_second_close_persists_nothing(
    ephemeral_postgres: _EphemeralPostgres,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep)
    _seed_active_entrada(ep, animal_id)
    _seed_active_adopcion(ep, animal_id)
    _force_second_close_event_failure(monkeypatch)

    with pytest.raises(RuntimeError, match="forced second closing-event"):
        close_all_on_death(
            _executor(ep),
            animal_id,
            date.today().isoformat(),
            created_by=ACTOR,
        )

    # DEATH_RECORDED and every closing event rolled back: a failed
    # death registration must not leave the animal dead with open
    # placements in the event log.
    assert _count(ep, "animal_lifecycle_events", animal_id) == 0


def test_close_all_on_death_happy_path_emits_every_event(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep)
    _seed_active_entrada(ep, animal_id)
    _seed_active_adopcion(ep, animal_id)

    close_all_on_death(
        _executor(ep), animal_id, date.today().isoformat(), created_by=ACTOR
    )

    # Same events as before A-03: DEATH_RECORDED plus one closing event
    # per active placement, all lineage-linked to the death event via
    # ``caused_by_event_id`` (they share one event_timestamp, so the
    # lineage is the only deterministic ordering).
    rows = ep.execute(
        "SELECT id, event_type, caused_by_event_id FROM animal_lifecycle_events "
        "WHERE animal_id = %s",
        [animal_id],
    )
    death = [r for r in rows if r["event_type"] == "DEATH_RECORDED"]
    closings = [r for r in rows if r["event_type"] != "DEATH_RECORDED"]
    assert len(death) == 1
    assert sorted(r["event_type"] for r in closings) == [
        "ADOPTION_CLOSED_BY_DEATH",
        "INTAKE_CLOSED_BY_DEATH",
    ]
    assert all(r["caused_by_event_id"] == death[0]["id"] for r in closings)
