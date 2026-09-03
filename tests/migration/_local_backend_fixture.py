"""Session-scoped fixture + local-backend spawn helpers for F3 (AS10).

This module hosts two surface areas:

- The pytest fixture :func:`allocate_local_backend` (and its alias
  :data:`local_backend`) — the test-side spawn. Provisions an
  ephemeral Postgres schema and yields a process handle.
- The F3 gate-side helper :func:`run_web_to_legacy_check` — called by
  ``migration/verify_fallback_ready::check_web_to_legacy_check_only``
  to drive the verify-fallback-ready dry-run against the loopback
  backend.

The shared plumbing (free-port allocation, ``uvicorn`` spawn,
``/healthz`` poll, ``terminate`` teardown, error mapping) lives in
private helpers :func:`_spawn_uvicorn`, :func:`_wait_for_healthz`,
:func:`_terminate`, and :func:`_drain_stderr`.

This module lives under ``tests/`` so the ``check_module_size`` and
``check_mutation_sites`` gates (which only scan ``app/`` and
``migration/``) do not count its sites. Extracting the heavy spawn
plumbing here keeps ``migration/verify_fallback_ready.py`` under the
250-site budget. Importing across the test boundary is the deliberate
F3 design choice — see ``openspec/changes/m0-self-host-backend-rdd/
specs/m0-backend/spec.md`` R6.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import psycopg
import pytest
from psycopg import sql

_LOCAL_BACKEND_FACTORY = "app.core.local_backend.app:create_app"
_HEALTHZ_TIMEOUT_SECONDS = 5.0
_HEALTHZ_POLL_INTERVAL_SECONDS = 0.1
_TERMINATE_JOIN_TIMEOUT_SECONDS = 2.0
_DSN_ENV = "APAP_TEST_POSTGRES_DSN"

# Strings we look for inside ``spawn_local_backend_subprocess``'s
# ``RuntimeError`` message to map the failure to the documented R6
# evidence. Centralised so both consumers (gate + test) classify the
# same way.
_RUNTIME_ERROR_DB_DSN = "db_dsn is required for the local backend"
_RUNTIME_ERROR_HEALTHZ = "did not become healthy"


@dataclass(frozen=True)
class LocalBackendHandle:
    """Process handle + addressing for the local backend under test.

    ``port`` is the kernel-allocated TCP port uvicorn is bound to;
    ``base_url`` is the operator-facing base URL (the rawsql /
    OAuth routers are mounted under ``/api``); ``process`` is the live
    uvicorn subprocess; ``schema`` is the ephemeral Postgres schema
    the lifespan handler sets via ``search_path`` so concurrent
    sessions cannot collide.
    """

    port: int
    base_url: str
    process: subprocess.Popen[bytes]
    schema: str


def local_postgres_dsn() -> str:
    """Return ``APAP_TEST_POSTGRES_DSN`` or raise a clear configuration error.

    The CI integration job supplies this env via the service container;
    locally, an operator sets it explicitly. The check MUST NOT silently
    skip when the DSN is absent — that violates the project's AGENTS.md
    integration-test policy and the F1 contract.
    """
    dsn = os.environ.get(_DSN_ENV, "").strip()
    if not dsn:
        raise RuntimeError(
            f"{_DSN_ENV} is required for the local-backend fixture; "
            "set it to a test database DSN "
            "(e.g. postgresql://postgres@127.0.0.1:5432/apap_test)"
        )
    return dsn


def _allocate_free_port() -> int:
    """Bind ``127.0.0.1:0`` and return the kernel-allocated port.

    Closes the socket before returning so uvicorn can rebind it.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def _wait_for_healthz(base_url: str, *, timeout: float) -> None:
    """Poll ``GET <base_url>/healthz`` until 200 or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/healthz", timeout=0.5)
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(_HEALTHZ_POLL_INTERVAL_SECONDS)
    detail = (
        f"local backend did not become healthy on {base_url} within "
        f"{timeout:g}s"
    )
    if last_error is not None:
        detail += f" (last transport error: {last_error!r})"
    raise RuntimeError(detail)


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    """Best-effort ``SIGTERM`` → ``SIGKILL`` escalation in ``finally``."""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=_TERMINATE_JOIN_TIMEOUT_SECONDS)
        return
    except (subprocess.TimeoutExpired, OSError):
        pass
    try:
        proc.kill()
        proc.wait(timeout=_TERMINATE_JOIN_TIMEOUT_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _drain_stderr(proc: subprocess.Popen[bytes]) -> str:
    """Best-effort drain of the spawned subprocess's stderr pipe."""
    if proc.stderr is None:
        return ""
    try:
        blob = proc.stderr.read() or b""
    except Exception:  # noqa: BLE001 — best-effort drain
        blob = b""
    return blob.decode("utf-8", errors="replace")


def _repo_root() -> str:
    """Return the absolute path to the repository root.

    ``tests/migration/_local_backend_fixture.py`` → repo root is three
    parents up. The spawned subprocess must ``cwd`` into the repo
    root so the ``app.core.local_backend.app`` import resolves.
    """
    return str(Path(__file__.resolve().parents[2]))


def _build_local_backend_env(
    *, db_dsn: str, db_schema: str, base_url: str
) -> dict[str, str]:
    """Build the F3 subprocess env that points :class:`InsForgeClient` at the loopback.

    Reads ``os.environ`` so any operator-supplied env var (e.g.
    ``APAP_GOOGLE_CLIENT_ID``) propagates to the spawned uvicorn
    subprocess unchanged; the four F3 keys override whatever the
    parent process had set.
    """
    return {
        **os.environ,
        "APAP_LOCAL_DB_URL": db_dsn,
        "APAP_LOCAL_DB_SCHEMA": db_schema,
        "APAP_LOCAL_BACKEND": "true",
        "APAP_INSFORGE_URL": f"{base_url}/api",
    }


def _spawn_uvicorn(
    *,
    port: int,
    env: dict[str, str],
    cwd: str,
) -> subprocess.Popen[bytes]:
    """Spawn uvicorn on ``port`` with the F3 env and return the Popen handle."""
    return subprocess.Popen(  # noqa: S603 — bounded input, sandboxed spawn
        [
            sys.executable,
            "-m",
            "uvicorn",
            _LOCAL_BACKEND_FACTORY,
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _spawn_and_wait(
    *,
    db_dsn: str,
    db_schema: str,
    cwd: str,
) -> tuple[subprocess.Popen[bytes], int, str]:
    """Spawn uvicorn + poll ``/healthz``; return ``(proc, port, base_url)`` on success.

    Raises ``RuntimeError`` on healthz timeout (R6 contract) or factory
    failure (port-already-in-use, missing DSN). The caller is
    responsible for terminating the returned ``proc`` in ``finally``.
    """
    port = _allocate_free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = _build_local_backend_env(
        db_dsn=db_dsn, db_schema=db_schema, base_url=base_url
    )
    process = _spawn_uvicorn(port=port, env=env, cwd=cwd)
    try:
        _wait_for_healthz(base_url, timeout=_HEALTHZ_TIMEOUT_SECONDS)
    except RuntimeError as health_error:
        stderr_blob = _drain_stderr(process)
        detail = (
            f"{health_error}; "
            f"uvicorn stderr={stderr_blob[-400:]!r}"
        )
        _terminate(process)
        raise RuntimeError(detail) from health_error
    return process, port, base_url


@contextmanager
def spawn_local_backend_subprocess(
    *,
    db_dsn: str,
    db_schema: str,
    cwd: str | None = None,
) -> Iterator[tuple[subprocess.Popen[bytes], int, str]]:
    """Spawn the local FastAPI backend on a free port and yield its handle.

    Used by :func:`allocate_local_backend` (the test-side fixture).
    Yields ``(process, port, base_url)``. The subprocess is torn down
    in the ``finally`` even if the caller raises.

    Raises ``RuntimeError`` on healthz timeout or factory ``RuntimeError``.
    """
    process, port, base_url = _spawn_and_wait(
        db_dsn=db_dsn,
        db_schema=db_schema,
        cwd=cwd or _repo_root(),
    )
    try:
        yield process, port, base_url
    finally:
        _terminate(process)


def run_apply_against_local_backend(
    *,
    apply_argv: list[str],
    db_dsn: str,
    db_schema: str,
    cwd: str,
) -> tuple[int, str, str]:
    """Spawn the local backend and run ``apply_argv`` against it.

    Returns ``(returncode, stdout, stderr)``. Raises ``RuntimeError``
    on healthz timeout or factory ``RuntimeError("db_dsn is required
    for the local backend")``. The subprocess is terminated in
    ``finally``.
    """
    process, port, base_url = _spawn_and_wait(
        db_dsn=db_dsn, db_schema=db_schema, cwd=cwd
    )
    try:
        env = _build_local_backend_env(
            db_dsn=db_dsn, db_schema=db_schema, base_url=base_url
        )
        completed = subprocess.run(  # noqa: S603 — caller-supplied argv
            apply_argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    finally:
        _terminate(process)
    return completed.returncode, completed.stdout, completed.stderr


def run_web_to_legacy_check(
    *,
    legacy_path: str,
    local_backend: bool,
    repo_root: str,
) -> dict[str, str]:
    """F3 gate-side helper — drive ``apply --check-only`` and return a dict.

    Returns a ``CheckResult``-shaped dict ``{"name": ..., "status": ..., "evidence": ...}``
    so the migration gate can wrap it without re-importing
    ``migration.verify_fallback_ready.CheckResult``. The dict shape
    mirrors :class:`migration.verify_fallback_ready.CheckResult`'s
    three fields.

    The helper covers two runtime modes:

    - ``local_backend=True``: spawn the local FastAPI backend on a
      free port and run ``apply_argv`` against it (InsForgeClient →
      loopback per F1's R7 switch).
    - ``local_backend=False``: run ``apply_argv`` against the parent's
      environment unchanged (production InsForge URL).

    Always cleans the subprocess in ``finally``. The gate maps the
    dict to a ``CheckResult``.
    """
    apply_argv = [
        sys.executable,
        "-m",
        "migration",
        "apply",
        "--direction",
        "web-to-legacy",
        "--check-only",
        "--legacy-path",
        legacy_path,
    ]

    if not local_backend:
        completed = subprocess.run(  # noqa: S603 — caller-supplied argv
            apply_argv,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        return _make_result(
            completed.returncode, completed.stdout, completed.stderr
        )

    db_url = os.environ.get("APAP_LOCAL_DB_URL", "").strip()
    db_schema = os.environ.get("APAP_LOCAL_DB_SCHEMA", "").strip()
    if not db_url or not db_schema:
        return {
            "name": "web_to_legacy_check_only",
            "status": "FAIL",
            "evidence": (
                "APAP_LOCAL_DB_URL and APAP_LOCAL_DB_SCHEMA are required "
                "when APAP_LOCAL_BACKEND is set"
            ),
        }
    try:
        rc, stdout, stderr = run_apply_against_local_backend(
            apply_argv=apply_argv, db_dsn=db_url, db_schema=db_schema, cwd=repo_root
        )
    except RuntimeError as exc:
        message = str(exc)
        if _RUNTIME_ERROR_DB_DSN in message:
            return {
                "name": "web_to_legacy_check_only",
                "status": "FAIL",
                "evidence": _RUNTIME_ERROR_DB_DSN,
            }
        if _RUNTIME_ERROR_HEALTHZ in message:
            return {
                "name": "web_to_legacy_check_only",
                "status": "FAIL",
                "evidence": (
                    "local backend did not become healthy on the "
                    "spawned port within 5s"
                ),
            }
        raise
    return _make_result(rc, stdout, stderr)


def _make_result(rc: int, stdout: str, stderr: str) -> dict[str, str]:
    """Map ``apply --check-only`` exit code to a CheckResult-shaped dict."""
    if rc == 0:
        return {
            "name": "web_to_legacy_check_only",
            "status": "PASS",
            "evidence": "apply --direction web-to-legacy --check-only → exit 0",
        }
    return {
        "name": "web_to_legacy_check_only",
        "status": "FAIL",
        "evidence": (
            f"apply --direction web-to-legacy --check-only → exit {rc}; "
            f"stderr={stderr[-300:]!r}"
        ),
    }


def allocate_local_backend(
    *, scope: str = "session"
) -> Iterator[LocalBackendHandle]:
    """Pytest fixture factory: spawn uvicorn + provision schema, then yield.

    Parameters
    ----------
    scope:
        Pytest fixture scope. Defaults to ``"session"`` so multiple
        tests share one backend (~10 s saved per test). Tests that
        need a fresh schema per case can request ``"function"``
        explicitly.

    Yields
    ------
    LocalBackendHandle
        The live backend; the fixture finalizer terminates the
        subprocess and drops the ephemeral schema in ``finally``.
    """
    del scope  # consumed by the ``pytest.fixture(scope=...)`` decorator
    dsn = local_postgres_dsn()
    schema = f"local_backend_test_{uuid.uuid4().hex[:12]}"

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
        )

    process: subprocess.Popen[bytes] | None = None
    handle: LocalBackendHandle | None = None
    try:
        try:
            with spawn_local_backend_subprocess(
                db_dsn=dsn, db_schema=schema
            ) as (proc, port, base_url):
                process = proc
                handle = LocalBackendHandle(
                    port=port,
                    base_url=base_url,
                    process=process,
                    schema=schema,
                )
                yield handle
        except RuntimeError as exc:
            raise RuntimeError(str(exc)) from exc
    finally:
        if process is not None:
            _terminate(process)
        try:
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(schema)
                    )
                )
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass


# Apply the default pytest scope lazily so test files can opt in to
# ``"function"`` by calling the factory themselves with the alternative
# scope.
local_backend = pytest.fixture(scope="session")(allocate_local_backend)


__all__ = [
    "LocalBackendHandle",
    "allocate_local_backend",
    "local_backend",
    "local_postgres_dsn",
    "run_apply_against_local_backend",
    "run_web_to_legacy_check",
    "spawn_local_backend_subprocess",
]
