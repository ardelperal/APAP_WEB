"""Tests for the route-handler size and Form-parameter ratchet
(AGENTS.md rule 28, issues #233 and #337).

``scripts/check_route_size.py`` enforces two per-function budgets on every
FastAPI route handler under ``app/``:

1. ``MAX_LINES`` (50): no handler may exceed this line count. Handlers
   that already exceeded it when the rule landed are in ``BASELINE`` and
   may only shrink (ratchet).

2. ``MAX_FORM_PARAMS`` (8, issue #337): no handler may declare more
   than this many ``Form(...)`` parameters. Handlers that already exceed
   it are in ``FORM_BASELINE`` and may only shrink — a handler that
   stays at 13 Form params after a "migration" is still a violation;
   the count must actually drop.

Mirrors ``tests/test_module_size.py``'s test shape.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_route_size.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_route_size", CHECKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_routes_module(root: Path, rel_posix: str, handler_lines: int) -> Path:
    """Write a fake ``routes.py`` with one ``@router.post`` handler whose
    body spans exactly ``handler_lines`` lines (the ``def`` line plus
    ``handler_lines - 1`` body statements).
    """
    path = root / Path(rel_posix)
    path.parent.mkdir(parents=True, exist_ok=True)
    body_lines = "\n".join(f"    x{i} = {i}" for i in range(handler_lines - 2))
    source = (
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n\n"
        "@router.post('/thing')\n"
        "def create_thing_view():\n"
        f"{body_lines}\n"
        "    return None\n"
    )
    path.write_text(source, encoding="utf-8")
    return path


def _write_routes_module_with_form_params(
    root: Path, rel_posix: str, form_param_count: int
) -> Path:
    """Write a fake ``routes.py`` with one ``@router.post`` handler that
    declares exactly ``form_param_count`` ``Form(...)`` parameters.
    """
    path = root / Path(rel_posix)
    path.parent.mkdir(parents=True, exist_ok=True)
    form_params = ",\n    ".join(
        f"field_{i}: str = Form(...)" for i in range(form_param_count)
    )
    source = (
        "from fastapi import APIRouter, Form\n"
        "router = APIRouter()\n\n"
        "@router.post('/thing')\n"
        f"def create_thing_view(\n"
        f"    {form_params},\n"
        "):\n"
        "    return None\n"
    )
    path.write_text(source, encoding="utf-8")
    return path


def test_current_tree_passes_with_baseline() -> None:
    """The checker exits 0 on the repository as it stands.

    Every handler over the budget must be in BASELINE at (at least)
    its current size — otherwise the gate would be born red.
    """
    checker = _load_checker()

    assert checker.main([str(REPO_ROOT)]) == 0


def test_baseline_matches_measured_tree() -> None:
    """BASELINE only lists real handlers, at their real (over-budget) span."""
    checker = _load_checker()

    assert checker.BASELINE, "expected a non-empty baseline of known offenders"
    for key, budget in checker.BASELINE.items():
        rel_posix, _, func_name = key.partition("::")
        path = REPO_ROOT / Path(rel_posix)
        assert path.is_file(), f"stale BASELINE entry: {key}"
        handlers = dict(checker._iter_route_handlers(path))
        assert func_name in handlers, f"stale BASELINE entry: {key} (function not found)"
        actual = handlers[func_name]
        assert actual == budget, (
            f"{key}: BASELINE says {budget} lines but the handler has "
            f"{actual} — re-measure and update BASELINE"
        )
        assert budget > checker.MAX_LINES, (
            f"{key}: baselined at {budget}, which is within the "
            f"{checker.MAX_LINES}-line budget — remove it from BASELINE"
        )


def test_flags_new_over_budget_handler(tmp_path: Path) -> None:
    checker = _load_checker()
    _write_routes_module(tmp_path, "app/modules/foo/routes.py", 60)

    violations, _notices = checker.check_tree(tmp_path, baseline={}, form_baseline={})

    assert len(violations) == 1
    assert "app/modules/foo/routes.py::create_thing_view" in violations[0]
    assert "60" in violations[0]
    assert str(checker.MAX_LINES) in violations[0]
    assert checker.main([str(tmp_path)]) == 1


def test_ratchet_flags_baselined_handler_that_grew(tmp_path: Path) -> None:
    checker = _load_checker()
    _write_routes_module(tmp_path, "app/modules/foo/routes.py", 90)

    violations, _notices = checker.check_tree(
        tmp_path,
        baseline={"app/modules/foo/routes.py::create_thing_view": 80},
        form_baseline={},
    )

    assert len(violations) == 1
    assert "app/modules/foo/routes.py::create_thing_view" in violations[0]
    assert "90" in violations[0]
    assert "80" in violations[0]


def test_baselined_handler_that_shrank_passes_and_suggests_baseline_update(
    tmp_path: Path,
) -> None:
    checker = _load_checker()
    _write_routes_module(tmp_path, "app/modules/foo/routes.py", 70)

    violations, notices = checker.check_tree(
        tmp_path,
        baseline={"app/modules/foo/routes.py::create_thing_view": 80},
        form_baseline={},
    )

    assert violations == []
    assert len(notices) == 1
    assert "app/modules/foo/routes.py::create_thing_view" in notices[0]
    assert "BASELINE" in notices[0]


def test_stale_baseline_entry_is_a_violation(tmp_path: Path) -> None:
    checker = _load_checker()
    (tmp_path / "app").mkdir()

    violations, _notices = checker.check_tree(
        tmp_path, baseline={"app/modules/gone/routes.py::gone_view": 80}, form_baseline={}
    )

    assert len(violations) == 1
    assert "app/modules/gone/routes.py::gone_view" in violations[0]


def test_ignores_non_route_functions(tmp_path: Path) -> None:
    """A large function that is NOT decorated with @router/@application
    is not a route handler and is exempt from the budget."""
    path = tmp_path / "app" / "modules" / "foo" / "routes.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"    x{i} = {i}" for i in range(80))
    path.write_text(f"def _helper():\n{body}\n    return None\n", encoding="utf-8")

    checker = _load_checker()
    violations, notices = checker.check_tree(tmp_path, baseline={}, form_baseline={})

    assert violations == []
    assert notices == []


def test_ci_workflow_lint_job_runs_route_size_gate() -> None:
    """The CI ``lint`` job must gate on ``scripts/check_route_size.py``,
    right after the module-size ratchet. Removing this step is a
    blocked change, mirroring
    ``test_ci_workflow_lint_job_runs_module_size_gate``.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    lint_job_start = workflow.index("\n  lint:")
    lint_job = workflow[lint_job_start : workflow.index("\n  test:", lint_job_start)]
    executable = "\n".join(
        line for line in lint_job.splitlines() if not line.lstrip().startswith("#")
    )

    assert "python scripts/check_route_size.py" in executable, (
        "The lint job must run the route-handler size ratchet "
        "(python scripts/check_route_size.py) so the 50-line budget "
        "and the shrink-only baseline gate CI, not just PR review."
    )


# --- Form-parameter budget tests (issue #337) --------------------------------


def test_form_baseline_matches_measured_tree() -> None:
    """FORM_BASELINE only lists real handlers, at their real (over-budget) Form count."""
    checker = _load_checker()

    # All three original FORM_BASELINE entries were migrated to Annotated[PydanticForm, Form()]
    # in issue #388: create_cesion_view (21→0), create_acogida_view (13→1),
    # update_acogida_view (12→1). All counts are now ≤ MAX_FORM_PARAMS (8),
    # so FORM_BASELINE is legitimately empty — the assertion below is a no-op.
    for key, budget in checker.FORM_BASELINE.items():
        rel_posix, _, func_name = key.partition("::")
        path = REPO_ROOT / Path(rel_posix)
        assert path.is_file(), f"stale FORM_BASELINE entry: {key}"
        handlers = {
            name: form_count
            for name, _, form_count in checker._iter_route_handlers_with_form_params(path)
        }
        assert func_name in handlers, f"stale FORM_BASELINE entry: {key} (function not found)"
        actual = handlers[func_name]
        assert actual == budget, (
            f"{key}: FORM_BASELINE says {budget} Form params but the handler has "
            f"{actual} — re-measure and update FORM_BASELINE"
        )
        assert budget > checker.MAX_FORM_PARAMS, (
            f"{key}: baselined at {budget}, which is within the "
            f"{checker.MAX_FORM_PARAMS}-param budget — remove it from FORM_BASELINE"
        )


def test_flags_new_over_form_budget_handler(tmp_path: Path) -> None:
    """A handler with more than MAX_FORM_PARAMS that is NOT in FORM_BASELINE
    is a violation."""
    checker = _load_checker()
    _write_routes_module_with_form_params(tmp_path, "app/modules/foo/routes.py", 10)

    violations, _notices = checker.check_tree(
        tmp_path, baseline={}, form_baseline={}
    )

    assert len(violations) == 1
    assert "app/modules/foo/routes.py::create_thing_view" in violations[0]
    assert "10" in violations[0]
    assert str(checker.MAX_FORM_PARAMS) in violations[0]


def test_ratchet_flags_baselined_form_handler_that_grew(tmp_path: Path) -> None:
    """A handler in FORM_BASELINE that increases its Form param count is a violation."""
    checker = _load_checker()
    _write_routes_module_with_form_params(tmp_path, "app/modules/foo/routes.py", 15)

    violations, _notices = checker.check_tree(
        tmp_path,
        baseline={},
        form_baseline={"app/modules/foo/routes.py::create_thing_view": 10},
    )

    assert len(violations) == 1
    assert "app/modules/foo/routes.py::create_thing_view" in violations[0]
    assert "15" in violations[0]
    assert "10" in violations[0]


def test_baselined_form_handler_that_shrank_passes_and_suggests_baseline_update(
    tmp_path: Path,
) -> None:
    """A handler in FORM_BASELINE that reduces its Form param count passes
    but emits a notice to update the baseline."""
    checker = _load_checker()
    _write_routes_module_with_form_params(tmp_path, "app/modules/foo/routes.py", 5)

    violations, notices = checker.check_tree(
        tmp_path,
        baseline={},
        form_baseline={"app/modules/foo/routes.py::create_thing_view": 10},
    )

    assert violations == []
    assert len(notices) == 1
    assert "app/modules/foo/routes.py::create_thing_view" in notices[0]
    assert "FORM_BASELINE" in notices[0]


def test_stale_form_baseline_entry_is_a_violation(tmp_path: Path) -> None:
    """A FORM_BASELINE entry for a handler that no longer exists is a violation."""
    checker = _load_checker()
    (tmp_path / "app").mkdir()

    violations, _notices = checker.check_tree(
        tmp_path, baseline={}, form_baseline={"app/modules/gone/routes.py::gone_view": 10}
    )

    assert len(violations) == 1
    assert "app/modules/gone/routes.py::gone_view" in violations[0]
    assert "Form params" in violations[0]


def test_handler_within_form_budget_passes(tmp_path: Path) -> None:
    """A handler with MAX_FORM_PARAMS or fewer Form params, not in FORM_BASELINE,
    passes without notices."""
    checker = _load_checker()
    _write_routes_module_with_form_params(tmp_path, "app/modules/foo/routes.py", 8)

    violations, notices = checker.check_tree(
        tmp_path, baseline={}, form_baseline={}
    )

    assert violations == []
    assert notices == []
