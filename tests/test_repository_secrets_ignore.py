"""Repository security: secrets and local coverage artifacts must be ignored.

These atoms pin the root ``.gitignore`` surface for PR4a + operator ``.env``
so a leaked credential file cannot be staged. They never read or print the
secret file contents.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GITIGNORE_PATH = REPO_ROOT / ".gitignore"


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args),
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )


def _check_ignored(path: str) -> bool:
    """Return True iff git would ignore ``path`` at the project root."""
    result = _git("check-ignore", "--no-index", "--verbose", path)
    return result.returncode == 0


def _gitignore_lines() -> list[str]:
    return [
        raw.rstrip("\r\n")
        for raw in GITIGNORE_PATH.read_text(encoding="utf-8").splitlines()
    ]


# --- .gitignore surface ---------------------------------------------------


def test_root_gitignore_ignores_env_at_project_root_only() -> None:
    """The root ``.env`` file is ignored; nested ``.env`` files are not."""
    assert GITIGNORE_PATH.is_file(), "Root .gitignore must exist"
    assert _check_ignored(".env"), (
        "Root .env must be ignored by the project .gitignore"
    )
    assert not _check_ignored("app/.env"), (
        ".gitignore must NOT broadly ignore .env under subdirectories; "
        "rules must match project-root only"
    )
    assert not _check_ignored("tests/.env"), (
        ".gitignore must NOT ignore tests/.env; the rule is project-root only"
    )


def test_root_gitignore_ignores_coverage_artifacts_only() -> None:
    """coverage.json and coverage_full.json are ignored; coverage* is not broad."""
    assert _check_ignored("coverage.json"), "coverage.json must be ignored"
    assert _check_ignored("coverage_full.json"), "coverage_full.json must be ignored"
    assert not _check_ignored("app/coverage.json"), (
        "coverage.json rule must be project-root only"
    )
    assert not _check_ignored("app/migration/coverage.json"), (
        "coverage.json rule must not match under subdirectories"
    )


def test_root_gitignore_preserves_env_example_trackability() -> None:
    """If a tracked ``.env.example`` template exists, it remains trackable.

    The project may not yet have a ``.env.example``; that is fine. If it
    exists in the working tree, ``git check-ignore`` must return ``False``
    so the template can be committed.
    """
    if not (REPO_ROOT / ".env.example").exists():
        pytest.skip(".env.example does not yet exist; no trackability contract to pin")
    assert not _check_ignored(".env.example"), (
        ".env.example must NOT be ignored; the operator uses it as a tracked template"
    )


def test_root_gitignore_does_not_ignore_codegraph() -> None:
    """AGENTS.md rule 14 forbids re-ignoring the codegraph index."""
    assert not _check_ignored(".codegraph"), (
        ".codegraph directory must remain tracked (AGENTS.md §14.4)"
    )
    # ``.codegraph/.gitignore`` is itself the project's own
    # internal ``!``-negated metadata; do NOT pin this in W1 narrow scope.


def test_root_gitignore_avoids_broad_doublestar_or_env_patterns() -> None:
    """No broad env patterns introduced by the W1 narrow-scope block.

    Pre-existing lines outside the W1 narrow scope (e.g. ``.engram/``,
    ``venv``, historic ``.codegraph-vba/``) are tolerated as long as no
    new ``**/.env`` or recursive env glob is introduced.
    """
    forbidden = re.compile(
        r"^\s*(?:\*\*[/\\]\.env|\.env[/\\]\*\*|\*\*/?\*\.env|\*\*/\.env)",
        re.IGNORECASE,
    )
    offenders = [line for line in _gitignore_lines() if forbidden.match(line)]
    assert not offenders, (
        "Broad or recursive env patterns detected in .gitignore: "
        f"{offenders!r}; PR4a adds only narrow project-root entries"
    )


def test_root_gitignore_has_narrow_secure_env_block_at_project_root() -> None:
    """Document the W1 narrow-scope contract in the gitignore surface."""
    lines = _gitignore_lines()
    assert any(line.strip() == "/.env" for line in lines), (
        "Root .gitignore must contain a literal `/.env` entry"
    )
    assert any(line.strip() == "/coverage.json" for line in lines), (
        "Root .gitignore must contain a literal `/coverage.json` entry"
    )
    assert any(line.strip() == "/coverage_full.json" for line in lines), (
        "Root .gitignore must contain a literal `/coverage_full.json` entry"
    )


def test_root_gitignore_ignores_atl_receipts_but_keeps_skill_registry() -> None:
    """Agent receipt files under ``.atl/`` are ignored; the registry is not.

    Tooling drops per-run receipt ``.md`` files into ``.atl/`` that are
    local noise, never source. Without an ignore rule they linger
    untracked in ``git status``. The one deliberate exception is the
    tracked ``skill-registry.md``, which a ``!`` negation must keep
    trackable (issue #207).
    """
    assert _check_ignored(".atl/some-agent-receipt.md"), (
        ".atl/*.md receipts must be ignored so they cannot pollute git status"
    )
    # ``_check_ignored`` cannot assert the negation: with ``--verbose``,
    # ``git check-ignore`` exits 0 for any matching pattern, including a
    # ``!`` exemption. Without ``--verbose`` an exempted path exits 1.
    registry = _git("check-ignore", "--no-index", ".atl/skill-registry.md")
    assert registry.returncode == 1, (
        ".atl/skill-registry.md is deliberately tracked and must stay trackable"
    )
    # Pre-existing rule: the generated registry cache stays ignored too.
    assert _check_ignored(".atl/.skill-registry.cache.json"), (
        ".atl/.skill-registry.cache.json must remain ignored (pre-existing rule)"
    )


# --- Working-tree state ---------------------------------------------------


def test_env_file_is_untracked_and_not_staged() -> None:
    """``.env`` is ignored by ``.gitignore`` so a leaked file cannot stage.

    Uses ``git check-ignore --no-index`` so the assertion holds whether
    or not an operator has actually created ``.env`` locally — without
    that primitive, fresh CI checkouts (no ``.env`` on disk) would fail
    the ``git status --ignored`` shape assertion even though the
    gitignore rule is correct.
    """
    assert _check_ignored(".env"), (
        "Root .env must be ignored so a leaked credential file cannot stage"
    )


def test_coverage_artifacts_remain_untracked() -> None:
    """coverage.json and coverage_full.json are ignored by .gitignore.

    Same ``git check-ignore --no-index`` shape as
    ``test_env_file_is_untracked_and_not_staged`` so the assertion holds
    in fresh CI checkouts that have not generated coverage artifacts.
    """
    for name in ("coverage.json", "coverage_full.json"):
        assert _check_ignored(name), (
            f"{name} must be ignored so it cannot stage or pollute status"
        )


def test_no_secret_history_in_git_log_for_env() -> None:
    """``.env`` must never have been tracked in any branch's history."""
    result = _git("log", "--all", "--pretty=format:", "--name-only", "--diff-filter=A", "--", ".env")
    assert result.returncode == 0, result.stderr
    additions = [line for line in result.stdout.splitlines() if line.strip() == ".env"]
    assert not additions, (
        f".env must never have been committed; found history entries: {additions!r}"
    )
    cached = _git("ls-files", "--error-unmatch", ".env")
    assert cached.returncode != 0, (
        ".env must NOT be in the git index at HEAD"
    )
