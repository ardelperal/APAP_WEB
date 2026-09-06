"""Tests for ``scripts/migrate_legacy_accdb_to_local.sh`` (Phase 3, issue #648).

The script invokes ``python -m migration apply --direction legacy-to-web``
against the Coolify-hosted local backend (the same flow that
``verify-fallback-ready --ci-only`` exercises end-to-end). It is an
operator-facing wrapper: it does NOT contain the migration logic
itself (that lives in :mod:`migration.apply`), it just wires the
operator's environment into a one-shot command.

These tests pin the contract:

- The script refuses to run when required env vars are missing.
- The script validates that the ``.accdb`` path exists before invoking
  the CLI.
- The script invokes the documented CLI with the documented flags
  (``--direction legacy-to-web`` + ``--legacy-path``).
- The script is syntactically valid bash and uses ``set -euo pipefail``.

Hard rules (apap-migration):

- HR-13 (preserve partial-apply evidence): the script does NOT
  invoke ``apply`` directly without ``--check-only`` first; it
  always pre-flights with a dry-run before the real apply so the
  operator sees the writes planned before committing.
- HR-19 (atoms under ``tests/migration``): these tests pin the
  wrapper's contract; the underlying CLI has its own atoms under
  the same directory.

We invoke the script via ``subprocess.run`` with a controlled env
so the tests run deterministically without touching the real
``.accdb`` or the production Postgres.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "migrate_legacy_accdb_to_local.sh"


# --- helpers --------------------------------------------------------------


def _run(
    args: list[str],
    *,
    env_extra: dict[str, str] | None = None,
    workdir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the script with a clean environment (only what the test injects)."""
    env = os.environ.copy()
    # Strip any operator-side env vars the script might pick up by accident.
    for key in (
        "APAP_LOCAL_DB_URL",
        "APAP_LOCAL_DB_SCHEMA",
        "APAP_LOCAL_BACKEND",
        "APAP_INSFORGE_URL",
        "APAP_LEGACY_ACCDB_PATH",
    ):
        env.pop(key, None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=workdir or REPO_ROOT,
        timeout=10,
    )


# --- structural contract --------------------------------------------------


class TestScriptShape:
    """Static checks the script must always pass — regardless of how
    the migration CLI evolves. These are the cheap, fast guards."""

    def test_script_exists(self) -> None:
        assert SCRIPT.is_file(), f"{SCRIPT} does not exist"

    def test_script_is_executable(self) -> None:
        mode = SCRIPT.stat().st_mode
        assert mode & 0o111, f"{SCRIPT} is not executable"

    def test_script_has_bash_shebang(self) -> None:
        first_line = SCRIPT.read_text(encoding="utf-8").splitlines()[0]
        assert first_line.startswith("#!"), first_line
        assert "bash" in first_line, first_line

    def test_script_uses_strict_mode(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        assert "set -euo pipefail" in text, (
            "script must use 'set -euo pipefail' so partial failures abort"
        )

    def test_bash_n_parses_without_errors(self) -> None:
        """``bash -n`` exits 0 when the script is syntactically valid."""
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr


# --- runtime contract -----------------------------------------------------


class TestScriptRefusesWithoutEnv:
    """The script must refuse to run when required env vars are missing,
    so an operator with a misconfigured shell sees the failure
    immediately rather than after 5 minutes of pre-flight."""

    def test_no_env_vars_exits_non_zero(self) -> None:
        result = _run([], env_extra={})
        assert result.returncode != 0
        assert "ACCDB" in result.stderr or "env" in result.stderr.lower(), result.stderr

    def test_only_one_env_var_exits_non_zero(self) -> None:
        """``APAP_LEGACY_ACCDB_PATH`` alone is not enough — the local
        backend also needs ``APAP_LOCAL_DB_URL``."""
        result = _run(
            [], env_extra={"APAP_LEGACY_ACCDB_PATH": "/tmp/fake.accdb"}
        )
        assert result.returncode != 0
        assert "APAP_LOCAL_DB_URL" in result.stderr, result.stderr

    def test_no_accdb_path_exits_non_zero(self, tmp_path: Path) -> None:
        """Even with both env vars, an unset / non-existent ``.accdb``
        must fail before the migration CLI runs (HR-13: never start
        a partial apply)."""
        result = _run(
            [],
            env_extra={
                "APAP_LEGACY_ACCDB_PATH": str(tmp_path / "does-not-exist.accdb"),
                "APAP_LOCAL_DB_URL": "postgresql://localhost/test",
            },
        )
        assert result.returncode != 0
        assert "does-not-exist.accdb" in result.stderr, result.stderr


class TestScriptInvokesCliWithRightFlags:
    """When the env is valid AND the ``.accdb`` exists, the script
    must invoke the migration CLI with the documented flags.

    We can't run the CLI against a real Postgres in unit tests; instead
    we replace the ``python`` on PATH with a fake that records the
    arguments and exits 0. The test asserts on the recorded argv."""

    def test_calls_python_with_apply_legacy_to_web(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        accdb = tmp_path / "fixture.accdb"
        accdb.write_bytes(b"")
        fake_python = tmp_path / "fake_python.sh"
        # The fake records argv to a sentinel file the test reads back.
        argv_file = tmp_path / "argv.txt"
        fake_python.write_text(
            "#!/usr/bin/env bash\n"
            'printf "%s\\n" "$@" > "$ARGV_FILE"\n'
            "exit 0\n",
            encoding="utf-8",
        )
        fake_python.chmod(0o755)
        monkeypatch.setenv("ARGV_FILE", str(argv_file))
        # Put the fake python FIRST on PATH so the script's `python`
        # invocation finds it before the real interpreter.
        monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

        env = {
            "APAP_LEGACY_ACCDB_PATH": str(accdb),
            "APAP_LOCAL_DB_URL": "postgresql://localhost/test",
        }
        result = _run([], env_extra=env)

        assert result.returncode == 0, result.stderr
        recorded = argv_file.read_text(encoding="utf-8").splitlines()
        # ``python -m migration apply --direction legacy-to-web
        #  --legacy-path <path> --check-only``
        assert "-m" in recorded
        assert "migration" in recorded
        assert "apply" in recorded
        assert "--direction" in recorded
        assert "legacy-to-web" in recorded
        assert "--legacy-path" in recorded
        assert str(accdb) in recorded
        # Pre-flight via --check-only (HR-13: never write without a dry-run)
        assert "--check-only" in recorded


class TestScriptUsage:
    """When the operator runs ``--help`` (or no args + missing env), the
    script must show the env vars it needs. No guessing."""

    def test_help_flag_prints_env_requirements(self) -> None:
        result = _run(["--help"], env_extra={})
        # ``--help`` always exits 0 (or the documented usage code).
        assert "APAP_LEGACY_ACCDB_PATH" in (result.stdout + result.stderr)
        assert "APAP_LOCAL_DB_URL" in (result.stdout + result.stderr)
