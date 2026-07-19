"""M0 infrastructure bootstrap helpers for live data migration.

The helpers in this module separate code readiness from real backend
mutation: tests inject fakes, while the operator runs the CLI checkpoint
against the intended InsForge infrastructure surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from app.core.insforge import InsForgeError
from migration.shadow_state import ShadowStateRepository

APAP_PHOTOS_BUCKET = "apap-photos"


class _ShadowClient(Protocol):
    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]: ...


class _BucketAdmin(Protocol):
    def get_bucket(self, bucket_name: str) -> dict[str, Any] | None: ...

    def ensure_bucket(self, bucket_name: str, *, is_public: bool = False) -> dict[str, Any]: ...


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
    bucket_admin: _BucketAdmin,
    bucket_name: str = APAP_PHOTOS_BUCKET,
) -> BucketEnsureResult:
    """Read back bucket state and fail closed unless it is private."""
    bucket = bucket_admin.get_bucket(bucket_name)
    if bucket is None:
        raise InsForgeError(
            404,
            {
                "error": "bucket_missing",
                "message": f"Bucket {bucket_name!r} does not exist",
            },
        )
    _assert_private_bucket(bucket_name, bucket)
    return BucketEnsureResult(bucket_name=bucket_name, is_public=False, status="exists")


def ensure_private_bucket(
    bucket_admin: _BucketAdmin,
    bucket_name: str = APAP_PHOTOS_BUCKET,
) -> BucketEnsureResult:
    """Create a missing bucket as private, then read back private state."""
    existing = bucket_admin.get_bucket(bucket_name)
    if existing is not None:
        _assert_private_bucket(bucket_name, existing)
        return BucketEnsureResult(bucket_name=bucket_name, is_public=False, status="exists")

    created = bucket_admin.ensure_bucket(bucket_name, is_public=False)
    _assert_private_bucket(bucket_name, created)

    readback = bucket_admin.get_bucket(bucket_name)
    if readback is None:
        raise InsForgeError(
            500,
            {
                "error": "bucket_readback_missing",
                "message": f"Bucket {bucket_name!r} was not visible after create",
            },
        )
    _assert_private_bucket(bucket_name, readback)
    return BucketEnsureResult(bucket_name=bucket_name, is_public=False, status="created")


def bootstrap_m0_infrastructure(
    client: _ShadowClient,
    *,
    bucket_admin: _BucketAdmin | None = None,
    bucket_name: str = APAP_PHOTOS_BUCKET,
) -> BootstrapResult:
    """Ensure shadow schema and private photo bucket before apply locks.

    The shadow table is always ensured via SQL DDL. The bucket admin
    defaults to ``client`` so production ``InsForgeClient`` can own both
    surfaces, while tests may inject a dedicated fake.
    """
    ensure_shadow_table(client)
    # cast: when no dedicated admin is injected, the production
    # ``InsForgeClient`` passed as ``client`` owns both surfaces.
    admin = bucket_admin or cast("_BucketAdmin", client)
    bucket = ensure_private_bucket(admin, bucket_name=bucket_name)
    return BootstrapResult(shadow_table_ready=True, bucket=bucket)


def _assert_private_bucket(bucket_name: str, bucket: dict[str, Any]) -> None:
    visibility = bucket.get("isPublic")
    if visibility is False:
        return
    if visibility is True:
        raise InsForgeError(
            409,
            {
                "error": "bucket_public_violation",
                "message": f"Bucket {bucket_name!r} exists but is public; recreate it private",
            },
        )
    raise InsForgeError(
        502,
        {
            "error": "bucket_visibility_unknown",
            "message": f"Bucket {bucket_name!r} visibility could not be verified",
        },
    )


__all__ = [
    "APAP_PHOTOS_BUCKET",
    "BootstrapResult",
    "BucketEnsureResult",
    "bootstrap_m0_infrastructure",
    "check_private_bucket",
    "ensure_private_bucket",
    "ensure_shadow_table",
]
