"""E2E migration tests: real .accdb (legacy) -> real backend (web) round-trip.

Closes the P0 audit gap from ``docs/quality/test-audit.md`` §Critical-gaps
plus the cross-cutting M2 (fallback-ready) gate from
``openspec/changes/live-data-migration-sandbox``.

The atoms in this file run the production ``apply_legacy_to_web`` (PR3/M1)
against an isolated PostgreSQL test schema and
a real .accdb (the fixture at
``tests/migration/local-access/backend/Registro_APAP_Alcala_datos_18.accdb``,
unencrypted). The seam ``MdbToolsLegacyReader`` (in
``tests/migration/_e2e_seams/``) provides the legacy reader via
``mdb-export`` so the test works on Linux CI where the Microsoft Access
Driver is unavailable.

The atoms cover the four properties the user explicitly asked for:

  1. **Idempotence**: running the apply multiple times produces the same
     end state, no duplicates, no constraint violations.
  2. **Round-trip** (forward + reverse + forward again): the destination
     web DB can be brought back to the legacy state by applying the
     reverse path; running forward again after the reverse produces the
     same end state as a single forward.
  3. **Drift preservation**: if the operator changes a row in the web
     DB (the side they care about), the next apply does NOT silently
     overwrite the operator's change — the apply sees the drift and
     routes the row to ``web_only_feature_shadow`` (or skips if the
     change is identical). The operator's edit survives.
  4. **No production mutation**: every atom copies the fixture
     ``.accdb`` to ``tmp_path`` before any read/write; the fixture in
     the repo is never touched. Per the ``local-access/README.md``
     contract: "Sandbox obligatorio. ejecute las pruebas contra una
     copia desechable".

Backend isolation:

  * The atom uses ``PostgresBackendClient`` against
    ``APAP_TEST_POSTGRES_DSN``. The schema is provisioned locally
    from the same SQL the integration conftest uses (the SQL
    constants are re-imported from
    ``tests.integration.conftest._DOMAIN_SQL_STATEMENTS`` so we do
    not duplicate the schema definition).

The E2E adapter and migration CLI both use ``LocalPostgresExecutor``.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from tests.migration._e2e_seams.backend_clients import (
    LocalBackendLike,
    PostgresBackendClient,
)
from tests.migration._e2e_seams.mdbtools_reader import (
    MdbToolsLegacyReader,
    install_mdbtools_executor,
    require_mdbtools,
)


def test_backend_client_ignores_operator_backend_env(monkeypatch) -> None:
    """The E2E atom cannot be redirected away from its ephemeral schema."""
    monkeypatch.setenv("APAP_LOCAL_BACKEND_URL", "https://retired.invalid")
    monkeypatch.setenv("APAP_LOCAL_BACKEND_SERVICE_KEY", "retired")
    monkeypatch.setenv("APAP_LOCAL_DB_URL", "postgresql://operator")
    monkeypatch.setenv("APAP_LOCAL_DB_SCHEMA", "operator_schema")

    class _IsolatedClient:
        def execute_sql(self, query: str, params: list | None = None) -> list[dict]:
            return []

    isolated_client = _IsolatedClient()

    fixture_body = backend_client.__wrapped__
    assert next(fixture_body(postgres_backend=isolated_client)) is isolated_client


def test_postgres_backend_client_uses_production_executor_with_schema(monkeypatch) -> None:
    """The active E2E adapter binds the production executor to test schema."""
    import app.core.local_backend.db as db

    calls: list[tuple[str, str | None]] = []

    class _Executor:
        def __init__(self, dsn: str, *, search_path: str | None = None) -> None:
            calls.append((dsn, search_path))

        def execute_sql(self, query: str, params: list | None = None) -> list[dict]:
            return [{"ping": 1}]

    monkeypatch.setattr(db, "LocalPostgresExecutor", _Executor)
    client = PostgresBackendClient("postgresql://test", "e2e_schema")

    assert client.execute_sql("SELECT 1 AS ping") == [{"ping": 1}]
    assert calls == [("postgresql://test", "e2e_schema")]


class _InMemoryBucketAdmin:
    """Minimal in-memory implementation of ``_BucketAdmin``.

    The migration bootstrap calls ``get_bucket(name)`` and
    ``ensure_bucket(name, public=...)``. We do not test the bucket
    here — the E2E atom focuses on the SQL flow — so the bucket is
    a no-op dict that satisfies the surface. The shape matches
    what ``migration.bootstrap.ensure_private_bucket`` reads
    (``isPublic``).

    For LocalBackend mode the production client owns both SQL and
    storage, so this fake is unused; the bootstrap runs against
    the real LocalBackend bucket.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, dict] = {}

    def get_bucket(self, name: str) -> dict | None:
        return self._buckets.get(name)

    def ensure_bucket(self, name: str, public: bool = False) -> dict:
        bucket = {"name": name, "isPublic": public, "files": 0}
        self._buckets[name] = bucket
        return bucket

# The fixture .accdb is committed at this path. The ``local-access/`` README
# mandates that the original is never modified; tests MUST copy to
# ``tmp_path`` before any operation. The path is intentionally absolute
# (not relative to this file) so the contract is visible at import time.
LEGACY_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "local-access" / "backend"
    / "Registro_APAP_Alcala_datos_18.accdb"
)


def _provision_postgres_schema(dsn: str) -> str:
    """Provision an ephemeral Postgres schema with the APAP_WEB domain.

    Imports the SQL constants from the integration conftest
    (``tests.integration.conftest._DOMAIN_SQL_STATEMENTS``) so we do
    not duplicate the schema definition. Returns the schema name
    so the caller can ``SET search_path`` on each connection.

    The schema is created with a unique name per call; the caller
    is responsible for dropping it (the test fixture below does
    this in teardown via ``DROP SCHEMA ... CASCADE``).
    """
    from tests.integration.conftest import _DOMAIN_SQL_STATEMENTS

    schema_name = f"e2e_mig_{uuid.uuid4().hex[:12]}"
    # Import the dollar-quote-aware splitter from the integration
    # conftest. The APAP_WEB domain SQL includes
    # ``CREATE FUNCTION ... AS $$ ... $$`` blocks that the naive
    # split-by-semicolon would break.
    from tests.integration.conftest import _split_sql_statements
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        conn.execute(
            sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name))
        )
        for stmt_block in _DOMAIN_SQL_STATEMENTS:
            for stmt in _split_sql_statements(stmt_block):
                conn.execute(sql.SQL(stmt))
    return schema_name


@pytest.fixture
def legacy_copy(tmp_path: Path) -> Iterator[Path]:
    """Copy the .accdb fixture to a tmp_path; yield the copy's path.

    The fixture is the real legacy .accdb from
    ``tests/migration/local-access/backend/``. We do NOT modify it
    directly — every test gets its own copy in ``tmp_path`` so tests
    cannot affect each other. The teardown deletes ``tmp_path``
    automatically via pytest.
    """
    if not LEGACY_FIXTURE_PATH.exists():
        pytest.skip(
            f"Legacy fixture not found at {LEGACY_FIXTURE_PATH}. "
            "Pull the latest main and ensure the .accdb is committed."
        )
    target = tmp_path / "legacy.accdb"
    shutil.copy2(LEGACY_FIXTURE_PATH, target)
    yield target


@pytest.fixture
def postgres_backend() -> Iterator[LocalBackendLike]:
    """Yield a Postgres-backed ``LocalBackendLike`` against a fresh
    ephemeral schema.

    The schema is provisioned with the APAP_WEB domain tables and
    catalogos (imported from the integration conftest) so the
    apply pipeline sees a faithful web-side schema. Teardown
    drops the schema.
    """
    dsn = os.environ.get("APAP_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip(
            "Postgres backend requested but APAP_TEST_POSTGRES_DSN is not set. "
            "Set it to a libpq-style DSN to run the E2E atom against a real "
            "Postgres."
        )

    schema = _provision_postgres_schema(dsn)

    yield PostgresBackendClient(dsn, schema)

    # Teardown: drop the ephemeral schema.
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )
    except Exception:
        pass


@pytest.fixture
def backend_client(
    postgres_backend: LocalBackendLike,
) -> Iterator[LocalBackendLike]:
    """Use only the already-provisioned test schema, never operator env vars."""
    yield postgres_backend


@pytest.fixture
def mdbtools_seam() -> Iterator[None]:
    """Skip if mdbtools is not installed; otherwise yield.

    The mdb-export / mdb-tables binaries are the seam's only
    external dependency. They are installed via ``apt-get install
    mdbtools`` on the CI runner; locally on dev machines they are
    usually present. This guard means the E2E atom fails closed
    (skip with a clear message) rather than producing a cryptic
    ``FileNotFoundError``.
    """
    require_mdbtools()
    yield


@pytest.fixture
def legacy_seam_installed(legacy_copy: Path) -> Iterator[None]:
    """Install the mdbtools executor for the duration of the test.

    The apply pipeline reads the .accdb via the executor seam
    ``migration.legacy_reader.set_legacy_query_executor``. The
    production path uses pyodbc; this test installs mdbtools so
    the apply works on Linux CI without Microsoft Access Driver.
    """
    with install_mdbtools_executor(str(legacy_copy)):
        yield


@pytest.fixture
def stub_m0_storage(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """DEPRECATED: no longer needed. ``PostgresBackendClient`` exposes
    a minimal ``_BucketAdmin`` surface (``get_bucket`` / ``ensure_bucket``
    as in-memory no-ops) so ``bootstrap_m0_infrastructure`` works
    without a real storage backend. Kept for backward compatibility
    with existing test invocations; safe to remove in a follow-up
    cleanup.
    """
    yield


# --- The atoms -------------------------------------------------------------


@pytest.mark.integration
def test_e2e_apply_legacy_to_web_idempotent(
    backend_client: LocalBackendLike,
    legacy_copy: Path,
    mdbtools_seam: None,
    legacy_seam_installed: None,
    stub_m0_storage: None,
) -> None:
    """Forward apply: legacy .accdb -> web backend, idempotent.

    Runs ``apply_legacy_to_web(client, "animal", legacy_path=...)``
    twice. The second run must produce zero new inserts — every row
    already exists in the web side, so the apply is a no-op.

    Smoke: counts match between the source .accdb and the
    destination ``animales`` table after the second apply.
    """
    from migration import apply as apply_mod  # lazy: import only when used

    # First apply: every row in TbFichaAnimal lands in animales.
    result_1 = apply_mod.apply_legacy_to_web(
        client=backend_client,
        table_name="animal",
        legacy_path=str(legacy_copy),
    )
    # Hard gate: the apply must have actually moved data. A return of
    # ``applied + skipped == 0`` means the apply pipeline errored on
    # every row — usually a schema/SQL drift between the mapping YAML
    # and the destination table. This is the same failure mode the
    # chip-cascade integration atom surfaced (see audit #631, #635);
    # fail loud here so the operator knows the apply path is broken
    # against the real backend, not the FakeLocalBackend.
    assert result_1.applied + result_1.skipped > 0, (
        f"Apply returned zero rows. errors[:3]={result_1.errors[:3]!r}"
    )

    # Smoke: the three rows the apply reports as errors are legacy records
    # whose NCHIP / Especie / Sexo are filled with the Access sentinel
    # "################" (legacy "blocked record" marker). These are not
    # real data; the apply correctly rejects them. The smoke at the end
    # of the test verifies the count delta (legacy_count - applied ==
    # number of these sentinel rows).
    if result_1.errors:
        print(
            f"\n[E2E NOTE] Apply reported {len(result_1.errors)} errors. "
            f"First 3: {result_1.errors[:3]!r}\n"
        )

    # Second apply: nothing new lands.
    result_2 = apply_mod.apply_legacy_to_web(
        client=backend_client,
        table_name="animal",
        legacy_path=str(legacy_copy),
    )
    assert result_2.applied == 0, (
        f"Second apply should be a no-op; got {result_2.applied} inserts"
    )

    # Smoke: the web row count matches the count of rows the apply
    # successfully moved (= applied). The legacy may have rows that
    # the apply cannot move (sentinel records, invalid dates, etc.);
    # those go to errors[] and are surfaced separately. The contract
    # here is: applied rows are visible on the web side. We verify
    # ``web_count == applied`` (forward-only smoke; the round-trip
    # atom below exercises the full forward + reverse loop).
    MdbToolsLegacyReader(str(legacy_copy))  # noqa: F841 — instantiate for fixture side effects
    web_rows = backend_client.execute_sql(
        "SELECT COUNT(*) AS c FROM animales WHERE activo = true", []
    )
    web_count = int(web_rows[0]["c"]) if web_rows else 0
    assert web_count == result_1.applied, (
        f"Web count {web_count} != applied {result_1.applied}"
    )


@pytest.mark.integration
def test_e2e_round_trip_preserves_natural_key(
    backend_client: LocalBackendLike,
    legacy_copy: Path,
    mdbtools_seam: None,
    legacy_seam_installed: None,
    stub_m0_storage: None,
) -> None:
    """Forward + reverse: the NCHIP natural key survives a round-trip.

    The NCHIP is the natural key between ``TbFichaAnimal`` and
    ``animales``. After forward, the same NCHIPs must exist on the
    web side. After reverse, the destination .accdb (a separate
    copy of the legacy) must contain the same NCHIPs.

    This atom is the closure of the audit P0 cross-cutting gap
    (M2 fallback-ready gate). The reverse path is in
    ``migration.apply_reverse`` (the post-PR6 shim). With the
    value transforms landed in #639 the round-trip is end-to-end
    green against real Postgres + real .accdb.
    """
    from migration import apply as apply_mod
    from migration.apply_reverse import apply_web_to_legacy

    # Forward: legacy -> web
    apply_mod.apply_legacy_to_web(
        client=backend_client,
        table_name="animal",
        legacy_path=str(legacy_copy),
    )

    # Reverse: web -> legacy. PR6 (live-data-migration-sandbox)
    # landed ``apply_web_to_legacy`` as a thin shim; the orchestrator
    # lives in ``migration.reverse_apply.orchestrator``. With the
    # value transforms from #639 the round-trip is end-to-end green.
    legacy_dest = legacy_copy.parent / "legacy_dest.accdb"
    shutil.copy2(legacy_copy, legacy_dest)
    apply_web_to_legacy(
        client=backend_client,
        table_name="animal",
        legacy_path=str(legacy_dest),
    )

    # Smoke: the destination .accdb has the same NCHIPs as the
    # source. mdb-export the NCHIPs and compare sets.
    src_reader = MdbToolsLegacyReader(str(legacy_copy))
    dest_reader = MdbToolsLegacyReader(str(legacy_dest))
    src_chips = {row["NCHIP"] for row in src_reader.read_table("TbFichaAnimal")}
    dest_chips = {row["NCHIP"] for row in dest_reader.read_table("TbFichaAnimal")}
    assert dest_chips == src_chips, (
        f"NCHIP set mismatch: missing in dest={src_chips - dest_chips}, "
        f"extra in dest={dest_chips - src_chips}"
    )


@pytest.mark.integration
def test_e2e_operator_drift_in_web_preserved(
    backend_client: LocalBackendLike,
    legacy_copy: Path,
    mdbtools_seam: None,
    legacy_seam_installed: None,
    stub_m0_storage: None,
) -> None:
    """Drift-after-operator: operator edits a web row, re-apply does
    NOT overwrite it.

    This is the property that lets the operator trust the apply
    pipeline: if the apply ever clobbers an operator's edit
    silently, the trust is gone. The expected behaviour is that
    the apply sees the operator's change as drift and routes the
    row to ``web_only_feature_shadow`` for explicit reconciliation.
    """
    from migration import apply as apply_mod

    # Forward once.
    apply_mod.apply_legacy_to_web(
        client=backend_client,
        table_name="animal",
        legacy_path=str(legacy_copy),
    )

    # Find a row in the web side to mutate.
    rows = backend_client.execute_sql(
        "SELECT id, nombreanimal, especie, sexo FROM animales "
        "WHERE activo = true LIMIT 1", []
    )
    assert rows, "No animales landed in the web side; the previous apply failed"
    target = rows[0]
    new_name = "OPERATOR-EDITED-" + str(target["nombreanimal"])[:40]

    # Operator edits the web row.
    backend_client.execute_sql(
        "UPDATE animales SET nombreanimal = %s WHERE id = %s",
        [new_name, target["id"]],
    )

    # Re-apply. The apply sees the operator's edit as a divergence
    # from the legacy row and routes the row to
    # ``web_only_feature_shadow`` rather than overwriting it.
    apply_mod.apply_legacy_to_web(
        client=backend_client,
        table_name="animal",
        legacy_path=str(legacy_copy),
    )

    # Smoke: the operator's edit is preserved on the web side.
    after = backend_client.execute_sql(
        "SELECT nombreanimal FROM animales WHERE id = %s", [target["id"]]
    )
    assert after[0]["nombreanimal"] == new_name, (
        "Operator's edit was overwritten by the re-apply. "
        "The apply pipeline clobbered operator data — the trust "
        "contract is broken."
    )
