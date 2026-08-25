"""Application-layer tests for paginated animal search."""
from __future__ import annotations

import pytest

from app.modules.animals.application.search_animals import search_animals
from app.modules.animals.domain.animal import AnimalSearchResult, Especie, Sexo


class _StubPort:
    """Capture one search call and return a configured result."""

    def __init__(self, result: AnimalSearchResult) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    def search_animals(self, **kwargs: object) -> AnimalSearchResult:
        self.calls.append(kwargs)
        return self._result


def _empty_result() -> AnimalSearchResult:
    return AnimalSearchResult(data=(), total=0, limit=50, offset=0)


def test_limit_at_or_below_zero_clamps_to_one() -> None:
    port = _StubPort(_empty_result())

    result = search_animals(port, limit=0)  # type: ignore[arg-type]

    assert result is port._result, "use case must return the port result unchanged"
    assert port.calls[0]["limit"] == 1, "non-positive limits must clamp to one"


def test_negative_offset_clamps_to_zero() -> None:
    port = _StubPort(_empty_result())

    search_animals(port, offset=-7)  # type: ignore[arg-type]

    assert port.calls[0]["offset"] == 0, "negative offsets must clamp to zero"


def test_delegates_all_filters_without_extra_side_effects() -> None:
    port = _StubPort(_empty_result())

    search_animals(
        port,  # type: ignore[arg-type]
        q="Luna",
        chip="941000000000001",
        especie=Especie.CANINA,
        sexo=Sexo.H,
        estado="acogida",
        fecha_alta_since="2026-01-01",
        fecha_alta_until="2026-12-31",
        limit=10,
        offset=20,
    )

    assert port.calls == [
        {
            "q": "Luna",
            "chip": "941000000000001",
            "especie": Especie.CANINA,
            "sexo": Sexo.H,
            "estado": "acogida",
            "fecha_alta_since": "2026-01-01",
            "fecha_alta_until": "2026-12-31",
            "limit": 10,
            "offset": 20,
        }
    ], "the use case must delegate exactly once with the normalized inputs"


@pytest.mark.parametrize(
    "field",
    ["q", "chip", "fecha_alta_since", "fecha_alta_until"],
)
def test_non_string_text_filter_raises_type_error(field: str) -> None:
    port = _StubPort(_empty_result())

    with pytest.raises(TypeError, match=f"{field} must be a string or None"):
        search_animals(port, **{field: 42})  # type: ignore[arg-type]

    assert port.calls == [], "invalid filters must not touch the port"
