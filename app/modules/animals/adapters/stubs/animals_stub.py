"""Stub adapter for ``AnimalsPort`` — pending local-backend implementation.

Replaces the deleted
:class:`app.modules.animals.adapters.local_backend.animals_local_backend_adapter.AnimalsInsforgeAdapter`
and its 7 sibling modules under ``app.modules.animals.adapters.local_backend.*``.
A real :class:`~app.core.local_backend.db.LocalPostgresExecutor`-backed
adapter lands in a follow-up slice; until then, every method raises
:class:`NotImplementedError` so the runtime fails loud per route.

Affected routes (return 500 until the real adapter lands):

- ``GET /animales`` (search_animals, list_animals)
- ``GET /animales/<nchip>`` (get_animal_by_nchip, get_animal_by_id)
- ``POST /animales`` (create_animal)
- ``PUT /animales/<id>`` (update_animal)
- ``DELETE /animales/<id>`` (delete_animal)
- ``POST /animales/<id>/lifecycle`` (record_lifecycle_event, list_lifecycle_events)
- ``POST /animales/<id>/chip`` (change_animal_chip)
- ``GET /animales/<id>/foto`` (resolve_animal_photo)

See issue #6' for the follow-up that replaces this stub with a real
local-backend implementation.
"""

from __future__ import annotations

from app.modules.animals.ports.animals_port import AnimalsPort


class StubAnimalsPort(AnimalsPort):
    """Placeholder :class:`AnimalsPort` whose every method raises."""

    def get_animal_by_nchip(self, *args, **kwargs):
        raise NotImplementedError(
            "AnimalsPort.get_animal_by_nchip: pending local-backend adapter, see #6'"
        )

    def get_animal_by_id(self, *args, **kwargs):
        raise NotImplementedError(
            "AnimalsPort.get_animal_by_id: pending local-backend adapter, see #6'"
        )

    def search_animals(self, *args, **kwargs):
        raise NotImplementedError(
            "AnimalsPort.search_animals: pending local-backend adapter, see #6'"
        )

    def list_animals(self, *args, **kwargs):
        raise NotImplementedError(
            "AnimalsPort.list_animals: pending local-backend adapter, see #6'"
        )

    def create_animal(self, *args, **kwargs):
        raise NotImplementedError(
            "AnimalsPort.create_animal: pending local-backend adapter, see #6'"
        )

    def update_animal(self, *args, **kwargs):
        raise NotImplementedError(
            "AnimalsPort.update_animal: pending local-backend adapter, see #6'"
        )

    def delete_animal(self, *args, **kwargs):
        raise NotImplementedError(
            "AnimalsPort.delete_animal: pending local-backend adapter, see #6'"
        )

    def record_lifecycle_event(self, *args, **kwargs):
        raise NotImplementedError(
            "AnimalsPort.record_lifecycle_event: pending local-backend adapter, see #6'"
        )

    def list_lifecycle_events(self, *args, **kwargs):
        raise NotImplementedError(
            "AnimalsPort.list_lifecycle_events: pending local-backend adapter, see #6'"
        )

    def change_animal_chip(self, *args, **kwargs):
        raise NotImplementedError(
            "AnimalsPort.change_animal_chip: pending local-backend adapter, see #6'"
        )

    def resolve_animal_photo(self, *args, **kwargs):
        raise NotImplementedError(
            "AnimalsPort.resolve_animal_photo: pending local-backend adapter, see #6'"
        )


__all__ = ["StubAnimalsPort"]
