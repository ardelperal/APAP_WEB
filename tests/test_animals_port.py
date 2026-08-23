"""Port tests for the animals slice (slice-completeness gate)."""
from __future__ import annotations

from app.modules.animals.adapters.insforge.animals_insforge_adapter import (
    AnimalsInsforgeAdapter,
)
from app.modules.animals.ports.animals_port import AnimalsPort


def test_insforge_adapter_satisfies_animals_port_protocol() -> None:
    """The concrete adapter must satisfy the :class:`AnimalsPort` Protocol.

    This is the structural check the slice-completeness gate looks
    for: a concrete adapter referenced from ``di/animals_di.py``
    must implement the Protocol declared in
    ``ports/animals_port.py``. ``runtime_checkable`` lets the
    Protocol be checked via ``isinstance`` after the duck-typed
    method exists.
    """
    adapter = AnimalsInsforgeAdapter(
        client=None, storage=None  # type: ignore[arg-type]
    )
    assert isinstance(adapter, AnimalsPort)
    assert hasattr(adapter, "get_animal_by_nchip")
