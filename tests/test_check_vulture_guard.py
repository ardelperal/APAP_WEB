"""Tests for the dead-code guard (issues #392, #424).

Every other CI gate here is pinned by a test — `test_ruff_ratchet.py`,
`test_module_size.py`, `test_check_rules.py`, `test_check_spec_drift.py`. This
one was not, and it shipped in a state where it **could not fail**: three
independent defects each reduced the pipeline to a no-op (see #424).

So these tests do not merely exercise the happy path; each one pins the exact
property whose absence made the guard useless:

1. vulture's real output shape is parsed (the regex matched nothing).
2. Decorator lines resolve to their `def` through the AST (the scan walked
   backward, away from the `def`, so the filter never fired).
3. References are cross-checked against the source tree (the check compared
   vulture's output against itself, where the condition is always true).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_vulture_guard as guard  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestVultureOutputParsing:
    """Defect 1: the pattern must match what vulture actually prints."""

    def test_parses_a_verbatim_vulture_line(self) -> None:
        line = "app/core/csrf.py:125: unused class 'CsrfMiddleware' (60% confidence)"
        assert guard.parse_vulture_output(line) == [
            ("app/core/csrf.py", 125, "CsrfMiddleware")
        ]

    def test_parses_every_symbol_type_vulture_emits(self) -> None:
        out = (
            "a.py:1: unused function 'f' (60% confidence)\n"
            "b.py:2: unused variable 'v' (60% confidence)\n"
            "c.py:3: unused attribute 'a' (60% confidence)\n"
        )
        assert [n for _, _, n in guard.parse_vulture_output(out)] == ["f", "v", "a"]

    def test_a_pattern_without_the_type_word_would_match_nothing(self) -> None:
        """The original bug, pinned so it cannot come back silently."""
        broken = re.compile(r"^([^\n:]+):(\d+):\s+unused\s+'([^']+)'")
        line = "app/core/csrf.py:125: unused class 'CsrfMiddleware' (60% confidence)"
        assert broken.match(line) is None
        assert guard.parse_vulture_output(line) != []

    def test_parses_windows_absolute_paths(self) -> None:
        """vulture emits absolute paths when the target is outside the cwd.

        Defect 4 (#424): a ``[^\\n:]+`` path group stops at the drive-letter
        colon, so the guard parsed correctly in CI (cwd = repo root, relative
        paths) and not at all anywhere else. That is what made it impossible
        to test in isolation, which is how the other defects survived.
        """
        line = (
            r"C:\repo\app\core\csrf.py:125: unused class 'CsrfMiddleware' "
            "(60% confidence)"
        )
        parsed = guard.parse_vulture_output(line)
        assert parsed == [(r"C:\repo\app\core\csrf.py", 125, "CsrfMiddleware")]

    def test_ignores_blank_and_unparseable_lines(self) -> None:
        assert guard.parse_vulture_output("\n\nnot a vulture line\n") == []


class TestDecoratorResolution:
    """Defect 2: vulture points at the decorator; the def is BELOW it."""

    SOURCE = """\
from fastapi import APIRouter

router = APIRouter()


@router.get("/animales")
def list_animales() -> list[str]:
    return []


def plain_helper() -> None:
    pass
"""

    MULTILINE_DECORATOR = """\
import pytest


@pytest.mark.parametrize(
    "value",
    [1, 2, 3],
)
def test_thing(value: int) -> None:
    pass
"""

    def test_decorator_line_resolves_to_its_def(self) -> None:
        lines = self.SOURCE.splitlines()
        assert lines[5].lstrip().startswith("@router.get")  # line 6, 1-indexed
        assert guard._find_def_line(lines, 6) == 7

    def test_decorated_symbol_is_filtered_out(self) -> None:
        defs = guard._ast_definitions(self.SOURCE)
        def_line = guard._find_def_line(self.SOURCE.splitlines(), 6)
        assert guard._decorated(defs, def_line) is True

    def test_undecorated_def_is_not_filtered(self) -> None:
        defs = guard._ast_definitions(self.SOURCE)
        def_line = guard._find_def_line(self.SOURCE.splitlines(), 12)
        assert guard._decorated(defs, def_line) is False

    def test_multiline_decorator_still_resolves(self) -> None:
        """A forward text scan breaks here; the AST does not."""
        lines = self.MULTILINE_DECORATOR.splitlines()
        assert lines[3].lstrip().startswith("@pytest.mark.parametrize")
        def_line = guard._find_def_line(lines, 4)
        assert lines[def_line - 1].lstrip().startswith("def test_thing")


class TestCrossReference:
    """Defect 3: references must come from the tree, not from vulture."""

    def test_collects_names_from_the_real_tree(self) -> None:
        referenced = guard.collect_referenced_names(REPO_ROOT)
        assert referenced, "expected a non-empty reference set"
        assert "execute_sql" in referenced

    def test_tests_are_a_reference_source_not_a_reporting_target(self) -> None:
        """A production helper exercised only by the suite is not dead (#392)."""
        assert "tests" in guard.REFERENCE_SCOPE
        assert "tests" not in guard.REPORT_SCOPE

    def test_string_literals_count_as_references(self, tmp_path: Path) -> None:
        """__all__ re-exports and getattr targets name symbols as strings."""
        pkg = tmp_path / "app"
        pkg.mkdir()
        (pkg / "m.py").write_text('__all__ = ["SomeSymbol"]\n', encoding="utf-8")
        assert "SomeSymbol" in guard.collect_referenced_names(tmp_path)

    def test_a_definition_alone_is_not_a_reference(self, tmp_path: Path) -> None:
        pkg = tmp_path / "app"
        pkg.mkdir()
        (pkg / "m.py").write_text(
            "def only_defined() -> None:\n    pass\n", encoding="utf-8"
        )
        assert "only_defined" not in guard.collect_referenced_names(tmp_path)


class TestBaselineIsHonest:
    def test_baseline_matches_the_measured_tree(self) -> None:
        """The baseline is what the guard reports, not a number chosen to pass.

        Mirrors test_ruff_ratchet.py / test_module_size.py: a baseline that
        drifts above the real count silently re-opens the door.
        """
        assert guard.main([str(REPO_ROOT)]) == 0

    def test_baseline_is_not_the_pre_deletion_count(self) -> None:
        """#392 shipped BASELINE=5 right after deleting those 5 (§32.P7)."""
        assert guard.BASELINE != 6


class TestTheGuardCanActuallyFail:
    """The property whose absence was the whole defect.

    Every other test here checks that the guard stays quiet on a clean tree —
    which the broken version also did, on every tree, forever. This is the one
    that distinguishes a gate from a decoration.
    """

    def _tree_with_dead_symbol(self, tmp_path: Path, count: int) -> Path:
        pkg = tmp_path / "app"
        pkg.mkdir()
        body = "\n".join(
            f"def never_called_{i}() -> None:\n    pass\n" for i in range(count)
        )
        (pkg / "m.py").write_text(body, encoding="utf-8")
        return tmp_path

    def test_fails_when_dead_code_exceeds_the_baseline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(guard, "BASELINE", 0)
        root = self._tree_with_dead_symbol(tmp_path, count=2)
        assert guard.main([str(root)]) == 1

    def test_passes_when_dead_code_is_within_the_baseline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(guard, "BASELINE", 2)
        root = self._tree_with_dead_symbol(tmp_path, count=2)
        assert guard.main([str(root)]) == 0

    def test_a_referenced_symbol_is_never_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(guard, "BASELINE", 0)
        pkg = tmp_path / "app"
        pkg.mkdir()
        (pkg / "m.py").write_text(
            "def helper() -> None:\n    pass\n", encoding="utf-8"
        )
        (pkg / "caller.py").write_text(
            "from app.m import helper\n\nhelper()\n", encoding="utf-8"
        )
        assert guard.main([str(tmp_path)]) == 0


class TestCiWiring:
    def test_lint_job_runs_the_guard(self) -> None:
        """A gate CI never invokes is §32.P6."""
        ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        assert "scripts/check_vulture_guard.py" in ci

    def test_vulture_is_a_declared_dependency(self) -> None:
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert "vulture" in pyproject

    def test_guard_runs_end_to_end(self) -> None:
        proc = subprocess.run(
            [sys.executable, "scripts/check_vulture_guard.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "check_vulture_guard: OK" in proc.stdout


class _FakeProc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


_FINDING = "app/x.py:3: unused function 'gone' (60% confidence)\n"
_MISSING = "/usr/bin/python3: No module named vulture\n"


class TestFailLoudWhenVultureDidNotRun:
    """Issue #1142: exit 1 is ambiguous ("dead code" vs "module missing")."""

    @staticmethod
    def _stub(monkeypatch: pytest.MonkeyPatch, proc: _FakeProc) -> None:
        monkeypatch.setattr(guard, "_vulture_available", lambda: True)
        monkeypatch.setattr(guard.subprocess, "run", lambda *_a, **_k: proc)

    def test_module_missing_is_an_error_naming_the_fix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_a: object, **_k: object) -> _FakeProc:
            raise AssertionError("must not run without the module")

        monkeypatch.setattr(guard, "_vulture_available", lambda: False)
        monkeypatch.setattr(guard.subprocess, "run", _boom)
        findings, error = guard._run_vulture(REPO_ROOT)
        assert findings == []
        assert error is not None
        assert "uv sync --extra dev" in error
        assert "uv run" in error

    def test_exit_1_with_stderr_and_no_findings_is_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub(monkeypatch, _FakeProc(1, "", _MISSING))
        findings, error = guard._run_vulture(REPO_ROOT)
        assert findings == []
        assert error is not None
        assert "No module named vulture" in error

    def test_exit_1_with_findings_is_reliable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub(monkeypatch, _FakeProc(1, _FINDING))
        findings, error = guard._run_vulture(REPO_ROOT)
        assert error is None
        assert findings == [("app/x.py", 3, "gone")]

    def test_exit_3_with_findings_is_reliable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """vulture 2.16 reports dead code with exit 3, not 1."""
        self._stub(monkeypatch, _FakeProc(3, _FINDING))
        findings, error = guard._run_vulture(REPO_ROOT)
        assert error is None
        assert findings == [("app/x.py", 3, "gone")]

    def test_exit_3_without_findings_is_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub(monkeypatch, _FakeProc(3, "garbled\n"))
        _findings, error = guard._run_vulture(REPO_ROOT)
        assert error is not None

    def test_exit_0_without_findings_is_clean(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub(monkeypatch, _FakeProc(0))
        assert guard._run_vulture(REPO_ROOT) == ([], None)

    def test_unexpected_exit_code_is_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub(monkeypatch, _FakeProc(2, "", "usage error\n"))
        findings, error = guard._run_vulture(REPO_ROOT)
        assert findings == []
        assert error is not None
        assert "exit code 2" in error

    def test_stderr_excerpt_is_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub(monkeypatch, _FakeProc(1, "", "x" * 5000))
        _findings, error = guard._run_vulture(REPO_ROOT)
        assert error is not None
        assert len(error) < 1000

    def test_unreliable_run_exits_non_zero_without_the_baseline_note(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._stub(monkeypatch, _FakeProc(1, "", _MISSING))
        assert guard.main([str(REPO_ROOT)]) == 1
        out = capsys.readouterr().out
        assert "FAIL check_vulture_guard" in out
        assert "update BASELINE" not in out
        assert "NOTE" not in out
