"""Contract tests for domain_lifecycle module."""

from __future__ import annotations

from pydantic import BaseModel

from app.core.domain_lifecycle import (
    ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL,
    ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL,
)


def test_lifecycle_events_sql() -> None:
    assert ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS animal_lifecycle_events" in (
        ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL
    )


def test_lifecycle_events_fk_to_animales() -> None:
    assert "REFERENCES animales(id)" in ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL


def test_lifecycle_events_event_type_check() -> None:
    assert "INTAKE_STARTED" in ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL
    assert "DEATH_RECORDED" in ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL


def test_lifecycle_events_natural_key() -> None:
    assert "UNIQUE (animal_id, event_type, event_timestamp)" in (
        ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL
    )


def test_current_state_sql() -> None:
    assert ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS animal_current_state" in (
        ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL
    )


def test_current_state_pk_is_animal_id() -> None:
    assert "animal_id UUID PRIMARY KEY" in ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL


def test_current_state_reconciliation_status_default() -> None:
    assert "DEFAULT 'pending'" in ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL


def test_lifecycle_event_model_exists() -> None:
    from app.core.domain_lifecycle import AnimalLifecycleEvent

    assert issubclass(AnimalLifecycleEvent, BaseModel)


def test_current_state_model_exists() -> None:
    from app.core.domain_lifecycle import AnimalCurrentState

    assert issubclass(AnimalCurrentState, BaseModel)
