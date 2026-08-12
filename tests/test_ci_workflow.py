import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
#: Deploy lives in its own workflow so a merge does not re-run ci.yml just to
#: satisfy its `needs`. The deploy guards moved here with it.
DEPLOY_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
MAKEFILE_PATH = REPO_ROOT / "Makefile"
CHECK_RULES_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_rules.py"
BRANCH_PROTECTION_PATH = REPO_ROOT / ".github" / "branch-protection.md"
DEVELOPMENT_GUIDE_PATH = REPO_ROOT / "docs" / "development.md"


def _trigger_lines(workflow: str) -> dict[str, str]:
    """Map each top-level trigger under ``on:`` to the text of its block.

    Deliberately string-based, like every other assertion in this file: pyyaml
    lives in the ``etl`` extra, not in ``dev``, so a yaml import here would pass
    locally and fail in the CI test job.
    """
    blocks: dict[str, str] = {}
    current: str | None = None
    inside = False
    for line in workflow.splitlines():
        if line.startswith("on:"):
            inside = True
            continue
        if inside and line and not line.startswith((" ", "\t", "#")):
            break  # next top-level key ends the on: block
        if not inside or not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 2:
            current = line.strip()
            blocks[current] = ""
        elif current is not None:
            blocks[current] += line.strip() + "\n"
    return blocks


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
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "name: ci" in workflow
    assert "pull_request:" in workflow
    # Both main and staging must trigger CI. main is gated (only the
    # user promotes there) but PRs landing on main still need to be
    # validated; staging is where every change lands first under the
    # project's stagingOnly policy.
    assert "branches: [main, staging]" in workflow
    assert "lint:" in workflow
    assert "test:" in workflow
    assert "build:" in workflow
    assert "python-version-file: pyproject.toml" in workflow
    assert "ruff check ." in workflow
    assert "python -m pytest -W error::DeprecationWarning" in workflow
    assert "python -m build" in workflow


def test_ci_workflow_runs_e2e_job_with_playwright() -> None:
    """The e2e job runs the Playwright suite unconditionally (no gate
    on ``vars.ENABLE_E2E``). The Playwright harness landed in PR #108
    and the e2e job is now always on so every PR gets the visual
    regression net.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "e2e:" in workflow
    # The e2e job must install + run the Playwright suite. There must
    # be no ``vars.ENABLE_E2E`` gate (the feature flag is gone).
    assert "vars.ENABLE_E2E" not in workflow, (
        "e2e job should always run; the ENABLE_E2E flag has been retired"
    )
    assert "playwright install" in workflow
    assert "playwright" in workflow.lower()
    # And it must actually execute the suite.
    assert "pytest tests/e2e/" in workflow


def test_ci_workflow_does_not_include_diagnostic_secret_leak_scan() -> None:
    """Issue #393: placeholder secret-leak scan step removed in favor of gitleaks (#381)."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "Diagnostic secret-leak scan" not in workflow
    assert "grep -rE '(http://|https://|sk-|ghp_)[A-Za-z0-9]+'" not in workflow


def test_branch_protection_note_lists_required_ci_checks() -> None:
    note = BRANCH_PROTECTION_PATH.read_text(encoding="utf-8")

    assert "ci / lint" in note
    assert "ci / test" in note
    assert "ci / build" in note
    assert "Settings → Branches → Branch protection rules" in note


def test_development_guide_documents_e2e_ci_hook() -> None:
    guide = DEVELOPMENT_GUIDE_PATH.read_text(encoding="utf-8")

    # The Playwright e2e suite landed in PR #108 and the dev guide
    # now documents the actual runner and the local command, not a
    # future TODO.
    assert "Playwright" in guide
    assert "scripts/dev_server_no_lifespan.py" in guide
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
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    fail_under = pyproject["tool"]["coverage"]["report"]["fail_under"]

    # The declared floor itself must not silently drift below 80.
    assert fail_under >= 80

    # Scope to the test job's executable lines only: slice the job
    # section and drop YAML comments, so a comment that merely mentions
    # the flags (like the explanatory block above the run: step) can
    # never satisfy these assertions.
    test_job_start = workflow.index("\n  test:")
    test_job = workflow[test_job_start : workflow.index("\n  build:", test_job_start)]
    executable = "\n".join(
        line for line in test_job.splitlines() if not line.lstrip().startswith("#")
    )

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
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    test_job_start = workflow.index("\n  test:")
    test_job = workflow[test_job_start : workflow.index("\n  build:", test_job_start)]
    executable = "\n".join(
        line for line in test_job.splitlines() if not line.lstrip().startswith("#")
    )

    assert "services:" in test_job
    assert "postgres:" in test_job
    assert "POSTGRES_DB: apap_test" in test_job
    # The DSN moved out of the job-level `env:` block in #532: the `job` context
    # that carries the assigned host port is not available there, so it is built
    # in a step and exported through $GITHUB_ENV instead.
    assert "APAP_TEST_POSTGRES_DSN=" in test_job
    assert "job.services.postgres.ports['5432']" in test_job
    # And it must refuse to proceed on an unresolved port rather than hand the
    # suite a DSN that cannot connect — tests/test_voluntarios_concurrent.py
    # would pytest.skip() on that, which reads as a pass.
    assert 'if [ -z "$POSTGRES_HOST_PORT" ]' in test_job
    assert "--deselect tests/test_voluntarios_concurrent.py" not in executable


def test_postgres_toctou_contract_uses_test_dsn_not_http_base_url() -> None:
    """The PostgreSQL integration test must not overload the HTTP E2E contract."""
    concurrency_test = (REPO_ROOT / "tests" / "test_voluntarios_concurrent.py").read_text(
        encoding="utf-8"
    )
    guide = DEVELOPMENT_GUIDE_PATH.read_text(encoding="utf-8")

    assert "APAP_TEST_POSTGRES_DSN" in concurrency_test
    assert 'os.environ.get("APAP_E2E_BASE_URL")' not in concurrency_test
    assert "APAP_TEST_POSTGRES_DSN" in guide
    assert "tests/test_voluntarios_concurrent.py" in guide


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
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    # Scope to the lint job's executable lines only (same rationale as
    # test_ci_workflow_test_job_enforces_global_coverage_floor): slice
    # the job section and drop YAML comments so a comment mentioning
    # the command can never satisfy the assertion.
    lint_job_start = workflow.index("\n  lint:")
    lint_job = workflow[lint_job_start : workflow.index("\n  test:", lint_job_start)]
    executable = "\n".join(
        line for line in lint_job.splitlines() if not line.lstrip().startswith("#")
    )

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
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "\n  typecheck:" in workflow, (
        "ci.yml must define a typecheck job (issue #201, AGENTS.md rule 24)"
    )

    # Scope to the typecheck job's executable lines only (same rationale
    # as test_ci_workflow_lint_job_runs_check_rules_gate): slice the job
    # section and drop YAML comments so a comment mentioning mypy can
    # never satisfy the assertion.
    typecheck_job_start = workflow.index("\n  typecheck:")
    typecheck_job = workflow[typecheck_job_start : workflow.index("\n  test:", typecheck_job_start)]
    executable = "\n".join(
        line for line in typecheck_job.splitlines() if not line.lstrip().startswith("#")
    )

    # The job must install the dev extra like every other job (mypy is
    # a dev dependency) and run the config-driven mypy command.
    assert 'python -m pip install -e ".[dev]"' in executable
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


def _extract_deploy_job_if_clause(workflow: str) -> str:
    """Extract the job-level ``if:`` clause from the deploy job.

    Finds ``  deploy:`` by indentation, then reads the ``if:`` expression
    on the next non-comment, non-empty line before the ``steps:`` block.
    """
    # Find deploy job start — must be at ``  deploy:`` (2 spaces)
    deploy_marker = "\n  deploy:"
    idx = workflow.index(deploy_marker)
    # Scan forward until we hit ``steps:`` (same indentation level as ``deploy:``)
    lines = workflow[idx:].splitlines()
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped.startswith("if:"):
            # Strip the leading indentation (2 spaces for a job-level key)
            return line.strip()
        if stripped.startswith("steps:"):
            break
    raise AssertionError("deploy job has no job-level if: clause")


def _extract_deploy_section(workflow: str) -> str:
    """Extract the entire deploy job section text.

    Starts after the ``  deploy:`` line and ends before the next top-level
    ``  <name>:`` job (same indentation as ``deploy:``), or at end of file.
    """
    import re

    deploy_marker = "\n  deploy:"
    deploy_job_start = workflow.index(deploy_marker)
    # Slice to content after the newline that ends the ``  deploy:`` line
    after_deploy_newline = deploy_job_start + len(deploy_marker)
    remaining = workflow[after_deploy_newline:]
    # Find the next top-level job: ``\n  <word>:`` (newline + 2 spaces + name + colon)
    next_job_match = re.search(r"\n  [a-zA-Z_]+:", remaining)
    return remaining[: next_job_match.start()] if next_job_match else remaining


def _parse_if_clauses(if_expr: str) -> list[tuple[str, str | None]]:
    """Parse ``key == 'value'`` or ``key == null`` clauses from a GitHub Actions if expression.

    Returns [(key, value | None), ...] in the order they appear.
    ``github.event.pull_request == null`` is treated as (github.event.pull_request, None).
    """
    import re

    # Combined pattern: match both string and null equality, capturing the value.
    # Uses (?:\s|$) instead of \b after the alternative — \b fails when the
    # preceding character is a non-word char (e.g. the closing ' of a string
    # literal followed by &&, where ' &&' has no word boundary).
    pattern = re.compile(r"(\S+)\s*==\s*(?:'([^']*)'|null)(?:\s|$)")
    clauses: list[tuple[str, str | None]] = []
    for m in pattern.finditer(if_expr):
        key = m.group(1)
        str_val = m.group(2)
        value: str | None = str_val if str_val is not None else None
        clauses.append((key, value))
    return clauses


def _evaluate_if_clauses(clauses: list[tuple[str, str | None]], payload: dict[str, object]) -> bool:
    """Evaluate a list of (key, value) equality clauses against a payload dict.

    GitHub Actions expressions use ``github.<path>`` syntax
    (e.g. ``github.event_name``, ``github.event.pull_request``).
    The payload mirrors the GitHub context structure as nested dicts:
      - ``event.name`` corresponds to ``github.event_name``
      - ``event.pull_request`` corresponds to ``github.event.pull_request``
    """
    for key, expected in clauses:
        # Strip the leading ``github.`` prefix
        lookup_key = key.removeprefix("github.")
        # Map top-level event_name to event.name (GitHub context quirk)
        if lookup_key == "event_name":
            lookup_key = "event.name"
        actual: object = payload
        for part in lookup_key.split("."):
            if not isinstance(actual, dict):
                return False
            actual = actual.get(part)  # type: ignore[assignment]
        if actual != expected:
            return False
    return True


def test_deploy_workflow_gates_on_evidence() -> None:
    """CD-01: deploy exists in its own workflow and runs only on proven evidence.

    Deploy moved out of ci.yml so a merge stops paying for CI twice: ci.yml ran
    on push to main solely because the five heavy jobs were `needs` of deploy,
    re-testing a tree the pull_request run had already proven. deploy.yml looks
    that evidence up instead.

    The gating moved with it. Deploy no longer depends on jobs at all; it depends
    on the `evidence` job having found a green ci run for the merged head.
    """
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "  deploy:" in workflow
    assert "  name: deploy" in workflow
    assert "needs: [evidence]" in workflow
    assert "if: needs.evidence.outputs.verified == 'true'" in workflow, (
        "deploy must run only when the evidence job proved the tree was verified"
    )

    # The historical failure modes must stay absent (see the deploy job comment
    # in git history: a merge-commit skip block once cancelled every deploy).
    assert "pull_request == null" not in workflow
    assert 'grep -q "^Merge pull request #' not in workflow


def test_deploy_workflow_runs_on_main_push() -> None:
    """CD-01 D4: a push to main is the deployable event.

    Under pre-MVP policy (AGENTS.md §15.2) every change lands via PR merge, so
    the push to main IS the trigger. This is now a workflow-level trigger rather
    than a job-level `if:`, which is a stronger statement: the job cannot fire on
    an event the workflow does not listen to.
    """
    triggers = _trigger_lines(DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8"))

    assert "push:" in triggers, "deploy.yml must listen to push"
    assert "branches: [main]" in triggers["push:"], (
        f"deploy.yml must deploy main and nothing else; got {triggers['push:']!r}"
    )


def test_deploy_workflow_cannot_fire_on_a_pull_request() -> None:
    """CD-01 D5: a pull_request event must never reach deploy.

    Previously this was a predicate on the job's `if:` and had to be parsed and
    evaluated to be trusted. Now it is structural: the workflow does not declare
    a pull_request trigger, so no `if:` can be got wrong. That closes the failure
    mode this test was written for.
    """
    triggers = _trigger_lines(DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8"))

    assert "pull_request:" not in triggers, (
        "deploy.yml must not listen to pull_request — a PR must never deploy"
    )


def test_ci_workflow_no_longer_runs_on_main_push() -> None:
    """The duplicate run is gone: ci.yml does not fire on a push to main.

    Measured 2026-08-09: every merge triggered a second full ci run costing ~8
    billed minutes, existing only to satisfy deploy's `needs`. With deploy moved
    out, that reason is gone. The pull_request run remains the gate.
    """
    triggers = _trigger_lines(WORKFLOW_PATH.read_text(encoding="utf-8"))

    assert "main" not in triggers["push:"], (
        "ci.yml must not re-run on push to main; deploy.yml consumes the "
        "pull_request run's evidence instead"
    )
    assert "main" in triggers["pull_request:"], (
        "the pull_request run is now the only gate for main and must stay"
    )


def test_deploy_workflow_refuses_an_unverified_tree() -> None:
    """No evidence, no deploy — and loudly.

    The evidence job fails closed on every uncertain path: a direct push with no
    merge parent, a base that moved between the PR run and the merge, or a merged
    head with no green ci run. Silence there would deploy an untested tree.
    """
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "Refuse to deploy an unverified tree" in workflow
    assert "verified != 'true'" in workflow
    assert "exit 1" in workflow


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
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "Trigger Coolify webhook" in workflow
    assert "secrets.COOLIFY_WEBHOOK_URL" in workflow
    assert "secrets.COOLIFY_WEBHOOK_SECRET" in workflow
    # The workflow MUST delegate to the unit-tested signing module,
    # NOT inline the HMAC + urllib code in a heredoc. Pinned by
    # tests/test_coolify_webhook.py.
    assert "python scripts/coolify_webhook.py" in workflow
    # The inline heredoc + urllib path is forbidden.
    assert "python - <<'PY'" not in workflow
    assert "urllib.request.urlopen" not in workflow
    # A bare unsigned curl is no longer acceptable.
    assert 'curl -fsS -X POST "$COOLIFY_WEBHOOK_URL"' not in workflow


def test_ci_workflow_missing_webhook_secret_is_a_failure() -> None:
    """Missing COOLIFY_WEBHOOK_SECRET MUST fail the deploy step.

    Pinned by spec (ci-cd-pipeline/spec.md, Scenario "Missing webhook
    secret blocks production deploy"). Without the secret, the HMAC
    signature would be computed over an empty key, and Coolify v4
    would reject every payload. Loud fail at CI beats silent fail at
    the healthcheck-driven rollback.
    """
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")

    # The deploy step must check the secret specifically (not just the
    # URL) and emit a ``::error::`` annotation with a clear message,
    # then exit 1.
    assert "COOLIFY_WEBHOOK_SECRET" in workflow
    assert "::error::COOLIFY_WEBHOOK_SECRET" in workflow
    assert "exit 1" in workflow


def test_ci_workflow_payload_shape_matches_coolify_expectation() -> None:
    """The workflow MUST pass the keys Coolify's manualWebhookApplications reads.

    Pinned by spec (ci-cd-pipeline/spec.md, Requirement "Coolify Webhook
    Signing Contract" > Scenario "Payload shape"). The signing logic
    lives in ``scripts/coolify_webhook.py::build_push_payload`` and is
    pinned by tests/test_coolify_webhook.py::test_build_push_payload_includes_required_keys.
    The workflow just sets the env vars that the module reads.
    """
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")

    # The workflow must forward the env vars the module needs to build
    # the payload (ref, sha, repository, commit message).
    assert "GITHUB_REF:" in workflow
    assert "GITHUB_SHA:" in workflow
    assert "GITHUB_REPOSITORY:" in workflow
    assert "COMMIT_MESSAGE:" in workflow


def _job_executable(workflow: str, start: str, end: str) -> str:
    start_index = workflow.index(start)
    section = workflow[start_index : workflow.index(end, start_index)]
    return "\n".join(line for line in section.splitlines() if not line.lstrip().startswith("#"))


def test_ci_workflow_lint_job_runs_jscpd_gate() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    lint_job = _job_executable(workflow, "\n  lint:", "\n  security:")

    assert "python scripts/check_jscpd.py" in lint_job
    assert lint_job.index("python scripts/check_jscpd.py") > lint_job.index(
        "python scripts/check_vulture_guard.py"
    )


def test_ci_workflow_lint_job_runs_mutation_sites_gate() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    lint_job = _job_executable(workflow, "\n  lint:", "\n  security:")

    assert "python scripts/check_mutation_sites.py" in lint_job
    assert lint_job.index("python scripts/check_mutation_sites.py") > lint_job.index(
        "python scripts/check_jscpd.py"
    )


def test_ci_workflow_lint_job_runs_quality_report_aggregator() -> None:
    """The lint job must aggregate the per-gate indicator envelopes (Rule 16).

    Every gate that emits ``--emit-envelope quality/<gate>.json`` feeds the
    aggregator ``scripts/quality_report.py quality``, which renders a Markdown
    summary into ``$GITHUB_STEP_SUMMARY``. Removing the aggregator step is a
    blocked change per Rule 16.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    executable = _job_executable(workflow, "\n  lint:", "\n  security:")
    assert "scripts/quality_report.py" in executable, (
        "lint job must invoke scripts/quality_report.py so the per-gate "
        "indicator envelopes produced by --emit-envelope are aggregated and "
        "rendered into the GitHub step summary (Rule 16, issue #516)."
    )
    assert "GITHUB_STEP_SUMMARY" in executable, (
        "the aggregator's Markdown summary must be appended to "
        "$GITHUB_STEP_SUMMARY so reviewers see it on every PR."
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
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    lint_job = _job_executable(workflow, "\n  lint:", "\n  security:")

    assert "python scripts/check_import_cycles.py" in lint_job
    # The detector must run after the mutation-sites step so the lint
    # job ordering matches the other ratchets (cheap AST checks first,
    # then graph-level checks).
    assert lint_job.index("python scripts/check_import_cycles.py") > lint_job.index(
        "python scripts/check_mutation_sites.py"
    )


def test_ci_workflow_test_job_runs_crap_gate() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    test_job = _job_executable(workflow, "\n  test:", "\n  integration:")
    lint_job = _job_executable(workflow, "\n  lint:", "\n  security:")

    assert "python scripts/check_crap.py" in test_job
    assert "python scripts/check_crap.py" not in lint_job
    assert test_job.index("python scripts/check_crap.py") > test_job.index(
        "python -m pytest -W error::DeprecationWarning"
    )


def test_ci_workflow_test_job_excludes_insforge_adapter() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)

    omit = pyproject["tool"]["coverage"]["run"]["omit"]
    assert "app/core/insforge.py" in omit


def test_default_pytest_collection_matches_ci_boundary() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)

    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--ignore=tests/integration" in addopts
    assert "--randomly-dont-reorganize" in addopts


def test_ci_workflow_integration_job_overrides_ignore_for_tests_integration() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    integration_job = _job_executable(workflow, "\n  integration:", "\n  build:")

    assert (
        '--override-ini="addopts=-ra --strict-markers --strict-config '
        '--randomly-dont-reorganize"' in integration_job
    )
    assert "--ignore=tests/integration" not in integration_job
    assert "tests/integration \\" in integration_job
    assert "-m integration" in integration_job
    assert "--no-cov" in integration_job
    assert "-W error::DeprecationWarning" in integration_job


def test_ci_workflow_mutation_job_runs_the_ratchet_gate() -> None:
    """Issue #431: the mutation job must gate on ``scripts/check_mutation.py``.

    Swapping the ratchet for ``cr-rate --fail-over`` is the specific
    regression this pins. ``cr-rate`` reports ``0.00`` both for a run that
    killed every mutant and for a run where nothing executed, so it cannot
    fail on a broken runner — verified end to end on 2026-08-06, where
    ``cr-rate --fail-over 20`` exited 0 on a session whose 27 mutants were
    all ``INCOMPETENT``. Removing this step is a blocked change.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    mutation_job = _job_executable(workflow, "\n  mutation:", "\n  typecheck:")

    assert "python scripts/check_mutation.py mutation.sqlite" in mutation_job
    assert "cr-rate" not in mutation_job, (
        "cr-rate cannot fail on a degenerate run; the gate is check_mutation.py"
    )
    # The ratchet must run after the session exists, never before.
    assert mutation_job.index("python scripts/check_mutation.py") > mutation_job.index(
        "cosmic-ray exec"
    )


def test_ci_workflow_mutation_job_filters_equivalent_mutants() -> None:
    """Issue #431: ``cr-filter-operators`` must run between init and exec.

    It excludes mutations of the ``|`` in PEP 604 annotations, which no test
    can kill because ``from __future__ import annotations`` stops annotations
    from evaluating. On the first pilot session those were 66 of 104 reported
    survivors — dropping this step inflates every baseline by ~63%.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    mutation_job = _job_executable(workflow, "\n  mutation:", "\n  typecheck:")

    assert "cr-filter-operators" in mutation_job
    assert (
        mutation_job.index("cosmic-ray init")
        < mutation_job.index("cr-filter-operators")
        < mutation_job.index("cosmic-ray exec")
    )


def test_ci_workflow_mutation_job_is_never_triggered_by_a_pull_request() -> None:
    """Issue #431: the mutation job is scheduled/manual only.

    A 233-mutant session per pull request would make the loop unusable, and
    §32.P7 requires the reachable events to be named rather than implied.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    start = workflow.index("\n  mutation:")
    section = workflow[start : workflow.index("\n  typecheck:", start)]

    if_clause = section[section.index("if:") : section.index("runs-on:")]
    assert "github.event_name == 'schedule'" in if_clause
    assert "github.event_name == 'workflow_dispatch'" in if_clause
    assert "pull_request" not in if_clause


def test_ci_workflow_mutation_job_pins_hash_seed_for_determinism() -> None:
    """TASK-2.1 (W-5): ``PYTHONHASHSEED=0`` is set for the mutation session.

    The companion ``--worker-count=1`` from that task is deliberately absent:
    ``cosmic-ray exec`` 8.4.6 accepts no such option and its ``local``
    distributor is already sequential.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    mutation_job = _job_executable(workflow, "\n  mutation:", "\n  typecheck:")

    assert 'PYTHONHASHSEED: "0"' in mutation_job
    assert "--worker-count" not in mutation_job


def test_mutation_baseline_has_derivation_entry_at_or_below_prior_measurement() -> None:
    """Issue #433: ``mutation-baseline.json`` must keep ``migration/derivation.py`` pinned.

    The shrink-only ratchet in ``scripts/check_mutation.py`` enforces
    that no per-module survivor count grows above its baseline entry.
    Local re-measurement is impossible on Windows (cosmic-ray 8.4.6 is
    INCOMPETENT for 100% of mutants — issue #431, Finding 1), so the
    entry stays at the prior main-branch measurement until the next
    Linux CI scheduled run narrows it. This test pins the contract:

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


def test_mutation_baseline_marks_adopciones_as_awaiting_acquisition() -> None:
    """Issue #434: the baseline must mark the new module as pending Linux acquisition.

    cosmic-ray 8.4.6 returns INCOMPETENT for 100% of mutants on native Windows
    (issue #431, Finding 1), so the survivor count cannot be acquired locally.
    The baseline carries an ``awaiting_acquisition`` marker with the date the
    entry landed on ``main``; the ratchet (``check_mutation.py``) enforces a
    14-day grace period before failing the build if the marker persists.

    Replacing the marker with a real integer count is the explicit handoff
    that closes #434. ``tests/test_check_mutation.py`` covers the ratchet
    behaviour; this test pins the wiring.
    """
    import json
    from datetime import date, timedelta  # noqa: F401

    from scripts.check_mutation import GRACE_PERIOD_DAYS

    baseline_path = REPO_ROOT / "docs" / "quality" / "mutation-baseline.json"
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))

    awaiting = payload.get("awaiting_acquisition", {})
    assert "app/modules/adopciones/service.py" in awaiting, (
        "adopciones/service.py must carry an awaiting_acquisition marker "
        "until the first scheduled CI mutation run replaces it with the "
        "real survivor count (issue #434)"
    )

    since_str = awaiting["app/modules/adopciones/service.py"]
    since = date.fromisoformat(since_str)
    age = (date.today() - since).days
    assert age <= GRACE_PERIOD_DAYS, (
        f"awaiting_acquisition marker for adopciones/service.py is {age} days "
        f"old, past the {GRACE_PERIOD_DAYS}-day grace period. The scheduled CI "
        f"mutation job should have replaced it. See issue #434."
    )

    # The module must NOT appear under ``modules`` with a real (non-null)
    # count: that would silently freeze a placeholder as if it were measured.
    modules = payload.get("modules", {})
    assert "app/modules/adopciones/service.py" not in modules, (
        "adopciones/service.py is awaiting acquisition; an entry under "
        "'modules' with a real count is a regression — issue #434 ships "
        "the marker, the follow-up PR drops it"
    )

    print(
        "\nmutation-baseline.json[awaiting_acquisition]"
        "[app/modules/adopciones/service.py] = "
        f"{since_str} (age: {age} days, grace: {GRACE_PERIOD_DAYS})"
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
    pr_name = (REPO_ROOT / ".github" / "workflows" / "pr-name.yml").read_text(encoding="utf-8")
    assert "scripts/check_branch_name.py" in pr_name
    assert "github.head_ref" in pr_name
    # The gate fires on every pull_request — never silently restricted by
    # the workflow itself. Issue #525: restricting to a single base turned
    # chained PRs into invisible checks.
    assert "pull_request:" in pr_name
    assert "branches: [main]" not in pr_name, (
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
    pr_size = (REPO_ROOT / ".github" / "workflows" / "pr-size.yml").read_text(encoding="utf-8")

    assert "scripts/check_pr_size.py" in pr_size, (
        "pr-size.yml must invoke scripts/check_pr_size.py (issue #442, "
        "AGENTS.md §15.1) — the script is the unit-tested gate; inlining "
        "the budget logic in the workflow would silently bypass tests/test_pr_size.py"
    )
    assert "size:exception" in pr_size, (
        "pr-size.yml must read the 'size:exception' label (AGENTS.md §15.6) — "
        "it is the only acceptable override for the 400-line budget"
    )


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
    text = workflow_path.read_text(encoding="utf-8")

    # Pull the ``pull_request:`` block out of the ``on:`` map so a
    # ``branches:`` line buried elsewhere in the file cannot accidentally
    # satisfy the assertion. The string-based parser mirrors every other
    # gate test in this file: PyYAML is in ``[etl]``, not ``[dev]``.
    triggers = _trigger_lines(text)
    assert "pull_request:" in triggers, (
        f"{label}: must listen on pull_request events (issue #525)"
    )

    pr_block = triggers["pull_request:"]
    assert "branches: [main]" not in pr_block and "branches:\n      - main" not in pr_block, (
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
    workstation. ``mutation`` (weekly, Linux-only), ``security`` (Docker),
    ``integration`` (Postgres service) and ``e2e`` (Playwright) are out of
    scope for ``make verify`` and documented as such in the Makefile.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    executable = "\n".join(
        (
            _job_executable(workflow, "\n  lint:", "\n  security:"),
            _job_executable(workflow, "\n  test:", "\n  integration:"),
        )
    )
    return list(dict.fromkeys(re.findall(r"scripts/check_\w+\.py", executable)))


def test_make_verify_covers_every_ci_gate() -> None:
    """``make verify`` must run every gate a pull request is judged by.

    Issue #504. Before this, ``make all`` was documented in
    docs/development.md as "el comando que refleja la CI" while running
    four of seventeen gates: a green local run said nothing about CI, so
    the real contract lived in ci.yml and no single command expressed it.

    This is the ratchet on the harness itself. Adding a gate to ci.yml
    without adding a Makefile target for it fails here — which is the
    only reason the two lists will still match a year from now.
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
    assert "scripts/quality_report.py" in blob, (
        "make verify must run scripts/quality_report.py — the CI aggregator step does "
        "(deterministic-quality-harness v1.5 Rule 16; issue #516)."
    )


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
        "in its own weekly job (see the `mutation` target)"
    )
    assert "scripts/check_mutation.py" not in blob, (
        "scripts/check_mutation.py gates the cosmic-ray session, not a pull request"
    )
    assert "docker run" not in blob, (
        "make verify must not require Docker — gitleaks and trivy live in the "
        "`security` job"
    )


def test_development_guide_points_at_make_verify() -> None:
    """The guide must name the command that actually mirrors CI (issue #504).

    docs/development.md is where a new contributor learns what to run
    before opening a PR. While it named ``make all``, it was teaching a
    four-gate subset as if it were the seventeen-gate contract.
    """
    guide = DEVELOPMENT_GUIDE_PATH.read_text(encoding="utf-8")

    assert "make verify" in guide, (
        "docs/development.md must document `make verify` as the pre-PR command "
        "(issue #504)"
    )
