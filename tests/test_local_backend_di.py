"""Composition-root regression tests for LocalBackend adapters."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.core.adapters.local_backend.auth_local_backend_adapter import (
    LocalBackendAuthUsersAdapter,
)
from app.core.adapters.local_backend.catalogos_local_backend_adapter import (
    LocalBackendCatalogosAdapter,
)
from app.core.adapters.local_backend.oauth_local_backend_adapter import (
    LocalBackendOAuthAdapter,
)
from app.core.adapters.local_backend.schema_bootstrap_local_backend_adapter import (
    LocalBackendSchemaBootstrapAdapter,
)
from app.core.di.auth_di import get_auth_users_port
from app.core.di.catalogos_di import get_catalogos_port
from app.core.di.oauth_di import get_oauth_port
from app.core.di.schema_bootstrap_di import get_schema_bootstrap_port
from app.modules.animals.adapters.local_backend.animals_local_backend_adapter import (
    AnimalsLocalBackendAdapter,
)
from app.modules.animals.di.animals_di import get_animals_port
from app.modules.cesiones.adapters.local_backend.cesiones_local_backend_adapter import (
    CesionesLocalBackendAdapter,
)
from app.modules.cesiones.di import get_cesiones_port
from app.modules.lifecycle.adapters.local_backend.lifecycle_local_backend_adapter import (
    LocalBackendLifecycleAdapter,
)
from app.modules.lifecycle.di.lifecycle_di import build_lifecycle_port
from app.modules.voluntarios.adapters.local_backend.voluntarios_local_backend_adapter import (
    VoluntariosLocalBackendAdapter,
)
from app.modules.voluntarios.di import get_voluntarios_port
from tests.sql_executor_fake import HandlerSqlExecutor


def _executor() -> HandlerSqlExecutor:
    return HandlerSqlExecutor(lambda _request: httpx.Response(200, json=[]))


@pytest.mark.parametrize(
    ("provider", "expected_type"),
    [
        (get_auth_users_port, LocalBackendAuthUsersAdapter),
        (get_catalogos_port, LocalBackendCatalogosAdapter),
        (get_oauth_port, LocalBackendOAuthAdapter),
        (get_schema_bootstrap_port, LocalBackendSchemaBootstrapAdapter),
        (get_animals_port, AnimalsLocalBackendAdapter),
        (get_cesiones_port, CesionesLocalBackendAdapter),
        (get_voluntarios_port, VoluntariosLocalBackendAdapter),
    ],
)
def test_request_provider_yields_real_local_backend_adapter(
    provider: Callable[[Any], Iterator[Any]],
    expected_type: type[Any],
) -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(sql_executor=_executor()))
    )

    dependency = provider(request)
    try:
        port = next(dependency)
    finally:
        dependency.close()

    assert type(port) is expected_type


def test_lifecycle_factory_builds_real_local_backend_adapter() -> None:
    port = build_lifecycle_port(_executor())

    assert type(port) is LocalBackendLifecycleAdapter
