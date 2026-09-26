"""Coherence between emitted lifecycle event types and the DB CHECK (issue #947).

``close_previous_situation`` emitted ``INTAKE_CLOSED_BY_FOSTER`` while the
``animal_lifecycle_events.event_type`` CHECK did not allow it, so every
Albergue -> Acogida transition failed against real Postgres. These tests
fail as soon as code emits an event type the CHECK would reject.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.domain_lifecycle import (
    ANIMAL_LIFECYCLE_EVENTS_ADD_EVENT_TYPE_CHECK_SQL,
    ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL,
    LIFECYCLE_EVENT_TYPES,
)
from app.modules.animals.lifecycle_events import LifecycleEventType
from app.modules.lifecycle.application.close_previous_situation import (
    CLOSING_EVENT_BY_CATEGORY,
)


@pytest.mark.parametrize("event_type", sorted(set(CLOSING_EVENT_BY_CATEGORY.values())))
def test_every_closing_event_is_an_allowed_event_type(event_type: str) -> None:
    assert event_type in LIFECYCLE_EVENT_TYPES


@pytest.mark.parametrize("event_type", sorted(member.value for member in LifecycleEventType))
def test_every_recorded_event_type_is_an_allowed_event_type(event_type: str) -> None:
    assert event_type in LIFECYCLE_EVENT_TYPES


@pytest.mark.parametrize("event_type", LIFECYCLE_EVENT_TYPES)
def test_create_table_and_existing_schema_upgrade_allow_the_same_types(event_type: str) -> None:
    assert f"'{event_type}'" in ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL
    assert f"'{event_type}'" in ANIMAL_LIFECYCLE_EVENTS_ADD_EVENT_TYPE_CHECK_SQL


def _event_type_literals_in_app() -> set[str]:
    """Every ``event_type="..."`` string literal passed as a keyword in ``app/``."""
    found: set[str] = set()
    for path in Path("app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.keyword) and node.arg == "event_type":
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    found.add(value.value)
    return found


def test_event_type_literals_are_found_in_app() -> None:
    # Guards the scan itself: close_all_on_death passes these as literals.
    assert {"INTAKE_CLOSED_BY_DEATH", "FOSTER_CLOSED_BY_DEATH"} <= _event_type_literals_in_app()


@pytest.mark.parametrize("event_type", sorted(_event_type_literals_in_app()))
def test_every_literal_event_type_in_app_is_allowed(event_type: str) -> None:
    assert event_type in LIFECYCLE_EVENT_TYPES
