"""Application-layer tests for ``list_animals`` (slice #420-7 second surface).

Mirrors the stub-port pattern from
``tests/test_animals_application_get_animal_by_nchip.py`` so the
use-case tests stay transport-free: the application code never
sees ``InsForgeClient`` or ``SqlExecutor``; it talks to the
:class:`AnimalsPort` Protocol only.
"""
from __future__ import annotations

from app.modules.animals.application.list_animals import (
    MAX_PAGE_SIZE,
    list_animals,
)
from app.modules.animals.domain.animal import Animal, Especie, Sexo


def _animal(nchip: str) -> Animal:
    """Build a minimal ``Animal`` for the given NCHIP — tests do not
    care about the rest of the fields."""
    return Animal(
        id=f"00000000-0000-0000-0000-{int(nchip[-12:]):012d}",
        NCHIP=nchip,
        NombreAnimal=f"Animal {nchip}",
        Especie=Especie.CANINA,
        Sexo=Sexo.H,
        FNacimiento="2024-01-01",
        activo=True,
    )


class _StubPort:
    """Stub implementation of :class:`AnimalsPort` for unit tests."""

    def __init__(self, animals: list[Animal]) -> None:
        self._animals = animals
        self.last_limit: int | None = None
        self.last_offset: int | None = None
        self.last_activo_only: bool | None = None

    def list_animals(
        self,
        *,
        limit: int,
        offset: int,
        activo_only: bool,
    ) -> list[Animal]:
        self.last_limit = limit
        self.last_offset = offset
        self.last_activo_only = activo_only
        return self._animals

    # The Protocol has more methods than the use case under test
    # exercises. Provide a no-op stub so the runtime Protocol check
    # (``@runtime_checkable``) does not blow up if another test
    # incidentally instantiates the stub for an unrelated assertion.
    def get_animal_by_nchip(self, nchip: str) -> Animal | None:  # pragma: no cover
        return None


def test_default_call_uses_defaults() -> None:
    """Defaults: limit=50, offset=0, activo_only=True — passed through verbatim."""
    port = _StubPort(animals=[])
    result = list_animals(port)

    assert result == []
    assert port.last_limit == 50
    assert port.last_offset == 0
    assert port.last_activo_only is True


def test_returns_port_results_unchanged() -> None:
    """The use case returns whatever the port produced — no decoration."""
    expected = [_animal("941000000000001"), _animal("941000000000002")]
    port = _StubPort(animals=expected)
    assert list_animals(port, limit=10, offset=5, activo_only=False) is expected


def test_negative_limit_clamps_to_one() -> None:
    """A bogus negative ``limit`` is clamped to ``1`` — the adapter's
    SQL needs ``LIMIT >= 1``; postgres rejects ``LIMIT 0`` in some
    versions and ``LIMIT -1`` always."""
    port = _StubPort(animals=[])
    list_animals(port, limit=-7)

    assert port.last_limit == 1


def test_oversized_limit_clamps_to_max_page_size() -> None:
    """A ``limit`` above :data:`MAX_PAGE_SIZE` is clamped to the cap so a
    misconfigured caller can't pull the whole table in one shot."""
    port = _StubPort(animals=[])
    list_animals(port, limit=MAX_PAGE_SIZE + 500)

    assert port.last_limit == MAX_PAGE_SIZE


def test_negative_offset_clamps_to_zero() -> None:
    """A bogus negative ``offset`` is clamped to ``0`` — postgres
    rejects ``OFFSET -1`` and the application has no business
    meaning for it."""
    port = _StubPort(animals=[])
    list_animals(port, offset=-3)

    assert port.last_offset == 0


def test_activo_only_false_passes_through() -> None:
    """The ``activo_only=False`` opt-out is forwarded to the port so the
    historical-record paths keep seeing inactive rows."""
    port = _StubPort(animals=[])
    list_animals(port, activo_only=False)

    assert port.last_activo_only is False
