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
import yaml

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


def test_security_job_runs_on_an_exact_runner() -> None:
    """The scanners run on an exact runner label. Which one has changed twice.

    PR #452 moved the basic gates off the self-hosted VPS to ``ubuntu-latest``, because
    the runner had chronic session-renewal problems that stalled queues. PR #508 pinned
    that to ``ubuntu-24.04`` for Hard Rule 15. This branch moves them back, and not as a
    preference: GitHub-hosted jobs on this account no longer start at all —

        The job was not started because recent account payments have failed or your
        spending limit needs to be increased.

    — arriving as ``runner_id=0``, no steps executed, failure in two seconds. A pinned
    hosted label that cannot be scheduled is not a gate.

    What survives every one of those reversals is the rule itself: the label must be
    exact. `[self-hosted, Linux, ARM64, apap, oracle]` names one specific machine, which
    satisfies that; what it costs is that a VPS accumulates state a hosted image would
    not, and that is the trade being made knowingly.

    Floating labels across ALL workflows are covered by
    test_no_workflow_runs_on_a_floating_runner — this one only pins the security job's
    own runner, which is what it has always done.
    """
    job = _job("security", "security-deep")
    assert "self-hosted" in job, (
        "security job must run on the self-hosted runner: the hosted pool cannot "
        "schedule jobs on this account (issue #519)"
    )
    assert "ubuntu-latest" not in job, (
        "security job must not run on a floating label (Hard Rule 15)"
    )


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


def test_secret_scan_proves_it_scanned_something() -> None:
    """Hard Rule 18: a zero-byte scan is not a clean tree.

    On a runner that is itself a container talking to the host daemon through the
    socket, `docker run -v "$PWD:/repo"` mounts a host path that does not exist. Docker
    creates an empty directory, gitleaks walks it, and reports:

        INF scanned ~0 bytes (0) in 1.99ms
        INF no leaks found

    Green. Observed in access2web-blueprint on this exact digest and command.

    The mount is a deployment concern and gets fixed there. This pins the other half:
    that the gate cannot reach that verdict again whatever the cause — a bad -v, a wrong
    working-directory, a checkout that failed quietly, an over-broad allowlist.

    Note which scanner caught it and which did not. trivy, given the identical broken
    mount, failed loudly because it looks for one named file. gitleaks passed because it
    walks a tree, and an empty tree has no secrets in it. Any gate that inspects a SET
    treats the empty set as success unless someone teaches it otherwise.
    """
    security = _job("security", "security-deep")

    assert "GITLEAKS_MIN_BYTES" in security, (
        "the secret scan must check how many bytes it inspected before accepting its "
        "verdict (issue #519, Hard Rule 18)"
    )
    assert "scanned ~" in security, (
        "the liveness proof must read the volume gitleaks itself reports, not infer it"
    )


def test_secret_scan_names_its_findings() -> None:
    """A count with no subject produces a retreat, not a correction (issue #519).

    Without `-v`, a hit ends the job at "leaks found: 2": no file, no line, no rule, no
    fingerprint. In access2web-blueprint that silence is what made "simplify the
    workflow" and "revert" look like the reasonable next steps — neither of which
    touches the finding. The fingerprint `-v` prints is also exactly what
    `.gitleaksignore` takes, so recording an exception stops requiring a local rerun.
    """
    security = _job("security", "security-deep")
    assert "--redact --no-banner -v" in security, (
        "the secret scan must run with -v so a finding arrives with file, line, rule "
        "and fingerprint"
    )


def test_full_history_scan_proves_it_had_history() -> None:
    """The same contract for `detect`, with the indicator that fits it.

    `detect` walks commits, so an empty history is what "did not run" looks like in this
    mode — and a scan over zero commits reports clean just as convincingly as one over
    ten thousand.
    """
    deep = _workflow()
    assert "rev-list --count" in deep, (
        "the full-history scan must prove it had history to walk before trusting its "
        "verdict (issue #519)"
    )


def test_no_workflow_runs_on_a_floating_runner() -> None:
    """Hard Rule 15, across every workflow rather than one job (issue #520).

    Four workflows sat on `ubuntu-latest` for as long as they have existed — deploy,
    pr-name, pr-size, plus the now-retired insforge-keep-alive (issue #656) — while the only runner check in this
    repository looked at the `security` job alone and stayed green throughout. A pin
    that covers one job of six workflows is a pin of that job, not of the rule.

    Each label is checked on its own, and that detail is load-bearing: `runs-on` is a
    scalar for a hosted runner and a LIST for a self-hosted one. Asking whether
    `str(value).endswith("-latest")` stops being able to fail the moment the first list
    appears, because a list ends in `]` — including `[self-hosted, ubuntu-latest]`.
    Since this repository has just moved to self-hosted labels, a check written the
    other way would have been born disarmed.
    """
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, job in (workflow.get("jobs") or {}).items():
            runs_on = job.get("runs-on", "")
            labels = runs_on if isinstance(runs_on, list) else [runs_on]
            for label in labels:
                if str(label).endswith("-latest"):
                    offenders.append(f"{path.name}::{name} -> {label}")
    assert not offenders, f"jobs on a floating runner label: {offenders}"


_SHA_PIN = re.compile(r"^[0-9a-f]{40}$")


def test_no_workflow_uses_a_floating_action_ref() -> None:
    """Hard Rule 15, action side: every external ``uses:`` is pinned to a 40-hex SHA (issue #527).

    #520 closed the runner half of the rule — every ``runs-on`` is exact, and
    the gate above watches every workflow rather than one job. The action half
    was left open: five third-party action refs in deploy.yml and
    e2e-self-hosted.yml rode moving tags (``@v5`` / ``@v6``) with nothing
    watching them. A tag is third-party code that can change under the workflow
    between two runs that are otherwise identical, and deploy.yml is the file
    that talks to production. The structural defect is the absence of a gate,
    not the absence of a pin: a rule without enforcement erodes.

    The contract the gate enforces:

    * **External third-party actions** (``owner/repo@ref``) must be pinned to
      exactly 40 lowercase hex characters — a commit SHA. Tags (``@v5``),
      branches (``@main``), and any other ref shape fail the gate.
    * **Local actions** (``./...``) and **container actions** (``docker://...``)
      are out of scope by construction: the SHA regex cannot match either
      shape, so they pass without a per-file allowlist. The gate stays
      generic — adding a new workflow, a new local action, or a new
      ``docker://`` step never requires editing this test.
    * **Liveness (Hard Rule 18).** An empty scan — zero ``uses:`` keys found
      across every workflow — fails the gate. A check that scanned nothing
      has proven nothing; "did not run" must never score as "clean".
    * **No trailing junk.** GitHub treats the entire ``uses:`` value as the
      ref, so an inline ``# v5`` after the SHA parses as part of the ref and
      breaks the pin. PyYAML strips YAML comments at parse time, so the
      regex sees only the SHA; a malformed value that survives parsing is
      rejected because its ref portion fails the 40-hex match.

    The SHAs to use are the ones already resolved on main for the same actions
    in ci.yml, pr-name.yml, and pr-size.yml. Issue #527 names them explicitly;
    the pinner's job is to copy those values into the offending workflows.
    This test asserts on the SHAPE, not on the value — a future maintainer
    who re-resolves the SHA for a legitimate reason (e.g. upstream re-tag) does
    not have to touch this test as long as the new ref is also a 40-hex SHA.
    """
    offenders: list[str] = []
    scanned_uses = 0
    for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (workflow.get("jobs") or {}).items():
            for step in (job.get("steps") or []):
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if not isinstance(uses, str) or not uses:
                    continue
                scanned_uses += 1
                # Local actions (`./...`) and `docker://` actions are not
                # third-party action refs. They have no `@`-separated commit,
                # so the SHA regex cannot match them and they pass without a
                # special case. This is the "no brittle allowlist" property.
                action_part, sep, ref = uses.rpartition("@")
                if not sep or not _SHA_PIN.match(ref):
                    offenders.append(
                        f"{path.name}::{job_name}: uses '{uses}' "
                        f"is not pinned to a 40-hex SHA"
                    )
    assert scanned_uses > 0, (
        "no `uses:` keys found across any workflow — the gate scanned nothing. "
        "Either every workflow lost its action refs (rule regression) or the "
        "scan path broke (Hard Rule 18)."
    )
    assert not offenders, (
        f"floating action refs (must be owner/repo@<40-hex SHA>): {offenders}"
    )
