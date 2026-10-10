"""Region contract for the S3 client (issue #1309).

Cloudflare R2 requires ``region="auto"``. The ``minio`` client otherwise signs
with its default (``us-east-1``), R2 rejects the signature and the health probe
reports ``storage: down``, which is what the `e2e` job saw once the credentials
reached the pytest step (issue #1095, slice 4 tramo C).
"""

from __future__ import annotations

import pytest

from app.core.local_backend import s3

R2_ENDPOINT = "https://account-id.r2.cloudflarestorage.com"


class TestRegionResolution:
    def test_r2_endpoint_defaults_to_auto(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("APAP_S3_REGION", raising=False)
        monkeypatch.setenv("APAP_S3_ENDPOINT", R2_ENDPOINT)

        assert s3._region() == "auto"

    def test_r2_endpoint_without_scheme_also_gets_auto(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("APAP_S3_REGION", raising=False)
        monkeypatch.setenv("APAP_S3_ENDPOINT", "account-id.r2.cloudflarestorage.com")

        assert s3._region() == "auto"

    def test_non_r2_endpoint_keeps_the_client_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("APAP_S3_REGION", raising=False)
        monkeypatch.setenv("APAP_S3_ENDPOINT", "http://127.0.0.1:59000")

        assert s3._region() is None

    def test_explicit_region_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APAP_S3_REGION", "eu-west-1")
        monkeypatch.setenv("APAP_S3_ENDPOINT", R2_ENDPOINT)

        assert s3._region() == "eu-west-1"


class TestClientWiring:
    def test_the_client_is_built_with_the_resolved_region(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pin the wiring, not just the helper: the caller must pass it.

        A helper nobody calls is how the R2 signature failure stayed invisible.
        """
        captured: dict[str, object] = {}

        class RecordingClient:
            def __init__(self, endpoint: str, **kwargs: object) -> None:
                captured["endpoint"] = endpoint
                captured.update(kwargs)

        import minio

        monkeypatch.delenv("APAP_S3_REGION", raising=False)
        monkeypatch.setattr(s3, "_endpoint", lambda: "account-id.r2.cloudflarestorage.com")
        monkeypatch.setattr(s3, "_credentials", lambda: ("key", "secret"))
        monkeypatch.setattr(minio, "Minio", RecordingClient)

        assert s3._unconfigured_client() is not None
        assert captured["region"] == "auto"
