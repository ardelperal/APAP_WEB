"""InsForge-adapter tests for the animals slice."""
from __future__ import annotations

from app.modules.animals.adapters.insforge.animals_insforge_adapter import (
    AnimalsInsforgeAdapter,
)
from app.modules.animals.adapters.insforge.animals_insforge_queries import (
    get_animal_by_nchip_sql,
)


class _FakeClient:
    """In-memory :class:`~app.core.data_access.SqlExecutor` for unit tests."""

    def __init__(self, rows: list[dict[str, object]] | Exception) -> None:
        self._rows = rows
        self.last_query: str | None = None
        self.last_params: list[object] | None = None

    def execute_sql(
        self, query: str, params: list[object] | None = None
    ) -> list[dict[str, object]]:
        self.last_query = query
        self.last_params = params
        if isinstance(self._rows, Exception):
            raise self._rows
        return self._rows


def test_returns_none_when_no_match() -> None:
    """An empty result set yields ``None`` (not an exception)."""
    client = _FakeClient(rows=[])
    adapter = AnimalsInsforgeAdapter(client=client)  # type: ignore[arg-type]
    assert adapter.get_animal_by_nchip("941000000012345") is None
    sql, params = get_animal_by_nchip_sql("941000000012345")
    assert client.last_query == sql
    assert client.last_params == params


def test_maps_row_to_domain() -> None:
    """A result row is mapped to the hexagonal :class:`Animal` dataclass."""
    client = _FakeClient(
        rows=[
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "NCHIP": "941000000012345",
                "NombreAnimal": "Luna",
                "Especie": "CANINA",
                "Sexo": "H",
                "FNacimiento": "2024-03-01",
                "activo": True,
            }
        ]
    )
    adapter = AnimalsInsforgeAdapter(client=client)  # type: ignore[arg-type]
    animal = adapter.get_animal_by_nchip("941000000012345")
    assert animal is not None
    assert animal.NCHIP == "941000000012345"
    assert animal.NombreAnimal == "Luna"
    assert animal.activo is True
