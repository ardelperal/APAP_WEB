"""Tests for the linter exclusion mechanism (PR-1B, post-merge fix).

After PR-1A landed on staging, six false positives surfaced in the
infrastructure layer (linter self-reference, fixture files, sandbox
DDL string). This PR introduces ``--exclude`` / ``.check_rulesignore``
to silence them. These tests verify the exclusion contract.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts import check_rules

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_rules.py"


# --- find_violations(exclude=...) ----------------------------------------


def _norm(p: Path) -> str:
    """Forward-slash-normalised path string for cross-platform substring matches."""
    return str(p).replace("\\", "/")


def test_exclude_removes_self_reference() -> None:
    """Default exclude set must silence ``scripts/check_rules.py`` self-flagging
    (Detector 4 hits its own marker at lines 29 + 245)."""
    violations = check_rules.find_violations(SCRIPT.parent.parent)
    assert any(
        _norm(v.file).endswith("scripts/check_rules.py") for v in violations
    ), "Baseline assumption: linter self-flags on the default exclude list"

    excluded = check_rules.find_violations(
        SCRIPT.parent.parent,
        exclude=frozenset({"scripts/check_rules.py"}),
    )
    assert not any(
        _norm(v.file).endswith("scripts/check_rules.py") for v in excluded
    ), "Exclusion failed: linter still flags scripts/check_rules.py"


def test_exclude_removes_fixture_violations() -> None:
    """``tests/_rule_helpers/fixtures/`` must be silenceable in one flag."""
    violations = check_rules.find_violations(SCRIPT.parent.parent)
    assert any("tests/_rule_helpers/fixtures" in _norm(v.file) for v in violations)

    excluded = check_rules.find_violations(
        SCRIPT.parent.parent,
        exclude=frozenset({"tests/_rule_helpers/fixtures"}),
    )
    assert not any(
        "tests/_rule_helpers/fixtures" in _norm(v.file) for v in excluded
    )


def test_exclude_does_not_remove_non_excluded_violations() -> None:
    """Exclusion is a SUBSET filter — paths not in the set are unaffected."""
    excluded = check_rules.find_violations(
        SCRIPT.parent.parent,
        exclude=frozenset({"scripts/check_rules.py"}),
    )
    # The migration-004 sandbox DDL string is NOT in the default exclude
    # set; verify the linter still flags it after partial exclusion.
    migration_hits = [
        v for v in excluded if "tests/test_migration_004.py" in _norm(v.file)
    ]
    assert migration_hits, (
        "Excluding scripts/check_rules.py should not silence other paths"
    )


def test_exclude_accepts_directory_and_file_paths() -> None:
    """Both file and directory paths are accepted in ``exclude``."""
    excluded = check_rules.find_violations(
        SCRIPT.parent.parent,
        exclude=frozenset(
            {
                "scripts/check_rules.py",
                "tests/_rule_helpers/fixtures",
                "tests/test_migration_004.py",
            }
        ),
    )
    assert not any(
        _norm(v.file).endswith("scripts/check_rules.py")
        or "tests/_rule_helpers/fixtures" in _norm(v.file)
        or "tests/test_migration_004.py" in _norm(v.file)
        for v in excluded
    )


# --- CLI --exclude flag --------------------------------------------------


def test_cli_accepts_repeatable_exclude_flag() -> None:
    """``--exclude PATH`` is repeatable; multiple values compose as a set."""
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            ".",
            "--exclude",
            "scripts/check_rules.py",
            "--exclude",
            "tests/_rule_helpers/fixtures",
            "--exclude",
            "tests/test_migration_004.py",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"CLI failed with --exclude set; stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    assert "violation" not in result.stderr.lower(), (
        f"Expected 0 violations after exclusion; got: {result.stderr!r}"
    )


def test_cli_exits_zero_with_defaults_when_violations_silenced() -> None:
    """``scripts/check_rules.py`` ships with ``DEFAULT_EXCLUDES`` so the
    ``check-rules`` Makefile target returns 0 on staging by default.

    Note: this verifies the CLI contract for the ``--exclude`` flag with
    an explicit list. The default behaviour (no flag) is preserved for
    back-compat — see ``test_cli_defaults_silence_audit_baseline``."""
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            ".",
            "--exclude",
            "scripts/check_rules.py",
            "--exclude",
            "tests/_rule_helpers/fixtures",
            "--exclude",
            "tests/test_migration_004.py",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0


def test_cli_defaults_silence_audit_baseline() -> None:
    """Without ``--exclude``, the linter applies ``DEFAULT_EXCLUDES`` so
    the 6 known false positives from PR-1A's post-merge verification are
    silenced. This is the new default behaviour — see PR-1B ``T-1B.9``.

    To override the defaults (e.g. for audit purposes) pass an explicit
    ``--exclude`` list. The behaviour mirrors ``git ls-files --exclude-standard``.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "."],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        "Without --exclude, DEFAULT_EXCLUDES must silence the 6 known false "
        "positives; CLI should exit 0 on staging. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# --- .check_rulesignore file ---------------------------------------------


def test_check_rulesignore_file_overrides_default(tmp_path: Path) -> None:
    """``.check_rulesignore`` is read when present; one path per line, comments
    with ``#``, blank lines tolerated."""
    repo = tmp_path / "proj"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "check_rules.py").write_text(
        check_rules.__file__ and Path(check_rules.__file__).read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (repo / ".check_rulesignore").write_text(
        "# silences the migration sandbox DDL string\n"
        "tests/test_migration_004.py\n"
        "\n"
        "scripts/check_rules.py\n",
        encoding="utf-8",
    )
    parsed = check_rules.parse_check_rulesignore(repo / ".check_rulesignore")
    assert parsed == frozenset(
        {"tests/test_migration_004.py", "scripts/check_rules.py"}
    )


def test_parse_check_rulesignore_handles_missing_file(tmp_path: Path) -> None:
    """A missing file → empty set (caller falls back to CLI excludes)."""
    assert check_rules.parse_check_rulesignore(
        tmp_path / "does-not-exist"
    ) == frozenset()
