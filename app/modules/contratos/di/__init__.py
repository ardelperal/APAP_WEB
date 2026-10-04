"""Composition root — Contratos slice DI (DOC-01 SLICE 2, issue #1109).

Wires the three stateless contract-side ports (template, PDF, object
storage) and the per-request :class:`SqlExecutor` to the application
use cases. The contract-side adapters are constructed at module load
time (the :class:`FilesystemContratosPlantillas` cache, the
:class:`ReportLabPdfGenerator` platypus state and the
:class:`MinioContratosStorage` are all stateless beyond their
constructor inputs), so the DI providers yield a stable per-request
view without rebuilding the adapters every time.

The :class:`SqlExecutor` is request-scoped and read from
``request.app.state.sql_executor`` -- the same seam other slices
use (``app.modules.cesiones.di``,
``app.modules.animals.di.animals_di``).

The MinIO client follows the ``apap-photos`` provisioning pattern:
bucket creation is delegated to deployment
(``scripts/create_minio_bucket.py`` creates ``apap-photos``; the
contratos bucket ``apap-contracts`` is provisioned by the same
operator run with the ``APAP_S3_BUCKET=apap-contracts`` override or
a follow-up script invocation). The lifespan wires the client on
``app.state.contratos_storage_client`` and the DI provider reads it.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.core.data_access import SqlExecutor
from app.modules.contratos.adapters.filesystem.contratos_filesystem_plantillas import (
    FilesystemContratosPlantillas,
)
from app.modules.contratos.adapters.local_backend.contratos_local_backend_pdf import (
    ReportLabPdfGenerator,
)
from app.modules.contratos.adapters.local_backend.contratos_local_backend_storage import (
    DEFAULT_BUCKET,
    MinioContratosStorage,
)
from app.modules.contratos.ports.contratos_pdf_port import ContratosPdfPort
from app.modules.contratos.ports.contratos_plantilla_port import (
    ContratosPlantillaPort,
)
from app.modules.contratos.ports.contratos_storage_port import (
    ContratosStoragePort,
)

#: Module-level singletons for the three stateless adapters. They
#: are constructed once at import time so the per-request DI
#: providers can yield them without rebuilding the reportlab state
#: or re-reading the filesystem cache. Tests override the DI
#: providers (or the ports directly) to substitute fakes; the
#: module-level constants are not mutated.
_plantilla_port: ContratosPlantillaPort = FilesystemContratosPlantillas()
_pdf_port: ContratosPdfPort = ReportLabPdfGenerator()


def get_contratos_plantilla_port() -> Iterator[ContratosPlantillaPort]:
    """Yield the slice's :class:`ContratosPlantillaPort`.

    The :class:`FilesystemContratosPlantillas` adapter caches
    template bodies on first read; the singleton is shared across
    requests so the cache amortises the file I/O. Tests override
    this provider via ``app.dependency_overrides`` to substitute a
    stub adapter.
    """
    yield _plantilla_port


def get_contratos_pdf_port() -> Iterator[ContratosPdfPort]:
    """Yield the slice's :class:`ContratosPdfPort`.

    :class:`ReportLabPdfGenerator` is stateless (it builds the
    platypus story per call from the CP-2 envelope); the singleton
    is shared across requests.
    """
    yield _pdf_port


def get_contratos_storage_port(
    request: Request,
) -> Iterator[ContratosStoragePort]:
    """Yield the slice's :class:`ContratosStoragePort`.

    The MinIO client is wired by the lifespan onto
    ``app.state.contratos_storage_client``. The DI provider reads
    it lazily so a deployment that does not configure MinIO still
    constructs a functional storage adapter (the underlying
    :class:`minio.Minio` raises on use, which is the same
    fail-closed behaviour ``apap-photos`` follows).
    """
    client = getattr(request.app.state, "contratos_storage_client", None)
    yield MinioContratosStorage(client)  # type: ignore[arg-type]


def get_contratos_storage_bucket() -> Iterator[str]:
    """Yield the default object-storage bucket name.

    Defaults to :data:`DEFAULT_BUCKET` (``apap-contracts``) so the
    route does not need to import the constant; tests override
    this provider to point at a temporary bucket.
    """
    yield DEFAULT_BUCKET


def get_contratos_sql_executor(request: Request) -> Iterator[SqlExecutor]:
    """Yield the per-request :class:`SqlExecutor` for the contratos table.

    Mirrors ``app.modules.cesiones.di.get_cesiones_port`` so the
    contratos application layer reaches the canonical queries
    module through the same request-scoped seam.
    """
    executor: SqlExecutor = request.app.state.sql_executor
    yield executor


__all__ = [
    "DEFAULT_BUCKET",
    "get_contratos_pdf_port",
    "get_contratos_plantilla_port",
    "get_contratos_sql_executor",
    "get_contratos_storage_bucket",
    "get_contratos_storage_port",
]
