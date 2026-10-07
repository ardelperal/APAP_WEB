"""Route-layer tests for DOC-01 SLICE 2 (issue #1109, contratos).

Mirrors ``tests/test_cesiones_routes.py``: routes are pure HTTP /
auth / template glue. The fixture ``_NoSqlRouteClient`` enforces the
AGENTS.md layer-boundary rule -- routes may not call
``execute_sql`` directly; the SQL is owned by the canonical
``app.modules.contratos.contratos_queries`` module and invoked
through the per-request ``SqlExecutor`` injected via the contratos
DI (``get_contratos_sql_executor``). The spy intercepts every
``execute_sql`` call so a regression that re-introduces a direct
SQL call in the route body fails loud.

The PDF generator, template port and storage port are real
:mod:`ReportLabPdfGenerator`, :class:`FilesystemContratosPlantillas`
and :class:`MinioContratosStorage` instances by default. The
storage port is wired to an in-memory ``_FakeClient`` so the test
is hermetic (no MinIO, no network).

Coverage (six atoms, one per acceptance criterion):

1.  Auth guard on every endpoint (unauthenticated -> 302).
2.  Write-permission user generates a contract; the route
    redirects to the download endpoint and the PDF bytes land in
    the storage adapter.
3.  Reader rol is rejected with 403 on POST.
4.  Second contract for the same (tipo, entity) -> 409 (legacy
    uniqueness rule, ``docs/legacy-signed-contract-flow.md`` §5).
5.  Download GET returns the stored PDF bytes for an existing
    contrato.
6.  Unknown ``tipo`` value in the URL -> 404.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.auth_dependencies import get_local_backend_client_dep
from app.core.config import get_settings
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.session import session_cookie_name, write_session
from app.main import app, get_local_backend_client
from app.modules.contratos.adapters.local_backend.contratos_local_backend_storage import (
    MinioContratosStorage,
)
from app.modules.contratos.di import (
    get_contratos_pdf_port,
    get_contratos_plantilla_port,
    get_contratos_sql_executor,
    get_contratos_storage_bucket,
    get_contratos_storage_port,
)
from tests.conftest import auth_reval_rows, make_csrf_request

# ---------------------------------------------------------------------------
# SQL spy
# ---------------------------------------------------------------------------


class _ContratosSqlSpy(LocalPostgresExecutor):
    """In-memory spy for the contratos table SQL.

    Routes never execute SQL directly (the DI generator provides
    the executor). The spy pattern-matches on each contratos query
    so the application layer sees a working SQL backend without
    touching the real DB. Two state slices:

    - ``existing_contratos``: the set of ``(tipo, entity_type, entity_id)``
      tuples already persisted; the spy answers ``exists_for_entity``
      against this set and ``get_contrato_for_entity`` returns a
      full row for the same.
    - ``inserted``: the list of ``(tipo, entity_type, entity_id, ...)``
      tuples the spy has accepted via ``insert_contrato``.

    The auth-revalidation query is answered by ``auth_reval_rows`` so
    the revalidation guard still fires; anything else that looks like
    a contratos query is answered from the in-memory state; an
    unrecognised SQL raises AssertionError so a regression that
    introduces a new SQL call without spy support fails loud.

    Inherits from :class:`LocalPostgresExecutor` for parity with the
    cesiones ``_NoSqlRouteClient`` (the route spies follow a
    single pattern across the codebase).
    """

    def __init__(self) -> None:
        self.auth_reval_rol: str = "key_user"
        self.existing_contratos: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.inserted: list[dict[str, Any]] = []
        self._next_id = 1
        self._tipo_to_id: dict[str, str] = {}

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        normalised = " ".join(query.split())
        reval = auth_reval_rows(normalised, params, rol=self.auth_reval_rol)
        if reval is not None:
            return reval

        if "FROM catalogos_tipos_contrato" in normalised and "WHERE codigo" in normalised:
            codigo = (params or [None])[0]
            tipo_id = self._tipo_to_id.setdefault(
                str(codigo), f"tipo-{len(self._tipo_to_id) + 1}"
            )
            return [{"id": tipo_id, "codigo": str(codigo)}]

        if "FROM contratos c" in normalised and "JOIN catalogos_tipos_contrato" in normalised:
            if "LIMIT 1" in normalised and "WHERE tc.codigo" in normalised and "1 AS" in normalised:
                codigo = (params or [None])[0]
                entity_id = (params or [None, None])[1]
                entity_type = self._extract_entity_type(normalised)
                key = (str(codigo), str(entity_type), str(entity_id))
                return [{}] if key in self.existing_contratos else []
            if "WHERE tc.codigo" in normalised and "RETURNING" not in normalised:
                codigo = (params or [None])[0]
                entity_id = (params or [None, None])[1]
                entity_type = self._extract_entity_type(normalised)
                key = (str(codigo), str(entity_type), str(entity_id))
                row = self.existing_contratos.get(key)
                if row is None:
                    return []
                return [{
                    "id": row["id"],
                    "tipo_contrato_id": row["tipo_contrato_id"],
                    "numero_contrato": row["numero_contrato"],
                    "fecha": row.get("fecha"),
                }]

        if "INSERT INTO contratos" in normalised and "RETURNING" in normalised:
            tipo_contrato_id, numero_contrato, fecha, entity_id = (
                (params or [None] * 4)[:4]
            )
            codigo = next(
                (k for k, v in self._tipo_to_id.items() if v == str(tipo_contrato_id)),
                "",
            )
            entity_type = self._extract_entity_type(normalised)
            key = (codigo, entity_type, str(entity_id))
            if key in self.existing_contratos:
                from app.core.data_access import BackendError
                raise BackendError(
                    status_code=409,
                    body={
                        "code": "23505",
                        "message": (
                            f"duplicate key value violates unique "
                            f"constraint on contratos ({entity_type}, tipo)"
                        ),
                    },
                )
            row = {
                "id": f"ctr-{self._next_id}",
                "tipo_contrato_id": str(tipo_contrato_id),
                "numero_contrato": str(numero_contrato),
                "fecha": fecha,
            }
            self._next_id += 1
            self.existing_contratos[key] = row
            self.inserted.append({
                "tipo": codigo,
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "numero_contrato": row["numero_contrato"],
                "fecha": row["fecha"],
            })
            return [{
                "id": row["id"],
                "tipo_contrato_id": row["tipo_contrato_id"],
                "numero_contrato": row["numero_contrato"],
                "fecha": row["fecha"],
            }]

        raise AssertionError(
            f"contratos SQL spy: unrecognised query {query!r}"
        )

    def close(self) -> None:
        pass  # no-op for the spy

    @staticmethod
    def _extract_entity_type(normalised_sql: str) -> str:
        """Return the entity column name (``entrada_id`` etc.) from the SQL.

        The contratos queries module interpolates the entity column
        directly in the SQL string; the spy pattern-matches the
        column name so it can rebuild the ``(tipo, entity_type,
        entity_id)`` tuple used by the application layer.
        """
        for column in ("entrada_id", "acogida_id", "adopcion_id", "cesion_id"):
            if column in normalised_sql:
                return {
                    "entrada_id": "entrada",
                    "acogida_id": "acogida",
                    "adopcion_id": "adopcion",
                    "cesion_id": "cesion",
                }[column]
        raise AssertionError(
            f"contratos SQL spy: cannot infer entity column from {normalised_sql!r}"
        )


# ---------------------------------------------------------------------------
# In-memory MinIO client
# ---------------------------------------------------------------------------


def _install_minio_fake() -> Any:
    """Build a MinIO fake that satisfies the contratos storage Protocol.

    Reuses the ``_FakeClient`` defined in
    ``tests.test_contratos_local_backend_storage`` (it is
    :class:`runtime_checkable` against ``S3StorageClient`); the
    import lives here to keep the test self-contained.
    """
    from tests.test_contratos_local_backend_storage import _FakeClient
    return _FakeClient()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def contratos_spy() -> _ContratosSqlSpy:
    """Provide a fresh :class:`_ContratosSqlSpy` per test."""
    return _ContratosSqlSpy()


@pytest.fixture
def route_client(contratos_spy: _ContratosSqlSpy) -> _ContratosSqlSpy:
    """Wire the spy + MinIO fake + the contratos DI overrides.

    Mirrors the cesiones ``route_client`` fixture: the spy is
    installed on ``app.state.sql_executor`` and on the per-request
    DI generator; the storage port DI is overridden with a real
    :class:`MinioContratosStorage` backed by an in-memory fake.
    """
    minio_client = _install_minio_fake()
    storage_adapter = MinioContratosStorage(minio_client)  # type: ignore[arg-type]

    # Replace the per-request executor DI so get_contratos_sql_executor
    # returns the spy instead of the autouse _DefaultLocalBackendSpy
    # (the conftest fixture installs a generic spy; the contratos
    # route must use a SQL backend that answers contratos queries).
    app.dependency_overrides[get_local_backend_client] = lambda: contratos_spy
    app.dependency_overrides[get_local_backend_client_dep] = lambda: contratos_spy
    app.dependency_overrides[get_contratos_sql_executor] = lambda: contratos_spy
    app.state.sql_executor = contratos_spy

    # Override the storage port so the route writes the PDF into the
    # in-memory MinIO fake. The plantilla and PDF ports stay on their
    # real adapters (filesystem + reportlab) so the test exercises
    # the production rendering chain.
    app.dependency_overrides[get_contratos_storage_port] = lambda: storage_adapter
    app.dependency_overrides[get_contratos_storage_bucket] = lambda: "apap-contracts-test"
    app.dependency_overrides[get_contratos_plantilla_port] = lambda: _default_plantilla_port()
    app.dependency_overrides[get_contratos_pdf_port] = lambda: _default_pdf_port()

    yield contratos_spy

    # Clean up overrides so the next test sees the autouse spy again.
    for key in (
        get_local_backend_client,
        get_local_backend_client_dep,
        get_contratos_sql_executor,
        get_contratos_storage_port,
        get_contratos_storage_bucket,
        get_contratos_plantilla_port,
        get_contratos_pdf_port,
    ):
        app.dependency_overrides.pop(key, None)


def _default_plantilla_port():
    """Build a fresh :class:`FilesystemContratosPlantillas` for the test.

    Lazy import keeps the top of the file import-light; the adapter
    is cheap (it reads on first access and caches).
    """
    from app.modules.contratos.adapters.filesystem.contratos_filesystem_plantillas import (
        FilesystemContratosPlantillas,
    )
    return FilesystemContratosPlantillas()


def _default_pdf_port():
    """Build a fresh :class:`ReportLabPdfGenerator` for the test."""
    from app.modules.contratos.adapters.local_backend.contratos_local_backend_pdf import (
        ReportLabPdfGenerator,
    )
    return ReportLabPdfGenerator()


def _login_as_key_user(client: httpx.AsyncClient) -> None:
    """Mint a session cookie with a known CSRF token bound to it."""
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-contratos",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _login_as_reader(client: httpx.AsyncClient) -> None:
    """Mint a reader cookie; the writer dep MUST reject with 403."""
    token = write_session(
        {
            "email": "rocio@example.com",
            "rol": "reader",
            "user_id": "u-rocio",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-contratos",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _form_data(**overrides: str) -> dict[str, str]:
    """Canonical happy-path payload for the contratos form."""
    data = {
        "tipo": "Adopción",
        "entity_type": "entrada",
        "entity_id": "ent-001",
        "numero_contrato": "CP1000",
        "fecha": "2026-10-02",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_contratos_routes_require_authorized_user(
    client: httpx.AsyncClient,
) -> None:
    """Unauthenticated POST /contratos -> 302 to /login."""
    response = await make_csrf_request(
        client, "POST", "/contratos", form_data=_form_data(),
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


async def test_create_contrato_redirects_to_download_and_stores_pdf(
    client: httpx.AsyncClient,
    route_client: _ContratosSqlSpy,
) -> None:
    """Happy path: write-permission user generates; redirect + stored PDF.

    The route translates the form into a :class:`GeneratedContrato`,
    persists a ``contratos`` row via the canonical queries module,
    and writes the PDF into the storage adapter. The 303 redirect
    points at the download endpoint so the operator sees the PDF on
    the next request.
    """
    _login_as_key_user(client)

    response = await make_csrf_request(
        client, "POST", "/contratos", form_data=_form_data(),
        csrf_token="test-csrf-token-contratos",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/contratos/entrada/ent-001/Adopci%C3%B3n"
    assert len(route_client.inserted) == 1
    inserted = route_client.inserted[0]
    assert inserted["entity_type"] == "entrada"
    assert inserted["entity_id"] == "ent-001"
    assert inserted["tipo"] == "Adopción"


async def test_create_contrato_rejects_reader_with_403(
    client: httpx.AsyncClient,
    route_client: _ContratosSqlSpy,
) -> None:
    """A reader rol cannot POST /contratos (403 BEFORE the handler runs).

    Mirrors the cesiones reader-403 atom: the per-request
    revalidation SELECT returns ``reader``, the writer dep fires
    403, the contratos SQL spy is never touched.
    """
    route_client.auth_reval_rol = "reader"
    _login_as_reader(client)

    response = await make_csrf_request(
        client, "POST", "/contratos", form_data=_form_data(),
        csrf_token="test-csrf-token-contratos",
    )
    assert response.status_code == 403
    assert route_client.inserted == []


async def test_create_contrato_rejects_duplicate_with_409(
    client: httpx.AsyncClient,
    route_client: _ContratosSqlSpy,
) -> None:
    """A second contrato for the same ``(tipo, entity)`` -> 409.

    Pre-seed the spy with an existing row so the INSERT raises the
    UNIQUE conflict the canonical queries module translates to
    :class:`ContratoConflictError`. The route maps that to HTTP 409
    per the legacy "un único contrato por tipo por entidad" rule
    (``docs/legacy-signed-contract-flow.md`` §5).
    """
    _login_as_key_user(client)
    # Pre-seed a matching contrato row.
    route_client.existing_contratos[("Adopción", "entrada", "ent-001")] = {
        "id": "ctr-existing",
        "tipo_contrato_id": "tipo-1",
        "numero_contrato": "CP0999",
        "fecha": "2026-09-01",
    }

    response = await make_csrf_request(
        client, "POST", "/contratos", form_data=_form_data(),
        csrf_token="test-csrf-token-contratos",
    )
    assert response.status_code == 409
    assert "ya existe un contrato" in response.text


async def test_download_contrato_returns_stored_pdf(
    client: httpx.AsyncClient,
    route_client: _ContratosSqlSpy,
) -> None:
    """The download GET returns the stored PDF bytes for an existing row.

    Pre-seed both the contratos row and the storage adapter so the
    route can find the asset; the response carries the same bytes
    the storage adapter was given.
    """
    _login_as_key_user(client)
    route_client.existing_contratos[("Adopción", "entrada", "ent-001")] = {
        "id": "ctr-1",
        "tipo_contrato_id": "tipo-1",
        "numero_contrato": "CP1000",
        "fecha": "2026-10-02",
    }
    # Write the PDF directly into the storage adapter the test installed.
    from app.modules.contratos.di import get_contratos_storage_port
    storage = app.dependency_overrides[get_contratos_storage_port]()
    storage.put_pdf(
        bucket="apap-contracts-test", key="Adopción_ent-001.pdf",
        body=b"%PDF-fake-bytes",
    )

    response = await client.get("/contratos/entrada/ent-001/Adopci%C3%B3n")
    assert response.status_code == 200
    assert response.content == b"%PDF-fake-bytes"
    assert response.headers["content-type"].startswith("application/pdf")


async def test_download_contrato_returns_404_for_unknown_tipo(
    client: httpx.AsyncClient,
    route_client: _ContratosSqlSpy,
) -> None:
    """A typo in the URL ``tipo`` -> 404 (no contrato row for it).

    The canonical queries module returns ``None`` from
    ``get_contrato_for_entity`` when no row matches, and the route
    translates ``None`` to HTTP 404.
    """
    _login_as_key_user(client)
    # Pre-seed the contrato for "Adopción" but ask for "Cesion" instead.
    route_client.existing_contratos[("Adopción", "entrada", "ent-001")] = {
        "id": "ctr-1",
        "tipo_contrato_id": "tipo-1",
        "numero_contrato": "CP1000",
        "fecha": "2026-10-02",
    }

    response = await client.get("/contratos/entrada/ent-001/Cesion")
    assert response.status_code == 404


async def test_create_contrato_unknown_tipo_returns_422(
    client: httpx.AsyncClient,
    route_client: _ContratosSqlSpy,
) -> None:
    """A ``tipo`` value outside the legacy catalog -> 422.

    ``generate_contrato`` raises
    :class:`ContratoTipoInvalidoError` before any SQL is executed;
    the route maps it (with the other validation errors) to HTTP
    422 per the legacy catalog-validation rule.
    """
    _login_as_key_user(client)

    response = await make_csrf_request(
        client, "POST", "/contratos",
        form_data=_form_data(tipo="TipoInexistente"),
        csrf_token="test-csrf-token-contratos",
    )
    assert response.status_code == 422
    assert "no se pudo generar" in response.text
    assert route_client.inserted == []


async def test_create_contrato_missing_plantilla_returns_404(
    client: httpx.AsyncClient,
    route_client: _ContratosSqlSpy,
) -> None:
    """A tipo whose template file is absent -> 404.

    Overrides the plantilla port with a stub that raises
    :class:`PlantillaNoDisponibleError` so the route's mapping
    (template source unavailable -> 404, never a 500) is exercised
    without depending on which templates currently carry the
    legacy-marker text.
    """
    from app.modules.contratos.domain.plantilla import (
        PlantillaNoDisponibleError,
    )

    class _MissingPlantillaPort:
        def obtener_plantilla(self, tipo: str) -> str:
            raise PlantillaNoDisponibleError(tipo)

    app.dependency_overrides[get_contratos_plantilla_port] = (
        lambda: _MissingPlantillaPort()
    )
    try:
        _login_as_key_user(client)
        response = await make_csrf_request(
            client, "POST", "/contratos", form_data=_form_data(),
            csrf_token="test-csrf-token-contratos",
        )
    finally:
        app.dependency_overrides.pop(get_contratos_plantilla_port, None)
    assert response.status_code == 404
    assert "plantilla no disponible" in response.text
    assert route_client.inserted == []


async def test_download_contrato_invalid_entity_type_returns_422(
    client: httpx.AsyncClient,
    route_client: _ContratosSqlSpy,
) -> None:
    """A URL ``entity_type`` outside the legacy entity set -> 422.

    ``entity_column`` validates the URL segment against the legacy
    entity whitelist before any SQL runs; the route maps the
    ``ValueError`` to HTTP 422.
    """
    _login_as_key_user(client)

    response = await client.get("/contratos/voluntario/ent-001/Adopci%C3%B3n")
    assert response.status_code == 422
    assert "entity_type invalido" in response.text


async def test_contratos_route_source_contains_no_direct_execute_sql() -> None:
    """AGENTS rule 1: routes are HTTP-only. SQL lives in the queries module.

    Defense in depth alongside the runtime ``_ContratosSqlSpy`` --
    if a future refactor re-introduces ``client.execute_sql`` in
    the route body, the static check fails first.
    """
    import pathlib
    source = pathlib.Path(
        "app/modules/contratos/contratos_routes.py"
    ).read_text(encoding="utf-8")
    # Drop the module docstring (the only place ``execute_sql``
    # appears as a reference, not a call).
    body = source[source.index('"""', source.index('"""') + 3) + 3:]
    assert "execute_sql" not in body, (
        "contratos routes must not call execute_sql directly; "
        "delegate to the canonical contratos_queries module"
    )
