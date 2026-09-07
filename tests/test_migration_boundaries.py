"""Tests for the migration boundary gate (issue #420, hardening roadmap Step 3).

``scripts/check_migration_boundaries.py`` classifies every file under
``migration/`` as pure / access-bound / orchestration and enforces a
forbidden-import set per class, plus a tests-per-module rule. The
checker is a stdlib-only script so the CI lint job can run it without
extra dependencies.

These tests exercise the checker against synthetic trees
(``tmp_path``), the real repository tree, and pin the CI wiring in
``.github/workflows/ci.yml``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_migration_boundaries.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_migration_boundaries", CHECKER_PATH)
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

    Every violation that predates the rule must be in ``BASELINE`` --
    otherwise the gate would be born red and get deleted within a week.
    """
    checker = _load_checker()

    assert checker.main([str(REPO_ROOT)]) == 0


def test_baseline_entries_are_still_real_violations() -> None:
    """``BASELINE`` may not accumulate stale entries.

    A baselined violation that no longer exists is silent headroom: the
    same forbidden import could come back for free. ``check_tree``
    reports each stale entry as a notice, so the baseline must produce
    none against the real tree.
    """
    checker = _load_checker()

    _violations, notices = checker.check_tree(REPO_ROOT)

    assert notices == [], (
        "stale BASELINE entries in scripts/check_migration_boundaries.py -- "
        "the violation is fixed, so delete the entry to lock in the "
        "improvement"
    )


def test_classifier_matches_documented_classes() -> None:
    """The classification allow-list agrees with the design doc."""
    checker = _load_checker()

    pure_samples = (
        "derivation.py",
        "diff_engine.py",
        "reconcile.py",
        "lock.py",
        "reporting.py",
        "ports/web_reader_port.py",
        "application/web_reader/load_web_snapshot.py",
    )
    access_samples = (
        "legacy_access_client.py",
        "legacy_reader.py",
    )
    orchestration_samples = (
        "apply.py",
        "cli.py",
        "cli_apply_reverse.py",
        "bootstrap.py",
        "mappings/__init__.py",
        "adapters/local_backend/web_reader_local_backend_adapter.py",
        "di/web_reader_di.py",
        "reverse_apply/orchestrator.py",
        "reverse_apply/per_row.py",
        "reverse_apply/lifecycle.py",
    )

    for stem in pure_samples:
        assert checker.classify_file(f"migration/{stem}") == "pure", stem
    for stem in access_samples:
        assert checker.classify_file(f"migration/{stem}") == "access-bound", stem
    for stem in orchestration_samples:
        assert checker.classify_file(f"migration/{stem}") == "orchestration", stem


# ---------------------------------------------------------------------------
# Rule 1 — pure modules
# ---------------------------------------------------------------------------


def _run_imports_only(root: Path, checker, *, baseline=None) -> tuple[list[str], list[str]]:
    """Run the import rules on a synthetic tree, skipping the test-per-module check.

    The synthetic trees for rules 1/2/3 lack a ``tests/`` directory,
    so the test-coverage rule would otherwise flag every module in
    ``REQUIRED_TESTS_FOR_MODULE`` as a violation -- noise that hides
    the rule under test. This helper bypasses that by temporarily
    clearing the test-mapping, running ``check_tree``, and restoring.
    """
    original = dict(checker.REQUIRED_TESTS_FOR_MODULE)
    checker.REQUIRED_TESTS_FOR_MODULE = {}
    try:
        return checker.check_tree(root, baseline=baseline)
    finally:
        checker.REQUIRED_TESTS_FOR_MODULE = original


def test_pure_module_must_not_import_app(tmp_path: Path) -> None:
    """A pure module that imports ``app/`` fails the gate.

    Mirrors the central hexagonal rule of ``check_layers.py``: pure
    layers must not reach across to the application side.
    """
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "migration/pure_thing.py": ("from app.core.data_access import SqlExecutor\n"),
        },
    )
    original = set(checker.PURE_FILENAMES)
    checker.PURE_FILENAMES = frozenset(original | {"pure_thing.py"})
    try:
        violations, _notices = _run_imports_only(tmp_path, checker, baseline={})
    finally:
        checker.PURE_FILENAMES = frozenset(original)

    assert len(violations) == 1
    assert "pure module imports" in violations[0]
    assert "app.core.data_access" in violations[0]


def test_pure_module_must_not_import_third_party_db_driver(tmp_path: Path) -> None:
    """A pure module that imports ``sqlalchemy`` (or similar) fails."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "migration/pure_db.py": "import sqlalchemy\n",
        },
    )
    original = set(checker.PURE_FILENAMES)
    checker.PURE_FILENAMES = frozenset(original | {"pure_db.py"})
    try:
        violations, _notices = _run_imports_only(tmp_path, checker, baseline={})
    finally:
        checker.PURE_FILENAMES = frozenset(original)

    assert len(violations) == 1
    assert "sqlalchemy" in violations[0]


def test_pure_module_must_not_import_legacy_seam(tmp_path: Path) -> None:
    """A pure module that imports ``migration.legacy_reader`` fails.

    The legacy seam is Windows-only; a pure module that depends on it
    would pull the Access driver into a Linux-CI test path.
    """
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "migration/legacy_access_client.py": "",
            "migration/legacy_reader.py": "",
            "migration/pure_quarantined.py": (
                "from migration.legacy_reader import load_legacy_snapshot\n"
            ),
        },
    )
    original = set(checker.PURE_FILENAMES)
    checker.PURE_FILENAMES = frozenset(original | {"pure_quarantined.py"})
    try:
        violations, _notices = _run_imports_only(tmp_path, checker, baseline={})
    finally:
        checker.PURE_FILENAMES = frozenset(original)

    assert len(violations) == 1
    assert "legacy_reader" in violations[0]


def test_pure_module_may_import_intra_migration(tmp_path: Path) -> None:
    """A pure module that imports a sibling migration module passes."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "migration/derivation.py": "",
            "migration/pure_user.py": ("from migration.derivation import DerivationResult\n"),
        },
    )
    original = set(checker.PURE_FILENAMES)
    checker.PURE_FILENAMES = frozenset(original | {"pure_user.py"})
    try:
        violations, _notices = _run_imports_only(tmp_path, checker, baseline={})
    finally:
        checker.PURE_FILENAMES = frozenset(original)

    assert violations == []


# ---------------------------------------------------------------------------
# Rule 2 — access-bound modules
# ---------------------------------------------------------------------------


def test_access_bound_module_must_not_import_app(tmp_path: Path) -> None:
    """The legacy seam must stay free of ``app/`` coupling."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "migration/legacy_access_client.py": ("from app.core.local_backend.db import LocalPostgresExecutor\n"),
        },
    )
    original = set(checker.ACCESS_BOUND_FILENAMES)
    checker.ACCESS_BOUND_FILENAMES = frozenset(original | {"legacy_access_client.py"})
    try:
        violations, _notices = _run_imports_only(tmp_path, checker, baseline={})
    finally:
        checker.ACCESS_BOUND_FILENAMES = frozenset(original)

    assert len(violations) == 1
    assert "app.core.local_backend" in violations[0]


def test_access_bound_module_may_import_intra_migration(tmp_path: Path) -> None:
    """The legacy reader legitimately depends on the legacy client."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "migration/legacy_access_client.py": "",
            "migration/legacy_reader.py": (
                "from migration.legacy_access_client import execute_legacy_sql\n"
            ),
        },
    )
    original = set(checker.ACCESS_BOUND_FILENAMES)
    checker.ACCESS_BOUND_FILENAMES = frozenset(
        original | {"legacy_access_client.py", "legacy_reader.py"}
    )
    try:
        violations, _notices = _run_imports_only(tmp_path, checker, baseline={})
    finally:
        checker.ACCESS_BOUND_FILENAMES = frozenset(original)

    assert violations == []


# ---------------------------------------------------------------------------
# Rule 3 — orchestration modules
# ---------------------------------------------------------------------------


def test_orchestration_module_must_not_import_app_modules(tmp_path: Path) -> None:
    """Orchestration MUST NOT depend on ``app.modules.*`` (business logic)."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "migration/cli.py": ("from app.modules.animals import get_animal_by_id\n"),
        },
    )

    violations, _notices = _run_imports_only(tmp_path, checker, baseline={})

    assert len(violations) == 1
    assert "app.modules.animals" in violations[0]


def test_orchestration_module_may_import_app_core(tmp_path: Path) -> None:
    """Orchestration MAY import ``app.core.*`` (cross-cutting utilities)."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "migration/apply.py": (
                "from app.core.logging import log_safe\n"
                "from app.core.data_access import SqlExecutor\n"
            ),
        },
    )

    violations, _notices = _run_imports_only(tmp_path, checker, baseline={})

    assert violations == []


# ---------------------------------------------------------------------------
# Rule 4 — tests per module
# ---------------------------------------------------------------------------


def test_module_without_test_is_a_violation(tmp_path: Path) -> None:
    """A new migration module without a referencing test fails the gate."""
    checker = _load_checker()
    # Set up the test search dirs so the check actually walks the tree.
    test_search = tmp_path / "tests" / "migration"
    test_search.mkdir(parents=True)
    # Write a real test file that references `covered.py` so the OTHER
    # mapping entries pass; only `uncovered.py` is missing.
    _write(
        tmp_path,
        "tests/migration/test_covered.py",
        "from migration.covered import thing\n",
    )

    # Override the mapping for this synthetic case.
    original = dict(checker.REQUIRED_TESTS_FOR_MODULE)
    checker.REQUIRED_TESTS_FOR_MODULE = {
        "covered.py": ("tests/migration/test_covered.py",),
        "uncovered.py": ("tests/migration/test_uncovered.py",),
    }
    try:
        # No TEST_SEARCH_DIRS patch here: `_check_tests_per_module` takes the mapping as an
        # argument and passes each entry's test paths straight to `_module_referenced_in_test`,
        # so nothing in the production path ever reads that constant. The patch this block used
        # to perform was a no-op; scoping to the synthetic tree comes entirely from
        # REQUIRED_TESTS_FOR_MODULE above. Surfaced by the #490 split, which moved the constant
        # out of the checker's namespace and turned the dead patch into an AttributeError.
        results = checker._check_tests_per_module(tmp_path)
    finally:
        checker.REQUIRED_TESTS_FOR_MODULE = original

    violations = [message for _key, message in results]
    assert len(violations) == 1
    assert "uncovered.py" in violations[0]


def test_module_with_test_is_not_a_violation(tmp_path: Path) -> None:
    """A module that IS referenced by a test passes."""
    checker = _load_checker()
    _write(
        tmp_path,
        "tests/migration/test_covered.py",
        "from migration.covered import thing\n",
    )

    original = dict(checker.REQUIRED_TESTS_FOR_MODULE)
    checker.REQUIRED_TESTS_FOR_MODULE = {
        "covered.py": ("tests/migration/test_covered.py",),
    }
    try:
        # See the sibling test: patching TEST_SEARCH_DIRS was a no-op, since
        # `_check_tests_per_module` reads the test paths from the mapping above.
        results = checker._check_tests_per_module(tmp_path)
    finally:
        checker.REQUIRED_TESTS_FOR_MODULE = original

    assert results == []


# ---------------------------------------------------------------------------
# Ratchet
# ---------------------------------------------------------------------------


def test_baselined_violation_passes_and_new_one_fails(tmp_path: Path) -> None:
    """The BASELINE ratchet: known debt is tolerated, new debt fails."""
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "migration/pure_debt.py": ("from app.core.data_access import SqlExecutor\n"),
        },
    )
    original = set(checker.PURE_FILENAMES)
    checker.PURE_FILENAMES = frozenset(original | {"pure_debt.py"})
    key = "migration/pure_debt.py -> app.core.data_access [pure-imports]"
    try:
        violations, notices = _run_imports_only(tmp_path, checker, baseline={key: "known debt"})
        assert violations == []
        assert notices == []
    finally:
        checker.PURE_FILENAMES = frozenset(original)

    # Add a NEW forbidden import — same file, different target.
    _tree(
        tmp_path,
        {
            "migration/pure_debt.py": (
                "from app.core.data_access import SqlExecutor\nimport sqlalchemy\n"
            ),
        },
    )
    original = set(checker.PURE_FILENAMES)
    checker.PURE_FILENAMES = frozenset(original | {"pure_debt.py"})
    try:
        violations, _notices = _run_imports_only(tmp_path, checker, baseline={key: "known debt"})
    finally:
        checker.PURE_FILENAMES = frozenset(original)

    assert len(violations) == 1
    assert "sqlalchemy" in violations[0]


def test_stale_baseline_entry_is_reported_as_a_notice(tmp_path: Path) -> None:
    checker = _load_checker()
    violations, notices = _run_imports_only(
        tmp_path,
        checker,
        baseline={"migration/gone.py -> sqlalchemy [pure-imports]": "no longer a violation"},
    )

    assert violations == []
    assert len(notices) == 1
    assert "no longer a violation" in notices[0]


# ---------------------------------------------------------------------------
# Emit-baseline CLI
# ---------------------------------------------------------------------------


def test_emit_baseline_prints_violations_and_exits_zero(tmp_path: Path, capsys) -> None:
    """``--emit-baseline`` prints every violation as a copy-pasteable line.

    Distinct from ``check_tree`` (which fails): the goal is acquisition,
    not failure. Exit code is 0 even when violations exist.
    """
    checker = _load_checker()
    _tree(
        tmp_path,
        {
            "migration/apply.py": ("from app.modules.animals import get_animal_by_id\n"),
        },
    )

    rc = checker._emit_baseline(tmp_path)
    captured = capsys.readouterr()

    assert rc == 0
    assert "app.modules.animals" in captured.out


# ---------------------------------------------------------------------------
# CI wiring
# ---------------------------------------------------------------------------


def test_ci_workflow_lint_job_runs_migration_boundaries_gate() -> None:
    """AGENTS.md §32.P3: the gate must be a CI step, not local-only.

    Same scoping rationale as
    ``test_ci_workflow_lint_job_runs_module_size_gate``: slice the
    ``lint`` job's section and drop YAML comments so a comment
    mentioning the command can never satisfy the assertion. Removing
    this step from ``ci.yml`` is a blocked change.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    lint_job_start = workflow.index("\n  lint:")
    lint_job = workflow[lint_job_start : workflow.index("\n  security:", lint_job_start)]
    executable = "\n".join(
        line for line in lint_job.splitlines() if not line.lstrip().startswith("#")
    )

    assert "python scripts/check_migration_boundaries.py" in executable, (
        "The lint job must run the migration boundary gate "
        "(python scripts/check_migration_boundaries.py) so the "
        "pure / access-bound / orchestration contract is enforced "
        "in CI, not just PR review (AGENTS.md \u00a732.P3)."
    )


def test_checker_is_under_module_size_budget() -> None:
    """AGENTS.md §21: the new gate is itself within the 700-line budget."""
    _load_checker()  # imports the module so we know it parses
    source = CHECKER_PATH.read_text(encoding="utf-8")
    lines = len(source.splitlines())

    assert lines <= 700, (
        f"check_migration_boundaries.py is {lines} lines; AGENTS.md \u00a721 "
        f"caps new modules at 700 lines."
    )
