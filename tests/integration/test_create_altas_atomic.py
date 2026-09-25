"""Integration tests: create_adopcion / create_acogida are atomic (issue #914, A-02).

Each alta chains four writes (entity INSERT, lifecycle event,
``close_previous_situation``, ``actualizar_estado_animal``). Before
A-02 every ``execute_sql`` ran on its own connection and committed
alone, so a failure in a middle step left the new adoption/stay row
persisted while the previous situation stayed open and
``animal_current_state`` went stale (an animal visible as both in
foster care and adopted).

These tests force a failure in ``close_previous_situation`` — the
middle step that turns a half-written alta into observable corruption
— and assert nothing persists. They follow the real-Postgres pattern
of ``test_lifecycle_created_by_actor.py`` (fakes hid three production
bugs; see audit 2026-09-24 finding A-02 / epic #911).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.acogidas import service as acogidas_service
from app.modules.adopciones import service as adopciones_service
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


def _force_close_failure(monkeypatch: pytest.MonkeyPatch, service: Any) -> None:
    """Replace ``close_previous_situation`` in the service module with a raiser.

    The service references the helper as a module global, so patching
    the module attribute intercepts the call after the entity INSERT
    and its lifecycle event have already run.
    """

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("forced close_previous_situation failure (issue #914)")

    monkeypatch.setattr(service, "close_previous_situation", _boom)


def test_create_adopcion_failure_in_close_persists_nothing(
    ephemeral_postgres: _EphemeralPostgres,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep)
    _force_close_failure(monkeypatch, adopciones_service)

    with pytest.raises(RuntimeError, match="forced close_previous_situation"):
        adopciones_service.create_adopcion(
            _executor(ep), _adopcion_params(animal_id), actor_user_id=ACTOR
        )

    # The adoption row AND its ADOPTION_STARTED event rolled back:
    # the animal must not appear adopted while its foster situation
    # is still open.
    assert _count(ep, "adopciones", animal_id) == 0
    assert _count(ep, "animal_lifecycle_events", animal_id) == 0


def test_create_acogida_failure_in_close_persists_nothing(
    ephemeral_postgres: _EphemeralPostgres,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep)
    _force_close_failure(monkeypatch, acogidas_service)

    with pytest.raises(RuntimeError, match="forced close_previous_situation"):
        acogidas_service.create_acogida(
            _executor(ep), _acogida_params(animal_id), actor_user_id=ACTOR
        )

    # The stay row AND its FOSTER_STARTED event rolled back.
    assert _count(ep, "acogidas", animal_id) == 0
    assert _count(ep, "animal_lifecycle_events", animal_id) == 0
