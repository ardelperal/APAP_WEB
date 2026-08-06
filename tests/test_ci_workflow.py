import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
MAKEFILE_PATH = REPO_ROOT / "Makefile"
CHECK_RULES_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_rules.py"
BRANCH_PROTECTION_PATH = REPO_ROOT / ".github" / "branch-protection.md"
DEVELOPMENT_GUIDE_PATH = REPO_ROOT / "docs" / "development.md"


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
    assert "APAP_TEST_POSTGRES_DSN:" in test_job
    assert "--deselect tests/test_voluntarios_concurrent.py" not in executable


def test_postgres_toctou_contract_uses_test_dsn_not_http_base_url() -> None:
    """The PostgreSQL integration test must not overload the HTTP E2E contract."""
    concurrency_test = (
        REPO_ROOT / "tests" / "test_voluntarios_concurrent.py"
    ).read_text(encoding="utf-8")
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
        rule_id
        for rule_id in expected_rule_ids
        if f": {rule_id}:" not in result.stdout
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
    return remaining[:next_job_match.start()] if next_job_match else remaining


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


def _evaluate_if_clauses(
    clauses: list[tuple[str, str | None]], payload: dict[str, object]
) -> bool:
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


def test_ci_workflow_defines_deploy_job_with_gating() -> None:
    """CD-01: deploy job exists, runs only on push to main, depends on lint+typecheck+test+integration+build.

    The only acceptable gating expression is exactly
    ``github.event_name == 'push' && github.ref == 'refs/heads/main'``.
    The dead ``github.event.pull_request == null`` clause must not appear
    (it is always null on a push event and was hiding the real bug).
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "  deploy:" in workflow
    assert "  name: deploy" in workflow
    # needs must reference the five required jobs (typecheck added by
    # issue #201; integration added by issue #329).
    assert "needs: [lint, typecheck, test, integration, build]" in workflow

    # Extract the job-level if: clause
    if_clause = _extract_deploy_job_if_clause(workflow)

    # Must be exactly the clean two-clause form — no pull_request == null
    assert (
        if_clause == "if: github.event_name == 'push' && github.ref == 'refs/heads/main'"
    ), f"deploy job if: must be exactly the push-to-main predicate; got: {if_clause!r}"

    # The dead pull_request == null clause must not appear anywhere in the deploy job
    deploy_section = _extract_deploy_section(workflow)
    assert (
        "pull_request == null" not in deploy_section
    ), "deploy job must not contain 'pull_request == null' — that clause is dead code on push events"

    # The merge-commit skip block must also be absent
    assert (
        'grep -q "^Merge pull request #' not in deploy_section
    ), "deploy job must not contain the merge-commit skip block"


def test_ci_workflow_deploy_runs_on_main_push() -> None:
    """CD-01 D4: the deploy job's if: evaluates True for a push to main.

    Under pre-MVP policy (AGENTS.md §15.2) every change lands via PR merge,
    so a push to main IS the deployable event. The if: must select it and
    must not have a merge-commit skip guard inside the run block.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    if_clause = _extract_deploy_job_if_clause(workflow)
    clauses = _parse_if_clauses(if_clause)

    # GitHub context structure: github.event_name (e.g. "push"),
    # github.ref (e.g. "refs/heads/main"), github.event.pull_request (null on push).
    # The payload mirrors this as {"event": {"name": ..., "pull_request": ...}, "ref": ...}
    push_to_main_payload: dict[str, object] = {
        "event": {"name": "push", "pull_request": None},
        "ref": "refs/heads/main",
    }
    assert _evaluate_if_clauses(clauses, push_to_main_payload), (
        f"deploy job if: {if_clause!r} must evaluate True for push to main"
    )

    # The deploy job's run steps must NOT contain the merge-commit skip block
    deploy_section = _extract_deploy_section(workflow)
    assert (
        'grep -q "^Merge pull request #' not in deploy_section
    ), "deploy job run steps must not contain the merge-commit skip guard"


def test_ci_workflow_deploy_skips_on_pr() -> None:
    """CD-01 D5: the deploy job's if: evaluates False for a pull_request event.

    A pull_request event must not trigger the deploy job, even if the PR
    targets main. The if: must be a pure push-to-main predicate.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    if_clause = _extract_deploy_job_if_clause(workflow)
    clauses = _parse_if_clauses(if_clause)

    # PR event: github.event_name = "pull_request", github.event.pull_request is a dict
    pr_payload: dict[str, object] = {
        "event": {"name": "pull_request", "pull_request": {"number": 42}},
        "ref": "refs/heads/main",
    }
    assert not _evaluate_if_clauses(clauses, pr_payload), (
        f"deploy job if: {if_clause!r} must evaluate False for pull_request event"
    )


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
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

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
    assert "curl -fsS -X POST \"$COOLIFY_WEBHOOK_URL\"" not in workflow


def test_ci_workflow_missing_webhook_secret_is_a_failure() -> None:
    """Missing COOLIFY_WEBHOOK_SECRET MUST fail the deploy step.

    Pinned by spec (ci-cd-pipeline/spec.md, Scenario "Missing webhook
    secret blocks production deploy"). Without the secret, the HMAC
    signature would be computed over an empty key, and Coolify v4
    would reject every payload. Loud fail at CI beats silent fail at
    the healthcheck-driven rollback.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

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
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    # The workflow must forward the env vars the module needs to build
    # the payload (ref, sha, repository, commit message).
    assert "GITHUB_REF:" in workflow
    assert "GITHUB_SHA:" in workflow
    assert "GITHUB_REPOSITORY:" in workflow
    assert "COMMIT_MESSAGE:" in workflow


def _job_executable(workflow: str, start: str, end: str) -> str:
    start_index = workflow.index(start)
    section = workflow[start_index : workflow.index(end, start_index)]
    return "\n".join(
        line for line in section.splitlines() if not line.lstrip().startswith("#")
    )


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



