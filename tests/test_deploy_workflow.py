"""Pin tests for the release e2e gate in deploy.yml (issue #908).

Issue #908 anchors the production e2e validation (docs/runbooks/e2e-production.md)
into the release path as a fail-closed checklist-contract gate: a signal-only
job that refuses to let a release proceed unless the operator recorded the e2e
gate evidence. It deliberately does NOT run Playwright, does NOT hold secrets,
and does NOT validate production — execution stays on the operator's station
per epic #909. These pins follow the string-based assertion style of
tests/test_ci_workflow.py (pyyaml is scanned by the gates, not imported here
beyond scripts/check_workflows.py's own use).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
GATE_JOB_NAME = "release-e2e-gate"
#: The evidence marker name is part of the operator contract: the runbook
#: checklist and this workflow must agree byte-for-byte.
EVIDENCE_MARKER = "APAP_E2E_GATE_EVIDENCE"
#: Auditable bypass syntax: a skip must record a reason, never be silent.
SKIP_PREFIX = "skipped:"
RUNBOOK_PATH = "docs/runbooks/e2e-production.md"


def _job_sections(workflow: str) -> dict[str, str]:
    """Return each top-level job's text without adding a YAML test dependency."""
    jobs = workflow[workflow.index("\njobs:\n") :]
    marks = [
        (match.group(1), match.start())
        for match in re.finditer(r"^  ([a-z][a-z0-9-]+):$", jobs, flags=re.MULTILINE)
    ]
    sections: dict[str, str] = {}
    for index, (name, start) in enumerate(marks):
        end = marks[index + 1][1] if index + 1 < len(marks) else len(jobs)
        sections[name] = jobs[start:end]
    return sections


def _gate_section() -> str:
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")
    return _job_sections(workflow)[GATE_JOB_NAME]


def test_release_e2e_gate_job_exists_and_blocks_deploy() -> None:
    """The gate exists in the release path and deploy cannot silently skip it.

    deploy.yml IS the release flow: it fires on every push to main and on
    manual dispatch. Wiring the gate into deploy's `needs:` means a red gate
    skips deploy — the release cannot proceed without the evidence check
    having passed, mirroring the evidence-job gate.
    """
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")
    sections = _job_sections(workflow)

    assert GATE_JOB_NAME in sections, (
        "deploy.yml must define the release-e2e-gate job in the release path"
    )
    deploy = sections["deploy"]
    assert "needs: [evidence, release-e2e-gate, ui-e2e-gate]" in deploy, (
        "deploy must need the e2e gates alongside evidence, so a failing or "
        "skipped gate blocks the release instead of being skipped silently"
    )


def test_release_e2e_gate_fails_closed_on_missing_evidence() -> None:
    """Absent or empty evidence fails the job loudly; present evidence passes.

    The gate reads the repository variable, and an empty value must produce a
    ::error:: annotation and a nonzero exit. There is no path where missing
    evidence stays green.
    """
    section = _gate_section()

    assert f"vars.{EVIDENCE_MARKER}" in section, (
        f"the gate must read the repository variable {EVIDENCE_MARKER}"
    )
    assert "::error::" in section
    assert "exit 1" in section
    # Fail-closed on emptiness, not on a keyword the value may not contain:
    # the check tests for an empty/unset marker and passes otherwise.
    assert '${APAP_E2E_GATE_EVIDENCE:-}' in section


def test_release_e2e_gate_opt_out_records_a_reason() -> None:
    """The only sanctioned bypass is `skipped:<reason>`, recorded in the workflow.

    Consistent with how the repo treats known exceptions: fail-closed with an
    auditable escape. The syntax is documented in the workflow itself so the
    operator contract lives next to the enforcement.
    """
    section = _gate_section()

    assert SKIP_PREFIX in section, (
        "the workflow must document the skipped:<reason> opt-out syntax"
    )


def test_release_e2e_gate_failure_message_references_runbook() -> None:
    """A red gate must point the operator at the procedure that produces evidence."""
    section = _gate_section()

    assert RUNBOOK_PATH in section


def test_release_e2e_gate_holds_no_secrets_and_runs_no_playwright() -> None:
    """Epic #909: the gate is signal-only — no secrets, no Playwright, no runner.

    If this job ever grows a secret reference or an e2e execution step, the
    design decision behind issue #908 has been violated.
    """
    section = _gate_section()

    assert "secrets." not in section, (
        "the gate must not reference any GitHub Actions secret"
    )
    assert "playwright" not in section.lower(), (
        "the gate must not run Playwright; execution stays on the operator's "
        "station per epic #909"
    )
    assert "docker" not in section.lower(), (
        "the gate must not run anything against the deploy host"
    )
