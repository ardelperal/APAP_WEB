"""Verify the M2 fallback-ready gate (issue #637, openspec PR7).

Closes the migration openspec's final requirement: a HARD CI gate
plus a publication gate that no operator may claim "fallback ready"
without proof.

The gate has two modes per the spec at
``openspec/changes/live-data-migration-sandbox/specs/live-migration-bidirectional-completion/spec.md``
section "Fallback-Ready Gate":

  * ``--ci-only`` (CI-runnable subset): round-trip test + PII audit
    verdict + ``apply_web_to_legacy --check-only``. No operator
    attestation required. This is the mode the CI job uses. Exits 0
    only when ALL CI conditions are green; otherwise exits 1 with a
    ``missing_ci_condition=<name>`` line on stderr.

  * (no flag, "full mode"): CI-runnable subset PLUS operator-attested
    conditions (``migration_report_signature.json`` exists and carries a
    valid ``operator_id``). Exit 0 only when BOTH pass. This is the mode
    the publication gate uses; the operator runs it locally after
    executing at least one real migration cycle.

The implementation is a series of small check functions, each
returning a ``(status, evidence)`` tuple. The orchestrator runs them
in order, aggregates the result, and exits with the appropriate code.

This module is intentionally CLI-only (no HTTP, no DB). It inspects
the repo filesystem and the PII audit doc's verdict. The only DB-touching
piece is ``apply_web_to_legacy --check-only``, which the orchestrator
shells out to via subprocess so the existing CLI surface is exercised
rather than re-implementing the reverse pipeline.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PII_AUDIT_PATH = REPO_ROOT / "docs" / "audits" / "pii-live-migration-2026-Q3.md"
ROUND_TRIP_TEST = "tests/migration/test_round_trip.py"
OPERATOR_SIGNATURE_PATH = REPO_ROOT / "migration_report_signature.json"



def _run_subprocess_check(
    args: list[str],
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run a subprocess and return ``(returncode, stdout, stderr)``.

    Centralised so the format is consistent and the orchestrator can
    treat the check as a function-of-state rather than a function-of-
    process.

    ``extra_env`` is merged on top of the inherited environment so
    checks can override specific variables (the local-backend fixture
    wiring uses this to inject ``APAP_LOCAL_BACKEND`` /
    ``APAP_LOCAL_BACKEND_URL`` without disturbing the rest of the env).
    """
    env = None
    if extra_env:
        env = {**os.environ, **extra_env}
    proc = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _pick_free_port() -> int:
    """Return an OS-assigned free TCP port.

    Lets the kernel pick so two CI jobs on the same host never collide.
    Used by the local-backend fixture wiring in
    ``check_web_to_legacy_check_only``.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_healthz(port: int, timeout_seconds: float) -> bool:
    """Poll ``GET /healthz`` until it returns 200 or the timeout elapses.

    The local backend's lifespan must complete before the executor on
    ``app.state`` is reachable — uvicorn returns the process socket
    immediately, but the lifespan only runs on the first request. We
    poll briefly to give the lifespan time to settle.
    """
    deadline = time.monotonic() + timeout_seconds
    url = f"http://127.0.0.1:{port}/healthz"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:  # noqa: S310
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.1)
    return False


def _provision_ephemeral_schema(dsn: str) -> str:
    """Provision an ephemeral APAP schema and return its name.

    Mirrors ``tests/integration/conftest.py::_EphemeralPostgres._provision``
    via ``app.core.schema_provisioning.provision_apap_schema`` so the
    web-to-legacy dry-run has the same domain tables it would have in
    production. The schema name is UUID-suffixed so concurrent runs do
    not collide; the caller is responsible for dropping it via
    ``_drop_ephemeral_schema``.
    """
    from app.core.schema_provisioning import provision_apap_schema

    schema = f"gate_{uuid.uuid4().hex[:12]}"
    provision_apap_schema(dsn, schema)
    return schema


def _drop_ephemeral_schema(dsn: str, schema: str) -> None:
    """Drop the ephemeral schema provisioned by ``_provision_ephemeral_schema``.

    Best-effort: failures here are swallowed (the gate reports the
    real error from the subprocess, not the cleanup). Production is
    never at risk because the schema name is unique per run.
    """
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')




__all__ = [
    "_run_subprocess_check",
    "_pick_free_port",
    "_wait_for_healthz",
    "_provision_ephemeral_schema",
    "_drop_ephemeral_schema",
]
