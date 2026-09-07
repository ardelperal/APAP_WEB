"""Use case: look up an animal by its business primary key (NCHIP).

The single application-layer entry point for NCHIP lookups.
Delegates to :class:`~app.modules.animals.ports.AnimalsPort` so
the application code stays transport-agnostic (AGENTS.md §31) —
no FastAPI, no LocalBackend, no Jinja in this file.

Empty / whitespace NCHIP short-circuits to ``None`` so the caller
does not have to validate the input.
"""
from __future__ import annotations

from app.modules.animals.domain.animal import Animal
from app.modules.animals.ports.animals_port import AnimalsPort


def get_animal_by_nchip(
    animals_port: AnimalsPort,
    nchip: str,
) -> Animal | None:
    """Return the animal with this NCHIP, or ``None`` if not found.

    Empty / whitespace NCHIP short-circuits to ``None``.
    """
    if not nchip or not nchip.strip():
        return None
    return animals_port.get_animal_by_nchip(nchip.strip())


__all__ = ["get_animal_by_nchip"]
