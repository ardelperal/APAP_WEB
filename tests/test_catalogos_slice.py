"""Tests for the hexagonal catalogos slice.

The new slice (``app/core/catalogos/``,
``app/core/ports/catalogos_port.py``,
``app/core/application/catalogos/``,
``app/core/adapters/insforge/catalogos_insforge_adapter.py``,
``app/core/di/catalogos_di.py``) is the pattern-defining slice for
the broader refactor. These tests pin the **new** pattern at three
levels:

1. **Use cases** — thin delegators over the
   :class:`CatalogosPort` Protocol. Tests use a recording fake
   implementing the Protocol; the assertion is on the call, not on
   the SQL.
2. **Adapter** — the InsForge adapter shapes the SQL and maps the
   raw row to the frozen domain entity. Tests cover both the SQL
   query string (against the canonical ``LIST_*_SQL`` constants the
   module exposes) and the row → entity mapping (against a row
   shape taken verbatim from the existing ``tests/test_catalogs.py``
   fixtures).
3. **DI helper** — the per-request port construction uses the
   pooled :class:`InsForgeClient` when the lifespan is active, and
   falls back to a lazily-created client when the transport bypasses
   the lifespan (lightweight ASGI tests).

The OLD API in ``app/core/catalogs.py`` is untouched (slice 1
establishes the new pattern; a follow-up PR retires the old file).
The existing ``tests/test_catalogs.py`` keeps its 29 tests as the
regression net for the legacy functions.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.adapters.insforge.catalogos_insforge_adapter import (
    InsForgeCatalogosAdapter,
)
from app.core.application.catalogos import (
    list_motivos as list_motivos_uc,
)
from app.core.application.catalogos import (
    list_origenes as list_origenes_uc,
)
from app.core.application.catalogos import (
    list_periodicidad as list_periodicidad_uc,
)
from app.core.application.catalogos import (
    list_pruebas as list_pruebas_uc,
)
from app.core.application.catalogos import (
    list_tipos_contrato as list_tipos_contrato_uc,
)
from app.core.catalogos.motivo import Motivo
from app.core.catalogos.origen import Origen
from app.core.catalogos.periodicidad import Periodicidad
from app.core.catalogos.prueba import Prueba
from app.core.catalogos.tipo_contrato import TipoContrato
from app.core.ports.catalogos_port import CatalogosPort

# --- use cases (delegation) --------------------------------------------------


class _RecordingPort:
    """Recording fake that implements :class:`CatalogosPort`.

    Records every call and returns the canned list the test set up.
    Used to assert the use case is a thin delegator (the call
    reaches the port, the port returns the canned list, the use case
    returns it unchanged).
    """

    def __init__(
        self,
        origenes: list[Origen] | None = None,
        motivos: list[Motivo] | None = None,
        pruebas: list[Prueba] | None = None,
        periodicidad: list[Periodicidad] | None = None,
        tipos_contrato: list[TipoContrato] | None = None,
    ) -> None:
        self.origenes = origenes or []
        self.motivos = motivos or []
        self.pruebas = pruebas or []
        self.periodicidad = periodicidad or []
        self.tipos_contrato = tipos_contrato or []
        self.calls: list[str] = []

    def list_origenes(self) -> list[Origen]:
        self.calls.append("list_origenes")
        return self.origenes

    def list_motivos(self) -> list[Motivo]:
        self.calls.append("list_motivos")
        return self.motivos

    def list_pruebas(self) -> list[Prueba]:
        self.calls.append("list_pruebas")
        return self.pruebas

    def list_periodicidad(self) -> list[Periodicidad]:
        self.calls.append("list_periodicidad")
        return self.periodicidad

    def list_tipos_contrato(self) -> list[TipoContrato]:
        self.calls.append("list_tipos_contrato")
        return self.tipos_contrato


def _origen(id_: str = "abc", codigo: str = "Acogida") -> Origen:
    return Origen(
        id=id_,
        codigo=codigo,
        nombre=codigo,
        descripcion=None,
        activo=True,
        orden=1,
    )


def _motivo(id_: str = "abc", codigo: str = "Abandono", especie: str = "AMBOS") -> Motivo:
    return Motivo(
        id=id_,
        codigo=codigo,
        nombre=codigo,
        especie=especie,
        activo=True,
        orden=1,
    )


def _prueba(id_: str = "abc", codigo: str = "Básico") -> Prueba:
    return Prueba(
        id=id_,
        codigo=codigo,
        nombre=codigo,
        especie="ambos",
        observaciones="analítica",
        activo=True,
        orden=1,
    )


def _periodicidad(
    id_: str = "abc",
    codigo: str = "Vacuna Polivalente",
    especie: str | None = "canina",
    periodicidad_meses: int | None = 12,
) -> Periodicidad:
    return Periodicidad(
        id=id_,
        codigo=codigo,
        nombre=codigo,
        especie=especie,
        periodicidad_meses=periodicidad_meses,
        activo=True,
        orden=1,
    )


def _tipo_contrato(id_: str = "abc", codigo: str = "Acogida") -> TipoContrato:
    return TipoContrato(
        id=id_,
        codigo=codigo,
        nombre=codigo,
        iniciales="AC",
        descripcion=None,
        tabla_legacy="TbAcogidaAnimal",
        campo_legacy="NCONTRATOACOGIDA",
        activo=True,
        orden=1,
    )


def test_list_origenes_delegates_to_port() -> None:
    """The use case calls the port and returns the port's result unchanged."""
    port = _RecordingPort(origenes=[_origen(), _origen(id_="def", codigo="Regalo")])
    rows = list_origenes_uc(port)
    assert port.calls == ["list_origenes"]
    assert len(rows) == 2
    assert rows[0].codigo == "Acogida"
    assert rows[1].codigo == "Regalo"


def test_list_motivos_delegates_to_port() -> None:
    port = _RecordingPort(motivos=[_motivo(), _motivo(id_="def", codigo="Maltrato")])
    rows = list_motivos_uc(port)
    assert port.calls == ["list_motivos"]
    assert len(rows) == 2
    assert rows[0].codigo == "Abandono"
    assert rows[1].codigo == "Maltrato"


def test_list_pruebas_delegates_to_port() -> None:
    port = _RecordingPort(pruebas=[_prueba(), _prueba(id_="def", codigo="Rabia")])
    rows = list_pruebas_uc(port)
    assert port.calls == ["list_pruebas"]
    assert len(rows) == 2


def test_list_periodicidad_delegates_to_port() -> None:
    port = _RecordingPort(
        periodicidad=[
            _periodicidad(),
            _periodicidad(id_="def", codigo="Rabia"),
        ]
    )
    rows = list_periodicidad_uc(port)
    assert port.calls == ["list_periodicidad"]
    assert len(rows) == 2


def test_list_tipos_contrato_delegates_to_port() -> None:
    port = _RecordingPort(
        tipos_contrato=[
            _tipo_contrato(),
            _tipo_contrato(id_="def", codigo="Adopción"),
        ]
    )
    rows = list_tipos_contrato_uc(port)
    assert port.calls == ["list_tipos_contrato"]
    assert len(rows) == 2


def test_list_origenes_returns_empty_when_port_returns_empty() -> None:
    """Empty port result is propagated (no special-casing in the use case)."""
    port = _RecordingPort(origenes=[])
    assert list_origenes_uc(port) == []


# --- adapter (SQL shape + row mapping) ---------------------------------------


class _RecordingExecutor:
    """Recording fake that satisfies :class:`SqlExecutor`.

    Returns the canned ``rows`` list and records the (query, params)
    pair so tests can assert the SQL shape against the
    ``LIST_*_SQL`` constants the adapter exposes.
    """

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, list[Any]]] = []

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((query, params or []))
        return self.rows


def test_adapter_list_origenes_uses_expected_sql() -> None:
    """The adapter uses the same SQL the legacy ``LIST_CATALOGOS_ORIGENES_SQL`` uses."""
    from app.core.adapters.insforge.catalogos_insforge_adapter import LIST_ORIGENES_SQL

    executor = _RecordingExecutor()
    InsForgeCatalogosAdapter(executor).list_origenes()
    assert len(executor.calls) == 1
    query, params = executor.calls[0]
    assert query.strip() == LIST_ORIGENES_SQL.strip()
    assert params == []


def test_adapter_list_motivos_uses_expected_sql() -> None:
    from app.core.adapters.insforge.catalogos_insforge_adapter import LIST_MOTIVOS_SQL

    executor = _RecordingExecutor()
    InsForgeCatalogosAdapter(executor).list_motivos()
    query, params = executor.calls[0]
    assert query.strip() == LIST_MOTIVOS_SQL.strip()
    assert params == []


def test_adapter_list_pruebas_uses_expected_sql() -> None:
    from app.core.adapters.insforge.catalogos_insforge_adapter import LIST_PRUEBAS_SQL

    executor = _RecordingExecutor()
    InsForgeCatalogosAdapter(executor).list_pruebas()
    query, params = executor.calls[0]
    assert query.strip() == LIST_PRUEBAS_SQL.strip()
    assert params == []


def test_adapter_list_periodicidad_uses_expected_sql() -> None:
    from app.core.adapters.insforge.catalogos_insforge_adapter import (
        LIST_PERIODICIDAD_SQL,
    )

    executor = _RecordingExecutor()
    InsForgeCatalogosAdapter(executor).list_periodicidad()
    query, params = executor.calls[0]
    assert query.strip() == LIST_PERIODICIDAD_SQL.strip()
    assert params == []


def test_adapter_list_tipos_contrato_uses_expected_sql() -> None:
    from app.core.adapters.insforge.catalogos_insforge_adapter import (
        LIST_TIPOS_CONTRATO_SQL,
    )

    executor = _RecordingExecutor()
    InsForgeCatalogosAdapter(executor).list_tipos_contrato()
    query, params = executor.calls[0]
    assert query.strip() == LIST_TIPOS_CONTRATO_SQL.strip()
    assert params == []


def test_adapter_list_origenes_maps_rows_to_entities() -> None:
    """The adapter maps the raw row dict to the :class:`Origen` entity."""
    rows = [
        {
            "id": "a-uuid",
            "codigo": "Acogida",
            "nombre": "Acogida",
            "descripcion": None,
            "activo": True,
            "orden": 1,
        },
        {
            "id": "b-uuid",
            "codigo": "Regalo",
            "nombre": "Regalo",
            "descripcion": "Regalo de terceros",
            "activo": True,
            "orden": 7,
        },
    ]
    executor = _RecordingExecutor(rows)
    origenes = InsForgeCatalogosAdapter(executor).list_origenes()
    assert len(origenes) == 2
    assert origenes[0] == Origen(
        id="a-uuid",
        codigo="Acogida",
        nombre="Acogida",
        descripcion=None,
        activo=True,
        orden=1,
    )
    assert origenes[1] == Origen(
        id="b-uuid",
        codigo="Regalo",
        nombre="Regalo",
        descripcion="Regalo de terceros",
        activo=True,
        orden=7,
    )


def test_adapter_list_periodicidad_propagates_nullable_columns() -> None:
    """The adapter surfaces ``None`` for ``especie`` / ``periodicidad_meses`` ``NULL``."""
    rows = [
        {
            "id": "a-uuid",
            "codigo": "Esterilización",
            "nombre": "Esterilización",
            "especie": None,
            "periodicidad_meses": None,
            "activo": True,
            "orden": 8,
        },
        {
            "id": "b-uuid",
            "codigo": "Vacuna Polivalente",
            "nombre": "Vacuna Polivalente",
            "especie": "canina",
            "periodicidad_meses": 12,
            "activo": True,
            "orden": 1,
        },
    ]
    executor = _RecordingExecutor(rows)
    periodicidades = InsForgeCatalogosAdapter(executor).list_periodicidad()
    assert periodicidades[0] == Periodicidad(
        id="a-uuid",
        codigo="Esterilización",
        nombre="Esterilización",
        especie=None,
        periodicidad_meses=None,
        activo=True,
        orden=8,
    )
    assert periodicidades[1] == Periodicidad(
        id="b-uuid",
        codigo="Vacuna Polivalente",
        nombre="Vacuna Polivalente",
        especie="canina",
        periodicidad_meses=12,
        activo=True,
        orden=1,
    )


def test_adapter_list_origenes_coerces_activo_string_to_bool() -> None:
    """The adapter coerces ``activo`` to ``bool`` even when the executor returns a string."""
    rows = [
        {
            "id": "a-uuid",
            "codigo": "Acogida",
            "nombre": "Acogida",
            "descripcion": None,
            "activo": "true",
            "orden": 1,
        },
    ]
    executor = _RecordingExecutor(rows)
    origenes = InsForgeCatalogosAdapter(executor).list_origenes()
    assert origenes[0].activo is True


def test_adapter_returns_empty_list_when_executor_returns_empty() -> None:
    """An empty executor result yields an empty entity list."""
    executor = _RecordingExecutor([])
    assert InsForgeCatalogosAdapter(executor).list_origenes() == []
    assert InsForgeCatalogosAdapter(executor).list_motivos() == []
    assert InsForgeCatalogosAdapter(executor).list_pruebas() == []
    assert InsForgeCatalogosAdapter(executor).list_periodicidad() == []
    assert InsForgeCatalogosAdapter(executor).list_tipos_contrato() == []


def test_adapter_satisfies_catalogos_port_protocol() -> None:
    """The adapter type-checks against :class:`CatalogosPort`.

    mypy enforces this via the explicit base class; this test
    documents the contract at runtime: an instance of the adapter
    is a usable :class:`CatalogosPort`.
    """
    executor = _RecordingExecutor()
    adapter: CatalogosPort = InsForgeCatalogosAdapter(executor)
    assert isinstance(adapter, InsForgeCatalogosAdapter)
    # The Protocol's method names are present on the adapter.
    for method in (
        "list_origenes",
        "list_motivos",
        "list_pruebas",
        "list_periodicidad",
        "list_tipos_contrato",
    ):
        assert hasattr(adapter, method)
        assert callable(getattr(adapter, method))


# --- DI helper ---------------------------------------------------------------


def test_get_catalogos_port_uses_pooled_client_when_present() -> None:
    """The DI helper builds the adapter from the pooled ``app.state.insforge_client``."""
    from fastapi import FastAPI

    from app.core.di.catalogos_di import get_catalogos_port

    app = FastAPI()
    executor = _RecordingExecutor()
    app.state.insforge_client = executor

    gen = get_catalogos_port(type("R", (), {"app": app})())
    adapter = next(gen)
    try:
        assert isinstance(adapter, InsForgeCatalogosAdapter)
        # The adapter holds the same executor instance.
        assert adapter._executor is executor  # noqa: SLF001 — internal seam
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_get_catalogos_port_falls_back_when_lifespan_skipped() -> None:
    """If ``app.state.insforge_client`` is missing, the helper creates a new client.

    This branch exists for lightweight ASGI test transports that
    bypass the lifespan. The exact fallback client is an
    :class:`InsForgeClient`; we only assert it is created and the
    adapter wraps it.
    """
    from fastapi import FastAPI

    from app.core.di.catalogos_di import get_catalogos_port
    from app.core.local_backend.db import LocalPostgresExecutor

    app = FastAPI()
    assert not hasattr(app.state, "insforge_client")

    req = type("R", (), {"app": app})()
    gen = get_catalogos_port(req)
    try:
        adapter = next(gen)
        assert isinstance(adapter, InsForgeCatalogosAdapter)
        assert isinstance(adapter._executor, InsForgeClient)  # noqa: SLF001
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


# --- domain entities (no I/O) ------------------------------------------------


def test_origen_is_immutable_value_object() -> None:
    """``Origen`` is a frozen dataclass — assigning to a field raises."""
    origen = _origen()
    with pytest.raises((AttributeError, Exception)):
        origen.codigo = "Mutated"  # type: ignore[misc]


def test_periodicidad_supports_nullable_columns() -> None:
    """``Periodicidad`` allows ``None`` for ``especie`` and ``periodicidad_meses``."""
    periodicidad = Periodicidad(
        id="a",
        codigo="Esterilización",
        nombre="Esterilización",
        especie=None,
        periodicidad_meses=None,
        activo=True,
        orden=None,
    )
    assert periodicidad.especie is None
    assert periodicidad.periodicidad_meses is None
    assert periodicidad.orden is None


def test_tipo_contrato_supports_nullable_legacy_columns() -> None:
    """``TipoContrato`` allows ``None`` for columns the legacy has not wired yet."""
    tipo = TipoContrato(
        id="a",
        codigo="Ficha de Seguimiento",
        nombre="Ficha de Seguimiento",
        iniciales=None,
        descripcion=None,
        tabla_legacy=None,
        campo_legacy=None,
        activo=True,
        orden=6,
    )
    assert tipo.tabla_legacy is None
    assert tipo.campo_legacy is None


# --- architectural rule pins -------------------------------------------------


def test_domain_layer_does_not_import_insforge() -> None:
    """Rule §31: domain layer has no InsForge dependency."""
    import app.core.catalogos as catalogos_pkg

    # The module's ``__dict__`` is the union of its re-exports; we
    # assert NONE of the public names are concrete InsForge classes.
    for name in catalogos_pkg.__all__:
        obj = getattr(catalogos_pkg, name)
        module = getattr(obj, "__module__", "") or ""
        assert "insforge" not in module.lower(), (
            f"domain entity {name!r} leaked InsForge import from {module!r}"
        )


def test_application_layer_does_not_import_insforge() -> None:
    """Rule §31: application layer depends on the Protocol, not on a concrete client."""
    from app.core.application import catalogos as app_pkg

    for module_name in app_pkg.__all__:
        module = __import__(
            f"app.core.application.catalogos.{module_name}",
            fromlist=["_"],
        )
        for attr in module.__dict__.values():
            attr_module = getattr(attr, "__module__", "") or ""
            # ``Protocol`` itself lives in ``typing``; the conftest
            # fakes live in this test file. Neither is the
            # ``app.core.insforge`` module.
            assert "insforge" not in attr_module.lower() or attr_module.startswith(
                "tests"
            ), (
                f"application module {module_name!r} leaked InsForge import "
                f"from {attr_module!r}"
            )


def test_di_layer_does_not_export_domain_or_port() -> None:
    """The DI helper exposes ONLY FastAPI dependencies — domain entities and
    ports are hidden behind the ``get_<slice>_port`` factories.

    As more slices land, ``app.core.di.__all__`` grows by one entry per
    slice (``get_catalogos_port``, ``get_schema_bootstrap_port``, ...).
    The invariant this test pins is: every exported name in
    ``app.core.di`` is a FastAPI dependency callable, NOT a domain
    entity or a Protocol class (the latter would let the route layer
    skip the DI seam and bind a port directly).
    """
    import importlib

    di_pkg = importlib.import_module("app.core.di")
    catalogos_di = importlib.import_module("app.core.di.catalogos_di")

    # catalogos_di is slice-scoped: it only exports its own dependency.
    assert catalogos_di.__all__ == ["get_catalogos_port"]

    # The package re-exports each slice's DI factory. None of those
    # factories are domain entities or Protocol classes.
    for export_name in di_pkg.__all__:
        attr = getattr(di_pkg, export_name)
        attr_module = getattr(attr, "__module__", "") or ""
        assert "core.domain" not in attr_module, (
            f"app.core.di leaked a domain import via {export_name!r} from {attr_module!r}"
        )
        assert "core.ports" not in attr_module, (
            f"app.core.di leaked a port import via {export_name!r} from {attr_module!r}"
        )
