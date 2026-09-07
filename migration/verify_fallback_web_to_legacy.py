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
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PII_AUDIT_PATH = REPO_ROOT / "docs" / "audits" / "pii-live-migration-2026-Q3.md"
ROUND_TRIP_TEST = "tests/migration/test_round_trip.py"
OPERATOR_SIGNATURE_PATH = REPO_ROOT / "migration_report_signature.json"


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one gate check.

    ``status`` is one of:
      * "PASS" — the condition is satisfied
      * "FAIL" — the condition is not satisfied; reason in evidence
      * "PENDING" — the condition is operator-attested (full mode only);
        the CI subset reports this as PASS-with-caveat

    ``name`` is the short identifier the orchestrator uses to format
    the ``missing_ci_condition=<name>`` line on failure. ``evidence`` is
    a one-line human-readable string the orchestrator prints as the
    receipt.
    """

    name: str
    status: str
    evidence: str


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
    ``APAP_INSFORGE_URL`` without disturbing the rest of the env).
    """
    env = None
    if extra_env:
        env = {**os.environ, **extra_env}
    proc = subprocess.run(  # noqa: S603 — args is a built argv list, no shell expansion.
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


def check_round_trip_test() -> CheckResult:
    """Run the round-trip test suite and assert it is green.

    The CI-runnable condition is that the round-trip test suite (PR6,
    M2 closure) passes against the real backend. We shell out to
    pytest because the test suite has its own fixtures (FakeLocalBackend
    seed, ephemeral_postgres, etc.) that the gate should not have to
    reproduce. The contract: the test exits 0 = round-trip is green.

    The check uses ``APAP_TEST_POSTGRES_DSN`` if the CI integration
    job sets it; otherwise the round-trip test falls back to
    FakeLocalBackend (which is the pre-PR6 verification path). Either
    way, exit 0 is the gate.
    """
    rc, stdout, stderr = _run_subprocess_check(
        [
            sys.executable,
            "-m",
            "pytest",
            ROUND_TRIP_TEST,
            "-q",
            "--tb=short",
        ],
        cwd=REPO_ROOT,
    )
    if rc == 0:
        return CheckResult(
            name="round_trip_test",
            status="PASS",
            evidence=f"pytest {ROUND_TRIP_TEST} → exit 0",
        )
    return CheckResult(
        name="round_trip_test",
        status="FAIL",
        evidence=(
            f"pytest {ROUND_TRIP_TEST} → exit {rc}; "
            f"stderr={stderr[-200:]!r}"
        ),
    )


def check_pii_audit_verdict() -> CheckResult:
    """Parse ``docs/audits/pii-live-migration-2026-Q3.md`` for the verdict.

    The spec (REQ-PII-Audit-Verdict) requires the verdict be ``PASS``.
    The PR4b PII audit doc carries the verdict as ``Verdict (PR4b):``
    followed by ``PASS:`` or ``FAIL:``. We match the first occurrence
    on the line; the audit doc is the single source of truth.
    """
    if not PII_AUDIT_PATH.exists():
        return CheckResult(
            name="pii_audit_verdict",
            status="FAIL",
            evidence=f"audit file missing at {PII_AUDIT_PATH}",
        )
    text = PII_AUDIT_PATH.read_text(encoding="utf-8")
    # ``PASS:`` or ``FAIL:`` immediately after a "## Verdict" heading.
    match = re.search(r"##\s*Verdict.*?\n+(PASS|FAIL)\s*:", text, re.DOTALL)
    if not match:
        return CheckResult(
            name="pii_audit_verdict",
            status="FAIL",
            evidence=(
                f"audit doc at {PII_AUDIT_PATH} has no parseable verdict "
                f"(expected 'PASS:' or 'FAIL:' under a '## Verdict' heading)"
            ),
        )
    verdict = match.group(1)
    return CheckResult(
        name="pii_audit_verdict",
        status="PASS" if verdict == "PASS" else "FAIL",
        evidence=f"audit verdict = {verdict}",
    )





def check_web_to_legacy_check_only() -> CheckResult:
    """Run ``apply --direction web-to-legacy --check-only`` and assert it exits 0.

    The spec (REQ-Web-To-Legacy-Symmetric) requires the reverse path
    be exercised as a dry-run. The CLI requires ``--legacy-path`` so
    the dry-run can iterate the legacy tables. We use the local-access
    backend fixture (the real .accdb the operator has authorised for
    sandbox use; it is committed to the repo and the README mandates
    copy-before-mutate discipline).

    M0 of self-host-backend-coolify (issue #641): the CLI's
    ``StubAuthUsersPort`` now points at the local backend when
    ``APAP_LOCAL_BACKEND=true`` and ``APAP_INSFORGE_URL`` targets it.
    If ``APAP_LOCAL_DB_URL`` is set in the parent env, this check
    auto-wires both: it provisions an ephemeral APAP schema, spawns
    the local backend on a free port, runs the migration CLI against
    it, and tears everything down. Without ``APAP_LOCAL_DB_URL`` the
    check falls back to the operator's manual setup (LocalBackend remote
    must be reachable).

    This is a soft check: if the CLI returns non-zero, we report FAIL
    but the orchestrator continues (other conditions may still
    pass). The operator sees a precise error in the receipt.
    """
    legacy_path = REPO_ROOT / "tests" / "migration" / "local-access" / "backend" / "Registro_APAP_Alcala_datos_18.accdb"
    if not legacy_path.exists():
        return CheckResult(
            name="web_to_legacy_check_only",
            status="FAIL",
            evidence=f"legacy fixture missing at {legacy_path}",
        )

    # M0 fixture wiring: if APAP_LOCAL_DB_URL is set, stand up the
    # local backend in-process with a fresh ephemeral schema, run the
    # check, then tear down. Otherwise inherit the parent's env
    # (operator must ensure the target — LocalBackend or local — is reachable).
    extra_env: dict[str, str] = {}
    backend_proc = None
    ephemeral_schema: str | None = None
    local_db_url = os.environ.get("APAP_LOCAL_DB_URL")
    if local_db_url:
        try:
            ephemeral_schema = _provision_ephemeral_schema(local_db_url)
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                name="web_to_legacy_check_only",
                status="FAIL",
                evidence=f"could not provision ephemeral schema: {exc}",
            )
        try:
            port = _pick_free_port()
        except OSError as exc:
            _drop_ephemeral_schema(local_db_url, ephemeral_schema)
            return CheckResult(
                name="web_to_legacy_check_only",
                status="FAIL",
                evidence=f"could not find a free port for the local backend: {exc}",
            )
        backend_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.core.local_backend.app:create_app",
                "--factory",
                "--port",
                str(port),
                "--host",
                "127.0.0.1",
            ],
            cwd=REPO_ROOT,
            env={
                **os.environ,
                "APAP_LOCAL_DB_URL": local_db_url,
                "APAP_LOCAL_DB_SCHEMA": ephemeral_schema,
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            if not _wait_for_healthz(port, timeout_seconds=5.0):
                stderr_bytes = backend_proc.stderr.read() if backend_proc.stderr else b""
                stderr_text = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
                return CheckResult(
                    name="web_to_legacy_check_only",
                    status="FAIL",
                    evidence=(
                        f"local backend did not become healthy on port {port} "
                        f"within 5s; stderr={stderr_text[-300:]!r}"
                    ),
                )
            extra_env = {
                "APAP_LOCAL_BACKEND": "true",
                "APAP_INSFORGE_URL": f"http://127.0.0.1:{port}",
                # Dummy key — the local backend does not authenticate.
                "APAP_INSFORGE_SERVICE_KEY": "local-backend-dummy-key",
            }
        except Exception:
            backend_proc.kill()
            raise

    try:
        rc, stdout, stderr = _run_subprocess_check(
            [
                sys.executable,
                "-m",
                "migration",
                "apply",
                "--direction",
                "web-to-legacy",
                "--check-only",
                "--legacy-path",
                str(legacy_path),
            ],
            cwd=REPO_ROOT,
            extra_env=extra_env or None,
        )
    finally:
        if backend_proc is not None:
            backend_proc.terminate()
            try:
                backend_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend_proc.kill()
        if ephemeral_schema is not None and local_db_url is not None:
            try:
                _drop_ephemeral_schema(local_db_url, ephemeral_schema)
            except Exception:  # noqa: BLE001
                pass  # best-effort cleanup

    if rc == 0:
        return CheckResult(
            name="web_to_legacy_check_only",
            status="PASS",
            evidence="apply --direction web-to-legacy --check-only → exit 0",
        )
    return CheckResult(
        name="web_to_legacy_check_only",
        status="FAIL",
        evidence=(
            f"apply --direction web-to-legacy --check-only → exit {rc}; "
            f"stderr={stderr[-300:]!r}"
        ),
    )


__all__ = ["check_web_to_legacy_check_only"]
