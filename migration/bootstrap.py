"""M0 infrastructure bootstrap helpers for live data migration.

The helpers in this module separate code readiness from real backend
mutation: tests inject fakes, while the operator runs the CLI checkpoint
against the intended LocalBackend infrastructure surface.

Post-#5 (LocalBackend runtime), the migration package no longer talks
to a LocalBackend backend for storage. Buckets were a legacy concept (the LocalBackend has no bucket backend)
that the LocalBackend does not implement (the LocalBackend is pure
postgres + a simple photo-storage stub in
:mod:`app.core.local_backend.storage`). The bucket-side helpers here
remain as no-op shims so the public ``migration.cli.ensure-bucket``
command still parses and exits 0; real bucket assertions against a
live backend land when storage goes through the dedicated photo-storage
path in #8 follow-ups.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from migration.shadow_state import ShadowStateRepository

APAP_PHOTOS_BUCKET = "apap-photos"


class _ShadowClient(Protocol):
    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class BucketEnsureResult:
    """Outcome of checking or creating the private photo bucket."""

    bucket_name: str
    is_public: bool
    status: str


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """Outcome of M0 infrastructure bootstrap."""

    shadow_table_ready: bool
    bucket: BucketEnsureResult


def ensure_shadow_table(client: _ShadowClient) -> None:
    """Ensure ``web_only_feature_shadow`` through its repository contract."""
    ShadowStateRepository(client).ensure_table()


def check_private_bucket(
    bucket_name: str = APAP_PHOTOS_BUCKET,
) -> BucketEnsureResult:
    """Legacy no-op shim — returns private bucket state without I/O.

    The legacy bucket backend was retired with the runtime in #5;
    this shim preserves the CLI surface (``migration.cli.ensure-bucket``)
    so existing operator scripts keep parsing and exit 0. Bucket state
    is asserted as private by the local photo-storage path in
    :mod:`app.core.local_backend.storage`; this function is a
    backward-compat shim only.
    """
    return BucketEnsureResult(bucket_name=bucket_name, is_public=False, status="exists")


def ensure_private_bucket(
    bucket_name: str = APAP_PHOTOS_BUCKET,
) -> BucketEnsureResult:
    """Legacy no-op shim — returns private bucket state without I/O.

    See :func:`check_private_bucket` for the rationale.
    """
    return BucketEnsureResult(bucket_name=bucket_name, is_public=False, status="exists")


def bootstrap_m0_infrastructure(
    client: _ShadowClient,
    *,
    bucket_name: str = APAP_PHOTOS_BUCKET,
) -> BootstrapResult:
    """Ensure shadow schema before apply locks.

    Bucket management is no longer an apply-path concern (see
    :func:`ensure_private_bucket` for the rationale). The shadow table
    is the only piece of M0 infrastructure the LocalBackend still owns.
    """
    ensure_shadow_table(client)
    bucket = check_private_bucket(bucket_name=bucket_name)
    return BootstrapResult(shadow_table_ready=True, bucket=bucket)


__all__ = [
    "APAP_PHOTOS_BUCKET",
    "BootstrapResult",
    "BucketEnsureResult",
    "bootstrap_m0_infrastructure",
    "check_private_bucket",
    "ensure_private_bucket",
    "ensure_shadow_table",
]
