"""Test classification ratchet for APAP_WEB.

Enforces that for every domain that mocks SQL in unit tests, there is at
least one integration test against real Postgres when the flow involves
behaviour that mocks cannot verify.

Per ``docs/quality/test-audit.md`` (2026-08-31) and the
``apap-testing-strategy`` skill, the canonical gaps are:

    - ``entradas`` batch CTE rollback (P0)
    - ``cesiones`` conflict resolution (P0)
    - ``auth`` revalidation round-trip (P0)
    - chip cascade across animals/voluntarios/acogidas (P0)
    - ``animal_lifecycle_events`` append-only trigger (P0)

The ratchet locks this in: every domain whose unit tests mock SQL must
have either:

  1. A matching ``tests/integration/test_<modulo>_queries_integration.py``, or
  2. An explicit entry in the ``BASELINE`` mapping module name -> rationale.

This is a shrink-only ratchet: entries may only be removed when the
matching integration file lands. Adding a unit test for a flow that the
audit flagged as P0 without the matching integration test is a regression
and fails the gate.

The list of in-scope domains is **curated from the audit** — it is not
discovered by file-name heuristics, because too many unit tests in this
repo exercise pure functions or meta-tests that do not warrant integration
coverage.

A second, unrelated gate lives in the same script (``_integration_marker_violations``):
every ``tests/integration/test_*.py`` file must carry the ``integration``
marker (module-level ``pytestmark`` or a decorator on every test), because
pytest selection depends on it in BOTH CI jobs -- the ``test`` job excludes
the whole ``tests/integration`` directory (``addopts``) and the
``integration`` job filters with ``-m integration``. A file missing the
marker collects in neither job and silently never runs (issue #932). This
gate is NOT baseline-able: an unmarked file is always a violation.

Usage::

    python scripts/check_test_classification.py [root]

``root`` defaults to the repository root. Exit code 0 when clean, 1 on any
violation. Stdlib-only, deterministic, no external services.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"
INTEGRATION_DIR = TESTS_DIR / "integration"

# Domains that have unit tests mocking SQL via httpx.MockTransport AND
# whose flows involve behaviour that httpx.MockTransport cannot verify
# against real Postgres (FK enforcement, triggers, CTE rollback,
# ON CONFLICT, soft-delete cascade).
#
# The list is curated from docs/quality/test-audit.md (2026-08-31). To add
# a new entry you must:
#   1. Land the integration file under tests/integration/ in the same PR.
#   2. Update docs/quality/test-audit.md to remove the gap.
#   3. Remove the matching BASELINE entry in this script (or move it to
#      COVERED once the integration file exists).
#
# This list is intentionally narrow — pure functions, helpers, route-layer
# contract tests, and meta-tests do not belong here. The skill
# ``apap-testing-strategy`` is the norm that defines the cut.
IN_SCOPE_DOMAINS: set[str] = {
    "acogidas",
    "adopciones",
    "auth",
    "cesiones",
    "entradas",
    "materiales",
    "salud",
    "sanidad",
}

# Domains that legitimately have only unit coverage at the moment.
# Each entry is (module_name, reason).
#
# A domain is "baselined" when:
#   - It is in IN_SCOPE_DOMAINS, AND
#   - It has unit tests that mock SQL, AND
#   - It does NOT have a matching integration file.
#
# The reason must cite docs/quality/test-audit.md so the BASELINE stays
# traceable to its source of truth.
BASELINE: dict[str, str] = {
}

REQUIRED_ATOMS: dict[str, frozenset[str]] = {
    "auth": frozenset(
        {
            "test_get_user_by_email_returns_user_when_active",
            "test_get_user_by_email_returns_none_after_deactivation",
        }
    ),
    "cesiones": frozenset(
        {
            "test_cesion_unique_constraint_fires_on_duplicate_entrada",
            "test_cesion_fk_constraint_fires_on_ghost_entrada",
        }
    ),
    "entradas": frozenset(
        {
            "test_commit_batch_cte_rolls_back_on_unique_violation",
            "test_commit_batch_cte_rolls_back_on_fk_violation",
        }
    ),
}


def _integration_contract_errors(integration_dir: Path, module: str) -> list[str]:
    """Validate that a module has collected integration atoms, not an empty file."""
    target = integration_dir / f"test_{module}_queries_integration.py"
    if not target.exists():
        return ["file is missing"]
    try:
        tree = ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        return [f"file is not parseable: {exc}"]

    tests = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }
    if not tests:
        return ["file collects no test functions"]

    errors: list[str] = []
    unmarked = [name for name, node in tests.items() if not _has_integration_marker(node)]
    if unmarked:
        errors.append(f"tests lack @pytest.mark.integration: {', '.join(sorted(unmarked))}")
    missing_atoms = sorted(REQUIRED_ATOMS.get(module, frozenset()) - tests.keys())
    if missing_atoms:
        errors.append(f"required P0 atoms are missing: {', '.join(missing_atoms)}")
    return errors


def _has_integration_marker(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Attribute) or decorator.attr != "integration":
            continue
        mark = decorator.value
        if (
            isinstance(mark, ast.Attribute)
            and mark.attr == "mark"
            and isinstance(mark.value, ast.Name)
            and mark.value.id == "pytest"
        ):
            return True
    return False


def _is_integration_mark_expr(value: ast.expr) -> bool:
    """True for the ``pytest.mark.integration`` attribute chain itself."""
    return (
        isinstance(value, ast.Attribute)
        and value.attr == "integration"
        and isinstance(value.value, ast.Attribute)
        and value.value.attr == "mark"
        and isinstance(value.value.value, ast.Name)
        and value.value.value.id == "pytest"
    )


def _has_module_level_integration_pytestmark(tree: ast.Module) -> bool:
    """True when top-level ``pytestmark`` names ``pytest.mark.integration``.

    Covers both ``pytestmark = pytest.mark.integration`` and
    ``pytestmark = [pytest.mark.integration, ...]`` — both apply the marker
    to every test collected from the module (pytest's own contract).
    """
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            continue
        value = node.value
        if isinstance(value, (ast.List, ast.Tuple)):
            if any(_is_integration_mark_expr(elt) for elt in value.elts):
                return True
        elif _is_integration_mark_expr(value):
            return True
    return False


def _integration_marker_file_errors(path: Path) -> list[str]:
    """Return violations when ``path`` does not carry the ``integration`` marker.

    A file is clean when either the whole module opts in via a top-level
    ``pytestmark = pytest.mark.integration`` (or a list containing it), or
    every ``test_*`` function/coroutine is individually decorated with
    ``@pytest.mark.integration``. A file with no collected tests (e.g. an
    empty scaffold) is not this gate's concern — ``_integration_contract_errors``
    already flags that for in-scope domains.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        return [f"{path.name}: file is not parseable: {exc}"]

    if _has_module_level_integration_pytestmark(tree):
        return []

    tests = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    if not tests:
        return []

    unmarked = sorted(node.name for node in tests if not _has_integration_marker(node))
    if not unmarked:
        return []
    return [
        f"{path.name}: no pytest.mark.integration marker (neither a module-level "
        f"pytestmark nor a decorator on every test) -- unmarked: {', '.join(unmarked)}"
    ]


def _integration_marker_violations(integration_dir: Path) -> list[str]:
    """Return violations for every ``tests/integration/test_*.py`` file
    that pytest's ``-m integration`` selection in the CI ``integration``
    job would silently skip (issue #932): a file under this directory
    whose tests never run in ANY CI job because it lacks the marker that
    both ``addopts`` (job ``test``, excludes the whole directory) and the
    ``integration`` job (``-m integration``) rely on.
    """
    if not integration_dir.exists():
        return []
    violations: list[str] = []
    for path in sorted(integration_dir.glob("test_*.py")):
        violations.extend(_integration_marker_file_errors(path))
    return violations


def check_tree(root: Path) -> tuple[list[str], list[str]]:
    """Return (violations, notices) for the test-classification ratchet."""
    integration_dir = root / "tests" / "integration"
    violations: list[str] = []
    open_baselined: set[str] = set()
    for module in sorted(IN_SCOPE_DOMAINS):
        contract_errors = _integration_contract_errors(integration_dir, module)
        if not contract_errors:
            continue
        if module in BASELINE:
            open_baselined.add(module)
            continue
        for error in contract_errors:
            violations.append(f"{module}: {error}")
    violations.extend(_integration_marker_violations(integration_dir))
    # Notices:
    # - BASELINE modules whose gap is still open (no integration file).
    # - BASELINE modules no longer in IN_SCOPE_DOMAINS (stale).
    notices = [
        f"{key}: baselined -- create tests/integration/test_{key}_queries_integration.py "
        f"to lock in the improvement. Reason: {BASELINE[key]}"
        for key in sorted(open_baselined)
    ] + [
        f"{key}: stale BASELINE entry (not in IN_SCOPE_DOMAINS) -- remove "
        f"from scripts/check_test_classification.py. Reason was: {BASELINE[key]}"
        for key in sorted(set(BASELINE) - IN_SCOPE_DOMAINS)
    ]
    return violations, notices


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    _pin_output_encoding()
    root = Path(args[0]).resolve() if args else REPO_ROOT

    violations, notices = check_tree(root)

    for notice in notices:
        print(f"NOTE {notice}")
    for violation in violations:
        print(f"FAIL {violation}")

    if violations:
        print(
            f"check_test_classification: {len(violations)} violation(s). Every "
            f"domain whose unit tests mock SQL must have an integration atom "
            f"against real Postgres when the flow involves FK enforcement, "
            f"triggers, CTE rollback, or ON CONFLICT. See "
            f"docs/quality/test-audit.md."
        )
        return 1
    open_baseline_count = sum(
        1 for n in notices if "baselined --" in n
    )
    print(
        f"check_test_classification: OK "
        f"({open_baseline_count} baselined gap(s) still open; "
        f"shrink by landing the matching integration file)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
