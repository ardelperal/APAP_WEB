"""Tests for the slice-completeness gate (AGENTS.md rule 33, hardening Step 2).

``scripts/check_slice_completeness.py`` proves every in-scope slice
has a Protocol in ``ports/``, every concrete adapter is wired from
``di/``, the application layer never imports concrete adapters, and
each occupied layer has a test file. Four assertions, one Python
script, stdlib only.

These tests exercise it against synthetic trees (``tmp_path``),
against the real repository tree, and pin the CI wiring in
``.github/workflows/ci.yml``.

Synthetic trees always create the *imported* module too: the checker
resolves every import via AST, so a test that only writes the
importing file would assert nothing.

The gate's own BASELINE is exercised end-to-end against the real
``main`` checkout so that ``test_baseline_entries_are_still_real_violations``
detects a forgotten BASELINE clean-up the moment the violation
disappears (mirrors ``tests/test_layers.py:67``).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_slice_completeness.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_slice_completeness", CHECKER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: Path, rel_posix: str, source: str = "") -> Path:
    path = root / rel_posix
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _tree(root: Path, files: dict[str, str]) -> None:
    """Write every file and an empty ``__init__.py`` for each package."""
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

    Every violation that predates the rule must be in ``BASELINE`` --
    otherwise the gate would be born red and get deleted within a week.
    """
    checker = _load_checker()
    assert checker.main([str(REPO_ROOT)]) == 0


def test_baseline_entries_are_still_real_violations() -> None:
    """The shrink-only ratchet must not accumulate stale entries.

    Mirrors ``tests/test_layers.py:67`` for ``check_layers.py``. A
    baselined violation that no longer exists is silent headroom: the
    same gap could come back for free.
    """
    checker = _load_checker()
    _violations, notices = checker.check_tree(REPO_ROOT)
    assert notices == [], (
        "stale BASELINE entries in scripts/check_slice_completeness.py -- "
        "the violation is fixed, delete the entry to lock in the improvement"
    )


# ---------------------------------------------------------------------------
# Discovery -- di-only slices are not in scope
# ---------------------------------------------------------------------------


def test_di_only_slice_is_excluded_from_inventory(tmp_path: Path) -> None:
    """An auxiliary ``di/<slice>_di.py`` without other layers is not a slice."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/di/auth_dependencies_di.py": (
                "def get_thing() -> int:\n    return 1\n"
            ),
        },
    )
    inventory = checker.discover_slices(tmp_path)
    # The file is classification-wise a "auth_dependencies" slice, but
    # di-only slices are not slices for the gate. The dictionary MUST
    # not contain it.
    assert "auth_dependencies" not in inventory


def test_discovery_finds_a_hexagonal_slice(tmp_path: Path) -> None:
    """A full hexagonal slice appears with all four layers in inventory."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/foo_port.py": (
                "from typing import Protocol\n"
                "class FooPort(Protocol):\n    def get(self) -> str: ...\n"
            ),
            "app/core/application/foo/get_thing.py": "def get_thing() -> str: return ''\n",
            "app/core/adapters/insforge/foo_insforge_adapter.py": (
                "from app.core.ports.foo_port import FooPort\n"
                "class InsForgeFooAdapter(FooPort):\n    def get(self) -> str: return ''\n"
            ),
            "app/core/di/foo_di.py": (
                "from app.core.adapters.insforge.foo_insforge_adapter import (\n"
                "    InsForgeFooAdapter,\n"
                ")\n"
                "def get_foo() -> InsForgeFooAdapter:\n    return InsForgeFooAdapter(None)\n"
            ),
        },
    )
    inventory = checker.discover_slices(tmp_path)
    assert "foo" in inventory
    assert set(inventory["foo"]) == {"ports", "application", "adapters", "di"}


def test_module_slice_is_discovered(tmp_path: Path) -> None:
    """``app/modules/<slice>/**`` counts as a delivery-layer slice."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/modules/widgets/service.py": "def list_widgets() -> list: return []\n",
            "app/modules/widgets/routes.py": "def handler() -> None: pass\n",
        },
    )
    inventory = checker.discover_slices(tmp_path)
    assert "widgets" in inventory
    delivery = inventory["widgets"]["delivery"]
    assert "app/modules/widgets/service.py" in delivery
    assert "app/modules/widgets/routes.py" in delivery


# ---------------------------------------------------------------------------
# Assertion 1 -- port-declared
# ---------------------------------------------------------------------------


def test_port_declared_passes_when_protocol_present(tmp_path: Path) -> None:
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/foo_port.py": (
                "from typing import Protocol\n"
                "class FooPort(Protocol):\n    def get(self) -> str: ...\n"
            ),
            "app/core/application/foo/x.py": "def x() -> str: return ''\n",
            "tests/test_foo_application.py": "def test_x() -> None: pass\n",
        },
    )
    inventory = checker.discover_slices(tmp_path)
    assert checker.check_port_declared(tmp_path, inventory) == []


def test_port_declared_fails_when_protocol_missing(tmp_path: Path) -> None:
    """A ports file with no Protocol-class is a violation."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/foo_port.py": (
                "# file is intentionally empty of Protocol classes\n"
            ),
            "app/core/application/foo/x.py": "def x() -> str: return ''\n",
            "tests/test_foo_application.py": "def test_x() -> None: pass\n",
        },
    )
    inventory = checker.discover_slices(tmp_path)
    results = checker.check_port_declared(tmp_path, inventory)
    assert len(results) == 1
    assert results[0][0] == "port-declared::foo"


def test_port_declared_fails_when_ports_file_missing(tmp_path: Path) -> None:
    """A slice with non-delivery layers but no ports file is a violation."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/application/foo/x.py": "def x() -> str: return ''\n",
            "tests/test_foo_application.py": "def test_x() -> None: pass\n",
        },
    )
    inventory = checker.discover_slices(tmp_path)
    results = checker.check_port_declared(tmp_path, inventory)
    assert len(results) == 1
    assert "app/core/ports/foo_port.py" in results[0][1]


def test_runtime_checkable_protocol_recognised(tmp_path: Path) -> None:
    """A class with ``@runtime_checkable`` on a Protocol-shaped base counts."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/foo_port.py": (
                "from typing import Protocol, runtime_checkable\n"
                "@runtime_checkable\n"
                "class FooPort(Protocol):\n"
                "    def get(self) -> str: ...\n"
            ),
            "app/core/application/foo/x.py": "def x() -> str: return ''\n",
            "tests/test_foo_application.py": "def test_x() -> None: pass\n",
        },
    )
    inventory = checker.discover_slices(tmp_path)
    assert checker.check_port_declared(tmp_path, inventory) == []


# ---------------------------------------------------------------------------
# Assertion 2 -- adapter-in-di
# ---------------------------------------------------------------------------


def test_adapter_in_di_passes_when_wired(tmp_path: Path) -> None:
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/foo_port.py": (
                "from typing import Protocol\n"
                "class FooPort(Protocol):\n    def get(self) -> str: ...\n"
            ),
            "app/core/adapters/insforge/foo_insforge_adapter.py": (
                "from app.core.ports.foo_port import FooPort\n"
                "class InsForgeFooAdapter(FooPort):\n"
                "    def get(self) -> str: return ''\n"
            ),
            "app/core/di/foo_di.py": (
                "from app.core.adapters.insforge.foo_insforge_adapter import InsForgeFooAdapter\n"
                "def get_foo() -> InsForgeFooAdapter: return InsForgeFooAdapter(None)\n"
            ),
            "app/core/application/foo/x.py": "def x() -> str: return ''\n",
            "tests/test_foo_application.py": "def test_x() -> None: pass\n",
        },
    )
    inventory = checker.discover_slices(tmp_path)
    assert checker.check_adapter_in_di(tmp_path, inventory) == []


def test_adapter_in_di_fails_when_adapter_not_imported(tmp_path: Path) -> None:
    """A di file that does NOT import the adapter is a violation."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/foo_port.py": (
                "from typing import Protocol\n"
                "class FooPort(Protocol):\n    def get(self) -> str: ...\n"
            ),
            "app/core/adapters/insforge/foo_insforge_adapter.py": (
                "from app.core.ports.foo_port import FooPort\n"
                "class InsForgeFooAdapter(FooPort):\n"
                "    def get(self) -> str: return ''\n"
            ),
            "app/core/di/foo_di.py": (
                "def get_foo() -> None: pass  # does NOT import the adapter\n"
            ),
            "app/core/application/foo/x.py": "def x() -> str: return ''\n",
            "tests/test_foo_application.py": "def test_x() -> None: pass\n",
        },
    )
    inventory = checker.discover_slices(tmp_path)
    results = checker.check_adapter_in_di(tmp_path, inventory)
    assert len(results) == 1
    assert "adapter-in-di::foo::" in results[0][0]


def test_queries_module_is_not_required_in_di(tmp_path: Path) -> None:
    """``<slice>_insforge_queries.py`` is used by the adapter, not by di.

    The check excludes these so the gate does not pick a fight with
    a valid adapter layout.
    """
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/foo_port.py": (
                "from typing import Protocol\n"
                "class FooPort(Protocol):\n    def get(self) -> str: ...\n"
            ),
            "app/core/adapters/insforge/foo_insforge_adapter.py": (
                "from app.core.adapters.insforge.foo_insforge_queries import QUERY\n"
                "from app.core.ports.foo_port import FooPort\n"
                "class InsForgeFooAdapter(FooPort):\n"
                "    def get(self) -> str: return ''\n"
            ),
            "app/core/adapters/insforge/foo_insforge_queries.py": (
                "QUERY = 'SELECT 1'\n"
            ),
            "app/core/di/foo_di.py": (
                "from app.core.adapters.insforge.foo_insforge_adapter import InsForgeFooAdapter\n"
                "def get_foo() -> InsForgeFooAdapter: return InsForgeFooAdapter(None)\n"
            ),
            "app/core/application/foo/x.py": "def x() -> str: return ''\n",
            "tests/test_foo_application.py": "def test_x() -> None: pass\n",
        },
    )
    inventory = checker.discover_slices(tmp_path)
    # Queries are excluded from the check; only the adapter matters.
    results = checker.check_adapter_in_di(tmp_path, inventory)
    assert results == []


# ---------------------------------------------------------------------------
# Assertion 3 -- application-adapter-free
# ---------------------------------------------------------------------------


def test_application_adapter_free_passes_when_clean(tmp_path: Path) -> None:
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/foo_port.py": (
                "from typing import Protocol\n"
                "class FooPort(Protocol):\n    def get(self) -> str: ...\n"
            ),
            "app/core/application/foo/x.py": (
                "from app.core.ports.foo_port import FooPort\n"
                "def use(p: FooPort) -> str: return p.get()\n"
            ),
            "app/core/adapters/insforge/foo_insforge_adapter.py": "x = 1\n",
            "app/core/di/foo_di.py": "x = 1\n",
            "tests/test_foo_application.py": "def test_x() -> None: pass\n",
        },
    )
    inventory = checker.discover_slices(tmp_path)
    assert checker.check_application_adapter_free(tmp_path, inventory) == []


def test_application_adapter_free_fails_on_concrete_import(tmp_path: Path) -> None:
    """Application importing the InsForge-shaped adapter is a violation."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/foo_port.py": (
                "from typing import Protocol\n"
                "class FooPort(Protocol):\n    def get(self) -> str: ...\n"
            ),
            "app/core/application/foo/x.py": (
                "from app.core.adapters.insforge.foo_insforge_adapter import (\n"
                "    InsForgeFooAdapter,\n"
                ")\n"
                "def use() -> InsForgeFooAdapter: return InsForgeFooAdapter()\n"
            ),
            "app/core/adapters/insforge/foo_insforge_adapter.py": "x = 1\n",
            "app/core/di/foo_di.py": (
                "from app.core.adapters.insforge.foo_insforge_adapter import InsForgeFooAdapter\n"
            ),
            "tests/test_foo_application.py": "def test_x() -> None: pass\n",
        },
    )
    inventory = checker.discover_slices(tmp_path)
    results = checker.check_application_adapter_free(tmp_path, inventory)
    assert len(results) == 1
    assert "application-adapter-free::app/core/application/foo/x.py" == results[0][0]


# ---------------------------------------------------------------------------
# Assertion 4 -- tests-per-layer
# ---------------------------------------------------------------------------


def test_tests_per_layer_passes_with_layer_specific_test(tmp_path: Path) -> None:
    """``tests/test_<slice>_<layer>.py`` is the cleanest signal."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/foo_port.py": (
                "from typing import Protocol\n"
                "class FooPort(Protocol):\n    def get(self) -> str: ...\n"
            ),
            "app/core/application/foo/x.py": "def x() -> str: return ''\n",
            "tests/test_foo_application.py": "def test_x() -> None: pass\n",
            "tests/test_foo_ports.py": "def test_p() -> None: pass\n",
        },
    )
    inventory = checker.discover_slices(tmp_path)
    assert checker.check_tests_per_layer(tmp_path, inventory) == []


def test_tests_per_layer_falls_back_to_integration(tmp_path: Path) -> None:
    """A ``test_<slice>_slice.py`` covers every layer the slice occupies."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/foo_port.py": (
                "from typing import Protocol\n"
                "class FooPort(Protocol):\n    def get(self) -> str: ...\n"
            ),
            "app/core/application/foo/x.py": "def x() -> str: return ''\n",
            "tests/test_foo_slice.py": "def test_x() -> None: pass\n",
        },
    )
    inventory = checker.discover_slices(tmp_path)
    assert checker.check_tests_per_layer(tmp_path, inventory) == []


def test_tests_per_layer_falls_back_to_wildcard(tmp_path: Path) -> None:
    """Any ``tests/test_<slice>_*.py`` covers every layer."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/foo_port.py": (
                "from typing import Protocol\n"
                "class FooPort(Protocol):\n    def get(self) -> str: ...\n"
            ),
            "app/core/application/foo/x.py": "def x() -> str: return ''\n",
            "tests/test_foo_extra.py": "def test_x() -> None: pass\n",
        },
    )
    inventory = checker.discover_slices(tmp_path)
    assert checker.check_tests_per_layer(tmp_path, inventory) == []


def test_tests_per_layer_fails_when_no_test_exists(tmp_path: Path) -> None:
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/foo_port.py": (
                "from typing import Protocol\n"
                "class FooPort(Protocol):\n    def get(self) -> str: ...\n"
            ),
            "app/core/application/foo/x.py": "def x() -> str: return ''\n",
        },
    )
    inventory = checker.discover_slices(tmp_path)
    results = checker.check_tests_per_layer(tmp_path, inventory)
    assert len(results) >= 1
    assert all(r[0].startswith("tests-per-layer::foo::") for r in results)


# ---------------------------------------------------------------------------
# Ratchet
# ---------------------------------------------------------------------------


def test_baselined_violation_passes_and_new_one_fails(tmp_path: Path) -> None:
    """A BASELINE entry silences exactly the violation it names."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/foo_port.py": (
                "from typing import Protocol\n"
                "class FooPort(Protocol):\n    def get(self) -> str: ...\n"
            ),
            "app/core/application/foo/x.py": (
                "from app.core.adapters.insforge.foo_insforge_adapter import (\n"
                "    InsForgeFooAdapter,\n"
                ")\n"
                "def use() -> InsForgeFooAdapter: return InsForgeFooAdapter()\n"
            ),
            "app/core/adapters/insforge/foo_insforge_adapter.py": "x = 1\n",
            "app/core/di/foo_di.py": (
                "from app.core.adapters.insforge.foo_insforge_adapter import InsForgeFooAdapter\n"
            ),
            "tests/test_foo_application.py": "def test_x() -> None: pass\n",
        },
    )
    key = (
        "application-adapter-free::app/core/application/foo/x.py"
    )
    violations, notices = checker.check_tree(
        tmp_path, baseline={key: "known debt"}
    )
    assert violations == []
    assert notices == []


def test_stale_baseline_entry_is_reported_as_a_notice(tmp_path: Path) -> None:
    """A BASELINE entry for a violation that has been fixed produces a notice."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/ports/foo_port.py": (
                "from typing import Protocol\n"
                "class FooPort(Protocol):\n    def get(self) -> str: ...\n"
            ),
            "tests/test_foo.py": "def test_x() -> None: pass\n",
        },
    )
    violations, notices = checker.check_tree(
        tmp_path, baseline={"port-declared::foo": "old"}
    )
    assert violations == []
    assert len(notices) == 1
    assert "no longer a violation" in notices[0]


def test_emit_baseline_prints_current_violations(tmp_path: Path) -> None:
    """``--emit-baseline`` produces a ``BASELINE`` skeleton ready to paste."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "app/core/application/foo/x.py": "def x() -> str: return ''\n",
            "tests/test_foo_application.py": "def test_x() -> None: pass\n",
        },
    )
    output = checker.emit_baseline(tmp_path)
    # The slice 'foo' has an application layer but no ports file -> one
    # port-declared violation is the only one to acquire.
    assert "port-declared::foo" in output


# ---------------------------------------------------------------------------
# CI wiring
# ---------------------------------------------------------------------------


def test_ci_workflow_lint_job_runs_slice_completeness_gate() -> None:
    """AGENTS.md rule 33: the CI ``lint`` job must gate on the checker.

    Same scoping rationale as
    ``test_ci_workflow_lint_job_runs_layers_gate``: slice the lint
    job's section and drop YAML comments, so a comment mentioning the
    command can never satisfy the assertion. Removing this step from
    ``ci.yml`` is a blocked change.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    lint_job_start = workflow.index("\n  lint:")
    lint_job = workflow[lint_job_start : workflow.index("\n  security:", lint_job_start)]
    executable = "\n".join(
        line for line in lint_job.splitlines() if not line.lstrip().startswith("#")
    )
    assert "python scripts/check_slice_completeness.py" in executable, (
        "The lint job must run the slice-completeness gate "
        "(python scripts/check_slice_completeness.py) so the "
        "architecture completeness assertion gates CI, not just PR "
        "review."
    )


def test_ci_workflow_runs_slice_gate_after_layers_gate() -> None:
    """The slice-completeness gate builds on the layer gate; it must run after."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    lint_job_start = workflow.index("\n  lint:")
    lint_job = workflow[lint_job_start : workflow.index("\n  security:", lint_job_start)]
    executable = "\n".join(
        line for line in lint_job.splitlines() if not line.lstrip().startswith("#")
    )
    layers_pos = executable.find("python scripts/check_layers.py")
    slice_pos = executable.find("python scripts/check_slice_completeness.py")
    assert layers_pos != -1 and slice_pos != -1, (
        "both gates must appear in the lint job -- the slice gate builds "
        "on the layer gate's classification"
    )
    assert slice_pos > layers_pos, (
        "the slice-completeness gate must run AFTER check_layers.py -- "
        "the layer classifier is the slice gate's source of truth"
    )
