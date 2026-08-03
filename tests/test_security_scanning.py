"""Wiring tests for the CI security scanners.

Issue #381: nothing in CI looked at dependency CVEs, leaked secrets, or the
vulnerability exposure of the pinned base images. These tests pin the wiring so
the jobs cannot be silently dropped, weakened, or gated off.

The tests deliberately assert on *absences* as well as presences. Issue #329
showed the failure mode: a job that exists, looks green in the job list, and
never runs anything is worse than no job at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
GITLEAKSIGNORE_PATH = REPO_ROOT / ".gitleaksignore"

pytestmark = pytest.mark.skipif(not WORKFLOW_PATH.exists(), reason="ci.yml not present")


def _workflow() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _job(name: str, next_name: str) -> str:
    """Return the body of job ``name``, comments stripped."""
    text = _workflow()
    start = text.index(f"\n  {name}:")
    end = text.index(f"\n  {next_name}:", start)
    return "\n".join(
        line for line in text[start:end].splitlines() if not line.lstrip().startswith("#")
    )


def test_security_job_exists_and_runs_on_the_self_hosted_runner() -> None:
    """The scanners must run on the project's own 24/7 runner."""
    job = _job("security", "security-deep")
    assert "[self-hosted, Linux, ARM64, apap, oracle]" in job


def test_security_job_runs_pip_audit() -> None:
    """Dependency CVE scanning is the gap this issue exists to close."""
    assert "pip_audit" in _job("security", "security-deep")


def test_security_job_runs_gitleaks_and_trivy_config() -> None:
    """Secret scanning and Dockerfile misconfiguration scanning on every PR."""
    job = _job("security", "security-deep")
    assert "gitleaks@sha256:" in job, "gitleaks must be pinned by digest"
    assert "trivy@sha256:" in job, "trivy must be pinned by digest"
    assert "config /repo/Dockerfile" in job


def test_security_job_is_not_gated_behind_a_default_off_variable() -> None:
    """Issue #329's failure mode: a job that exists but never runs.

    The light scanners must execute on every PR. A ``vars.*`` condition would
    silently disable them the moment the variable is unset.
    """
    job = _job("security", "security-deep")
    assert "vars." not in job, "the security job must not be gated on an org variable"


def test_no_scanner_step_swallows_its_exit_code() -> None:
    """A scanner that cannot fail is false assurance, not a guard."""
    both = _job("security", "security-deep") + _job("security-deep", "typecheck")
    assert "continue-on-error" not in both
    assert "|| true" not in both, "a scanner step must never swallow its exit code"
    assert both.count("--exit-code 1") >= 3, "each scanner must fail the job on findings"


def test_deep_job_is_scheduled_not_per_pull_request() -> None:
    """Heavy scanning runs weekly and on tags — never on every PR.

    While the MVP is being built, pulling base images per pull request costs
    minutes and changes nothing: a pinned base image cannot differ between two
    PRs on the same day.
    """
    deep = _job("security-deep", "typecheck")
    assert "github.event_name == 'schedule'" in deep
    assert "startsWith(github.ref, 'refs/tags/')" in deep
    assert "pull_request" not in deep

    assert re.search(r"^  schedule:", _workflow(), re.MULTILINE), (
        "the workflow needs a schedule trigger or security-deep never fires"
    )


def test_deep_job_scans_history_and_base_images() -> None:
    """The deep job must cover what the light job structurally cannot."""
    deep = _job("security-deep", "typecheck")
    assert "fetch-depth: 0" in deep, "history scanning needs the full clone"
    assert "detect --source=." in deep
    assert "Dockerfile" in deep and "image" in deep


def test_gitleaksignore_entries_carry_a_dated_reason() -> None:
    """Every allowlisted finding must say when it was assessed and why.

    An undocumented allowlist entry is indistinguishable from a silenced leak.
    """
    assert GITLEAKSIGNORE_PATH.exists(), ".gitleaksignore must exist"
    lines = GITLEAKSIGNORE_PATH.read_text(encoding="utf-8").splitlines()

    entries = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    assert entries, "the allowlist must contain the known false positive"

    comments = "\n".join(ln for ln in lines if ln.lstrip().startswith("#"))
    for entry in entries:
        path = entry.split(":", 1)[0]
        assert path in comments, f"allowlist entry {path} has no explanatory comment"
    assert re.search(r"20\d{2}-\d{2}-\d{2}", comments), "entries must carry a date"


def test_gitleaks_runs_with_a_relative_target() -> None:
    """Fingerprints are `<file>:<rule>:<line>` — the path must be relative.

    Scanning an absolute `/repo` yields `/repo/tests/...` findings, which no
    relative .gitleaksignore entry can ever match, so the allowlist silently
    does nothing and the job fails forever. The first CI run of this job did
    exactly that.
    """
    both = _job("security", "security-deep") + _job("security-deep", "typecheck")
    assert "-w /repo" in both, "gitleaks must run with /repo as the working directory"
    assert "dir /repo" not in both, "scan `.`, not the absolute /repo path"
    assert "--source=/repo" not in both, "scan `.`, not the absolute /repo path"


def test_gitleaksignore_does_not_quote_the_flagged_values() -> None:
    """An allowlist must not contain the secrets it allowlists.

    The first version of this file quoted the fixture value in its own
    explanatory comment, and gitleaks flagged .gitleaksignore itself.
    """
    text = GITLEAKSIGNORE_PATH.read_text(encoding="utf-8")
    assert "ik_test_service" not in text
    assert "abc123def456" not in text
