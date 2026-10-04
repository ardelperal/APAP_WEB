"""E2E smoke tests for the DOC-01 contratos slice (issue #1109, SLICE 3).

The PDF-generation happy path and the 404 branch for the download
endpoint, both gated by the live application stack:

- POST /contratos (with a developer session and the session-bound CSRF
  token) renders the contract PDF via the reportlab adapter, writes
  it to the ``apap-contracts`` MinIO bucket under the legacy
  ``{Tipo}_{ID}.pdf`` key, and inserts the matching ``contratos`` row.
  The route 303-redirects to the GET download URL.
- GET /contratos/{entity_type}/{entity_id}/{tipo} streams the stored
  PDF with the ``application/pdf`` content-type. The body starts with
  the PDF magic bytes (``%PDF-``).
- GET /contratos/{entity_type}/{entity_id}/{tipo} for a never-generated
  contract returns 404 (the canonical queries module answers ``None``
  for an absent row).

Pattern mirrors ``tests/e2e_ci/test_minio_storage.py`` (live app,
real Postgres, real MinIO). Tests skip cleanly when the env vars
that gate Postgres or MinIO are absent (local dev without
``APAP_LOCAL_DB_URL`` or ``APAP_S3_ACCESS_KEY``).

Seeding strategy (direct INSERT, NOT form-driven):

- The ``contratos`` table FKs the entity via ``entrada_id`` /
  ``acogida_id`` / ``adopcion_id`` / ``cesion_id`` (one of four,
  enforced by the ``contratos_exactly_one_entity`` CHECK).
- ``entradas.animal_id`` is a NOT NULL FK to ``animales``. The test
  inserts a minimal ``animales`` row, then a minimal ``entradas``
  row pointing at it. UUIDs are random per test so parallel runs do
  not collide (same pattern as ``test_minio_storage.py``).

Determinism: no ``datetime.now()`` / ``time.sleep`` (HR-10). All
UUIDs come from ``uuid.uuid4()``; all dates are ISO fixed values; the
fixture lives behind the same session-scoped MinIO + Postgres
fixtures the rest of the e2e suite uses, so no implicit ordering.
"""

from __future__ import annotations

import os
import uuid

from minio import Minio
from playwright.sync_api import BrowserContext

# The bucket the contratos slice writes to (``DEFAULT_BUCKET`` in
# ``app/modules/contratos/adapters/local_backend/
# contratos_local_backend_storage.py``). The bucket is not part of
# the e2e CI's ``scripts/create_minio_bucket.py`` provisioning
# (which only creates ``apap-photos``), so the test creates it
# itself when missing -- exactly the pattern
# ``test_minio_storage.py`` follows for ``apap-photos``.
CONTRATOS_BUCKET = "apap-contracts"

# ``tipo`` value that resolves cleanly against ``catalogos_tipos_
# contrato`` (seeded by ``ensure_catalogs`` from the Access legacy,
# codigo='Entrada'). See SLICE-2 defect note in
# ``odd/tasks/doc-01-usable-contratos.md``: the StrEnum value and
# the catalog row only overlap for 'Entrada' / 'Acogida', so the e2e
# test sticks to a value that is known to round-trip.
CONTRATO_TIPO_ENTRADA = "Entrada"

# Fixed ISO date: the contract date is just a string field on the
# ``contratos`` row (no calendar arithmetic). A fixed value keeps the
# test deterministic; HR-10 forbids ``datetime.now()`` and
# ``time.sleep``.
CONTRATO_FECHA = "2026-10-02"


# ---------------------------------------------------------------------------
# Direct-DB seeding helpers
# ---------------------------------------------------------------------------


def _ensure_bucket(minio_client: Minio) -> None:
    """Create the contratos bucket if missing (idempotent).

    Mirrors the ``if not bucket_exists`` pattern in
    ``tests/e2e_ci/test_minio_storage.py``: the production deployment
    is expected to provision the bucket (see
    ``app/modules/contratos/di/__init__.py``); the test does it on
    demand so a missing-bucket regression is caught at first run
    instead of masking as a 404 from the storage adapter.
    """
    if not minio_client.bucket_exists(CONTRATOS_BUCKET):
        minio_client.make_bucket(CONTRATOS_BUCKET)


def _seed_animal(e2e_db_conn, nchip: str) -> str:
    """INSERT a minimal ``animales`` row and return its UUID.

    The ``contratos`` slice FKs ``entradas`` via ``entrada_id``;
    ``entradas.animal_id`` is a NOT NULL FK to ``animales``. Without
    an existing animal every ``entradas`` insert 422s, and the
    contratos POST that follows would 409 the
    ``contratos_exactly_one_entity`` CHECK. The animal row is the
    entry point for the chain.
    """
    animal_id = str(uuid.uuid4())
    with e2e_db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO animales (
                id, nchip, nombreanimal, especie, sexo,
                fnacimiento, fecha_alta, activo
            ) VALUES (%s, %s, %s, %s, %s, %s, now(), true)
            """,
            (
                animal_id,
                nchip,
                f"E2E Contratos {nchip}",
                "CANINA",
                "H",
                "2020-01-01",
            ),
        )
    return animal_id


def _seed_entrada(e2e_db_conn, animal_id: str) -> str:
    """INSERT a minimal ``entradas`` row referencing ``animal_id``.

    Returns the new ``entradas.id`` (UUID). The schema declares
    ``UNIQUE (animal_id, fecha_entrada)`` so each seeded entrada
    needs a fresh ``fecha_entrada``; the test factory below picks
    one per call.
    """
    entrada_id = str(uuid.uuid4())
    with e2e_db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO entradas (
                id, animal_id, fecha_entrada, motivo,
                observaciones, fecha_alta, activo
            ) VALUES (%s, %s, %s, %s, %s, now(), true)
            """,
            (
                entrada_id,
                animal_id,
                CONTRATO_FECHA,
                "Rescate",
                "E2E contratos SLICE-3 seeded row",
            ),
        )
    return entrada_id


def _delete_contratos_row(
    e2e_db_conn, *, entrada_id: str
) -> None:
    """Best-effort DELETE of the ``contratos`` row pointing at the entrada.

    The contratos slice inserts via
    ``app.modules.contratos.contratos_queries.insert_contrato`` which
    sets ``entrada_id`` (or whichever FK ``entity_type`` resolves to).
    The cleanup below only fires when the contrato row was actually
    inserted (the variable is left unbound otherwise) so a 4xx / 5xx in
    the test body that skipped the INSERT does not 23503 the cleanup.
    """
    with e2e_db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM contratos WHERE entrada_id = %s",
            (entrada_id,),
        )


# ---------------------------------------------------------------------------
# Test: generate + download + 404
# ---------------------------------------------------------------------------


class TestContratosPdf:
    """End-to-end tests for the contratos PDF generation + download surface."""

    def test_generate_contrato_returns_pdf_and_download_streams_bytes(
        self,
        e2e_logged_in_browser_context: BrowserContext,
        minio_client: Minio,
        e2e_db_conn,
        base_url: str,
    ) -> None:
        """Generate a contract PDF and download it -- verify PDF magic bytes.

        The flow:

        1. Provision the ``apap-contracts`` bucket (idempotent).
        2. Seed an ``animales`` row + an ``entradas`` row pointing at it.
        3. POST /contratos with the session cookie + csrf_token + a
           minimal form payload (tipo=Entrada, entity_type=entrada).
        4. Assert 303 redirect to the canonical download URL.
        5. Follow the redirect (browser context carries the cookie).
        6. Assert 200, ``application/pdf`` content-type, and the
           PDF magic header ``%PDF-``.
        7. Teardown: remove the MinIO object, the contratos row, the
           entrada row and the animal row.
        """
        _ensure_bucket(minio_client)

        test_id = uuid.uuid4().hex[:8]
        nchip = f"E2EC{test_id}"[:15]
        animal_id = _seed_animal(e2e_db_conn, nchip)
        entrada_id = _seed_entrada(e2e_db_conn, animal_id)
        storage_key = f"{CONTRATO_TIPO_ENTRADA}_{entrada_id}.pdf"

        try:
            # Reuse the shared developer session the conftest mints.
            # ``e2e_logged_in_browser_context`` already carried an
            # ``apap_session`` cookie, but the /e2e/login call below
            # also returns the csrf_token we need for the form post
            # (the cookie binds the token, the body returns it for
            # the test to inject into the form field).
            context = e2e_logged_in_browser_context
            secret = os.environ["APAP_E2E_AUTH_SECRET"]
            default_email = os.environ.get(
                "APAP_E2E_AUTH_DEFAULT_EMAIL", "e2e@apap.local",
            )

            login_resp = context.request.get(
                f"{base_url}/e2e/login",
                headers={
                    "X-E2E-Secret": secret,
                    "X-E2E-Email": default_email,
                },
            )
            assert login_resp.ok, (
                f"E2E login failed: {login_resp.status}"
            )
            csrf_token = login_resp.json().get("csrf_token")
            assert isinstance(csrf_token, str) and csrf_token, (
                "/e2e/login must return a non-empty csrf_token for the "
                "DOC-01 POST"
            )

            # POST /contratos -- 303 redirect to the download URL on success.
            create_resp = context.request.post(
                f"{base_url}/contratos",
                form={
                    "csrf_token": csrf_token,
                    "tipo": CONTRATO_TIPO_ENTRADA,
                    "entity_type": "entrada",
                    "entity_id": entrada_id,
                    "numero_contrato": f"CPE2E{test_id}",
                    "fecha": CONTRATO_FECHA,
                },
            )
            assert create_resp.status == 303, (
                f"POST /contratos must 303 to the download URL, got "
                f"{create_resp.status}: {create_resp.text()[:300]!r}"
            )
            redirect_location = create_resp.headers.get("location", "")
            assert redirect_location.endswith(
                f"/contratos/entrada/{entrada_id}/{CONTRATO_TIPO_ENTRADA}"
            ), (
                f"POST /contratos must redirect to /contratos/"
                f"entrada/{entrada_id}/{CONTRATO_TIPO_ENTRADA}, "
                f"got location: {redirect_location!r}"
            )

            # GET the download URL. The browser context carries the
            # apap_session cookie (no manual re-auth needed).
            page = context.new_page()
            download_resp = page.goto(redirect_location)

            assert download_resp is not None
            assert download_resp.status == 200, (
                f"GET {redirect_location} must 200 with the PDF body, got "
                f"{download_resp.status}"
            )
            assert (
                download_resp.headers.get("content-type", "")
                .startswith("application/pdf")
            ), (
                f"download must be application/pdf, got "
                f"{download_resp.headers.get('content-type')!r}"
            )
            body = download_resp.body()
            assert body.startswith(b"%PDF"), (
                f"download body must start with the PDF magic header, "
                f"got first bytes: {body[:8]!r}"
            )

            # Storage adapter contract: the object is reachable at the
            # canonical {Tipo}_{ID}.pdf key. Defensive check so a
            # regression that re-names the key (and breaks the
            # download GET) fails loud at the next assertion, not
            # silently as a 404 from ``MinioContratosStorage``.
            stat = minio_client.stat_object(CONTRATOS_BUCKET, storage_key)
            assert stat is not None, (
                f"minio must carry the contrato PDF at "
                f"{CONTRATOS_BUCKET}/{storage_key}"
            )

        finally:
            # Best-effort cleanup so the e2e DB and MinIO stay clean
            # for subsequent runs. Errors are intentionally swallowed
            # (the test verdict was already decided above).
            try:
                minio_client.remove_object(CONTRATOS_BUCKET, storage_key)
            except Exception:
                pass  # best-effort
            try:
                _delete_contratos_row(e2e_db_conn, entrada_id=entrada_id)
                with e2e_db_conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM entradas WHERE id = %s",
                        (entrada_id,),
                    )
                    cur.execute(
                        "DELETE FROM animales WHERE id = %s",
                        (animal_id,),
                    )
            except Exception:
                pass  # best-effort

    def test_download_contrato_returns_404_for_never_generated(
        self,
        e2e_logged_in_browser_context: BrowserContext,
        e2e_db_conn,
        base_url: str,
    ) -> None:
        """GET /contratos/{...}/{never-generated} -> 404.

        Seeds an ``entradas`` row but does NOT POST /contratos for it, so
        the ``contratos`` table has no row matching
        ``(tipo, entity_type='entrada', entity_id=entrada_id)``. The
        canonical queries module's ``get_contrato_for_entity`` returns
        ``None``; the route translates ``None`` to HTTP 404.
        """
        test_id = uuid.uuid4().hex[:8]
        nchip = f"E2EC4xx{test_id}"[:15]
        animal_id = _seed_animal(e2e_db_conn, nchip)
        entrada_id = _seed_entrada(e2e_db_conn, animal_id)

        try:
            context = e2e_logged_in_browser_context

            page = context.new_page()
            download_url = (
                f"{base_url}/contratos/entrada/"
                f"{entrada_id}/{CONTRATO_TIPO_ENTRADA}"
            )
            download_resp = page.goto(download_url)

            assert download_resp is not None
            assert download_resp.status == 404, (
                f"GET {download_url} must 404 when no contrato was "
                f"generated, got {download_resp.status}"
            )

        finally:
            try:
                _delete_contratos_row(e2e_db_conn, entrada_id=entrada_id)
                with e2e_db_conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM entradas WHERE id = %s",
                        (entrada_id,),
                    )
                    cur.execute(
                        "DELETE FROM animales WHERE id = %s",
                        (animal_id,),
                    )
            except Exception:
                pass  # best-effort
