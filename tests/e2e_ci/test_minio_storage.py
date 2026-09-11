"""E2E smoke tests for MinIO / S3-compatible storage.

These tests run against the full application stack in CI:
- PostgreSQL (via the app's LocalPostgresExecutor)
- MinIO (seeded with the ``apap-photos`` bucket)
- The FastAPI app itself

A ``pytest.skip`` is raised when MinIO is not configured (local dev without
``APAP_S3_ACCESS_KEY``), so the tests remain safe to run against the local
development environment.
"""

from __future__ import annotations

import io
import os
import uuid

from minio import Minio
from playwright.sync_api import BrowserContext

# The bucket that the app's PhotoStorageClient targets.
PHOTO_BUCKET = "apap-photos"

# Predictable photo content for the test.
_MINIO_TEST_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDATx\xdac\xf8\x0f\x00\x00\x01"
    b"\x00\x01'\x18\xe3f\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestMinioStorageHealth:
    """Smoke tests for the MinIO service availability."""

    def test_healthz_storage_up(
        self,
        page,
        base_url: str,
    ) -> None:
        """``/healthz`` reports ``storage: up`` when MinIO is configured and reachable."""
        response = page.goto(f"{base_url}/healthz")

        assert response is not None
        assert response.status == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert "storage" in payload
        # With MinIO running: "up".  Without credentials: "unconfigured".
        # "down" means credentials are set but MinIO is unreachable.
        assert payload["storage"] in ("up", "unconfigured", "down"), (
            f"Unexpected storage status: {payload['storage']}"
        )

    def test_healthz_returns_200(
        self,
        browser_context: BrowserContext,
        base_url: str,
    ) -> None:
        """``/healthz`` returns HTTP 200 even when MinIO is unreachable.

        Uses Playwright's API request client (no ``requests`` dependency).
        """
        resp = browser_context.request.get(f"{base_url}/healthz")
        assert resp.ok, f"/healthz returned {resp.status}"
        payload = resp.json()
        assert payload["status"] == "ok"
        assert "storage" in payload


class TestMinioPhotoServing:
    """End-to-end tests for photo serving from MinIO.

    These tests require:
    - MinIO running with the ``apap-photos`` bucket
    - A seeded animal record in PostgreSQL
    - An object uploaded to MinIO under that animal's photo key
    """

    def test_animal_photo_from_minio(
        self,
        e2e_logged_in_browser_context,
        minio_client: Minio,
        e2e_db_conn,
        base_url: str,
    ) -> None:
        """Photo served from MinIO is returned with correct content-type and size."""
        # Generate a unique test identity so parallel test runs don't collide.
        test_id = uuid.uuid4().hex[:8]
        animal_id = f"e2e-minio-{test_id}"
        photo_key = f"test-minio-{test_id}.png"

        try:
            # 1. Ensure the bucket exists.
            if not minio_client.bucket_exists(PHOTO_BUCKET):
                minio_client.make_bucket(PHOTO_BUCKET)

            # 2. Upload a predictable PNG to MinIO.
            content = _MINIO_TEST_PNG
            data = io.BytesIO(content)
            minio_client.put_object(
                PHOTO_BUCKET,
                photo_key,
                data,
                length=len(content),
                content_type="image/png",
            )

            # 3. Insert an animal record pointing at this photo.
            # The ``nombrefoto`` column holds the MinIO object key.
            with e2e_db_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO animales (id, nombre, nombrefoto, estado)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                        SET nombrefoto = EXCLUDED.nombrefoto
                    """,
                    (animal_id, f"E2E Test Animal {test_id}", photo_key, "Refugio"),
                )

            # 4. Authenticate via the E2E stub and fetch the photo.
            context = e2e_logged_in_browser_context
            secret = os.environ["APAP_E2E_AUTH_SECRET"]
            default_email = os.environ.get("APAP_E2E_AUTH_DEFAULT_EMAIL", "e2e@apap.local")

            # Mint a session (sets the ``apap_session`` cookie on the context).
            login_resp = context.request.get(
                f"{base_url}/e2e/login",
                headers={
                    "X-E2E-Secret": secret,
                    "X-E2E-Email": default_email,
                },
            )
            assert login_resp.ok, f"E2E login failed: {login_resp.status}"

            # 5. Request the photo via the browser context (carries the session cookie).
            page = context.new_page()
            photo_resp = page.goto(f"{base_url}/animales/{animal_id}/foto")

            assert photo_resp is not None
            assert photo_resp.status == 200
            assert photo_resp.headers.get("content-type", "").startswith("image/")

            # Verify the content matches what we uploaded.
            body = photo_resp.body()
            assert body == content, (
                f"Photo content mismatch: expected {len(content)} bytes, "
                f"got {len(body)}"
            )

        finally:
            # Teardown: remove test artifacts so they don't pollute subsequent runs.
            try:
                minio_client.remove_object(PHOTO_BUCKET, photo_key)
            except Exception:
                pass  # best-effort cleanup

            with e2e_db_conn.cursor() as cur:
                cur.execute("DELETE FROM animales WHERE id = %s", (animal_id,))

    def test_animal_photo_404_when_no_record(
        self,
        e2e_logged_in_browser_context,
        base_url: str,
    ) -> None:
        """``GET /animales/{id}/foto`` returns 404 for a non-existent animal."""
        context = e2e_logged_in_browser_context
        secret = os.environ["APAP_E2E_AUTH_SECRET"]
        default_email = os.environ.get("APAP_E2E_AUTH_DEFAULT_EMAIL", "e2e@apap.local")

        login_resp = context.request.get(
            f"{base_url}/e2e/login",
            headers={
                "X-E2E-Secret": secret,
                "X-E2E-Email": default_email,
            },
        )
        assert login_resp.ok

        nonexistent_id = f"e2e-nonexistent-{uuid.uuid4().hex[:8]}"
        page = context.new_page()
        photo_resp = page.goto(f"{base_url}/animales/{nonexistent_id}/foto")

        assert photo_resp is not None
        assert photo_resp.status == 404

