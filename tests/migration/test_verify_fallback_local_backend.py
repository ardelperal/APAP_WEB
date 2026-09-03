"""AS10 acceptance test for F3 (m0-self-host-backend-rdd).

End-to-end verification that ``migration.cli_verify_fallback_ready --ci-only``
exits 0 against the local FastAPI backend spawned in-process.

The fixture (see ``tests/migration/_local_backend_fixture.py``) provisions
an ephemeral Postgres schema and starts ``uvicorn
app.core.local_backend.app:create_app --factory`` on a free port. The
test then sets ``APAP_LOCAL_BACKEND=true`` and
``APAP_INSFORGE_URL=http://127.0.0.1:<port>/api`` so the verify-fallback-
ready gate's ``_run_web_to_legacy_check_only`` helper takes the
``local_backend=True`` branch (F3 contract). The test runs the standalone
entry point ``python -m migration.cli_verify_fallback_ready --ci-only``
in a subprocess and asserts the exit code + receipt line.

The F3 plan (`openspec/changes/m0-self-host-backend-rdd/tasks.md` T3.3)
mandates exactly one atom, marked ``integration`` so it runs in the
integration test job alongside the F1/F2 coverage.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.migration._local_backend_fixture import (
    LocalBackendHandle,
    local_backend,
    local_postgres_dsn,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Sanity anchors — the F3 contract pins the InsForge URL form so the
# loopback InsForgeClient can be reached end-to-end. ``/api`` is the
# mount path for the rawsql + storage + OAuth routers (see
# ``app/core/local_backend/app.py``).
_EXPECTED_INSFORGE_URL_SUFFIX = "/api"
_VERIFY_CLI_MODULE = "migration.cli_verify_fallback_ready"


@pytest.mark.integration
def test_web_to_legacy_check_only_passes_against_local_backend(
    monkeypatch: pytest.MonkeyPatch,
    local_backend: LocalBackendHandle,
) -> None:
    """End-to-end AS10: drive the F1 → F2 → F3 chain and assert PASS.

    Steps:

    1. The session-scoped ``local_backend`` fixture has already
       provisioned the ephemeral Postgres schema and spawned uvicorn
       (T3.2). It yields a ``LocalBackendHandle`` carrying the bound
       port + process handle + schema name.

    2. ``local_postgres_dsn`` is called to enforce the AGENTS.md
       "MUST NOT silently skip" policy: missing ``APAP_TEST_POSTGRES_DSN``
       raises loudly instead of silently skipping.

    3. Set ``APAP_LOCAL_BACKEND=true`` and
       ``APAP_INSFORGE_URL=http://127.0.0.1:<port>/api`` via
       ``monkeypatch.setenv`` so the F3 dispatch in
       ``check_web_to_legacy_check_only`` reads them at check time.
       ``monkeypatch`` restores the prior env on teardown — no leak
       across tests, even if this one crashes.

    4. Invoke ``python -m migration.cli_verify_fallback_ready --ci-only``
       in a subprocess against the repo root. The subprocess inherits
       the monkeypatched env, so the gate takes the ``local_backend=True``
       branch and runs the dry-run against the loopback InsForgeClient.

    5. Assert exit code 0 AND that stdout contains the substring
       ``web_to_legacy_check_only: PASS`` so a regression where only
       one of the three CI conditions passes cannot satisfy this atom
       by accident.
    """
    # Step 2 — fail loudly if the DSN is missing. The fixture factory
    # also reads this, but we call it explicitly here so the failure
    # surfaces AS the first action of the test body, not as a deferred
    # fixture-resolution error.
    local_postgres_dsn()

    # Step 3 — point the gate's environment at the loopback. The
    # monkeypatch keys are the contract surface; the gate reads
    # ``APAP_LOCAL_BACKEND`` at check time (not import time) per F3.
    expected_insforge_url = f"{local_backend.base_url}{_EXPECTED_INSFORGE_URL_SUFFIX}"
    monkeypatch.setenv("APAP_LOCAL_BACKEND", "true")
    monkeypatch.setenv("APAP_INSFORGE_URL", expected_insforge_url)
    # The check also reads the DSN/schema envs so its spawned
    # uvicorn can re-bind the local backend factory against the same
    # schema the fixture provisioned.
    monkeypatch.setenv("APAP_LOCAL_DB_URL", os.environ["APAP_TEST_POSTGRES_DSN"])
    monkeypatch.setenv("APAP_LOCAL_DB_SCHEMA", local_backend.schema)

    # Step 4 — drive the standalone CLI. ``capture_output=True`` so we
    # can assert on stdout/stderr without the operator stream noise
    # polluting the test report.
    completed = subprocess.run(  # noqa: S603 — explicit argv, repo-root cwd
        [sys.executable, "-m", _VERIFY_CLI_MODULE, "--ci-only"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
    )

    # Step 5 — the F3 acceptance scenario. Surface the captured output
    # on failure so the developer sees the full receipt, not just the
    # assertion error. ``stderr`` is included because the gate writes
    # ``missing_ci_condition=<name>`` lines to stderr on FAIL.
    if completed.returncode != 0:
        pytest.fail(
            "verify-fallback-ready did not exit 0 against the local backend:\n"
            f"  returncode={completed.returncode}\n"
            f"  stdout=\n{completed.stdout}\n"
            f"  stderr=\n{completed.stderr}"
        )
    # The receipt format is ``[PASS    ] web_to_legacy_check_only   ...``
    # (see ``migration.verify_fallback_ready.format_receipt``). Match
    # the bare check identifier AND the PASS verdict in close proximity
    # — both on the same line — so a regression where one check passes
    # but the web_to_legacy line regresses to FAIL cannot satisfy this
    # atom by accident. We match the raw line format rather than a
    # colon-separated variant so the assertion stays robust against
    # future receipt-format edits.
    matching_line = next(
        (
            line
            for line in completed.stdout.splitlines()
            if "web_to_legacy_check_only" in line and "PASS" in line
        ),
        None,
    )
    assert matching_line is not None, (
        "verify-fallback-ready exited 0 but did not report "
        "web_to_legacy_check_only: PASS:\n"
        f"  stdout=\n{completed.stdout}\n"
        f"  stderr=\n{completed.stderr}"
    )


__all__ = ["test_web_to_legacy_check_only_passes_against_local_backend"]


# ``local_backend`` and ``local_postgres_dsn`` are imported for fixture
# registration and the DSN guard. They are also re-exported here so a
# downstream test file can pull them from this module if it ever adds a
# second AS10-shaped atom.
__all__ += ["local_backend", "local_postgres_dsn"]
