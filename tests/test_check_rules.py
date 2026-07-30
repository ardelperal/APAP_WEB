"""Tests for the AST-based rule linter (scripts/check_rules.py).

Per Slice 1 of hardening-2026-q2/specs/01-dev-tooling-gate/spec.md.
Parametrized suite proves each detector both directions plus the CLI contract.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_rules import (
    QuerySeamBaselineNote,
    Violation,
    _check_nested_checkout_layout,
    _is_client_execute_sql_call,
    find_violations,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "_rule_helpers" / "fixtures"
QUERY_SEAM_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "query_seam"
SCRIPT = REPO_ROOT / "scripts" / "check_rules.py"


def _rule_violations(target: Path, rule_id: str) -> list[Violation]:
    return [v for v in find_violations(target) if v.rule_id == rule_id]


# --- per-detector parametrized suite --------------------------------------


@pytest.mark.parametrize(
    "fixture_subdir",
    [
        pytest.param("detector2_positive", id="auth_defaults_true_positive"),
        pytest.param("detector3_positive", id="http_exception_redirect_positive"),
        pytest.param("detector4_positive", id="hardcoded_role_check_positive"),
    ],
)
def test_detector_flags_seeded_violation(fixture_subdir: str) -> None:
    """Each positive fixture must produce a violation with its expected rule_id."""
    rule_id_by_dir = {
        "detector2_positive": "auth_defaults_true",
        "detector3_positive": "http_exception_redirect",
        "detector4_positive": "hardcoded_role_check_in_ddl",
    }
    rule_id = rule_id_by_dir[fixture_subdir]
    target = FIXTURES / fixture_subdir
    matching = _rule_violations(target, rule_id)
    assert matching, f"Expected {rule_id} in {target}; got no matches"
    assert all(isinstance(v, Violation) for v in matching)
    assert all(v.file.suffix == ".py" for v in matching)


@pytest.mark.parametrize(
    "fixture_subdir,forbidden_rule_id",
    [
        pytest.param("detector1_negative", "route_uses_execute_sql", id="rule1_clean"),
        pytest.param("detector2_negative", "auth_defaults_true", id="rule6_clean"),
        pytest.param("detector3_negative", "http_exception_redirect", id="rule7_clean"),
        pytest.param("detector4_negative", "hardcoded_role_check_in_ddl", id="rule4_clean"),
    ],
)
def test_detector_does_not_flag_clean_code(
    fixture_subdir: str, forbidden_rule_id: str
) -> None:
    """Clean fixtures must NOT trigger the corresponding detector."""
    target = FIXTURES / fixture_subdir
    matching = _rule_violations(target, forbidden_rule_id)
    assert not matching, f"False positive {forbidden_rule_id} in {target}: {matching}"


# --- Detector 1 detail: line must point at the call site, not the decorator


def test_detector1_violation_references_correct_line() -> None:
    """Violation's line must point at the execute_sql call inside the body."""
    fixture = FIXTURES / "detector1_positive" / "handler.py"
    expected_lines = {
        node.lineno
        for node in ast.walk(ast.parse(fixture.read_text(encoding="utf-8")))
        if _is_client_execute_sql_call(node)
    }
    assert expected_lines, "fixture must seed a client.execute_sql call"
    violations = _rule_violations(
        FIXTURES / "detector1_positive", "route_uses_execute_sql"
    )
    assert violations
    assert violations[0].line in expected_lines
    assert violations[0].file.name == "handler.py"


# --- CLI exit-code contract ----------------------------------------------


def test_cli_exits_zero_when_clean() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(FIXTURES / "detector1_negative")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Expected exit 0 on clean fixture; got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_cli_exits_one_when_violation_present() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(FIXTURES / "detector1_positive")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, (
        f"Expected exit 1 on violation; got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "route_uses_execute_sql" in result.stdout


# --- Detector 10 (Rule 25): duplicate_helper_definition -------------------


def test_detector10_flags_new_duplicate_beyond_baseline() -> None:
    """``_opt`` defined in two fixture files (neither in the real repo's
    BASELINE_DUPLICATE_HELPERS) must be flagged in both files."""
    target = FIXTURES / "detector10_violates"
    matching = _rule_violations(target, "duplicate_helper_definition")
    flagged_files = {v.file.name for v in matching}
    assert flagged_files == {"routes.py"}
    # Both the foo/ and bar/ copies must be flagged (2 distinct files).
    assert len({v.file for v in matching}) == 2


def test_detector10_does_not_flag_single_definition() -> None:
    """A watched name defined in exactly one file must NOT be flagged."""
    target = FIXTURES / "detector10_clean"
    matching = _rule_violations(target, "duplicate_helper_definition")
    assert not matching


def test_detector10_baseline_grandfathers_known_repo_duplication() -> None:
    """The real repo's known (#227) duplication must NOT be flagged —
    only NEW files beyond BASELINE_DUPLICATE_HELPERS would be."""
    matching = _rule_violations(REPO_ROOT, "duplicate_helper_definition")
    assert not matching, (
        "New duplicate_helper_definition violation(s) beyond the tracked "
        f"#227 baseline: {[(str(v.file), v.line) for v in matching]}"
    )


# --- Detector 11 (Rule 26): unjustified_lazy_import ------------------------


def test_detector11_flags_unjustified_lazy_import() -> None:
    target = FIXTURES / "detector11_violates"
    matching = _rule_violations(target, "unjustified_lazy_import")
    assert matching
    assert matching[0].file.name == "violating_handler.py"


def test_detector11_flags_empty_lazy_import_marker() -> None:
    target = FIXTURES / "detector11_empty_marker"
    matching = _rule_violations(target, "unjustified_lazy_import")
    assert matching


def test_detector11_allows_justified_lazy_import() -> None:
    target = FIXTURES / "detector11_clean"
    matching = _rule_violations(target, "unjustified_lazy_import")
    assert not matching


def test_detector11_repo_has_no_unjustified_lazy_imports() -> None:
    """The two known lazy imports (issue #226, config.py + auth_dependencies.py)
    both carry a 'lazy-import:' marker as of this rule landing."""
    matching = _rule_violations(REPO_ROOT, "unjustified_lazy_import")
    assert not matching, (
        f"Unjustified lazy import(s): {[(str(v.file), v.line) for v in matching]}"
    )


# --- Detector 12 (Rule 27): cross_module_submodule_import / _private_import


def test_detector12_flags_submodule_reach() -> None:
    target = FIXTURES / "detector12_violates_submodule"
    matching = _rule_violations(target, "cross_module_submodule_import")
    assert matching
    assert matching[0].file.name == "routes.py"


def test_detector12_flags_plain_import_submodule_reach() -> None:
    target = FIXTURES / "detector12_violates_import"
    matching = _rule_violations(target, "cross_module_submodule_import")
    assert matching
    assert matching[0].file.name == "routes.py"


def test_detector12_flags_private_name_import() -> None:
    target = FIXTURES / "detector12_violates_private"
    matching = _rule_violations(target, "cross_module_private_import")
    assert matching
    assert matching[0].file.name == "routes.py"


def test_detector12_does_not_flag_public_api_import() -> None:
    target = FIXTURES / "detector12_clean"
    matching = _rule_violations(
        target, "cross_module_submodule_import"
    ) + _rule_violations(target, "cross_module_private_import")
    assert not matching


def test_detector12_repo_only_has_the_known_baselined_violation() -> None:
    """The real repo must produce zero NEW cross-module violations beyond
    the single #231 baseline entry (foster/assignment.py -> animals.service).
    The acogidas/routes.py -> foster.assignment instance found by the same
    2026-07-20 review was fixed directly in this PR (import renamed to the
    public ``assignment_service`` alias foster/__init__.py already exports).
    """
    submodule = _rule_violations(REPO_ROOT, "cross_module_submodule_import")
    private = _rule_violations(REPO_ROOT, "cross_module_private_import")
    assert not private, (
        f"New cross_module_private_import violation(s): "
        f"{[(str(v.file), v.line) for v in private]}"
    )
    assert not submodule, (
        f"New cross_module_submodule_import violation(s) beyond the #231 "
        f"baseline: {[(str(v.file), v.line) for v in submodule]}"
    )


# --- Detector 13 (Rule 22): query_seam_violation -------------------------


def _query_seam_violations(
    target: Path,
) -> tuple[list[Violation], list[QuerySeamBaselineNote]]:
    """Return (violations, baseline_notes) for the query seam detector.

    Used for fixture directories. The legacy fixture uses ``sample`` as the
    module name (not a real domain module); the check below correctly
    identifies it as a baselined module and emits the appropriate note or
    violation based on whether it is in BASELINE_NO_QUERIES_MODULES.
    """
    import ast

    from scripts.check_rules import (
        _check_query_seam_violation,
    )

    violations: list[Violation] = []
    notes: list[QuerySeamBaselineNote] = []
    for path in target.rglob("service.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        # Derive module name from path: target/app/modules/<M>/service.py
        # parts[0]="app", parts[1]="modules", parts[2]=<M>, parts[3]=service.py
        try:
            rel = path.relative_to(target)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) < 3 or parts[0] != "app" or parts[1] != "modules":
            continue
        module_name = parts[2]
        results = _check_query_seam_violation(tree, module_name, path)
        for r in results:
            if isinstance(r, Violation):
                violations.append(r)
            else:
                notes.append(r)
    return violations, notes


def _violations_for_module(
    module_dir: Path,
) -> list[Violation]:
    """Return query_seam_violation violations for a single module directory.

    The ``module_dir.name == "sample"`` guard skips the fixture sample
    module when this helper is accidentally called with a fixture dir;
    for real-repo calls the module name comes from BASELINE_NO_QUERIES_MODULES
    which does not contain ``sample``.
    """
    import ast

    from scripts.check_rules import (
        _check_query_seam_violation,
    )

    service_path = module_dir / "service.py"
    if not service_path.exists():
        return []
    try:
        tree = ast.parse(service_path.read_text(encoding="utf-8"), filename=str(service_path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    module_name = module_dir.name
    if module_name == "sample":
        return []  # skip fixture sample (not a real domain module)
    results = _check_query_seam_violation(tree, module_name, service_path)
    return [r for r in results if isinstance(r, Violation)]


# T1: Baseline ratchet — BASELINE_NO_QUERIES_MODULES may only shrink
@pytest.mark.parametrize(
    "module_name",
    [
        pytest.param("materiales", id="materiales_has_queries_py"),
        pytest.param("acogidas", id="acogidas_has_queries_py"),
    ],
)
def test_baseline_no_queries_modules_shrink_only(module_name: str) -> None:
    """Adding a module that HAS queries.py to BASELINE_NO_QUERIES_MODULES
    must fail the ratchet: modules that already follow §22 cannot be
    added to the baseline because it would cause false negatives for
    compliant modules (T1 per the tasks spec)."""
    from scripts.check_rules import BASELINE_NO_QUERIES_MODULES

    assert module_name not in BASELINE_NO_QUERIES_MODULES, (
        f"{module_name!r} is NOT in BASELINE_NO_QUERIES_MODULES — "
        f"modules that already have queries.py (and therefore follow §22) "
        f"must NOT be added to the baseline; the ratchet only shrinks."
    )


# T2: Legacy fixture — no queries.py, has SQL constant → CRITICAL violation
def test_detector13_legacy_module_violates() -> None:
    """A legacy module (in BASELINE_NO_QUERIES_MODULES) without queries.py
    but with a _*_SQL constant in service.py must be flagged."""
    target = QUERY_SEAM_FIXTURES / "legacy"
    violations, notes = _query_seam_violations(target)
    assert violations, "Expected query_seam_violation for legacy module; got none"
    assert violations[0].rule_id == "query_seam_violation"


# T3: Compliant fixture — has queries.py + SQL constant → no violation
def test_detector13_compliant_module_passes() -> None:
    """A compliant module with both queries.py and _*_SQL in service.py
    must NOT be flagged (it follows the §22 seam correctly)."""
    target = QUERY_SEAM_FIXTURES / "compliant"
    violations, notes = _query_seam_violations(target)
    assert not violations, f"Compliant module should not be flagged: {violations}"


# T4: Empty fixture — service.py with no SQL → no violation
def test_detector13_empty_service_passes() -> None:
    """A module with service.py containing no SQL constants must NOT be
    flagged (no violation possible when there are no _*_SQL constants)."""
    target = QUERY_SEAM_FIXTURES / "empty"
    violations, notes = _query_seam_violations(target)
    assert not violations, f"Empty service should not be flagged: {violations}"


# T5: Sibling fixture — batch_service.py with SQL (not service.py) → ignored
def test_detector13_sibling_batch_service_ignored() -> None:
    """A batch_service.py sibling file with SQL (but no service.py SQL)
    must NOT be flagged — the detector only checks service.py."""
    target = QUERY_SEAM_FIXTURES / "sibling"
    violations, notes = _query_seam_violations(target)
    assert not violations, (
        f"batch_service.py SQL should not be flagged (detector checks "
        f"service.py only): {violations}"
    )


# T6: Real repo — all legacy modules in baseline produce zero violations
def test_detector13_repo_legacy_modules_grandfathered() -> None:
    """The seven legacy modules currently without queries.py are in
    BASELINE_NO_QUERIES_MODULES and must NOT produce violations."""
    from scripts.check_rules import BASELINE_NO_QUERIES_MODULES

    violations: list[Violation] = []
    for module_name in BASELINE_NO_QUERIES_MODULES:
        module_dir = REPO_ROOT / "app" / "modules" / module_name
        if not module_dir.exists():
            continue
        violations.extend(_violations_for_module(module_dir))
    assert not violations, (
        f"Legacy baselined modules should not produce violations: "
        f"{[(str(v.file), v.line, v.rule_id) for v in violations]}"
    )


# T7: Real repo — compliant modules produce zero violations
def test_detector13_repo_compliant_modules_passes() -> None:
    """The modules that already follow §22 (acogidas, materiales) must
    NOT produce query_seam_violation violations."""
    violations: list[Violation] = []
    for module_name in ("acogidas", "materiales"):
        module_dir = REPO_ROOT / "app" / "modules" / module_name
        if not module_dir.exists():
            continue
        violations.extend(_violations_for_module(module_dir))
    assert not violations, (
        f"Compliant modules (acogidas, materiales) should not be flagged: "
        f"{[(str(v.file), v.line, v.rule_id) for v in violations]}"
    )


# T8: Synthetic new module with _*_SQL but no queries.py → CRITICAL
def test_detector13_new_module_with_sql_violates() -> None:
    """A NEW module (not in BASELINE_NO_QUERIES_MODULES) with _*_SQL
    in service.py but no queries.py must be flagged as a CRITICAL
    violation (it is violating §22 without grandfathering)."""
    target = QUERY_SEAM_FIXTURES / "synthetic_violation"
    violations, notes = _query_seam_violations(target)
    assert violations, (
        "Expected query_seam_violation for synthetic new module with SQL; got none"
    )
    assert violations[0].rule_id == "query_seam_violation"


# T22: linter exits 0 on main (7 baseline INFO notes, no CRITICAL)
def test_detector13_linter_exits_zero_on_main() -> None:
    """scripts/check_rules.py . must exit 0 on main — the seven legacy
    modules are grandfathered in BASELINE_NO_QUERIES_MODULES and the
    two compliant modules (acogidas, materiales) have queries.py."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(REPO_ROOT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Expected exit 0 on main; got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "query_seam_violation" not in result.stdout, (
        f"query_seam_violation should not appear on main: {result.stdout}"
    )


# T9: Regression — Detector 13 must catch ast.AnnAssign, not just ast.Assign
def test_detector_13_annassign_critical_violation() -> None:
    """Detector must catch ast.AnnAssign, not just ast.Assign (issue #290 fix)."""
    fixtures_root = Path(__file__).parent / "fixtures" / "query_seam"
    path = fixtures_root / "annassign_violation"
    violations, _notes = _query_seam_violations(path)
    assert any(v.rule_id == "query_seam_violation" for v in violations), (
        f"Annotated assignment SQL was not flagged. "
        f"violations={[v.rule_id for v in violations]}"
    )


# --- Nested-checkout guard (issue #340) -------------------------------------


def test_guard_detects_apap_web_root() -> None:
    """The APAP_WEB/ root has 00_main/ as a subdirectory and .git as a
    FILE (gitdir: worktree root). Running check_rules.py from there
    walks nested checkouts and produces false violations. The guard
    detects this layout and returns an error message."""
    # REPO_ROOT is the worktree (wt-340/); its parent's parent is the
    # actual APAP_WEB root (C:/00repos/codigo/APAP_WEB/).
    apap_web_root = REPO_ROOT.parent.parent
    # This layout only exists on the local Windows dev setup with flat worktrees.
    # In CI (Linux, regular clone) there is no 00_main/ sibling — skip.
    if not (apap_web_root / "00_main").is_dir():
        pytest.skip("00_main/ not found — not running from APAP_WEB flat-layout root")
    result = _check_nested_checkout_layout(apap_web_root)
    assert result is not None, (
        "Expected guard to detect APAP_WEB/ root layout "
        "(has 00_main/ subdir and .git as file)"
    )
    assert "00_main/" in result, "Error message must direct operator to 00_main/"
    assert "run from" in result.lower() or "cd 00_main" in result.lower()


def test_guard_allows_canonical_worktree() -> None:
    """Running from 00_main/ (where .git is a directory, not a file)
    must NOT trigger the guard."""
    # REPO_ROOT is the canonical worktree (00_main/ equivalent).
    result = _check_nested_checkout_layout(REPO_ROOT)
    assert result is None, (
        "Canonical worktree (00_main/) must not trigger the guard; "
        f"got: {result}"
    )


def test_guard_allows_normal_repo() -> None:
    """A normal repo (no 00_main/ subdirectory) must not trigger."""
    result = _check_nested_checkout_layout(FIXTURES)
    assert result is None, (
        f"Normal repo (no 00_main/ subdirectory) must not trigger; got: {result}"
    )


def test_guard_cli_fails_from_apap_web_root() -> None:
    """CLI must exit 1 when cwd is the APAP_WEB/ root layout."""
    # REPO_ROOT is the worktree (wt-340/); its parent's parent is the
    # actual APAP_WEB root (C:/00repos/codigo/APAP_WEB/).
    apap_web_root = REPO_ROOT.parent.parent
    # This layout only exists on the local Windows dev setup with flat worktrees.
    # In CI (Linux, regular clone) there is no 00_main/ sibling — skip.
    if not (apap_web_root / "00_main").is_dir():
        pytest.skip("00_main/ not found — not running from APAP_WEB flat-layout root")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "."],
        capture_output=True,
        text=True,
        cwd=str(apap_web_root),
    )
    assert result.returncode == 1, (
        f"Expected exit 1 from APAP_WEB/ root; got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "00_main/" in combined, (
        f"Error message must mention 00_main/: {combined}"
    )
