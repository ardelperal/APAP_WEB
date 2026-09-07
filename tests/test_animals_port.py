"""Port tests for the animals slice (slice-completeness gate)."""
from __future__ import annotations

import httpx

from app.modules.animals.adapters.local_backend.animals_local_backend_adapter import (
    AnimalsLocalBackendAdapter,
)
from app.modules.animals.ports.animals_port import AnimalsPort
from tests.sql_executor_fake import HandlerSqlExecutor


def test_local_backend_adapter_satisfies_animals_port_protocol() -> None:
    """The concrete adapter must satisfy the :class:`AnimalsPort` Protocol.

    This is the structural check the slice-completeness gate looks
    for: a concrete adapter referenced from ``di/animals_di.py``
    must implement the Protocol declared in
    ``ports/animals_port.py``. ``runtime_checkable`` lets the
    Protocol be checked via ``isinstance`` after the duck-typed
    method exists.
    """
    adapter = AnimalsLocalBackendAdapter(
        client=None, storage=None  # type: ignore[arg-type]
    )
    assert isinstance(adapter, AnimalsPort)
    port_methods = {
        "get_animal_by_nchip",
        "list_animals",
        "create_animal",
        "update_animal",
        "delete_animal",
        "record_lifecycle_event",
        "list_lifecycle_events",
        "change_animal_chip",
        "resolve_animal_photo",
        "get_animal_by_id",
        "search_animals",
    }
    assert port_methods.issubset(dir(adapter)), "adapter must implement all port methods"


def test_adapter_without_storage_returns_placeholder_for_known_photo() -> None:
    executor = HandlerSqlExecutor(
        lambda _request: httpx.Response(200, json=[{"NombreFoto": "animal.jpg"}])
    )
    adapter = AnimalsLocalBackendAdapter(client=executor, storage=None)

    photo = adapter.resolve_animal_photo("animal-1")

    assert photo is not None
    assert photo.is_placeholder is True
    assert photo.media_type == "image/png"
    assert b"".join(photo.stream).startswith(b"\x89PNG\r\n\x1a\n")
