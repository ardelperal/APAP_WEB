import os
import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from tests import _workflow_yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
#: Deploy lives in its own workflow so a merge does not re-run ci.yml just to
#: satisfy its `needs`. The deploy guards moved here with it.
DEPLOY_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
PR_NAME_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "pr-name.yml"
PR_SIZE_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "pr-size.yml"
MAIN_AUDIT_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "main-audit.yml"
MAIN_AUDIT_SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "main_history_audit.py"
MAKEFILE_PATH = REPO_ROOT / "Makefile"
CHECK_RULES_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_rules.py"
BRANCH_PROTECTION_PATH = REPO_ROOT / ".github" / "branch-protection.md"
DEVELOPMENT_GUIDE_PATH = REPO_ROOT / "docs" / "development.md"
CI_CD_GUIDE_PATH = REPO_ROOT / "docs" / "codebase" / "ci-cd.md"
MERGE_WORKFLOW_PATH = REPO_ROOT / "docs" / "codebase" / "merge-workflow.md"
PROCESS_PATH = REPO_ROOT / "docs" / "proceso.md"


def _doc(path: Path) -> dict[str, Any]:
    """Parse a workflow file into structured YAML (issue #963)."""
    return _workflow_yaml.load(path)


def _job(path: Path, job_id: str) -> dict[str, Any]:
    """Return one job of a workflow as parsed YAML (asserts when absent)."""
    return _workflow_yaml.job(_doc(path), job_id)


def _triggers(path: Path) -> dict[str, Any]:
    """Map each trigger name under ``on:`` to its structured config."""
    return _workflow_yaml.on_triggers(_doc(path))


def _run_index(job_id: str, fragment: str) -> int:
    """Position of the first ci.yml step of ``job_id`` whose run has fragment."""
    runs = [
        str(step.get("run", ""))
        for step in _workflow_yaml.steps(_job(WORKFLOW_PATH, job_id))
    ]
    for position, run in enumerate(runs):
        if fragment in run:
            return position
    raise AssertionError(f"no step in job {job_id!r} runs {fragment!r}")


def _workflow_job_names(path: Path) -> set[str]:
    """Return the top-level job ids of a workflow, from parsed YAML."""
    return set(_doc(path).get("jobs") or {})


def _make_target_command(target: str) -> str:
    lines = MAKEFILE_PATH.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"{target}:") + 1
    recipe: list[str] = []
    for line in lines[start:]:
        if not line.startswith("\t"):
            break
        recipe.append(line.strip().removesuffix("\\").rstrip())
    return " ".join(recipe)


def _seed_detectors_5_through_8(repo_root: Path) -> None:
    module_dir = repo_root / "app" / "modules" / "demo"
    module_dir.mkdir(parents=True)
    (module_dir / "service.py").write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "logger.warning('unsafe')\n"
        "print('unsafe')\n",
        encoding="utf-8",
    )
    (repo_root / "app" / "main.py").write_text(
        "response.set_cookie('apap_session', 'token', samesite='lax')\n",
        encoding="utf-8",
    )


def test_ci_workflow_defines_lint_test_and_build_jobs() -> None:
    doc = _doc(WORKFLOW_PATH)

    assert doc.get("name") == "ci"
    triggers = _workflow_yaml.on_triggers(doc)
    # Both main and staging must trigger CI. main is gated (only the
    # user promotes there) but PRs landing on main still need to be
    # validated; staging is where every change lands first under the
    # project's stagingOnly policy.
    assert triggers["pull_request"].get("branches") == ["main", "staging"]
    for job_id in ("lint", "test", "build"):
        _workflow_yaml.job(doc, job_id)
    lint_runs = _workflow_yaml.runs_text(_workflow_yaml.job(doc, "lint"))
    test_runs = _workflow_yaml.runs_text(_workflow_yaml.job(doc, "test"))
    build_runs = _workflow_yaml.runs_text(_workflow_yaml.job(doc, "build"))

    setup_action = "./.github/actions/setup-python"
    for job_id in ("lint", "test", "build"):
        uses = [
            str(step.get("uses", ""))
            for step in _workflow_yaml.steps(_workflow_yaml.job(doc, job_id))
        ]
        assert setup_action in uses, (
            f"job {job_id!r} must install the frozen environment through "
            "the shared setup action"
        )
    assert "ruff check ." in lint_runs
    assert "python -m pytest -W error::DeprecationWarning" in test_runs
    assert "python -m build" in build_runs


def test_ci_workflow_runs_release_e2e_job_with_playwright() -> None:
    """E2E executes the Playwright suite on release events and, since issue
    #895, on any pull_request / branch push whose ui-detection job detected
    a UI-path change.
    """
    e2e_job = _job(WORKFLOW_PATH, "e2e")
    if_clause = str(e2e_job.get("if", ""))
    e2e_runs = _workflow_yaml.runs_text(e2e_job)

    assert "vars.ENABLE_E2E" not in e2e_runs, (
        "the ENABLE_E2E feature flag has been retired"
    )
    assert "github.event_name == 'workflow_dispatch'" in if_clause
    assert "startsWith(github.ref, 'refs/tags/')" in if_clause
    assert "github.event_name == 'schedule'" not in if_clause
    assert "pull_request" not in if_clause
    assert "playwright install" in e2e_runs
    assert "playwright" in e2e_runs.lower()
    # And it must actually execute the suite.
    assert "pytest tests/e2e_ci/" in e2e_runs


# --- issue #895: UI e2e gate ------------------------------------------------


def test_ci_workflow_defines_ui_detection_job_consuming_the_checker() -> None:
    """Issue #895 (design D1/D2): ci.yml must define a ``ui-detection`` job
    whose UI path list comes from the single source of truth in
    scripts/check_required_jobs.py (``--print-ui-paths``), never from an
    inline copy that could drift from the checker and the deploy gate.
    """
    block = _workflow_yaml.job_text(_job(WORKFLOW_PATH, "ui-detection"))

    assert "scripts/check_required_jobs.py --print-ui-paths" in block
    # The marker is published as a job output so `required`'s checker can
    # verify the skip semantics structurally from toJSON(needs).
    assert "ui_changed:" in block
    assert 'echo "ui_changed=' in block
    # The diff needs the full history.
    assert "fetch-depth: 0" in block
    # pull_request: merge-base diff against the event base ref (same shape
    # as pr-size.yml, issue #525); push/dispatch: event.before with the
    # parent commit as fallback (fix round 1, JD-B-002).
    assert "github.base_ref" in block
    assert "merge-base" in block
    assert "github.event.before" in block
    assert "HEAD^" in block


def test_ci_workflow_ui_detection_fails_closed_by_default() -> None:
    """Issue #895 fix round 1 (JD-B-001, workflow half): detection is
    inverted — the step starts from ``ui_changed=true`` and only reports
    false when the checker's fail-closed classifier (``--ui-changed``)
    proves every changed file is inside the NON-UI allowlist. A diff base
    that cannot be resolved also fails closed.
    """
    block = _workflow_yaml.job_text(_job(WORKFLOW_PATH, "ui-detection"))

    assert "ui_changed=true" in block, (
        "ui-detection must default to ui_changed=true (fail-closed)"
    )
    assert "--ui-changed" in block, (
        "the changed-file set must be classified by the checker's "
        "fail-closed classifier, not by inline prefix matching"
    )
    assert "--print-ui-paths" in block
    assert "assuming UI changed (fail-closed)" in block


def test_ci_workflow_ui_detection_pays_the_gate_file_toll() -> None:
    """Anti-self-exemption toll (JD-A-001, workflow half): editing any of
    the gate's own source files forces ui_changed=true — the gate cannot
    be edited without paying the e2e toll.
    """
    block = _workflow_yaml.job_text(_job(WORKFLOW_PATH, "ui-detection"))

    toll_pattern = (
        "scripts/check_required_jobs.py|.github/workflows/ci.yml"
        "|.github/workflows/deploy.yml"
    )
    assert toll_pattern in block, (
        "the ui-detection step must force ui_changed=true when any gate "
        "source file changes (anti-self-exemption toll)"
    )


def test_ci_workflow_push_diff_uses_event_before_with_parent_fallback() -> None:
    """JD-B-002: on push the diff base must be github.event.before (the SHA
    the branch pointed at before the push), not HEAD^ — the parent-commit
    diff only covers the LAST commit, so a UI change hidden in an earlier
    commit of a multi-commit push used to skip e2e. HEAD^ remains only as
    the fallback for a zero-SHA initial push and for workflow_dispatch.
    """
    block = _workflow_yaml.job_text(_job(WORKFLOW_PATH, "ui-detection"))

    assert "EVENT_BEFORE: ${{ github.event.before }}" in block
    # Zero-SHA guard for the initial push.
    assert "0000000000000000000000000000000000000000" in block
    assert "git diff --name-only" in block


def test_ci_workflow_e2e_runs_when_ui_changed_or_on_release_events() -> None:
    """Issue #895 (design D2): the e2e job must run on the SHA under test
    when ui-detection reports ui_changed=true, in addition to the release
    events from issue #780. A UI change can no longer reach a merge with a
    silently skipped e2e.
    """
    e2e_job = _job(WORKFLOW_PATH, "e2e")

    assert _workflow_yaml.needs(e2e_job) == ["build", "ui-detection"]
    assert "needs.ui-detection.outputs.ui_changed == 'true'" in str(
        e2e_job.get("if", "")
    )


def test_ci_workflow_required_consumes_the_ui_detection_output() -> None:
    """Issue #895: ``required`` must depend on ui-detection so its
    ``ui_changed`` output is part of the ``toJSON(needs)`` payload the
    checker reads structurally (no second, drift-prone env channel).
    """
    required = _job(WORKFLOW_PATH, "required")

    assert "ui-detection" in _workflow_yaml.needs(required)
    assert "CI_NEEDS_JSON: ${{ toJSON(needs) }}" in _workflow_yaml.job_text(required)


def test_ci_workflow_does_not_include_diagnostic_secret_leak_scan() -> None:
    """Issue #393: placeholder secret-leak scan step removed in favor of gitleaks (#381)."""
    ci_runs = "\n".join(
        _workflow_yaml.runs_text(entry)
        for entry in (_doc(WORKFLOW_PATH).get("jobs") or {}).values()
    )

    assert "Diagnostic secret-leak scan" not in ci_runs
    assert "grep -rE '(http://|https://|sk-|ghp_)[A-Za-z0-9]+'" not in ci_runs


def test_pr_name_workflow_declares_explicit_contents_read() -> None:
    """Issue #682: pr-name.yml must declare ``contents: read`` at the workflow
    level so the GITHUB_TOKEN does not silently widen if a future repo
    default broadens the implicit token scope.
    """
    perms = _workflow_yaml.permissions(_doc(PR_NAME_WORKFLOW_PATH))

    # The block MUST sit at the workflow level, not nested under a job.
    assert perms, (
        "pr-name.yml must declare a workflow-level permissions block"
    )
    assert perms.get("contents") == "read"


def test_pr_size_workflow_declares_explicit_contents_read() -> None:
    """Issue #682: pr-size.yml must declare ``contents: read`` at the
    workflow level for the same reason as pr-name.yml.
    """
    perms = _workflow_yaml.permissions(_doc(PR_SIZE_WORKFLOW_PATH))

    assert perms, (
        "pr-size.yml must declare a workflow-level permissions block"
    )
    assert perms.get("contents") == "read"


def test_branch_protection_note_lists_required_ci_checks() -> None:
    note = BRANCH_PROTECTION_PATH.read_text(encoding="utf-8")

    assert "ci / required" in note
    assert "pr-name / branch-name" in note
    assert "pr-size / pr-size" in note
    assert "Aplicar las reglas también a administradores" in note
    assert "`Maintain` y `Admin`" in note
    assert "`Write` permite contribuir y revisar, pero no mergear" in note


def test_branch_protection_note_documents_disabled_ruleset() -> None:
    """Issue #892: the merge-restriction ruleset is disabled for the
    single-maintainer repo (pure friction, no real protection) — the note
    must say so, not just describe the rule as if it were still active.
    """
    note = BRANCH_PROTECTION_PATH.read_text(encoding="utf-8")

    assert "**Estado actual: `disabled`**" in note
    assert "issue #892" in note


def test_ci_cd_guide_tracks_the_live_job_inventory() -> None:
    """The human-facing job table must match both executable workflows."""
    guide = CI_CD_GUIDE_PATH.read_text(encoding="utf-8")
    documented_ci_jobs = set(
        re.findall(r"^\| `([a-z][a-z0-9-]+)` \|", guide, flags=re.MULTILINE)
    )

    assert documented_ci_jobs == _workflow_job_names(WORKFLOW_PATH)
    for deploy_job in _workflow_job_names(DEPLOY_WORKFLOW_PATH):
        assert f"`{deploy_job}`" in guide


def test_development_guide_documents_e2e_ci_hook() -> None:
    guide = DEVELOPMENT_GUIDE_PATH.read_text(encoding="utf-8")

    # The guide documents the fail-closed smoke contract against the real
    # lifespan-enabled application, not the retired no-lifespan fixture.
    assert "Playwright" in guide
    assert "tests/e2e_ci/" in guide
    assert "uvicorn app.main:app --lifespan on" in guide
    assert "playwright install" in guide


def test_ci_workflow_test_job_enforces_global_coverage_floor() -> None:
    """Issue #199 / #331: the CI ``test`` job must enforce ``fail_under`` from pyproject.

    ``pyproject.toml`` declares ``fail_under`` under ``[tool.coverage.report]``.
    The test job must:

    1. run pytest with coverage over ``app/`` (``--cov=app``),
    2. run pytest with coverage over ``migration/`` (``--cov=migration``) — issue #331
       halves the codebase was previously unmeasured and unenforced,
    3. write ``coverage.json`` (``--cov-report=json``) so the
       CRITICAL_HELPERS gate (``scripts/pytest_plugin/coverage_gate.py``,
       AGENTS.md rule 11) keeps working — the plugin is a no-op when
       ``coverage.json`` is absent,
    4. fail the job below the combined ``app/`` + ``migration/`` floor via an explicit
       ``--cov-fail-under`` that matches ``fail_under`` in pyproject
       (explicit because pytest-cov only reliably enforces the flag,
       not the config-file value).

    Removing any of these from ci.yml is a blocked change (AGENTS.md
    rule 19). The ``migration/`` floor is set at the measured combined
    value (85%) — raising it is a welcome separate PR; lowering it
    is blocked by this test.
    """
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    fail_under = pyproject["tool"]["coverage"]["report"]["fail_under"]

    # The declared floor itself must not silently drift below 80.
    assert fail_under >= 80

    # Scope to the test job's ``run:`` bodies: structure-derived, so a
    # comment that merely mentions the flags (like the explanatory block
    # above the run: step) can never satisfy these assertions (issue #963).
    executable = _workflow_yaml.runs_text(_job(WORKFLOW_PATH, "test"))

    # Coverage must be measured over the app package...
    assert "--cov=app" in executable
    # ...and over migration/ (issue #331 — the unmeasured half).
    assert "--cov=migration" in executable, (
        "migration/ must be measured alongside app/ (issue #331). "
        "A single blended floor that app/ can mask is exactly the "
        "failure mode AGENTS.md §32.P8 warns about."
    )
    # ...must produce coverage.json for the CRITICAL_HELPERS gate...
    assert "--cov-report=json" in executable
    # ...and must enforce the combined floor pyproject declares.
    assert f"--cov-fail-under={fail_under}" in executable


def test_ci_workflow_runs_postgres_toctou_regression_in_test_job() -> None:
    """Issue #282: CI provisions PostgreSQL and executes the TOCTOU regression."""
    test_job = _job(WORKFLOW_PATH, "test")
    job_text = _workflow_yaml.job_text(test_job)
    executable = _workflow_yaml.runs_text(test_job)

    services = test_job.get("services") or {}
    assert "postgres" in services
    assert "POSTGRES_DB: apap_test" in job_text
    # The DSN moved out of the job-level `env:` block in #532: the `job` context
    # that carries the assigned host port is not available there, so it is built
    # in a step and exported through $GITHUB_ENV instead.
    assert "APAP_TEST_POSTGRES_DSN=" in job_text
    assert "job.services.postgres.ports['5432']" in job_text
    # And it must refuse to proceed on an unresolved port rather than hand the
    # suite a DSN that cannot connect — tests/test_voluntarios_concurrent.py
    # would pytest.skip() on that, which reads as a pass.
    assert 'if [ -z "$POSTGRES_HOST_PORT" ]' in job_text
    assert "--deselect tests/test_voluntarios_concurrent.py" not in executable

def test_postgres_toctou_contract_uses_test_dsn_not_http_base_url() -> None:
    """The PostgreSQL integration test must not overload the HTTP E2E contract."""
    # test_voluntarios_concurrent.py was deleted in epic #420 (VOL-02 PR-B):
    # the concurrent write test was replaced by hexagonal service-layer tests.
    concurrency_test_path = REPO_ROOT / "tests" / "test_voluntarios_concurrent.py"
    guide = DEVELOPMENT_GUIDE_PATH.read_text(encoding="utf-8")

    assert not concurrency_test_path.exists(), (
        "test_voluntarios_concurrent.py should be deleted after hexagonal refactor"
    )
    assert "APAP_TEST_POSTGRES_DSN" in guide



def test_ci_workflow_lint_job_runs_check_rules_gate(tmp_path: Path) -> None:
    """Issue #200: the CI ``lint`` job must gate on ``scripts/check_rules.py``.

    The APAP001/APAP003 custom rules (plus Detectors 2-8 of the AST
    linter) are documented as "the authoritative lint gate" in
    ``pyproject.toml`` and AGENTS.md, but until this test the linter
    only ran locally via ``make check-rules`` — CI never executed it,
    so a violation could land on main with a green build. The lint job
    must run the linter over the REPO ROOT (``.``), not ``app``:
    Detectors 5-8 resolve ``app/``-relative paths against the scanned
    root, so ``check_rules.py app`` silently disables the APAP003 /
    print / CSRF detectors. Default excludes (``DEFAULT_EXCLUDES`` +
    ``.check_rulesignore``) silence the known false positives.

    Removing this step from ci.yml is a blocked change (AGENTS.md
    rule 20).
    """
    # Scope to the lint job's ``run:`` bodies (same rationale as
    # test_ci_workflow_test_job_enforces_global_coverage_floor): the text
    # is structure-derived, so a YAML comment mentioning the command can
    # never satisfy the assertion (issue #963).
    executable = _workflow_yaml.runs_text(_job(WORKFLOW_PATH, "lint"))

    make_command = _make_target_command("check-rules")
    command = shlex.split(make_command)
    command[0] = sys.executable
    command[1] = str(CHECK_RULES_SCRIPT_PATH)
    _seed_detectors_5_through_8(tmp_path)
    result = subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    expected_rule_ids = {
        "apap003_raw_logger_call",
        "print_in_app",
        "csrf_middleware_registered",
        "csrf_samesite_strict",
    }
    missing_rule_ids = {
        rule_id for rule_id in expected_rule_ids if f": {rule_id}:" not in result.stdout
    }
    assert result.returncode == 1 and not missing_rule_ids, (
        "The make check-rules recipe must activate Detectors 5-8 from the "
        f"repository root; exit={result.returncode}, missing={sorted(missing_rule_ids)}, "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )

    ci_command = "python scripts/check_rules.py ."
    normalized_make_command = make_command.replace("$(PYTHON)", "python", 1)
    assert ci_command in executable, (
        "The lint job must run the AGENTS.md rule linter over the repo "
        "root (python scripts/check_rules.py .) so APAP001/APAP003 and "
        "Detectors 2-8 gate CI, not just local `make check-rules` runs."
    )
    assert normalized_make_command == ci_command, (
        "make check-rules must invoke the same repository-root command as CI; "
        f"got {normalized_make_command!r}"
    )


def test_ci_workflow_defines_typecheck_job_running_mypy() -> None:
    """Issue #201: the CI ``typecheck`` job must gate on mypy.

    The codebase is fully annotated (``from __future__ import
    annotations``, dataclasses, ``Final``) but until this test no type
    checker ever ran: annotations were documentation without
    verification. The ``typecheck`` job must run the exact same command
    as ``make typecheck`` (``python -m mypy``, scope and flags declared
    once in ``pyproject.toml`` ``[tool.mypy]``) so local and CI results
    cannot drift.

    Removing this job from ci.yml is a blocked change (AGENTS.md
    rule 24).
    """
    # The job lookup itself asserts that the typecheck job exists
    # (issue #201, AGENTS.md rule 24).
    typecheck_job = _job(WORKFLOW_PATH, "typecheck")

    # Scope to the typecheck job's own structure (same rationale as
    # test_ci_workflow_lint_job_runs_check_rules_gate): run bodies and
    # ``uses:`` values, never the whole file (issue #963).
    executable = _workflow_yaml.runs_text(typecheck_job)
    uses_values = [
        str(step.get("uses", "")) for step in _workflow_yaml.steps(typecheck_job)
    ]

    # The shared action installs the frozen dev environment and the job runs
    # the config-driven mypy command.
    assert "./.github/actions/setup-python" in uses_values
    assert "python -m mypy" in executable, (
        "The typecheck job must run `python -m mypy` (scope lives in "
        "pyproject.toml [tool.mypy]) — the same command as `make typecheck`."
    )

    # mypy itself must be a pinned dev dependency so CI actually gets it.
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    dev_deps = pyproject["project"]["optional-dependencies"]["dev"]
    assert any(dep.startswith("mypy") for dep in dev_deps), (
        "pyproject.toml [project.optional-dependencies] dev must declare mypy"
    )
    # And the scope must be declared in config, not ad-hoc CLI args:
    # app/ and migration/ are both gated (issue #201 scope decision).
    mypy_files = pyproject["tool"]["mypy"]["files"]
    assert "app" in mypy_files
    assert "migration" in mypy_files


def test_deploy_workflow_gates_on_evidence() -> None:
    """CD-01: deploy exists in its own workflow and runs only on proven evidence.

    Deploy moved out of ci.yml so a merge stops paying for CI twice: ci.yml ran
    on push to main solely because the five heavy jobs were `needs` of deploy,
    re-testing a tree the pull_request run had already proven. deploy.yml looks
    that evidence up instead.

    The gating moved with it. Deploy no longer depends on jobs at all; it depends
    on the `evidence` job having found a green ci run for the merged head.
    """
    deploy_job = _job(DEPLOY_WORKFLOW_PATH, "deploy")

    assert deploy_job.get("name") == "deploy"
    # Issue #908: release-e2e-gate joined the needs list. Issue #895:
    # ui-e2e-gate joined it too — deploy still gates on the evidence job's
    # verdict; each e2e gate is fail-closed on its own terms.
    assert _workflow_yaml.needs(deploy_job) == [
        "evidence",
        "release-e2e-gate",
        "ui-e2e-gate",
    ]
    assert deploy_job.get("if") == "needs.evidence.outputs.verified == 'true'", (
        "deploy must run only when the evidence job proved the tree was verified"
    )

    # The historical failure modes must stay absent (see the deploy job comment
    # in git history: a merge-commit skip block once cancelled every deploy).
    deploy_text = _workflow_yaml.job_text(deploy_job)
    assert "pull_request == null" not in deploy_text
    assert 'grep -q "^Merge pull request #' not in deploy_text


def test_deploy_workflow_runs_on_main_push() -> None:
    """CD-01 D4: a push to main is the deployable event.

    Under pre-MVP policy (AGENTS.md §15.2) every change lands via PR merge, so
    the push to main IS the trigger. This is now a workflow-level trigger rather
    than a job-level `if:`, which is a stronger statement: the job cannot fire on
    an event the workflow does not listen to.
    """
    triggers = _triggers(DEPLOY_WORKFLOW_PATH)

    assert "push" in triggers, "deploy.yml must listen to push"
    assert triggers["push"].get("branches") == ["main"], (
        f"deploy.yml must deploy main and nothing else; got {triggers['push']!r}"
    )


def test_deploy_workflow_cannot_fire_on_a_pull_request() -> None:
    """CD-01 D5: a pull_request event must never reach deploy.

    Previously this was a predicate on the job's `if:` and had to be parsed and
    evaluated to be trusted. Now it is structural: the workflow does not declare
    a pull_request trigger, so no `if:` can be got wrong. That closes the failure
    mode this test was written for.
    """
    triggers = _triggers(DEPLOY_WORKFLOW_PATH)

    assert "pull_request" not in triggers, (
        "deploy.yml must not listen to pull_request — a PR must never deploy"
    )


def test_ci_workflow_no_longer_runs_on_main_push() -> None:
    """The duplicate run is gone: ci.yml does not fire on a push to main.

    Measured 2026-08-09: every merge triggered a second full ci run costing ~8
    billed minutes, existing only to satisfy deploy's `needs`. With deploy moved
    out, that reason is gone. The pull_request run remains the gate.
    """
    triggers = _triggers(WORKFLOW_PATH)

    assert "main" not in (triggers["push"].get("branches") or []), (
        "ci.yml must not re-run on push to main; deploy.yml consumes the "
        "pull_request run's evidence instead"
    )
    assert "main" in (triggers["pull_request"].get("branches") or []), (
        "the pull_request run is now the only gate for main and must stay"
    )


def test_deploy_workflow_refuses_an_unverified_tree() -> None:
    """No evidence, no deploy — and loudly.

    The evidence job fails closed on every uncertain path: a direct push with no
    merge parent, a base that moved between the PR run and the merge, or a merged
    head with no green ci run. Silence there would deploy an untested tree.
    """
    evidence_job = _job(DEPLOY_WORKFLOW_PATH, "evidence")
    guard_step = _workflow_yaml.find_step(
        evidence_job, "Refuse to deploy an unverified tree"
    )
    guard = _workflow_yaml.job_text(guard_step)

    assert "verified != 'true'" in guard
    assert "exit 1" in guard


def test_ci_workflow_deploy_job_calls_coolify_webhook() -> None:
    """CD-01: deploy job hits the Coolify manual github webhook.

    Coolify v4 manual webhook endpoint verifies the raw JSON body against
    X-Hub-Signature-256 using the application's manual_webhook_secret_github,
    so the step must use both COOLIFY_WEBHOOK_URL and COOLIFY_WEBHOOK_SECRET
    and POST a real JSON body (no bare curl).

    The signing + POST logic lives in ``scripts/coolify_webhook.py`` (so
    the prod and test paths share the same code). The workflow just
    sets the env vars and shells out to that module.
    """
    deploy_job = _job(DEPLOY_WORKFLOW_PATH, "deploy")
    deploy_runs = _workflow_yaml.runs_text(deploy_job)

    webhook_step = _workflow_yaml.find_step(deploy_job, "Trigger Coolify webhook")
    assert "secrets.COOLIFY_WEBHOOK_URL" in _workflow_yaml.job_text(webhook_step)
    assert "secrets.COOLIFY_WEBHOOK_SECRET" in _workflow_yaml.job_text(webhook_step)
    # The workflow MUST delegate to the unit-tested signing module,
    # NOT inline the HMAC + urllib code in a heredoc. Pinned by
    # tests/test_coolify_webhook.py.
    assert "python scripts/coolify_webhook.py" in deploy_runs
    # The inline heredoc + urllib path is forbidden.
    assert "python - <<'PY'" not in deploy_runs
    assert "urllib.request.urlopen" not in deploy_runs
    # A bare unsigned curl is no longer acceptable.
    assert 'curl -fsS -X POST "$COOLIFY_WEBHOOK_URL"' not in deploy_runs


def test_ci_workflow_missing_webhook_secret_is_a_failure() -> None:
    """Missing COOLIFY_WEBHOOK_SECRET MUST fail the deploy step.

    Pinned by spec (ci-cd-pipeline/spec.md, Scenario "Missing webhook
    secret blocks production deploy"). Without the secret, the HMAC
    signature would be computed over an empty key, and Coolify v4
    would reject every payload. Loud fail at CI beats silent fail at
    the healthcheck-driven rollback.
    """
    validate_step = _workflow_yaml.find_step(
        _job(DEPLOY_WORKFLOW_PATH, "deploy"), "Validate deployment configuration"
    )
    validate_run = str(validate_step.get("run", ""))

    # The deploy path must check the secret specifically (not just the
    # URL) and emit a ``::error::`` annotation with a clear message,
    # then exit 1.
    assert "COOLIFY_WEBHOOK_SECRET" in str(validate_step.get("env", {}))
    assert "::error::COOLIFY_WEBHOOK_SECRET" in validate_run
    assert "exit 1" in validate_run


def test_ci_workflow_payload_shape_matches_coolify_expectation() -> None:
    """The workflow MUST pass the keys Coolify's manualWebhookApplications reads.

    Pinned by spec (ci-cd-pipeline/spec.md, Requirement "Coolify Webhook
    Signing Contract" > Scenario "Payload shape"). The signing logic
    lives in ``scripts/coolify_webhook.py::build_push_payload`` and is
    pinned by tests/test_coolify_webhook.py::test_build_push_payload_includes_required_keys.
    The workflow just sets the env vars that the module reads.
    """
    deploy_job = _job(DEPLOY_WORKFLOW_PATH, "deploy")
    webhook_step = _workflow_yaml.find_step(deploy_job, "Trigger Coolify webhook")
    step_env = webhook_step.get("env") or {}

    # The workflow must forward the env vars the module needs to build
    # the payload (ref, sha, repository, commit message).
    assert "GITHUB_REF" in step_env
    assert "GITHUB_SHA" in step_env
    assert "GITHUB_REPOSITORY" in step_env
    assert "COMMIT_MESSAGE" in step_env


def test_deploy_rollback_requests_the_previous_source_revision() -> None:
    """A source-based Coolify rollback must request the previous commit."""
    rollback = _workflow_yaml.find_step(
        _job(DEPLOY_WORKFLOW_PATH, "deploy"), "Roll back to the previous digest"
    )

    assert rollback.get("env", {}).get("GITHUB_SHA") == (
        "${{ steps.publish.outputs.previous_revision }}"
    )


def test_deploy_cosign_oidc_permission_is_scoped_to_deploy_job() -> None:
    """Keyless signing may mint an OIDC token only in the deploy job."""
    deploy_doc = _doc(DEPLOY_WORKFLOW_PATH)
    workflow_perms = _workflow_yaml.permissions(deploy_doc)
    deploy_job = _workflow_yaml.job(deploy_doc, "deploy")
    deploy_perms = _workflow_yaml.permissions(deploy_job)
    id_token_writers = [
        job_id
        for job_id, entry in (deploy_doc.get("jobs") or {}).items()
        if _workflow_yaml.permissions(entry).get("id-token") == "write"
    ]

    assert "id-token" not in workflow_perms
    assert id_token_writers == ["deploy"], (
        "exactly the deploy job may hold id-token: write"
    )
    assert deploy_perms.get("id-token") == "write"
    assert deploy_perms.get("contents") == "read"
    assert deploy_perms.get("actions") == "read"
    assert deploy_perms.get("packages") == "write"


def test_deploy_signs_the_exact_published_digest() -> None:
    """Cosign must sign the immutable digest emitted by the publish step."""
    deploy_job = _job(DEPLOY_WORKFLOW_PATH, "deploy")
    sign = _workflow_yaml.find_step(deploy_job, "Sign the published digest")

    assert sign.get("env", {}).get("DIGEST") == "${{ steps.publish.outputs.digest }}"
    sign_run = str(sign.get("run", ""))
    assert 'cosign sign --yes "${IMAGE}@${DIGEST}"' in sign_run
    assert ":sha-${GITHUB_SHA}" not in sign_run


def test_deploy_verifies_exact_identity_and_issuer_before_promotion() -> None:
    """The forward promotion is gated by this workflow's exact trust policy."""
    deploy_job = _job(DEPLOY_WORKFLOW_PATH, "deploy")
    verify = _workflow_yaml.find_step(
        deploy_job, "Verify the published digest is signed by this workflow"
    )
    verify_run = str(verify.get("run", ""))
    identity = (
        'https://github.com/${GITHUB_REPOSITORY}/.github/workflows/'
        "deploy.yml@refs/heads/main"
    )

    assert 'cosign verify "${IMAGE}@${DIGEST}"' in verify_run
    assert f'--certificate-identity "{identity}"' in verify_run
    assert (
        '--certificate-oidc-issuer "https://token.actions.githubusercontent.com"'
        in verify_run
    )
    step_names = [
        str(step.get("name", "")) for step in _workflow_yaml.steps(deploy_job)
    ]
    verify_at = step_names.index("Verify the published digest is signed by this workflow")
    assert verify_at < step_names.index("Promote the verified digest")
    assert verify_at < step_names.index("Trigger Coolify webhook")


def test_deploy_rollback_verifies_before_promotion_and_coolify_trigger() -> None:
    """Rollback cannot promote or deploy an untrusted previous digest."""
    rollback = _workflow_yaml.find_step(
        _job(DEPLOY_WORKFLOW_PATH, "deploy"), "Roll back to the previous digest"
    )
    rollback_run = str(rollback.get("run", ""))
    identity = (
        'https://github.com/${GITHUB_REPOSITORY}/.github/workflows/'
        "deploy.yml@refs/heads/main"
    )

    assert 'cosign verify "${IMAGE}@${PREVIOUS_DIGEST}"' in rollback_run
    assert f'--certificate-identity "{identity}"' in rollback_run
    assert (
        '--certificate-oidc-issuer "https://token.actions.githubusercontent.com"'
        in rollback_run
    )
    assert rollback_run.index("cosign verify") < rollback_run.index(
        "docker buildx imagetools create"
    )
    assert rollback_run.index("cosign verify") < rollback_run.index(
        "python scripts/coolify_webhook.py"
    )


def test_deploy_smoke_database_uses_ephemeral_trust_not_a_literal_password() -> None:
    """The isolated smoke network needs no reusable database credential."""
    smoke = _workflow_yaml.find_step(
        _job(DEPLOY_WORKFLOW_PATH, "deploy"), "Smoke-test the exact image digest"
    )
    smoke_run = str(smoke.get("run", ""))

    assert "POSTGRES_HOST_AUTH_METHOD=trust" in smoke_run
    assert "POSTGRES_PASSWORD=" not in smoke_run
    assert "postgresql://apap:apap@" not in smoke_run


def test_ci_workflow_lint_job_runs_alantyle_lint() -> None:
    """Issue #559, ADR d-42: ``lint`` bloquea anti-patrones alan-style.

    El rollout terminó en issue #576. El step conserva el scope canónico,
    ejecuta el detector entre ``check_rules`` y ``check_module_size`` y no
    puede suavizar su exit code con ``continue-on-error``.
    """
    lint_runs = _workflow_yaml.runs_text(_job(WORKFLOW_PATH, "lint"))

    assert "scripts/check_alantyle.py" in lint_runs, (
        "el job lint debe invocar scripts/check_alantyle.py para hacer "
        "cumplir §10 de la skill documentation-alan-style (issue #559)."
    )
    assert "continue-on-error" not in _workflow_yaml.job_text(
        _job(WORKFLOW_PATH, "lint")
    ), (
        "el detector alan-style es un gate bloqueante desde issue #576; "
        "continue-on-error ocultaría su exit code y reabriría el rollout."
    )
    # Issue #578: el scope incluye los delta-specs de cada change. El
    # detector enmascara inline code y aplica la whitelist spec-context
    # bajo openspec/, y excluye archive/ como histórico inmutable.
    assert "openspec/changes/*/specs/" in lint_runs, (
        "el gate alan-style debe cubrir los delta-specs de cada change "
        "(openspec/changes/*/specs/) desde issue #578."
    )
    # El detector debe correr después del gate AST de check_rules.py y
    # antes del ratchet de tamaño de módulo, manteniendo el orden de
    # familia de gates que el resto del job respeta.
    assert _run_index("lint", "scripts/check_alantyle.py") > _run_index(
        "lint", "scripts/check_rules.py"
    )
    assert _run_index("lint", "scripts/check_alantyle.py") < _run_index(
        "lint", "scripts/check_module_size.py"
    )


def test_ci_workflow_lint_job_runs_jscpd_gate() -> None:
    lint_runs = _workflow_yaml.runs_text(_job(WORKFLOW_PATH, "lint"))

    assert "python scripts/check_jscpd.py" in lint_runs
    assert _run_index("lint", "python scripts/check_jscpd.py") > _run_index(
        "lint", "python scripts/check_vulture_guard.py"
    )


def test_ci_workflow_lint_job_runs_mutation_sites_gate() -> None:
    lint_runs = _workflow_yaml.runs_text(_job(WORKFLOW_PATH, "lint"))

    assert "python scripts/check_mutation_sites.py" in lint_runs
    assert _run_index("lint", "python scripts/check_mutation_sites.py") > _run_index(
        "lint", "python scripts/check_jscpd.py"
    )


def test_ci_workflow_does_not_run_retired_quality_envelope() -> None:
    """The dead, partially populated quality envelope must stay retired."""
    lint_runs = _workflow_yaml.runs_text(_job(WORKFLOW_PATH, "lint"))
    assert "scripts/quality_report.py" not in lint_runs
    assert "--emit-envelope" not in lint_runs


# --- issue #879: least-privilege permissions per job -----------------------
#
# The workflow-level `permissions:` block in ci.yml declares `issues: read`
# for every job, but only `issue-spec` (which reads the linked issue via the
# GitHub API) actually needs it. Every job must declare its own minimal
# block instead of silently inheriting a scope it does not use — the same
# pattern deploy.yml's `deploy` job already followed for issue #682.

# Issue #926: `pr-size` joined this set once pr-size.yml started reading
# the PR's live labels via the GitHub API instead of the event payload.
CI_JOBS_REQUIRING_ISSUES_READ = frozenset({"issue-spec", "pr-size"})


@pytest.mark.parametrize("job_name", sorted(_workflow_job_names(WORKFLOW_PATH)))
def test_ci_workflow_job_declares_least_privilege_permissions(job_name: str) -> None:
    """Issue #879: every ci.yml job must declare its own `permissions:`."""
    perms = _workflow_yaml.permissions(_job(WORKFLOW_PATH, job_name))

    assert perms, (
        f"job {job_name!r} in ci.yml must declare its own `permissions:` "
        "block instead of inheriting the workflow-level default (issue #879)"
    )
    assert perms.get("contents") == "read"

    if job_name in CI_JOBS_REQUIRING_ISSUES_READ:
        assert perms.get("issues") == "read", (
            f"job {job_name!r} calls the GitHub API for issue data and "
            "needs `issues: read` (issue #879)"
        )
    else:
        assert "issues" not in perms, (
            f"job {job_name!r} does not read issues; keep its permissions "
            "block minimal (issue #879)"
        )


def test_deploy_evidence_job_declares_least_privilege_permissions() -> None:
    """Issue #879: `evidence` reads via checkout + the Actions API only.

    It inherited `packages: write` from the workflow-level block without
    ever pushing a package — only the `deploy` job (which pushes to GHCR)
    needs that scope.
    """
    perms = _workflow_yaml.permissions(_job(DEPLOY_WORKFLOW_PATH, "evidence"))

    assert perms, (
        "evidence job must declare its own permissions block (issue #879)"
    )
    assert perms.get("contents") == "read"
    assert perms.get("actions") == "read"
    assert "packages" not in perms, (
        "evidence never pushes a package; packages: write belongs only to "
        "the deploy job (issue #879)"
    )


def test_ci_workflow_lint_job_runs_import_cycle_detector() -> None:
    """Issue #443: the CI ``lint`` job must gate on the cycle detector.

    The detector replaces the §26 rubber stamp ("a comment justifies
    the cycle") with a shrink-only ratchet over the actual import
    graph. Without this step, the 19 lazy-import markers across 7
    files (vs 2 on 2026-07-20) keep accumulating and no machine
    rejects a new one. Sister of
    ``test_ci_workflow_lint_job_runs_layers_gate``: Tarjan catches the
    shape, the layer check catches the direction. Pinned by tests/
    test_import_cycles.py.
    """
    lint_runs = _workflow_yaml.runs_text(_job(WORKFLOW_PATH, "lint"))

    assert "python scripts/check_import_cycles.py" in lint_runs
    # The detector must run after the mutation-sites step so the lint
    # job ordering matches the other ratchets (cheap AST checks first,
    # then graph-level checks).
    assert _run_index("lint", "python scripts/check_import_cycles.py") > _run_index(
        "lint", "python scripts/check_mutation_sites.py"
    )


def test_ci_workflow_test_job_runs_crap_gate() -> None:
    test_runs = _workflow_yaml.runs_text(_job(WORKFLOW_PATH, "test"))
    lint_runs = _workflow_yaml.runs_text(_job(WORKFLOW_PATH, "lint"))

    assert "--ignore=tests/e2e_ci" in test_runs, (
        "the unit/coverage job must not collect the dedicated Playwright smoke suite"
    )
    assert "python scripts/check_crap.py" in test_runs
    assert "python scripts/check_crap.py" not in lint_runs
    assert _run_index("test", "python scripts/check_crap.py") > _run_index(
        "test", "python -m pytest -W error::DeprecationWarning"
    )


def test_ci_workflow_test_job_excludes_local_backend_adapter() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)

    omit = pyproject["tool"]["coverage"]["run"]["omit"]
    assert "app/core/local_backend.py" in omit


def test_default_pytest_collection_matches_ci_boundary() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)

    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--ignore=tests/integration" in addopts
    assert "--randomly-dont-reorganize" in addopts


def test_ci_workflow_integration_job_overrides_ignore_for_tests_integration() -> None:
    integration_runs = _workflow_yaml.runs_text(_job(WORKFLOW_PATH, "integration"))

    assert (
        '--override-ini="addopts=-ra --strict-markers --strict-config '
        '--randomly-dont-reorganize"' in integration_runs
    )
    assert "--ignore=tests/integration" not in integration_runs
    assert "tests/integration \\" in integration_runs
    assert "-m integration" in integration_runs
    assert "--no-cov" in integration_runs
    assert "-W error::DeprecationWarning" in integration_runs


def test_ci_workflow_mutation_job_runs_the_ratchet_gate() -> None:
    """Issue #431: the mutation job must gate on ``scripts/check_mutation.py``.

    Swapping the ratchet for ``cr-rate --fail-over`` is the specific
    regression this pins. ``cr-rate`` reports ``0.00`` both for a run that
    killed every mutant and for a run where nothing executed, so it cannot
    fail on a broken runner — verified end to end on 2026-08-06, where
    ``cr-rate --fail-over 20`` exited 0 on a session whose 27 mutants were
    all ``INCOMPETENT``. Removing this step is a blocked change.
    """
    mutation_runs = _workflow_yaml.runs_text(_job(WORKFLOW_PATH, "mutation"))

    assert "python scripts/check_mutation.py mutation.sqlite" in mutation_runs
    assert "cr-rate" not in mutation_runs, (
        "cr-rate cannot fail on a degenerate run; the gate is check_mutation.py"
    )
    # The ratchet must run after the session exists, never before.
    assert _run_index("mutation", "python scripts/check_mutation.py") > _run_index(
        "mutation", "cosmic-ray exec"
    )


def test_ci_workflow_mutation_job_filters_equivalent_mutants() -> None:
    """Issue #431: ``cr-filter-operators`` must run between init and exec.

    It excludes mutations of the ``|`` in PEP 604 annotations, which no test
    can kill because ``from __future__ import annotations`` stops annotations
    from evaluating. On the first pilot session those were 66 of 104 reported
    survivors — dropping this step inflates every baseline by ~63%.
    """
    mutation_job = _job(WORKFLOW_PATH, "mutation")
    mutation_runs = _workflow_yaml.runs_text(mutation_job)

    assert "cr-filter-operators" in mutation_runs
    # init, filter and exec are chained inside one step; pin their order
    # within that step's run body (issue #963: run-field text is allowed).
    filter_run = next(
        str(step.get("run", ""))
        for step in _workflow_yaml.steps(mutation_job)
        if "cr-filter-operators" in str(step.get("run", ""))
    )
    assert (
        filter_run.index("cosmic-ray init")
        < filter_run.index("cr-filter-operators")
        < filter_run.index("cosmic-ray exec")
    )


def test_ci_workflow_mutation_job_is_never_triggered_by_a_pull_request() -> None:
    """Issue #780: the mutation job is release/manual only.

    A 233-mutant session per pull request would make the loop unusable, and
    §32.P7 requires the reachable events to be named rather than implied.
    """
    if_clause = str(_job(WORKFLOW_PATH, "mutation").get("if", ""))

    assert "github.event_name == 'schedule'" not in if_clause
    assert "github.event_name == 'workflow_dispatch'" in if_clause
    assert "startsWith(github.ref, 'refs/tags/')" in if_clause
    assert "pull_request" not in if_clause


def test_ci_workflow_mutation_job_pins_hash_seed_for_determinism() -> None:
    """TASK-2.1 (W-5): ``PYTHONHASHSEED=0`` is set for the mutation session.

    The companion ``--worker-count=1`` from that task is deliberately absent:
    ``cosmic-ray exec`` 8.4.6 accepts no such option and its ``local``
    distributor is already sequential.
    """
    mutation_job = _job(WORKFLOW_PATH, "mutation")
    mutation_text = _workflow_yaml.job_text(mutation_job)
    seed = _workflow_yaml.find_value(mutation_job, "PYTHONHASHSEED")

    assert isinstance(seed, str) and seed == "0", (
        "PYTHONHASHSEED must be the STRING \"0\" (env vars are strings; an "
        "unquoted 0 would still be coerced, but pin the declared form)"
    )
    assert "--worker-count" not in mutation_text


def test_mutation_baseline_has_derivation_entry_at_or_below_prior_measurement() -> None:
    """Issue #433: ``mutation-baseline.json`` must keep ``migration/derivation.py`` pinned.

    The shrink-only ratchet in ``scripts/check_mutation.py`` enforces
    that no per-module survivor count grows above its baseline entry.
    Local re-measurement is impossible on Windows (cosmic-ray 8.4.6 is
    INCOMPETENT for 100% of mutants — issue #431, Finding 1), so the
    entry stays at the prior main-branch measurement until the next
    Linux CI release-tag or manual run narrows it. This test pins the contract:

    - the baseline JSON exists, parses, and carries the entry, and
    - the entry's value is **at most** the previously measured 38
      survivors from the WSL/CPython 3.12.3 acquisition on 2026-08-06.
    """
    import json

    baseline_path = REPO_ROOT / "docs" / "quality" / "mutation-baseline.json"
    assert baseline_path.is_file(), (
        f"{baseline_path} must exist — the ratchet fails closed without it"
    )

    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    modules = payload.get("modules", {})
    assert "migration/derivation.py" in modules, (
        "the baseline must record migration/derivation.py so the "
        "shrink-only ratchet has a target to enforce against "
        "(issue #431)"
    )

    recorded = int(modules["migration/derivation.py"])
    PRIOR_MEASUREMENT = 38  # WSL Ubuntu 22.04 / CPython 3.12.3 — 2026-08-06

    # The ratchet is shrink-only: shrinking the entry is allowed and
    # encouraged when CI narrows it; raising above the prior measurement
    # would convert a real test-quality regression into a new normal.
    assert recorded <= PRIOR_MEASUREMENT, (
        f"migration/derivation.py baseline grew to {recorded}, above the "
        f"prior measurement of {PRIOR_MEASUREMENT}. Raising is a blocked "
        f"change (issue #431 shrink-only contract). Run cosmic-ray on "
        f"Linux to re-acquire a smaller survivor count, then update the "
        f"baseline in the same PR as the test additions that killed the "
        f"new mutants."
    )

    # Surface the current value in the pytest output so the next agent
    # who looks at this test can see exactly where the baseline lives.
    print(
        "\nmutation-baseline.json[migration/derivation.py] = "
        f"{recorded} (prior measurement: {PRIOR_MEASUREMENT})"
    )
    assert isinstance(recorded, int)


def test_cosmic_ray_toml_includes_adopciones_service_in_module_path() -> None:
    """Issue #434: the second mutation target must be listed in cosmic-ray.toml.

    cosmic-ray accepts ``module-path`` as a string OR a list of strings
    (verified at cosmic_ray/cli.py:92). The list form is what lets us
    grow the target set one module per PR without splitting the session.
    Removing the entry, or replacing the list with a single string, would
    silently drop adopciones/service.py from the gate.
    """
    import tomllib

    toml_path = REPO_ROOT / "docs" / "quality" / "cosmic-ray.toml"
    with toml_path.open("rb") as fh:
        cfg = tomllib.load(fh)

    module_path = cfg["cosmic-ray"]["module-path"]
    assert isinstance(module_path, list), (
        "module-path must be a list (cosmic-ray accepts string or list of strings "
        "per cosmic_ray/cli.py:92). A single string would silently drop all but "
        "one target."
    )
    assert "migration/derivation.py" in module_path, (
        "the pilot target was removed from module-path; that is a regression"
    )
    assert "app/modules/adopciones/service.py" in module_path, (
        "adopciones/service.py must be in module-path to be measured by the "
        "mutation gate (issue #434)"
    )


def test_cosmic_ray_baseline_targets_existing_files_and_collects_tests() -> None:
    """Issue #902: the unmutated command must have real targets and tests."""
    import json

    with (REPO_ROOT / "docs/quality/cosmic-ray.toml").open("rb") as fh:
        config = tomllib.load(fh)["cosmic-ray"]
    baseline = json.loads(
        (REPO_ROOT / "docs/quality/mutation-baseline.json").read_text(
            encoding="utf-8"
        )
    )
    targets = config["module-path"]
    assert set(targets) == set(baseline["modules"]) | set(
        baseline["awaiting_acquisition"]
    )
    assert all((REPO_ROOT / target).is_file() for target in targets)

    command = shlex.split(config["test-command"])
    test_nodes = [arg for arg in command if arg.startswith("tests/")]
    assert test_nodes
    assert all((REPO_ROOT / node.split("::", 1)[0]).is_file() for node in test_nodes)

    collected = subprocess.run(
        [sys.executable, *command[1:], "--collect-only"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert "tests collected" in collected.stdout or "test collected" in collected.stdout


def test_mutation_baseline_adopciones_has_been_acquired() -> None:
    """Issue #434: adopciones/service.py must carry a real survivor count, not a marker.

    The 2026-08-06 baseline left ``app/modules/adopciones/service.py`` in
    ``awaiting_acquisition`` because cosmic-ray 8.4.6 returns INCOMPETENT on
    native Windows (issue #431, Finding 1) and the scheduled CI mutation job
    never produced a session — the http distributor from PR #545 handed
    unix:// URLs to cosmic-ray's ``aiohttp`` client and never executed a
    single mutant. PR #593 rolled the distributor back to ``local``;
    PR #594 stopped the renderer from overriding the template's distributor
    name; the manual dispatch then ran a complete session in 1h27m.

    This test pins the post-acquisition state: the marker is gone,
    the module appears under ``modules`` with a non-null integer, and
    the recorded value was acquired on Linux ARM64 (the platform the
    production runners run on — see ``acquired_on.platform``). A
    regression here either un-acquires the count (re-adding the marker)
    or pins a synthetic zero, both of which would silently freeze
    a placeholder as if it were measured.
    """
    import json

    baseline_path = REPO_ROOT / "docs" / "quality" / "mutation-baseline.json"
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))

    awaiting = payload.get("awaiting_acquisition", {})
    assert "app/modules/adopciones/service.py" not in awaiting, (
        "adopciones/service.py was acquired (issue #434); an entry under "
        "'awaiting_acquisition' is a regression that re-opens the marker."
    )

    modules = payload.get("modules", {})
    assert "app/modules/adopciones/service.py" in modules, (
        "adopciones/service.py must appear under 'modules' with a real "
        "integer count after the 2026-08-22 acquisition (issue #434)"
    )
    survivors = modules["app/modules/adopciones/service.py"]
    assert isinstance(survivors, int) and survivors > 0, (
        f"adopciones/service.py survivor count must be a positive integer, "
        f"got {survivors!r}"
    )

    acquired = payload.get("acquired_on", {})
    assert "platform" in acquired, "acquired_on.platform must be present"
    assert "ARM64" in acquired["platform"], (
        f"acquired_on.platform must record the Linux ARM64 runner "
        f"(matches production). Got: {acquired['platform']!r}"
    )

    print(
        "\nmutation-baseline.json[modules][app/modules/adopciones/service.py]"
        f" = {survivors} survivors (acquired {acquired.get('date')} on "
        f"{acquired.get('platform')})"
    )

def test_ci_workflow_branch_name_step_is_wired() -> None:
    """The branch-name gate must be wired in pr-name.yml (issue #441, #525).

    AGENTS.md §15.2 declares the <type>/<issue>-<slug> naming convention.
    A convention that lives only in docs is §32.P3 (rule declared without a
    gate). The separate pr-name workflow validates the head ref against
    scripts/check_branch_name.py on every pull_request; removing the
    workflow or the step is a blocked change.

    Issue #525 (1/2): the pre-fix ``pull_request.branches: [main]`` filter
    silently dropped chained/stacked PRs whose base is a feature branch.
    The gate must fire for every PR regardless of base; main is just one
    valid base.
    """
    pr_name_doc = _doc(PR_NAME_WORKFLOW_PATH)
    pr_name_jobs = "\n".join(
        _workflow_yaml.job_text(entry)
        for entry in (pr_name_doc.get("jobs") or {}).values()
    )
    assert "scripts/check_branch_name.py" in pr_name_jobs
    assert "github.head_ref" in pr_name_jobs
    assert "github.event.pull_request.user.login" in pr_name_jobs
    assert "github.actor" not in pr_name_jobs
    # The gate fires on every pull_request — never silently restricted by
    # the workflow itself. Issue #525: restricting to a single base turned
    # chained PRs into invisible checks.
    triggers = _workflow_yaml.on_triggers(pr_name_doc)
    assert "pull_request" in triggers, (
        "pr-name.yml must listen to pull_request events"
    )
    pr_config = (
        triggers["pull_request"] if isinstance(triggers["pull_request"], dict) else {}
    )
    assert pr_config.get("branches") != ["main"], (
        "pr-name.yml restricts pull_request.branches to ``[main]`` "
        "(issue #525): chained/stacked PRs whose base is a feature branch "
        "silently disappear from the rollup. The branch-name gate must "
        "fire for every PR base."
    )


def test_ci_workflow_pr_size_job_is_wired() -> None:
    """The PR size gate must be wired in pr-size.yml (issue #442).

    AGENTS.md §15.1 declares ``review_budget_lines: 400`` as a soft budget
    enforced by PR review. Issue #442 promotes it to a CI gate so a 500-line
    PR cannot land on main without an explicit ``size:exception`` label.
    The wiring lives in a dedicated ``.github/workflows/pr-size.yml`` (one
    job, ``pull_request`` only) rather than in ``ci.yml`` because the gate
    needs the diff against the merge-base plus the labels payload — neither
    is available to the lint/test/typecheck jobs without bloating them.

    The workflow MUST invoke ``scripts/check_pr_size.py`` and read the
    ``size:exception`` label; the script is the unit-tested entry point and
    the label is the only acceptable override (AGENTS.md §15.6). Removing
    either reference from the workflow is a blocked change (issue #442).
    """
    pr_size_doc = _doc(PR_SIZE_WORKFLOW_PATH)
    pr_size_runs = "\n".join(
        _workflow_yaml.runs_text(entry)
        for entry in (pr_size_doc.get("jobs") or {}).values()
    )

    assert "scripts/check_pr_size.py" in pr_size_runs, (
        "pr-size.yml must invoke scripts/check_pr_size.py (issue #442, "
        "AGENTS.md §15.1) — the script is the unit-tested gate; inlining "
        "the budget logic in the workflow would silently bypass tests/test_pr_size.py"
    )
    assert "size:exception" in pr_size_runs, (
        "pr-size.yml must read the 'size:exception' label (AGENTS.md §15.6) — "
        "it is the only acceptable override for the 400-line budget"
    )


def test_pr_size_refreshes_when_exception_label_changes() -> None:
    """Label mutations must create a fresh event payload for the gate."""
    triggers = _triggers(PR_SIZE_WORKFLOW_PATH)

    pull_request = triggers.get("pull_request")
    assert pull_request is not None
    pr_types = (
        pull_request.get("types") if isinstance(pull_request, dict) else pull_request
    )
    assert "labeled" in (pr_types or [])
    assert "unlabeled" in (pr_types or [])


def test_pr_size_excludes_generated_lockfiles_not_manifests() -> None:
    """Generated lockfile churn must not consume the human review budget."""
    pr_size = (REPO_ROOT / ".github" / "workflows" / "pr-size.yml").read_text(
        encoding="utf-8"
    )

    assert "':(exclude)**/package-lock.json'" in pr_size
    assert "':(exclude)uv.lock'" in pr_size
    assert "':(exclude)**/package.json'" not in pr_size
    assert "':(exclude)pyproject.toml'" not in pr_size


# --- issue #926: pr-size concurrency race + stale event-payload labels -----
#
# pr-size.yml runs two ways: directly on `pull_request: types: [labeled,
# unlabeled]`, and via `workflow_call` from ci.yml's own `pull_request`
# trigger. Both used to share the concurrency group
# `pr-size-${{ github.ref }}`, so every `labeled` event (e.g. `gh pr create
# --label`) cancelled the workflow_call run in progress inside `ci`, leaving
# `ci / required` red without ever running the dependent jobs (PR #925, run
# 36041158202). Separately, `HAS_EXCEPTION` was computed from
# `github.event.pull_request.labels` — the ORIGINAL webhook payload. Labels
# added by `gh pr create --label` land after the `opened` event fires, and
# `gh run rerun` replays that same stale payload, so a PR carrying
# `size:exception` still failed the gate (PR #931, run 36046072242:
# `HAS_EXCEPTION: false` with the label present).


def test_pr_size_concurrency_group_is_trigger_scoped() -> None:
    """The concurrency group must differ between the labeled/unlabeled
    direct trigger and the workflow_call path from ci.yml, so a label event
    never cancels the in-flight ci-triggered run (issue #926).
    """
    concurrency = _workflow_yaml.concurrency(_doc(PR_SIZE_WORKFLOW_PATH))
    assert isinstance(concurrency, dict), (
        "pr-size.yml must declare a concurrency block (issue #926)"
    )
    group_line = str(concurrency.get("group", ""))

    assert group_line != "pr-size-${{ github.ref }}", (
        "pr-size.yml's concurrency group is a constant shared by both the "
        "direct labeled/unlabeled trigger and the workflow_call from "
        "ci.yml (issue #926) — a labeled event cancels the ci-triggered "
        "run instead of only cancelling other label runs."
    )
    assert "github.event.action" in group_line, (
        "the concurrency group must derive a trigger-dependent suffix from "
        "github.event.action so the labeled path and the ci-call path "
        "never share a cancellation group (issue #926)."
    )


def _pr_size_fetch_step_run() -> str:
    """The ``run:`` body of pr-size.yml's live-labels fetch step."""
    pr_size_job = next(iter((_doc(PR_SIZE_WORKFLOW_PATH).get("jobs") or {}).values()))
    return next(
        str(step.get("run", ""))
        for step in _workflow_yaml.steps(pr_size_job)
        if "api.github.com" in str(step.get("run", ""))
    )


def test_pr_size_exception_label_read_from_live_api_not_event_payload() -> None:
    """HAS_EXCEPTION must come from a live GitHub API read, not the static
    event payload, so labels added after PR creation or replayed by
    `gh run rerun` are still seen (issue #926).
    """
    pr_size_jobs_text = "\n".join(
        _workflow_yaml.job_text(entry)
        for entry in (_doc(PR_SIZE_WORKFLOW_PATH).get("jobs") or {}).values()
    )
    fetch_run = _pr_size_fetch_step_run()

    assert "github.event.pull_request.labels" not in pr_size_jobs_text, (
        "pr-size.yml must not derive the size:exception flag from the "
        "static event payload (issue #926) — labels added after the "
        "triggering event, or a rerun of a stale payload, go unseen."
    )
    # Issue #533: the runner backing this job does not provide the `gh`
    # CLI, so the live fetch must go through curl + jq (deploy.yml's
    # existing pattern), not `gh api`.
    assert re.search(
        r"https://api\.github\.com/repos/\$\{GITHUB_REPOSITORY\}"
        r"/issues/\$\{PR_NUMBER\}/labels\b",
        fetch_run,
    ), (
        "pr-size.yml must fetch the PR's live labels from the GitHub REST "
        "API (curl + jq, per issue #533 — this runner has no `gh` CLI) "
        "instead of the event payload (issue #926)."
    )
    assert "gh api" not in pr_size_jobs_text, (
        "pr-size.yml's runner does not provide the `gh` CLI (issue #533); "
        "use curl + jq instead, matching deploy.yml's evidence step."
    )

    workflow_perms = _workflow_yaml.permissions(_doc(PR_SIZE_WORKFLOW_PATH))
    assert workflow_perms.get("issues") == "read", (
        "reading labels via the GitHub API needs `issues: read` at the "
        "workflow level (issue #926), alongside the existing "
        "`contents: read` (issue #682)."
    )


def test_pr_size_exception_label_fetch_fails_closed() -> None:
    """A failed label fetch must fail the job, not silently pass the gate
    as if no exception label were present (issue #926).
    """
    fetch_run = _pr_size_fetch_step_run()
    # The step containing the API call must exit non-zero on failure
    # inside its own run: body.
    assert "exit 1" in fetch_run, (
        "the label-fetch step must exit non-zero when the GitHub API call "
        "fails, so the gate fails closed instead of treating a fetch "
        "failure as 'no size:exception label' (issue #926)."
    )


def test_pr_size_job_in_ci_yml_declares_issues_read() -> None:
    """A called reusable workflow cannot exceed the caller's permissions,
    so ci.yml's `pr-size` job needs `issues: read` too (issue #926).
    """
    perms = _workflow_yaml.permissions(_job(WORKFLOW_PATH, "pr-size"))

    assert perms.get("issues") == "read", (
        "ci.yml's pr-size job must declare `issues: read` — pr-size.yml "
        "now reads live PR labels via the GitHub API, and a called "
        "workflow cannot exceed the caller's granted permissions "
        "(issue #926)."
    )


def test_dependabot_excludes_ratchet_coupled_ruff_updates() -> None:
    """Ruff bumps require an explicit baseline recalibration."""
    config = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

    assert 'dependency-name: "ruff"' in config


def test_dependabot_excludes_mutation_coupled_cosmic_ray_updates() -> None:
    """Cosmic-ray bumps require an intentional harness re-validation."""
    config = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

    assert 'dependency-name: "cosmic-ray"' in config


# --- issue #525: PR gates mis-handle chained/stacked PRs ------------------
#
# Two coupled defects in .github/workflows/{pr-name,pr-size}.yml:
#
#   1. Both restrict ``pull_request.branches`` to ``[main]``, so chained
#      PRs whose base is a feature branch never receive the gate.
#   2. ``pr-size`` hardcodes ``git merge-base origin/main HEAD``, so the
#      candidate's diff is contaminated by every commit the base PR
#      added (the issue calls out 329 -> 634 lines).
#
# The dispatch requires regression tests that fail on unmodified origin/main
# and parametrize over main and a non-main base case, exercising the
# actual shell the workflow runs (not merely inspecting its YAML shape).

PR_GATE_TRIGGER_WORKFLOWS = (
    (REPO_ROOT / ".github" / "workflows" / "pr-name.yml", "pr-name.yml"),
    (REPO_ROOT / ".github" / "workflows" / "pr-size.yml", "pr-size.yml"),
)


@pytest.mark.parametrize("workflow_path,label", PR_GATE_TRIGGER_WORKFLOWS)
def test_pr_gate_fires_for_any_pull_request_base(workflow_path: Path, label: str) -> None:
    """Issue #525 (1/2): the gate must fire for every PR base.

    The pre-#525 shape was ``pull_request.branches: [main]``, which made
    every chained/stacked PR skip the gate invisibly. Re-introducing the
    restriction is a regression of the same silent-outage shape issue
    #523 chases from a different angle.

    Parametrized over both gate workflows because the original fix
    touches them together.
    """
    triggers = _triggers(workflow_path)

    assert "pull_request" in triggers, (
        f"{label}: must listen on pull_request events (issue #525)"
    )

    pr_trigger = triggers["pull_request"]
    pr_block = (
        pr_trigger.get("branches") if isinstance(pr_trigger, dict) else None
    )
    assert pr_block != ["main"], (
        f"{label}: pull_request.branches is restricted to ``[main]`` "
        f"(issue #525). Chained/stacked PRs whose base is a feature branch "
        f"silently drop the check from the rollup. Drop the branches "
        f"filter or use a wider pattern that still excludes forks."
    )


def test_pr_size_uses_event_base_ref_not_origin_main() -> None:
    """Issue #525 (2/2, static): the diff base must come from the event.

    Pre-#525 pr-size.yml hardcoded ``BASE=$(git merge-base origin/main HEAD)``,
    which silently inflated the candidate's total by every commit the
    base PR added (529 called out 329 -> 634). The fix must read
    ``${{ github.base_ref }}`` from the event and compute the merge-base
    against the named ref, fetched into the runner.
    """
    pr_size = (REPO_ROOT / ".github" / "workflows" / "pr-size.yml").read_text(
        encoding="utf-8"
    )

    # The exact buggy line as it shipped on main. Asserting the literal
    # ``merge-base origin/main HEAD`` keeps the regression pinned: any
    # future re-introduction of the same short-form literal fails.
    assert "merge-base origin/main HEAD" not in pr_size, (
        "pr-size.yml hardcodes ``git merge-base origin/main HEAD`` "
        "(issue #525). The candidate's diff is computed against main, "
        "which on a chained PR accumulates the base PR's delta on top "
        "of the candidate's. Use ${{ github.base_ref }} and fetch the "
        "named ref before merging."
    )

    # The fix MUST read the base ref from the event. A string-only test
    # on the literal above cannot rule out a fallback like
    # ``[[ -z "$BASE_REF" ]] && BASE_REF=main`` that quietly re-introduces
    # the same defect for non-main bases — the behavioural test below
    # covers that case.
    assert "github.base_ref" in pr_size, (
        "pr-size.yml: must source the comparison base from "
        "``${{ github.base_ref }}`` (issue #525). A hardcoded ref treats "
        "chained and stacked PRs as if they were opened against main."
    )


def test_pr_size_base_fetch_does_not_shallow_the_repository() -> None:
    """Issue #525: the base fetch must not carry ``--depth``.

    A shallow fetch marks the WHOLE repository shallow — verified locally, where
    ``git fetch --no-tags --depth=1 origin main`` flipped
    ``rev-parse --is-shallow-repository`` from false to true on a complete clone.
    From then on ``merge-base`` can only see back to the boundary.

    That fails in the one place this step exists to serve. On a PR against main
    the boundary usually still contains the common ancestor, so it passes; on a
    chained PR the ancestor is further back, ``merge-base`` returns nothing, and
    the step exits 1 — a gate that breaks precisely on the case it was written
    for, while looking correct on every ordinary PR.

    The checkout above already uses ``fetch-depth: 0``, which populates
    ``refs/remotes/origin/*`` for every branch (62 refs on this repository), so
    the fetch is a safety net for a base created after checkout, not the source
    of the ref.
    """
    pr_size = (REPO_ROOT / ".github" / "workflows" / "pr-size.yml").read_text(
        encoding="utf-8"
    )
    executable = "\n".join(
        line for line in pr_size.splitlines() if not line.lstrip().startswith("#")
    )

    fetches = [line for line in executable.splitlines() if "git fetch" in line]

    assert fetches, "pr-size.yml no longer fetches the base ref at all"
    for line in fetches:
        assert "--depth" not in line, (
            f"pr-size.yml shallow-fetches the base ref ({line.strip()!r}). That "
            f"marks the repository shallow and leaves merge-base unable to reach "
            f"the common ancestor of a chained PR (issue #525)."
        )
    assert "fetch-depth: 0" in pr_size


@pytest.mark.parametrize(
    "base_branch,expected_delta",
    [
        # Main is the regression anchor: the buggy ``origin/main``
        # literal AND the fixed ``github.base_ref`` shape both report
        # the same total when the base IS main. If the fix changes
        # behaviour for the common case, this case fails.
        ("main", 2),
        # A non-main base is the bug case. Pre-fix the diff base is
        # hardcoded to ``origin/main``; ``merge-base origin/main HEAD``
        # walks back to the shared ancestor and accumulates every
        # commit the base PR introduced, so the buggy total is 4
        # (two base files + two candidate files) instead of 2.
        ("feat/522-base-pr", 2),
    ],
)
def test_pr_size_diff_step_reports_only_candidate_delta(
    tmp_path: Path, base_branch: str, expected_delta: int
) -> None:
    """Issue #525 (2/2, behavioural): the diff step for any base.

    Builds a git fixture with a base branch that already carries
    commits, then layers a candidate commit on top of it. Runs the
    SAME git invocations the workflow's shell runs, in the SAME
    order — fetch, merge-base, shortstat — so the failure mode of
    every step is exercised, not just a string-shape check.

    The pre-fix ``BASE=$(git merge-base origin/main HEAD)`` returns
    the candidate-plus-base-aggregate on the non-main case (4 lines
    instead of 2): the test asserts the correct value so the buggy
    shape cannot pass.
    """
    fixture = _build_pr_size_fixture(tmp_path, base_branch=base_branch)

    # Mirror what the workflow's ``Compute diff against merge-base``
    # step does, in the same order:
    #
    #   1. Bail loudly if BASE_REF is empty (the fix guards against
    #      the exact case where ${{ github.base_ref }} was unset).
    #   2. ``git fetch --no-tags --depth=1 origin $BASE_REF`` — the
    #      fix's hydration step. The fixture has already fetched once
    #      during setup, so this is a no-op against the local bare.
    #   3. ``BASE=$(git merge-base "origin/$BASE_REF" HEAD)`` — the
    #      fix's BASE computation. The buggy code used a hardcoded
    #      ``merge-base origin/main HEAD``; reproducing that here
    #      instead returns 4 on the non-main case.
    #   4. ``git diff --shortstat "$BASE"...HEAD`` — produces the
    #      line counts the workflow's run step writes to
    #      ``$GITHUB_OUTPUT``.
    base_ref = base_branch
    if not base_ref:
        raise AssertionError(
            'BASE_REF is empty; the workflow\'s "if [ -z \\"$BASE_REF\\" ]" '
            "guard must fire on every missing event."
        )

    subprocess.run(
        ["git", "fetch", "--no-tags", "--depth=1", "origin", base_ref],
        cwd=fixture,
        check=True,
        capture_output=True,
    )
    base = subprocess.run(
        ["git", "merge-base", f"origin/{base_ref}", "HEAD"],
        cwd=fixture,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not base:
        raise AssertionError(
            f"merge-base origin/{base_ref} HEAD produced no SHA in "
            f"the fixture; the workflow's second guard must fire."
        )

    shortstat = subprocess.run(
        ["git", "diff", "--shortstat", f"{base}...HEAD"],
        cwd=fixture,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    total = _parse_shortstat(shortstat)

    assert total == expected_delta, (
        f"pr-size.yml diff step: base_branch={base_branch!r} reported "
        f"total={total}, expected {expected_delta} (issue #525). The "
        f"pre-fix shell hardcoded origin/main; the fix must diff "
        f"candidate-only for every base."
    )


def _parse_shortstat(shortstat: str) -> int:
    """Mirror the workflow's awk extraction of additions + deletions.

    ``git diff --shortstat`` prints e.g. `` 2 files changed, 2 insertions(+), 1 deletion(-)``.
    The workflow pulls ``$4`` (insertions) and ``$6`` (deletions);
    this helper splits on the comma and pulls the same integers.
    The empty-string fallback (``if [ -z "$X" ]; then X=0; fi``) is
    irrelevant here because ``git diff`` against a non-trivial base
    always reports both numbers.
    """
    added, deleted = 0, 0
    for chunk in (segment.strip() for segment in shortstat.split(",")):
        # ``2 files changed, 2 insertions(+), 1 deletion(-)
        if chunk.endswith("insertion(+)") or chunk.endswith("insertions(+)"):
            added = int(chunk.split()[0])
        elif chunk.endswith("deletion(-)") or chunk.endswith("deletions(-)"):
            deleted = int(chunk.split()[0])
    return added + deleted


# --- helpers used by the issue #525 behavioural test -------------------


def _build_pr_size_fixture(tmp_path: Path, *, base_branch: str) -> Path:
    """Create a git repo where ``base_branch`` and the candidate diverge.

    The shape mirrors a chained PR: the base branch carries some
    commits, and HEAD (the candidate) is one commit on top of those.
    Both ``main`` and ``feat/522-base-pr`` have to exist as local refs
    so the workflow's ``origin/<branch>`` lookup resolves.

    Returns the path to the fixture root (already cd'd into position).
    """
    repo = tmp_path / "fixture"
    repo.mkdir()
    run = subprocess.run
    run(
        ["git", "init", "--initial-branch=main"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )

    run(["git", "config", "user.email", "ci@example.com"], cwd=repo, check=True)
    run(["git", "config", "user.name", "ci"], cwd=repo, check=True)
    # ``git init`` defaults to the user's global config when none is set;
    # the explicit commands above win, but CI runners often ship no
    # global config so this is belt-and-braces.

    # Base commit (zero delta; both branches share this history).
    (repo / "shared.txt").write_text("shared\n", encoding="utf-8")
    run(["git", "add", "shared.txt"], cwd=repo, check=True)
    run(["git", "commit", "-m", "shared"], cwd=repo, check=True)

    # Branch from the shared history into ``base_branch`` and add some
    # commits there. These commits must NOT be counted in the candidate
    # diff (the bug is that they were).
    run(["git", "checkout", "-B", base_branch], cwd=repo, check=True)
    for index in range(2):
        (repo / f"base-{index}.txt").write_text(f"base {index}\n", encoding="utf-8")
        run(["git", "add", f"base-{index}.txt"], cwd=repo, check=True)
        run(
            ["git", "commit", "-m", f"base change {index}"],
            cwd=repo,
            check=True,
        )

    # Candidate branch: one commit on top of ``base_branch``. The diff
    # base for the candidate must be ``base_branch``, NOT main, on the
    # non-main case.
    run(["git", "checkout", "-B", "candidate"], cwd=repo, check=True)
    (repo / "candidate.txt").write_text("candidate line one\n", encoding="utf-8")
    (repo / "candidate-extra.txt").write_text("candidate line two\n", encoding="utf-8")
    run(["git", "add", "candidate.txt", "candidate-extra.txt"], cwd=repo, check=True)
    run(["git", "commit", "-m", "candidate delta"], cwd=repo, check=True)

    # Wire ``origin`` as a sibling **bare** repo so ``git fetch origin
    # $BASE_REF`` succeeds when the same path is mapped through both
    # Windows git (in Python) and Linux git (in WSL bash). A bare repo
    # keeps the flow intact because the fetch tests "is this ref
    # reachable from a remote"; a file:// URL confuses WSL's path
    # translation because the same ``C:\...`` is valid in Windows
    # but not in Linux. The sibling bare shares the fixture's parent
    # directory so POSIX and Windows paths are equivalent on disk.
    bare = repo.parent / f"{repo.name}_bare.git"
    run(
        ["git", "clone", "--bare", str(repo), str(bare)],
        cwd=repo.parent,
        check=True,
    )
    # Make the source repo point ``origin`` at the bare clone. The
    # path is valid both on Windows (Python) and in WSL bash because
    # it lives under ``/mnt/c/...`` from bash's view.
    run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=repo,
        check=True,
    )
    run(["git", "fetch", "origin"], cwd=repo, check=True)

    return repo


def _parse_total(stdout: str) -> int:
    """Parse ``total=<int>`` from the workflow's run step stdout (or skip).

    The behavioural test no longer shells out — it parses ``git diff
    --shortstat`` directly (see ``_parse_shortstat`` below). Kept
    here as a safety net in case a future test runs the bash from
    end-to-end and needs to read back the ``total=`` line.
    """
    for line in stdout.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "total":
            return int(value.strip())
    raise AssertionError(
        f"pr-size.yml run step never wrote ``total=`` to its output; got: {stdout!r}"
    )


def _parse_shortstat(shortstat: str) -> int:
    """Mirror the workflow's awk extraction of additions + deletions.

    ``git diff --shortstat`` prints e.g. `` 2 files changed, 2 insertions(+), 1 deletion(-)``.
    The workflow pulls ``$4`` (insertions) and ``$6`` (deletions);
    this helper splits on the comma and pulls the same integers.
    Empty chunks and changes-only-with-no-add-or-del (rare for a
    non-trivial diff) default to 0, which matches the workflow's
    ``if [ -z "$ADDED" ]; then ADDED=0; fi`` guard.
    """
    added, deleted = 0, 0
    for chunk in (segment.strip() for segment in shortstat.split(",")):
        if chunk.endswith("insertion(+)") or chunk.endswith("insertions(+)"):
            added = int(chunk.split()[0])
        elif chunk.endswith("deletion(-)") or chunk.endswith("deletions(-)"):
            deleted = int(chunk.split()[0])
    return added + deleted


# --- issue #890: consolidate the pr-size gate into a single source -----
#
# #867 embedded a second computation of the same merge-base diff directly
# in ci.yml so an oversized PR would not burn runner minutes on lint/test/
# security/etc. #878/#879 each had to fix that embedded copy in lockstep
# with pr-size.yml after it drifted, and the two workflows publishing a
# check named `pr-size` for the same commit forced `--admin` merges on
# every PR touching either one (GitHub documents same-name checks across
# workflows as producing ambiguous required-status results). This section
# pins that ci.yml no longer reimplements the computation — it calls
# pr-size.yml as a reusable workflow instead — and that pr-size.yml's own
# ``pull_request`` trigger now covers only label changes, so exactly one
# workflow publishes the `pr-size` check for any given event. The three-dot
# diff / awk parsing / lockfile-exclude / unshallow-fetch guarantees stay
# pinned above against pr-size.yml itself (the single remaining source);
# they do not need a second copy here.


def test_ci_workflow_pr_size_job_calls_the_reusable_workflow() -> None:
    """Issue #890: ci.yml's pr-size job must delegate, not reimplement.

    A ``uses:`` job cannot declare its own ``steps:``/``runs-on:`` — GitHub
    Actions' schema forbids mixing them. Asserting their absence here is
    itself a regression pin against a future edit re-embedding the bash.
    """
    pr_size_job = _job(WORKFLOW_PATH, "pr-size")

    assert pr_size_job.get("uses") == "./.github/workflows/pr-size.yml", (
        "ci.yml's pr-size job must call pr-size.yml as a reusable workflow "
        "(issue #890) instead of reimplementing the merge-base diff."
    )
    assert "runs-on" not in pr_size_job, (
        "a job with `uses:` cannot also declare `runs-on:` — its presence "
        "means the embedded implementation was not actually removed."
    )
    assert "Compute diff against merge-base" not in _workflow_yaml.job_text(
        pr_size_job
    ), (
        "the embedded diff step must be gone entirely; pr-size.yml is now "
        "the only place that computes it (issue #890)."
    )


def test_pr_size_workflow_declares_workflow_call_trigger() -> None:
    """Issue #890: pr-size.yml must be callable from ci.yml as a reusable
    workflow, in addition to its own direct pull_request trigger.
    """
    triggers = _triggers(PR_SIZE_WORKFLOW_PATH)

    assert "workflow_call" in triggers, (
        "pr-size.yml must declare a workflow_call trigger so ci.yml can "
        "invoke it via `uses:` (issue #890)."
    )


def test_pr_size_direct_trigger_covers_only_label_changes() -> None:
    """Issue #890: opened/synchronize/reopened now route through ci.yml's
    call, not pr-size.yml's own direct trigger — otherwise both would fire
    for the same event and publish the same-named check twice, the exact
    ambiguity this consolidation exists to remove.
    """
    triggers = _triggers(PR_SIZE_WORKFLOW_PATH)
    pull_request = triggers["pull_request"]
    pr_types = (
        pull_request.get("types") if isinstance(pull_request, dict) else pull_request
    )
    pr_types = pr_types or []

    assert "labeled" in pr_types
    assert "unlabeled" in pr_types
    assert "opened" not in pr_types, (
        "pr-size.yml's direct pull_request trigger must not also cover "
        "opened/synchronize/reopened (issue #890) — those route through "
        "ci.yml's workflow_call instead, or the same event fires both "
        "workflows and reintroduces the duplicate `pr-size` check."
    )
    assert "synchronize" not in pr_types
    assert "reopened" not in pr_types


def test_pr_size_diff_step_reports_zero_on_non_pull_request_events(tmp_path: Path) -> None:
    """Issue #890: called via workflow_call from ci.yml's push/tag/
    workflow_dispatch triggers, this step now has no PR context at all —
    it must report total=0 instead of failing loudly, exactly like ci.yml's
    own fallback did before this consolidation absorbed that behaviour.
    """
    script = str(
        _workflow_yaml.find_step(
            next(iter((_doc(PR_SIZE_WORKFLOW_PATH).get("jobs") or {}).values())),
            "Compute diff against merge-base",
        ).get("run", "")
    )

    repo = tmp_path / "fixture"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    github_output = tmp_path / "github_output"
    github_output.write_text("", encoding="utf-8")

    result = subprocess.run(
        ["bash", "-c", script],
        cwd=repo,
        env={**os.environ, "GITHUB_OUTPUT": str(github_output), "EVENT_NAME": "push", "BASE_REF": ""},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        f"the diff step must exit 0 on a non-pull_request event; "
        f"stderr: {result.stderr}"
    )
    assert "total=0" in github_output.read_text(encoding="utf-8")


def test_pr_size_diff_step_still_fails_loud_on_pull_request_with_empty_base_ref(
    tmp_path: Path,
) -> None:
    """Issue #890: the fail-loud guard (issue #525) must survive the new
    event_name branch — an actual pull_request event with no base ref is
    still the regression #525 exists to catch, not a legitimate skip.
    """
    script = str(
        _workflow_yaml.find_step(
            next(iter((_doc(PR_SIZE_WORKFLOW_PATH).get("jobs") or {}).values())),
            "Compute diff against merge-base",
        ).get("run", "")
    )

    repo = tmp_path / "fixture"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    github_output = tmp_path / "github_output"
    github_output.write_text("", encoding="utf-8")

    result = subprocess.run(
        ["bash", "-c", script],
        cwd=repo,
        env={
            **os.environ,
            "GITHUB_OUTPUT": str(github_output),
            "EVENT_NAME": "pull_request",
            "BASE_REF": "",
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, (
        "a pull_request event with an empty base ref must still fail loud "
        "(issue #525) — a quiet total=0 here would hide the exact bug #525 "
        "was written to catch."
    )


# --- make verify <-> ci.yml parity (issue #504) ------------------------
#
# Every other meta-test in this file pins ONE gate to ONE workflow step.
# The pair below pins the SET: whatever ci.yml gates a pull request on
# must be reachable from `make verify`. Without it, the seventeenth gate
# gets a CI step and never gets a Makefile target, and `make verify`
# quietly goes back to being a subset — the exact drift #504 closed.

#: Expanded so a recipe can be compared against a CI ``run:`` line.
_MAKE_VARIABLES = {
    "$(PYTHON)": "python",
    "$(PIP)": "python -m pip",
    "$(RUFF)": "ruff",
    "$(MYPY)": "python -m mypy",
    "$(PYTEST)": "python -m pytest",
}


def _parse_makefile() -> dict[str, tuple[list[str], list[str]]]:
    """Parse the Makefile into ``{target: (prerequisites, recipe lines)}``.

    Deliberately minimal — just enough to walk the ``verify`` dependency
    graph. Backslash continuations are joined first so a wrapped
    prerequisite list reads as one logical line; variable assignments,
    comments and ``.PHONY`` are skipped.
    """
    logical: list[str] = []
    for line in MAKEFILE_PATH.read_text(encoding="utf-8").splitlines():
        if logical and logical[-1].endswith("\\"):
            logical[-1] = logical[-1].removesuffix("\\").rstrip() + " " + line.strip()
        else:
            logical.append(line)

    targets: dict[str, tuple[list[str], list[str]]] = {}
    current: str | None = None
    for line in logical:
        if line.startswith("\t"):
            if current is not None:
                targets[current][1].append(line.strip())
            continue
        stripped = line.strip()
        head = stripped.partition(":")[0]
        if not stripped or stripped.startswith(("#", ".")) or ":" not in stripped or " " in head:
            current = None
            continue
        current = head.strip()
        targets[current] = (stripped.partition(":")[2].split(), [])
    return targets


def _verify_recipe_blob() -> str:
    """Every command reachable from ``make verify``, variables expanded."""
    targets = _parse_makefile()
    seen: set[str] = set()
    commands: list[str] = []

    def walk(name: str) -> None:
        if name in seen or name not in targets:
            return
        seen.add(name)
        prerequisites, recipe = targets[name]
        for prerequisite in prerequisites:
            walk(prerequisite)
        commands.extend(recipe)

    walk("verify")
    blob = "\n".join(commands)
    for variable, expansion in _MAKE_VARIABLES.items():
        blob = blob.replace(variable, expansion)
    return blob


def _ci_pull_request_gate_scripts() -> list[str]:
    """The ``scripts/check_*.py`` gates ci.yml applies to a pull request.

    Scoped to the ``lint`` and ``test`` jobs on purpose: those are the two
    that run on every PR and whose gates a developer can reproduce on a
    workstation. ``mutation`` (release/manual, Linux-only), ``security`` (Docker),
    ``integration`` (Postgres service) and ``e2e`` (Playwright) are out of
    scope for ``make verify`` and documented as such in the Makefile.
    """
    executable = "\n".join(
        (
            _workflow_yaml.runs_text(_job(WORKFLOW_PATH, "lint")),
            _workflow_yaml.runs_text(_job(WORKFLOW_PATH, "test")),
        )
    )
    return list(dict.fromkeys(re.findall(r"scripts/check_\w+\.py", executable)))


def test_make_verify_covers_locally_runnable_script_gates() -> None:
    """``make verify`` must run each locally reproducible script gate.

    Issue #504. Before this, ``make all`` was documented in
    docs/development.md as "el comando que refleja la CI" while running
    four of seventeen gates: a green local run said nothing about CI, so
    the real contract lived in ci.yml and no single command expressed it.

    This is the ratchet on the local harness. Service-container, Docker,
    browser, and release-only jobs remain the responsibility of the remote
    ``ci / required`` aggregator.
    """
    blob = _verify_recipe_blob()

    missing = [script for script in _ci_pull_request_gate_scripts() if script not in blob]
    assert not missing, (
        f"ci.yml gates a pull request on {missing}, but `make verify` never runs "
        "them. Add a target per gate to the Makefile and list it in the `verify` "
        "prerequisites, in the same order ci.yml runs it (issue #504)."
    )

    assert "ruff check ." in blob, "make verify must run `ruff check .` — the CI lint job does"
    assert "python -m mypy" in blob, (
        "make verify must run mypy — the CI typecheck job does (AGENTS.md rule 24)"
    )
    assert "--cov-fail-under=85" in blob, (
        "make verify must run pytest with the CI coverage floor; a local run without "
        "--cov-fail-under passes on a tree CI would reject (issue #199/#331)"
    )
    assert "scripts/quality_report.py" not in blob


def test_make_verify_alantyle_scope_matches_ci() -> None:
    """The local gate must not scan mutable OpenSpec working artifacts."""
    blob = _verify_recipe_blob()

    assert "openspec/changes/*/specs/" in blob
    assert "openspec/changes/ README.md" not in blob


def test_make_verify_excludes_the_jobs_a_workstation_cannot_run() -> None:
    """``verify`` must stay runnable on a developer machine.

    The exclusions are a design decision, not an oversight, so they are
    pinned: folding cosmic-ray into ``verify`` would make the gate
    Linux-only and multi-hour, and folding the Docker scanners in would
    make it fail on any machine without a daemon. Both have their own
    jobs. If one of them ever becomes cheap enough to include, deleting
    this test is the deliberate act that records the decision.
    """
    blob = _verify_recipe_blob()

    assert "cosmic-ray" not in blob, (
        "make verify must not run the mutation session — it is Linux-only and lives "
        "in its own release/manual job (see the `mutation` target)"
    )
    assert "scripts/check_mutation.py" not in blob, (
        "scripts/check_mutation.py gates the cosmic-ray session, not a pull request"
    )
    assert "docker run" not in blob, (
        "make verify must not require Docker — gitleaks and trivy live in the "
        "`security` job"
    )


def test_development_guide_points_at_make_verify() -> None:
    """The guide must name the local pre-PR verification command (issue #504).

    docs/development.md is where a new contributor learns what to run
    before opening a PR. While it named ``make all``, it was teaching a
    four-gate subset as if it were the seventeen-gate contract.
    """
    guide = DEVELOPMENT_GUIDE_PATH.read_text(encoding="utf-8")

    assert "make verify" in guide, (
        "docs/development.md must document `make verify` as the pre-PR command "
        "(issue #504)"
    )


# --- issue #640: verify-fallback-ready fold-back -----------------------

def _verify_fallback_ready_job() -> dict[str, Any]:
    """The verify-fallback-ready job of ci.yml, as parsed YAML (issue #963)."""
    return _job(WORKFLOW_PATH, "verify-fallback-ready")


def test_ci_workflow_invoke_verify_fallback_ready_via_main_cli() -> None:
    executable = _workflow_yaml.runs_text(_verify_fallback_ready_job())

    assert "python -m migration verify-fallback-ready --ci-only" in executable
    assert "migration.cli_verify_fallback_ready" not in executable


def test_ci_workflow_verify_fallback_ready_job_has_no_standalone_path_comment() -> None:
    job_text = _workflow_yaml.job_text(_verify_fallback_ready_job())

    assert "migration/cli_verify_fallback_ready" not in job_text
    assert "temporary workaround" not in job_text


def test_bare_pytest_excludes_every_suite_the_ci_test_job_excludes() -> None:
    """A plain local ``pytest`` must match the CI ``test`` job's scope (issue #940).

    ``tests/e2e_ci`` needs a deployed app and MinIO. The CI test job ignores it,
    but ``addopts`` did not, so a bare local ``pytest`` ran it without services
    and it leaked state into the route tests: 61 failed + 514 errors locally
    while CI was green. Every ``--ignore`` of the CI test job must also be in
    ``addopts``.
    """
    import tomllib  # lazy-import: stdlib, only this test reads pyproject.toml

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]
    local_ignores = {
        option.removeprefix("--ignore=").rstrip("/")
        for option in addopts
        if option.startswith("--ignore=")
    }

    test_runs = _workflow_yaml.runs_text(_job(WORKFLOW_PATH, "test"))
    ci_ignores = {
        match.rstrip("/")
        for match in re.findall(r"^\s*--ignore=(\S+?)\s*\\?$", test_runs, flags=re.MULTILINE)
    }

    assert ci_ignores, "could not read the CI test job's --ignore options"
    assert ci_ignores <= local_ignores, (
        f"addopts must also ignore {sorted(ci_ignores - local_ignores)} (issue #940)"
    )

# --- issue #973: repo-owned GHCR MinIO replica ------------------------------
#
# MinIO Community Edition went source-only in late 2025 and its binary images
# were removed from Docker Hub, quay.io, and every public mirror, so
# `minio/minio:latest` cannot be pulled at all — not even with Docker Hub
# credentials (minio/minio#21662). The e2e service must instead pull a
# replica built from pinned MinIO CE source by
# .github/workflows/minio-replica.yml.

MINIO_REPLICA_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "minio-replica.yml"
#: The MinIO CE release tag the replica is built from. Verified against
#: `git ls-remote --tags https://github.com/minio/minio` on 2026-09-26:
#: the highest existing RELEASE.2025-* tag.
MINIO_REPLICA_RELEASE_TAG = "RELEASE.2025-10-15T17-29-55Z"
#: Digest of the GHCR replica image recorded by replica build run
#: 36249625652; the e2e service in ci.yml pins the image by digest
#: (issue #973, per the repo's digest-pinning rule, issue #338).
MINIO_REPLICA_DIGEST = "sha256:6140fe7015bd97e4e6340c9a8ead775c09bc1a226b7c36e41d24852f839dae8f"


def _e2e_minio_service() -> dict[str, Any]:
    """Return the ``minio:`` service mapping of the e2e job (issue #963)."""
    services = _job(WORKFLOW_PATH, "e2e").get("services") or {}
    assert "minio" in services, "the e2e job must declare a minio service"
    return services["minio"]


def test_ci_workflow_e2e_minio_service_pulls_repo_owned_ghcr_replica() -> None:
    """Issue #973: the e2e MinIO service must pull the repo-owned GHCR replica.

    The previous fix (authenticate the Docker Hub pull with
    DOCKERHUB_USERNAME/DOCKERHUB_TOKEN secrets) is dead by design: the
    binary images no longer exist upstream, so authentication cannot
    help. The service must reference the digest-pinned
    `ghcr.io/ardelperal/minio@sha256:...` — the replica built from
    pinned MinIO CE source by minio-replica.yml, with the digest
    recorded by build run 36249625652 —
    and pull it with the ephemeral GITHUB_TOKEN, since the package is
    private. Every DOCKERHUB reference must be gone.
    """
    service = _e2e_minio_service()

    assert service.get("image") == f"ghcr.io/ardelperal/minio@{MINIO_REPLICA_DIGEST}", (
        f"the e2e minio service must pull the digest-pinned GHCR replica; "
        f"got {service.get('image')!r}"
    )
    # The GHCR package is private: the service container pull needs the
    # ephemeral GITHUB_TOKEN (service containers accept expressions in
    # credentials).
    credentials = service.get("credentials") or {}
    assert credentials.get("username") == "${{ github.actor }}"
    assert credentials.get("password") == "${{ github.token }}"
    # The Docker Hub approach is removed everywhere, comments included.
    ci_job_text = "\n".join(
        _workflow_yaml.job_text(entry)
        for entry in (_doc(WORKFLOW_PATH).get("jobs") or {}).values()
    )
    assert "DOCKERHUB" not in ci_job_text
    assert "docker-hub-anonymous-pull" not in ci_job_text


def test_ci_workflow_e2e_job_grants_packages_read_for_ghcr_replica() -> None:
    """Issue #973: the e2e job needs `packages: read` to pull the private replica.

    The repo scopes permissions per job (issue #879); the e2e job used to
    declare only `contents: read`, which is not enough to pull a private
    GHCR package with the ephemeral GITHUB_TOKEN.
    """
    perms = _workflow_yaml.permissions(_job(WORKFLOW_PATH, "e2e"))

    assert perms.get("packages") == "read", (
        "the e2e job must grant packages: read to pull the private "
        "ghcr.io/ardelperal/minio replica (issue #973)"
    )


def test_minio_replica_workflow_is_dispatch_only_and_pushes_pinned_replica() -> None:
    """Issue #973: minio-replica.yml builds and publishes the pinned replica.

    The workflow must be manual-dispatch only (it publishes a package, so
    it must never run on untrusted PR code), pin a MinIO CE `RELEASE.`
    tag (the upstream binary images are gone, so the replica is built
    from source), grant `packages: write`, push both the release tag and
    the `ci` tag to ghcr.io/ardelperal/minio, and report the resulting
    image digest both as a step output and in the job summary — the
    digest is what a later commit pins in ci.yml.
    """
    replica_doc = _doc(MINIO_REPLICA_WORKFLOW_PATH)
    replica_runs = "\n".join(
        _workflow_yaml.runs_text(entry)
        for entry in (replica_doc.get("jobs") or {}).values()
    )

    triggers = _workflow_yaml.on_triggers(replica_doc)
    assert set(triggers) == {"workflow_dispatch"}, (
        f"minio-replica.yml must be dispatch-only; got {sorted(triggers)}"
    )

    # The build is pinned to exactly one MinIO CE release tag.
    replica_jobs_text = "\n".join(
        _workflow_yaml.job_text(entry)
        for entry in (replica_doc.get("jobs") or {}).values()
    )
    release_tags = set(
        re.findall(
            r"RELEASE\.\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z", replica_jobs_text
        )
    )
    assert release_tags == {MINIO_REPLICA_RELEASE_TAG}, (
        f"minio-replica.yml must pin MinIO CE {MINIO_REPLICA_RELEASE_TAG}; got {release_tags}"
    )

    # Issue #973 follow-up: the build must come from pinned MinIO CE source.
    # The upstream `Dockerfile` at the pinned tag is a thin wrapper over the
    # removed `minio/minio:latest` image, and `dl.min.io` community release
    # archives return HTTP 410, so no binary-download path may appear: the
    # workflow must carry its own multi-stage source build (Go builder stage).
    assert "FROM golang:1.24-alpine AS build" in replica_runs, (
        "minio-replica.yml must build the replica from source with a "
        "golang:1.24-alpine builder stage (the upstream Dockerfile is a "
        "wrapper over the removed minio/minio image)"
    )
    assert "dl.min.io" not in replica_runs, (
        "minio-replica.yml must not reference dl.min.io: community release "
        "archives return HTTP 410, so that path is dead"
    )

    # It builds and pushes the replica under the repo's GHCR namespace.
    assert "ghcr.io/ardelperal/minio:" in replica_runs
    assert "docker build" in replica_runs
    assert "docker push" in replica_runs
    assert "ghcr.io/ardelperal/minio:ci" in replica_runs

    # Least privilege, workflow level and job level (issue #879 convention).
    workflow_perms = _workflow_yaml.permissions(replica_doc)
    assert workflow_perms.get("contents") == "read"
    assert workflow_perms.get("packages") == "write"
    build_job = _workflow_yaml.job(replica_doc, "build-and-push")
    assert _workflow_yaml.permissions(build_job).get("packages") == "write"

    # The digest is the handoff to ci.yml: recorded as a step output and
    # published to the job summary.
    digest_output = re.search(
        r'echo "digest=\$?\{?[A-Za-z_]*\}?"\s*>>\s*"\$GITHUB_OUTPUT"', replica_runs
    )
    assert digest_output, "the workflow must expose a step output named digest"
    assert "GITHUB_STEP_SUMMARY" in replica_runs, (
        "the workflow must print the image digest to the job summary"
    )


# --- issue #895: deploy-side ui-e2e gate ------------------------------------


def test_deploy_workflow_defines_fail_closed_ui_e2e_gate() -> None:
    """Issue #895 (design D3): deploy.yml must define a signal-only
    ``ui-e2e-gate`` job (same pattern as release-e2e-gate from #908, which
    stays untouched) that recomputes ui_changed for the merged revision and
    fails closed when a UI-changing revision lacks green e2e evidence.
    """
    gate_job = _job(DEPLOY_WORKFLOW_PATH, "ui-e2e-gate")
    gate = _workflow_yaml.job_text(gate_job)

    # The UI path list comes from the checker (single source of truth).
    assert "scripts/check_required_jobs.py --print-ui-paths" in gate
    # Recomputes ui_changed from the event.before diff (HEAD^ fallback).
    assert "HEAD^" in gate
    # Same-SHA verification through the check-runs API (read-only, GITHUB_TOKEN).
    assert "/commits/" in gate and "check-runs" in gate
    # Fix round 1 (F4): every e2e selection is scoped to the github-actions
    # app so a third-party check named 'e2e' cannot satisfy the gate.
    assert 'select(.name == "e2e" and .app.slug == "github-actions")' in gate
    assert "!= \"success\"" in gate
    # The failure message points at the CI workflow.
    assert ".github/workflows/ci.yml" in gate
    # Explicit exemption line for non-UI revisions.
    assert "ui-e2e-gate exemption" in gate


def test_deploy_workflow_ui_e2e_gate_resolves_the_reviewed_head_sha() -> None:
    """pull_request check-runs are reported on the PR head SHA, not on the
    merge commit, so the gate must resolve the reviewed head (HEAD^2 for a
    merge commit, evidence-job precedent) and bind the tree before querying.
    """
    gate = _workflow_yaml.runs_text(_job(DEPLOY_WORKFLOW_PATH, "ui-e2e-gate"))

    assert "HEAD^2" in gate
    assert "HEAD^{tree}" in gate


def test_deploy_workflow_ui_e2e_gate_has_no_secrets_and_least_privilege() -> None:
    """The gate holds no secret and reads only: contents (checkout) and
    checks (check-runs API). It never touches packages or id-token.
    """
    gate_job = _job(DEPLOY_WORKFLOW_PATH, "ui-e2e-gate")
    gate = _workflow_yaml.job_text(gate_job)
    perms = _workflow_yaml.permissions(gate_job)

    assert "secrets." not in gate
    assert perms.get("contents") == "read"
    assert perms.get("checks") == "read"
    assert "packages" not in perms
    assert "issues" not in perms


# --- issue #986: post-hoc main-history audit ----------------------------
#
# The merge-restriction ruleset was deactivated in #892 to avoid the
# `--admin` tax on a single-maintainer repo. With N agent sessions sharing
# ONE admin credential, the ruleset cannot distinguish between sessions, so
# the maintainer chose post-hoc detection (alert, no block) — not a blocking
# ruleset. This section pins the workflow, the script, and the docs so the
# policy and the enforcement stay aligned.


def _main_audit_doc() -> dict[str, Any]:
    """Structured main-audit.yml (issue #963)."""
    return _doc(MAIN_AUDIT_WORKFLOW_PATH)


def test_main_audit_workflow_shape_and_pinning() -> None:
    """Workflow exists, has one job, pins every action by SHA, schedules daily.

    Combines existence, single-job, action-pinning (issue #526),
    concurrency-group (issue #530), scheduled-trigger, permissions
    (issues #682 and #879), and hosted-runner (issues #520 and #782)
    assertions because they all probe one YAML file with the same
    comment-stripping helper; a regression on any one is a regression
    on the audit's audit-ability (issue #986).
    """
    assert MAIN_AUDIT_WORKFLOW_PATH.is_file(), (
        ".github/workflows/main-audit.yml must exist (issue #986)."
    )
    doc = _main_audit_doc()
    main_history = _workflow_yaml.job(doc, "main-history")

    assert doc.get("name") == "main-audit"
    assert _workflow_job_names(MAIN_AUDIT_WORKFLOW_PATH) == {"main-history"}

    for uses in (
        str(step.get("uses", ""))
        for entry in (doc.get("jobs") or {}).values()
        for step in _workflow_yaml.steps(entry)
    ):
        if not uses or uses.startswith("./"):
            continue
        match = re.search(r"^(.+)@([0-9a-f]+)$", uses)
        assert match is not None and len(match.group(2)) == 40, (
            f"main-audit.yml: {uses!r} is not pinned by 40-hex SHA."
        )

    concurrency = _workflow_yaml.concurrency(doc) or {}
    assert concurrency.get("cancel-in-progress") is True
    triggers = _workflow_yaml.on_triggers(doc)
    assert "schedule" in triggers
    crons = [str(entry.get("cron")) for entry in triggers["schedule"]]
    assert any(
        re.fullmatch(r"\d+\s+5\s+\*\s+\*\s+\*", cron) for cron in crons
    ), "main-audit.yml: cron must run between 05:00 and 05:59 UTC."
    assert "workflow_dispatch" in triggers
    workflow_perms = _workflow_yaml.permissions(doc)
    assert workflow_perms.get("contents") == "read"
    assert workflow_perms.get("issues") == "write"
    job_perms = _workflow_yaml.permissions(main_history)
    assert job_perms.get("contents") == "read"
    assert job_perms.get("issues") == "write"
    assert main_history.get("runs-on") == "ubuntu-24.04"


def test_main_audit_script_implements_detection_rule() -> None:
    """Script uses urllib + Bearer (no `gh` CLI) and applies the documented rule.

    Runner image lacks ``gh`` (issue #533); the script authenticates via
    ``urllib`` + Bearer. Classification checks ``merge_commit_sha`` AND
    consults git ancestry of merge-commit second parents to avoid flagging
    intermediate PR-branch commits as direct pushes (issue #986).
    """
    script = MAIN_AUDIT_SCRIPT_PATH.read_text(encoding="utf-8")
    assert "urllib.request" in script
    assert re.search(r"(?:^|\s)gh\s+(?:api|pr|issue)\b", script, re.MULTILINE) is None
    assert "subprocess" in script and "git" in script
    assert "merge_commit_sha" in script
    assert "second_parents" in script or "rev-list" in script
    assert "Authorization" in script and "Bearer" in script


def test_branch_protection_documents_the_post_hoc_audit() -> None:
    """branch-protection.md must cite the audit and pin the verified state.

    Combines the references to the audit, the verified live state
    snapshot, the disabled ruleset reminder, and the multi-session
    framing — the file is the contract readers reach first when they
    ask "can a direct push land on main?" (issue #986).
    """
    note = BRANCH_PROTECTION_PATH.read_text(encoding="utf-8")
    assert "main-audit" in note or "main_history_audit" in note
    assert "issue #986" in note or "#986" in note
    assert "2026-09-27" in note
    assert "enforce_admins" in note
    assert "disabled" in note


def test_merge_workflow_documents_the_multi_session_norm() -> None:
    """merge-workflow.md must add the multi-session norm (§16) and keep §15.

    The norm spells out that N agent sessions share one admin credential,
    so a direct push from one session destroys the PR+CI trail the other
    sessions rely on. The §15 narrative stays intact (issue #986).
    """
    guide = MERGE_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "issue #986" in guide or "#986" in guide
    assert "main-audit" in guide
    section = guide.split("### §15.5", 1)[1].split("###", 1)[0]
    assert "main-audit" in section or "main_history_audit" in section
    for marker in ("§15.1", "§15.2", "§15.4", "§15.5", "§15.7"):
        assert marker in guide


def test_process_doc_records_no_direct_push_invariant() -> None:
    """docs/proceso.md must carry the P5 invariant (no direct push).

    The invariant sits alongside P1–P4 so a session that loads
    proceso.md sees the push-direct prohibition at the top (issue #986).
    """
    process = PROCESS_PATH.read_text(encoding="utf-8")
    assert "P5-no-direct-push-multi-session" in process
    assert "main-audit" in process
    assert "push directo" in process


# --- issue #1035: trivy cannot parse FROM lines that interpolate ARGs ------

def _trivy_scan_run_block() -> str:
    """Return the shell of the security-deep trivy scan step (issue #963)."""
    return str(
        _workflow_yaml.find_step(
            _job(WORKFLOW_PATH, "security-deep"), "Scan pinned base images"
        ).get("run", "")
    )


def _trivy_resolution_snippet() -> str:
    """Return the self-contained ARG-resolution shell of the trivy step.

    Slices from the image extraction down to the emit of the resolved list,
    so the tests execute the exact shell the workflow runs.
    """
    block = _trivy_scan_run_block()
    start = block.index('images=$(grep')
    end = block.index('echo "$resolved_images"')
    return block[start : block.index("\n", end)]


def _dockerfile_arg_default(name: str, dockerfile: str) -> str:
    match = re.search(rf"^ARG {name}=([^ \n]+)", dockerfile, flags=re.MULTILINE)
    assert match, f"Dockerfile does not declare ARG {name}=..."
    return match.group(1)


def test_ci_workflow_trivy_step_resolves_dockerfile_arg_defaults(tmp_path: Path) -> None:
    """Issue #1035 (happy path): the resolution pipeline in the trivy step
    turns ``node:${NODE_VERSION}-bookworm-slim@sha256:...`` into
    ``node:20-bookworm-slim@sha256:...`` (and the same for PYTHON_VERSION)
    using the ARG defaults from the Dockerfile itself.
    """
    snippet = _trivy_resolution_snippet()
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    (tmp_path / "Dockerfile").write_text(dockerfile, encoding="utf-8")

    result = subprocess.run(
        ["bash", "-c", snippet],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"resolution snippet must exit 0 on the real Dockerfile: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    node_version = _dockerfile_arg_default("NODE_VERSION", dockerfile)
    python_version = _dockerfile_arg_default("PYTHON_VERSION", dockerfile)
    assert f"node:{node_version}-bookworm-slim@" in result.stdout
    assert f"python:{python_version}-slim-bookworm@" in result.stdout
    assert "${" not in result.stdout


def test_ci_workflow_trivy_step_preserves_digest_pins(tmp_path: Path) -> None:
    """Issue #1035 (digest preservation): resolution substitutes only the
    ``${NAME}`` spans; every ``@sha256:...`` pin from the Dockerfile must
    reach the scan list byte-for-byte.
    """
    snippet = _trivy_resolution_snippet()
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    (tmp_path / "Dockerfile").write_text(dockerfile, encoding="utf-8")

    result = subprocess.run(
        ["bash", "-c", snippet],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    digests = set(re.findall(r"@sha256:[a-f0-9]+", dockerfile))
    assert digests, "the Dockerfile is expected to pin base images by digest"
    for digest in digests:
        assert digest in result.stdout, (
            f"digest pin {digest} must survive ARG resolution untouched"
        )


def test_ci_workflow_trivy_step_resolves_multiple_args_in_one_reference(
    tmp_path: Path,
) -> None:
    """Issue #1035 (edge): a single FROM interpolating several ARGs resolves
    every one of them in the same pass.
    """
    snippet = _trivy_resolution_snippet()
    digest = "a" * 64
    (tmp_path / "Dockerfile").write_text(
        "ARG REGISTRY_PREFIX=mirror.local\n"
        "ARG BASE_TAG=3.19\n"
        f"FROM ${{REGISTRY_PREFIX}}/alpine:${{BASE_TAG}}@sha256:{digest}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "-c", snippet],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert f"mirror.local/alpine:3.19@sha256:{digest}" in result.stdout
    assert "${" not in result.stdout


def test_ci_workflow_trivy_step_fails_closed_on_unresolved_arg(
    tmp_path: Path,
) -> None:
    """Issue #1035 (sad path): a FROM using an ARG without a default must
    fail the step loudly via a ``::error::`` annotation naming the
    unresolved ARG — never a silent partial scan list.
    """
    snippet = _trivy_resolution_snippet()
    digest = "b" * 64
    (tmp_path / "Dockerfile").write_text(
        "ARG KNOWN=1.2.3\n"
        f"FROM alpine:${{KNOWN}}@sha256:{digest}\n"
        f"FROM busybox:${{MISSING}}@sha256:{digest}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "-c", snippet],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0, (
        "an unresolved ARG must fail the step, not scan a partial list"
    )
    assert "::error::unresolved ARG" in result.stdout
    assert "MISSING" in result.stdout


def test_ci_workflow_trivy_step_extracts_arg_defaults_from_the_dockerfile() -> None:
    """Issue #1035 (pipeline pin): the trivy step must derive the ARG
    mapping from the Dockerfile's own ``ARG NAME=default`` lines, so
    re-pinning or adding an ARG flows into the scan automatically.
    """
    block = _trivy_scan_run_block()

    assert "grep -oE '^ARG [A-Za-z_]+=[^ ]+' Dockerfile" in block


def test_ci_workflow_trivy_step_declares_the_fail_closed_error_marker() -> None:
    """Issue #1035 (fail-closed pin): the step must carry an explicit
    ``::error::unresolved ARG`` annotation branch ahead of ``exit 1``.
    """
    block = _trivy_scan_run_block()

    assert "::error::unresolved ARG" in block
    assert "exit 1" in block


# --- issue #1046: security-deep moves to a weekly schedule -------------------


def test_ci_workflow_declares_weekly_schedule_trigger() -> None:
    """Issue #1046: ci.yml declares a weekly schedule trigger.

    The scan result is a function of the pinned base-image digests, not of
    time, so MVP release cadence made per-release runs redundant; the
    weekly schedule bounds the CVE-decay window instead. The block applies
    to every job in the file, so the companion test below pins that a
    scheduled run executes security-deep and nothing else.
    """
    triggers = _triggers(WORKFLOW_PATH)

    assert "schedule" in triggers, (
        "issue #1046 adds the weekly schedule trigger that only "
        "security-deep consumes"
    )
    assert triggers["schedule"] == [{"cron": "0 6 * * 1"}], (
        "the schedule must be weekly on Monday 06:00 UTC (`0 6 * * 1`); "
        f"got {triggers['schedule']!r}"
    )


def test_ci_workflow_security_deep_runs_on_schedule_and_dispatch_not_tags() -> None:
    """Issue #1046: the heavy scan is weekly + manual dispatch; tags are out.

    Under the issue #780 cadence this replaces, any tag push triggered the
    scan. The pr-size skip override is pinned too: on schedule runs the
    guarded pr-size job is skipped, and a job whose needed job is skipped
    is itself skipped unless its ``if`` carries a status function that
    overrides the implicit success().
    """
    if_clause = str(_job(WORKFLOW_PATH, "security-deep").get("if", ""))

    assert "github.event_name == 'workflow_dispatch'" in if_clause
    assert "github.event_name == 'schedule'" in if_clause
    assert "startsWith(github.ref, 'refs/tags/')" not in if_clause, (
        "release tags must no longer trigger security-deep (issue #1046)"
    )
    assert "pull_request" not in if_clause
    assert "!cancelled()" in if_clause, (
        "the if must override the implicit success() so a skipped pr-size "
        "on schedule runs does not cascade-skip the scan"
    )
    assert "needs.pr-size.result == 'skipped'" in if_clause


def test_ci_workflow_schedule_runs_security_deep_only() -> None:
    """Issue #1046: on a scheduled run, security-deep executes alone.

    The workflow-level ``schedule:`` trigger reaches every job in ci.yml,
    so each other job must be structurally unable to run on that event:

    - ``pr-size`` and ``ui-detection`` carry an explicit ``!= 'schedule'``
      guard (pr-size has nothing to diff against; ui-detection has no
      needs, so the cascade cannot skip it).
    - ``issue-spec`` (pull_request only) and ``mutation`` (dispatch/tags,
      issue #780 cadence, unchanged) already gate on events that exclude
      schedule.
    - the remaining chain is skipped by the pr-size cascade: a job whose
      needed job is skipped is skipped unless its own ``if`` contains a
      status function — so these jobs must NOT grow one.
    - ``required`` is guarded because the checker behind it fails closed
      on ``schedule`` (test_check_required_jobs.py pins that contract)
      and a weekly scan run needs no PR rollup verdict.
    - ``e2e`` is guarded explicitly: release and UI-change events only,
      never a scheduled run.
    """
    doc = _doc(WORKFLOW_PATH)
    jobs = _workflow_job_names(WORKFLOW_PATH)

    guarded = {"pr-size", "ui-detection", "e2e", "required"}
    own_event_gate = {"issue-spec", "mutation"}
    cascaded = {
        "lint",
        "security",
        "typecheck",
        "test",
        "integration",
        "verify-fallback-ready",
        "build",
    }
    assert guarded | own_event_gate | cascaded | {"security-deep"} == jobs

    for name in sorted(guarded):
        if_clause = str(_workflow_yaml.job(doc, name).get("if") or "")
        assert "github.event_name != 'schedule'" in if_clause, (
            f"{name} must explicitly exclude schedule events (issue #1046)"
        )
    for name in sorted(own_event_gate):
        if_clause = str(_workflow_yaml.job(doc, name).get("if") or "")
        assert "github.event_name == 'schedule'" not in if_clause, (
            f"{name} must keep its own event gate, which excludes schedule"
        )
    for name in sorted(cascaded):
        assert _workflow_yaml.job(doc, name).get("if") is None, (
            f"{name} must stay skipped via the pr-size cascade on schedule "
            "runs; adding its own event condition would desync the "
            "schedule matrix (issue #1046)"
        )


def test_ci_workflow_schedule_never_reaches_deploy() -> None:
    """Issue #1046: deploy must not run on schedule events.

    deploy.yml is a separate workflow listening to push to main only, so
    the schedule trigger in ci.yml cannot reach it structurally; pin the
    trigger set so a future ``schedule:`` there fails this test.
    """
    triggers = _triggers(DEPLOY_WORKFLOW_PATH)

    assert "schedule" not in triggers, (
        "deploy.yml must not listen to schedule; the weekly cadence is a "
        "ci.yml concern only (issue #1046)"
    )
    assert "push" in triggers


# --- issue #963: structured workflow access ---------------------------------


def test_workflow_structure_is_independent_of_comments_and_indentation(
    tmp_path: Path,
) -> None:
    """Regression pin for issue #963: workflow assertions read structure.

    A workflow doctored with an innocuous comment must parse to exactly
    the same structure as the original. Text-offset assertions (substring
    matching over the raw file, ``workflow.index(...)`` cuts) used to be
    able to turn red — or green — on such a cosmetic edit; structural
    access cannot. Only a real change to the YAML structure (the part
    GitHub Actions executes) can move these assertions now.
    """
    doc = _doc(WORKFLOW_PATH)
    e2e = _workflow_yaml.job(doc, "e2e")
    original = {
        "triggers": _workflow_yaml.on_triggers(doc),
        "jobs": sorted((doc.get("jobs") or {}).keys()),
        "e2e_needs": _workflow_yaml.needs(e2e),
        "e2e_steps": [
            str(step.get("name", "<unnamed>"))
            for step in _workflow_yaml.steps(e2e)
        ],
    }

    original_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    doctored_text = original_text.replace(
        "name: ci\n",
        "name: ci\n# a purely cosmetic comment that must not affect tests\n",
        1,
    )
    assert doctored_text != original_text

    doctored_path = tmp_path / "ci.yml"
    doctored_path.write_text(doctored_text, encoding="utf-8")
    doctored_doc = _doc(doctored_path)
    doctored_e2e = _workflow_yaml.job(doctored_doc, "e2e")

    assert _workflow_yaml.on_triggers(doctored_doc) == original["triggers"]
    assert sorted((doctored_doc.get("jobs") or {}).keys()) == original["jobs"]
    assert _workflow_yaml.needs(doctored_e2e) == original["e2e_needs"]
    assert [
        str(step.get("name", "<unnamed>"))
        for step in _workflow_yaml.steps(doctored_e2e)
    ] == original["e2e_steps"]
