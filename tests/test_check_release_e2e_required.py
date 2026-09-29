"""Behaviour tests for scripts/check_release_e2e_required.py (issue #1131).

The selector decides whether a deployed range touches e2e-sensitive paths. It
must fail closed: when it cannot decide, the authenticated battery is required.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_release_e2e_required as cer  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_PATTERNS = REPO_ROOT / ".github" / "release-e2e-paths.txt"


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "paths.txt"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_patterns_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    path = _write(tmp_path, "# why\n\napp/core/auth.py\n  app/core/csrf.py  \n# more\n")

    assert cer.load_patterns(path) == ["app/core/auth.py", "app/core/csrf.py"]


@pytest.mark.parametrize("text", ["", "# only comments\n\n"])
def test_empty_pattern_file_is_an_error(tmp_path: Path, text: str) -> None:
    with pytest.raises(cer.SelectorError):
        cer.load_patterns(_write(tmp_path, text))


def test_missing_pattern_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(cer.SelectorError):
        cer.load_patterns(tmp_path / "nope.txt")


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("app/core/auth.py", "app/core/auth.py", True),
        ("app/core/auth.py", "app/core/auth.pyc", False),
        ("app/core/auth*.py", "app/core/auth_cache.py", True),
        ("app/core/auth*.py", "app/core/sub/auth_x.py", False),
        ("app/core/auth/**", "app/core/auth/a.py", True),
        ("app/core/auth/**", "app/core/auth/deep/a.py", True),
        ("app/core/auth/**", "app/core/authx/a.py", False),
        ("app/**/*.sql", "app/core/migration/sql/001.sql", True),
        ("app/**/*.sql", "app/x.sql", True),
        ("**/csrf.py", "app/core/csrf.py", True),
        ("app/?.py", "app/a.py", True),
        ("app/?.py", "app/ab.py", False),
        ("a.b", "aXb", False),
    ],
)
def test_glob_semantics(pattern: str, path: str, expected: bool) -> None:
    assert cer.matches(pattern, path) is expected


def test_matching_files_returns_sorted_hits_only() -> None:
    files = ["docs/x.md", "app/core/csrf.py", "app/core/auth.py"]

    assert cer.matching_files(files, ["app/core/*.py"]) == [
        "app/core/auth.py",
        "app/core/csrf.py",
    ]
    assert cer.matching_files(["docs/x.md"], ["app/core/*.py"]) == []


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "one")
    return tmp_path


def test_changed_files_from_git_lists_the_range(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "b dir").mkdir()
    (repo / "b dir" / "é.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "two")
    head = _git(repo, "rev-parse", "HEAD")

    assert cer.changed_files_from_git(base, head, cwd=repo) == ["b dir/é.txt"]


def test_git_failure_is_an_error(repo: Path) -> None:
    with pytest.raises(cer.SelectorError):
        cer.changed_files_from_git("0" * 40, "1" * 40, cwd=repo)


def test_refs_that_look_like_options_are_rejected(repo: Path) -> None:
    with pytest.raises(cer.SelectorError):
        cer.changed_files_from_git("--output=x", "HEAD", cwd=repo)


def test_stdin_mode_not_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patterns = _write(tmp_path, "app/core/auth.py\n")
    monkeypatch.setattr(sys, "stdin", io.StringIO("docs/a.md\nREADME.md\n"))

    assert cer.main(["--stdin", "--patterns", str(patterns)]) == 0
    assert "::notice::" in capsys.readouterr().out


def test_stdin_mode_required_lists_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patterns = _write(tmp_path, "app/core/auth.py\n")
    monkeypatch.setattr(sys, "stdin", io.StringIO("docs/a.md\napp/core/auth.py\n"))

    assert cer.main(["--stdin", "--patterns", str(patterns)]) == 10
    out = capsys.readouterr().out
    assert "::notice::" in out
    assert "app/core/auth.py" in out


def test_empty_change_list_is_not_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    patterns = _write(tmp_path, "app/core/auth.py\n")
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    assert cer.main(["--stdin", "--patterns", str(patterns)]) == 0


def test_unreadable_pattern_file_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("docs/a.md\n"))

    assert cer.main(["--stdin", "--patterns", str(tmp_path / "missing.txt")]) == 10
    assert "required" in capsys.readouterr().out.lower()


def test_git_failure_fails_closed_in_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    repo: Path,
) -> None:
    patterns = _write(tmp_path, "app/core/auth.py\n")
    monkeypatch.chdir(repo)

    assert cer.main(["--base", "0" * 40, "--head", "1" * 40, "--patterns", str(patterns)]) == 10
    assert "::notice::" in capsys.readouterr().out


def test_git_mode_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    patterns = _write(tmp_path, "src/**\n")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "src").mkdir()
    (repo / "src" / "x.py").write_text("x", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "two")
    monkeypatch.chdir(repo)

    assert cer.main(["--base", base, "--head", "HEAD", "--patterns", str(patterns)]) == 10


@pytest.mark.parametrize(
    "argv",
    [[], ["--base", "a"], ["--head", "b"], ["--stdin", "--base", "a", "--head", "b"], ["--bogus"]],
)
def test_usage_errors_exit_two(argv: list[str]) -> None:
    assert cer.main(argv) == 2


def test_real_pattern_file_is_valid_and_every_pattern_matches_a_tracked_file() -> None:
    patterns = cer.load_patterns(REAL_PATTERNS)
    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"], check=True, capture_output=True, text=True
    ).stdout.splitlines()

    dead = [p for p in patterns if not cer.matching_files(tracked, [p])]

    assert not dead, f"patterns matching no tracked file (rotted?): {dead}"


def test_real_pattern_file_selects_the_auth_surface_and_skips_docs() -> None:
    patterns = cer.load_patterns(REAL_PATTERNS)

    assert cer.matching_files(["app/core/csrf.py", "app/core/session.py"], patterns)
    assert cer.matching_files(["docs/roadmap.md", "README.md"], patterns) == []
