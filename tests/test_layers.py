"""Tests for the hexagonal layer + vertical-slice ratchet (AGENTS.md rule 33).

``scripts/check_layers.py`` enforces three things over ``app/``:
dependency direction between layers, purity of the inner layers, and
vertical-slice boundaries. The checker is a stdlib-only script so the CI
lint job can run it without extra dependencies.

These tests exercise it against synthetic trees (``tmp_path``), against
the real repository tree, and pin the CI wiring in
``.github/workflows/ci.yml``.

Synthetic trees always create the *imported* module too: the checker
resolves every import against the filesystem, so a test that only writes
the importing file would assert nothing.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_layers.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_layers", CHECKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: Path, rel_posix: str, source: str = "") -> Path:
    path = root / Path(rel_posix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _tree(root: Path, files: dict[str, str]) -> None:
    """Write every file, plus an empty ``__init__.py`` for each package."""
    for rel, source in files.items():
        _write(root, rel, source)
    for rel in files:
        parts = Path(rel).parts[:-1]
        for depth in range(1, len(parts) + 1):
            init = root / Path(*parts[:depth]) / "__init__.py"
            if not init.exists():
                init.write_text("", encoding="utf-8")


# ---------------------------------------------------------------------------
# The real tree
# ---------------------------------------------------------------------------


def test_current_tree_passes_with_baseline() -> None:
    """The checker exits 0 on the repository as it stands.

    Every violation that predates the rule must be in BASELINE —
    otherwise the gate would be born red and get deleted within a week.
    """
    checker = _load_checker()

    assert checker.main([str(REPO_ROOT)]) == 0


def test_baseline_entries_are_still_real_violations() -> None:
    """BASELINE may not accumulate stale entries.

    A baselined violation that no longer exists is silent headroom: the
    same forbidden import could come back for free. ``check_tree``
    reports each stale entry as a notice, so the baseline must produce
    none against the real tree.
    """
    checker = _load_checker()

    _violations, notices = checker.check_tree(REPO_ROOT)

    assert notices == [], (
        "stale BASELINE entries in scripts/check_layers.py — the violation is "
        "fixed, so delete the entry to lock in the improvement"
    )


def test_every_layer_declares_its_allowed_imports() -> None:
    """LAYER_ORDER and ALLOWED_IMPORTS must not drift apart."""
    checker = _load_checker()

    assert set(checker.LAYER_ORDER) == set(checker.ALLOWED_IMPORTS)
    for layer, allowed in checker.ALLOWED_IMPORTS.items():
        assert layer in allowed, f"{layer} must be allowed to import itself"
        assert allowed <= set(checker.LAYER_ORDER), f"{layer} allows an unknown layer"


# ---------------------------------------------------------------------------
# Axis 1 — dependency direction
# ---------------------------------------------------------------------------


def test_application_may_not_import_adapters(tmp_path: Path) -> None:
    """The central hexagonal rule: use cases receive adapters by injection.

    This is the APAP_WEB analogue of dysflow's
    ``check-core-adapter-boundary.mjs``.
    """
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/adapters/local_backend/auth_local_backend_adapter.py": "",
            "app/core/application/auth/get_user.py": (
                "from app.core.adapters.stubs.auth_users_stub import Adapter\n"
            ),
        },
    )

    violations, _notices = checker.check_tree(tmp_path, baseline={})

    assert len(violations) == 1
    assert "application" in violations[0]
    assert "injection" in violations[0]


def test_di_may_wire_adapters_into_application(tmp_path: Path) -> None:
    """The composition root is exactly the place that may see both."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/adapters/local_backend/auth_local_backend_adapter.py": "",
            "app/core/application/auth/get_user.py": "",
            "app/core/di/auth_di.py": (
                "from app.core.adapters.stubs.auth_users_stub import Adapter\n"
                "from app.core.application.auth.get_user import get_user\n"
            ),
        },
    )

    violations, _notices = checker.check_tree(tmp_path, baseline={})

    assert violations == []


def test_domain_may_not_import_infrastructure(tmp_path: Path) -> None:
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/local_backend.py": "",
            "app/core/domain/auth/user.py": "from app.core.local_backend import Client\n",
        },
    )

    violations, _notices = checker.check_tree(tmp_path, baseline={})

    assert len(violations) == 1
    assert "centre of the hexagon" in violations[0]


def test_inner_layer_may_not_import_delivery(tmp_path: Path) -> None:
    """Dependency inversion: app/core must never reach into app/modules."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/modules/tasks/service.py": "",
            "app/core/tasks/scheduler.py": (
                "from app.modules.tasks import service\n"
            ),
        },
    )

    violations, _notices = checker.check_tree(tmp_path, baseline={})

    assert violations
    assert all("dependency inversion" in v for v in violations)


def test_delivery_may_import_inward(tmp_path: Path) -> None:
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/application/auth/get_user.py": "",
            "app/core/ports/auth_port.py": "",
            "app/modules/animals/routes.py": (
                "from app.core.application.auth.get_user import get_user\n"
                "from app.core.ports.auth_port import AuthUsersPort\n"
            ),
        },
    )

    violations, _notices = checker.check_tree(tmp_path, baseline={})

    assert violations == []


# ---------------------------------------------------------------------------
# Axis 2 — vertical slices
# ---------------------------------------------------------------------------


def test_slice_may_not_import_another_slice_internals(tmp_path: Path) -> None:
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/modules/foster/assignment_service.py": "",
            "app/modules/acogidas/routes.py": (
                "from app.modules.foster.assignment_service import assign\n"
            ),
        },
    )

    violations, _notices = checker.check_tree(tmp_path, baseline={})

    assert len(violations) == 1
    assert "internals" in violations[0]
    assert "app.modules.foster" in violations[0]


def test_slice_may_import_another_slice_package_root(tmp_path: Path) -> None:
    """Cross-slice traffic is allowed through the public package root.

    The other slice's ``__init__`` decides what it exposes; that is the
    seam, and it stays reviewable.
    """
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/modules/animals/__init__.py": "get_animal_by_id = None\n",
            "app/modules/foster/assignment.py": (
                "from app.modules.animals import get_animal_by_id\n"
            ),
        },
    )

    violations, _notices = checker.check_tree(tmp_path, baseline={})

    assert violations == []


def test_core_slice_may_not_import_a_sibling_slice(tmp_path: Path) -> None:
    """Inside app/core, slices do not talk to each other at all."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/application/animals/list_animals.py": "",
            "app/core/application/auth/get_user.py": (
                "from app.core.application.animals.list_animals import list_animals\n"
            ),
        },
    )

    violations, _notices = checker.check_tree(tmp_path, baseline={})

    assert len(violations) == 1
    assert "vertical slices own their column" in violations[0]


def test_adapter_slice_is_split_on_the_vendor_segment(tmp_path: Path) -> None:
    """``schema_bootstrap_local_backend_adapter`` is the schema_bootstrap slice.

    Splitting on the first underscore would read it as ``schema`` and
    then flag its own port as a cross-slice import.
    """
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/schema_bootstrap_port.py": "",
            "app/core/adapters/local_backend/schema_bootstrap_local_backend_adapter.py": (
                "from app.core.ports.schema_bootstrap_port import SchemaBootstrapPort\n"
            ),
        },
    )

    rel = "app/core/adapters/local_backend/schema_bootstrap_local_backend_adapter.py"
    assert checker.classify_slice(rel, "adapters") == "schema_bootstrap"

    violations, _notices = checker.check_tree(tmp_path, baseline={})

    assert violations == []


# ---------------------------------------------------------------------------
# Axis 3 — purity
# ---------------------------------------------------------------------------


def test_pure_layer_may_not_import_a_web_framework(tmp_path: Path) -> None:
    checker = _load_checker()
    _tree(
        tmp_path,
        {"app/core/application/auth/get_user.py": "from fastapi import Depends\n"},
    )

    violations, _notices = checker.check_tree(tmp_path, baseline={})

    assert len(violations) == 1
    assert "fastapi" in violations[0]


def test_delivery_may_import_a_web_framework(tmp_path: Path) -> None:
    checker = _load_checker()
    _tree(tmp_path, {"app/modules/animals/routes.py": "from fastapi import APIRouter\n"})

    violations, _notices = checker.check_tree(tmp_path, baseline={})

    assert violations == []


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_imported_symbol_is_not_mistaken_for_a_module(tmp_path: Path) -> None:
    """Regression: ``from x import SOME_CONSTANT`` is not an edge to ``x.SOME_CONSTANT``.

    The checker resolves every import candidate against the filesystem.
    Without that, importing a constant from a sibling domain module
    produced a phantom module path that fell through to the
    infrastructure default and reported a violation that does not exist.
    """
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/domain_lifecycle.py": "ANIMAL_CREATE_TABLE_SQL = ''\n",
            "app/core/domain.py": (
                "from app.core.domain_lifecycle import ANIMAL_CREATE_TABLE_SQL\n"
            ),
        },
    )

    violations, _notices = checker.check_tree(tmp_path, baseline={})

    assert violations == []
    assert checker.resolve_module(tmp_path, "app.core.domain_lifecycle.ANY") is None


def test_relative_imports_resolve_against_the_owning_package(tmp_path: Path) -> None:
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/local_backend.py": "",
            "app/core/domain/auth/user.py": "from ...local_backend import Client\n",
        },
    )

    violations, _notices = checker.check_tree(tmp_path, baseline={})

    assert len(violations) == 1
    assert "centre of the hexagon" in violations[0]


# ---------------------------------------------------------------------------
# Ratchet
# ---------------------------------------------------------------------------


def test_baselined_violation_passes_and_new_one_fails(tmp_path: Path) -> None:
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/local_backend.py": "",
            "app/core/domain/auth/user.py": "from app.core.local_backend import Client\n",
        },
    )
    key = "app/core/domain/auth/user.py -> app.core.local_backend [layer-direction]"

    violations, notices = checker.check_tree(tmp_path, baseline={key: "known debt"})

    assert violations == []
    assert notices == []

    _write(tmp_path, "app/core/config.py", "")
    _write(
        tmp_path,
        "app/core/domain/auth/user.py",
        "from app.core.local_backend import Client\nfrom app.core.config import settings\n",
    )
    violations, _notices = checker.check_tree(tmp_path, baseline={key: "known debt"})

    assert len(violations) == 1
    assert "app.core.config" in violations[0]


def test_stale_baseline_entry_is_reported_as_a_notice(tmp_path: Path) -> None:
    checker = _load_checker()
    _tree(tmp_path, {"app/core/domain/auth/user.py": ""})

    violations, notices = checker.check_tree(
        tmp_path, baseline={"app/core/domain/auth/user.py -> x [layer-direction]": "old"}
    )

    assert violations == []
    assert len(notices) == 1
    assert "no longer a violation" in notices[0]


# ---------------------------------------------------------------------------
# CI wiring
# ---------------------------------------------------------------------------


def test_ci_workflow_lint_job_runs_layers_gate() -> None:
    """AGENTS.md rule 33: the CI ``lint`` job must gate on the checker.

    The architecture is only real if CI runs it. Same scoping rationale
    as ``test_ci_workflow_lint_job_runs_module_size_gate``: slice the
    lint job's section and drop YAML comments so a comment mentioning
    the command can never satisfy the assertion. Removing this step from
    ci.yml is a blocked change.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    lint_job_start = workflow.index("\n  lint:")
    lint_job = workflow[lint_job_start : workflow.index("\n  security:", lint_job_start)]
    executable = "\n".join(
        line for line in lint_job.splitlines() if not line.lstrip().startswith("#")
    )

    assert "python scripts/check_layers.py" in executable, (
        "The lint job must run the hexagonal layer + slice ratchet "
        "(python scripts/check_layers.py) so the architecture gates CI, "
        "not just PR review."
    )
