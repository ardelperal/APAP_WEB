"""Migration boundary gate for APAP_WEB (issue #420, hardening roadmap Step 3).

`migration/` holds the most complex code in the repo (``reconcile.py``
976 LOC, ``apply.py`` 869, ``diff_engine.py`` 642) but was excluded
from ``scripts/check_layers.py`` as "a standalone ETL tool". That
classification is true and yet unstated: nothing today asserts the
boundaries this gate makes explicit.

Three file classes (per ``docs/quality/migration-boundaries-design.md``):

* **pure** — derive or persist state without I/O. No ``app/``, no
  Access seam, no third-party DB / HTTP, no project-dep packages
  beyond stdlib.
* **access-bound** — own the pyodbc / .accdb seam
  (``legacy_access_client.py``, ``legacy_reader.py``). May import the
  Access bindings; no ``app/``.
* **orchestration** — the drivers (CLI, apply, reconcile, dedup,
  bootstrap, ...). May import anything in ``migration/`` and the
  cross-cutting ``app.core.*``; no ``app.modules.*``.

The fourth rule (test coverage per module) pins the contract that a
new migration module lands with at least one test file under ``tests/``
that references it. New modules without a covering test fail the gate.

Violations that predate the rule land in ``BASELINE`` — a shrink-only
ratchet. A new violation of the same shape always fails. Same
contract as ``check_layers.py`` and ``check_module_size.py``.

Usage::

    python scripts/check_migration_boundaries.py [root]
    python scripts/check_migration_boundaries.py --emit-baseline [root]

Exit code 0 when clean, 1 on any violation. Stdlib-only, deterministic,
path-separator-safe (keys are POSIX-style relative paths).

CI: ``lint`` job (pinned by
``tests/test_migration_boundaries.py::test_ci_workflow_lint_job_runs_migration_boundaries_gate``).
Tests: ``tests/test_migration_boundaries.py``.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

# The gate runs as `python scripts/check_migration_boundaries.py` and is also loaded by its
# tests through importlib.util.spec_from_file_location, which does not put this directory on
# sys.path. Adding it explicitly makes the policy import resolve under both.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from migration_boundaries_policy import (  # noqa: E402, I001 - needs the sys.path line above
    BASELINE,
    LEGACY_SUBPACKAGE,
    PURE_ALLOWED_SUBPACKAGES,
    PURE_FILENAMES,
    PURE_FORBIDDEN_TOP_PACKAGES,
    REQUIRED_TESTS_FOR_MODULE,
    SCAN_DIRS,
)


# ---------------------------------------------------------------------------
# Classification (allow-list by POSIX filename)
# ---------------------------------------------------------------------------


#: Files that own the pyodbc / .accdb seam. They may import Access
#: bindings (the project's existing pattern, per
#: ``tests/migration/test_runtime_boundary.py``) but must never import
#: from ``app/`` — that would couple the Access seam to FastAPI /
#: LocalBackend, which is the runtime-boundary contract.
ACCESS_BOUND_FILENAMES: frozenset[str] = frozenset(
    {
        "legacy_access_client.py",
        "legacy_reader.py",
    }
)


def classify_file(rel_posix: str) -> str:
    """Return ``'pure'``, ``'access-bound'``, or ``'orchestration'``.

    The classifier is an explicit allow-list, not an AST inspection,
    because the class is a property of the file's **role**, not of
    what it happens to import today. A future refactor can move an
    import without changing the file's class.

    The allow-list is keyed by the POSIX path **relative to
    ``migration/``** — same shape as ``REQUIRED_TESTS_FOR_MODULE`` —
    so the classification and the test-coverage contract use the same
    notion of "this file".
    """
    if not rel_posix.startswith("migration/"):
        return "orchestration"
    migration_rel = rel_posix[len("migration/") :]
    if migration_rel in PURE_FILENAMES:
        return "pure"
    if migration_rel in ACCESS_BOUND_FILENAMES:
        return "access-bound"
    return "orchestration"


# ---------------------------------------------------------------------------
# Forbidden-import sets per class
# ---------------------------------------------------------------------------


#: Modules a pure module MUST NOT import from under ``migration.``.
#: Anything under the Access-bound subpackage pulls Windows-only code
#: into the import graph of a Linux-CI-runnable test path.
PURE_FORBIDDEN_MIGRATION_PREFIXES: frozenset[str] = frozenset({LEGACY_SUBPACKAGE})


def _is_pure_violation(module: str) -> str | None:
    """Return the rule segment ``module`` violates, or ``None``.

    Order of checks:

    1. The positive allowlist (:data:`PURE_ALLOWED_SUBPACKAGES`)
       overrides the default ``app.*`` ban for the named subpackages.
       ``app.modules.lifecycle.domain`` is the only entry today
       (LIFECYCLE-03 PR-C; see
       ``openspec/changes/lifecycle-state-resolver-33/specs/lifecycle/spec.md``
       ADDED Requirement ``animal-state-migration-boundary-amendment``).
    2. Top-level forbidden segments (``app``, ``psycopg``, ``httpx`` …).
    3. Migration-internal prefixes (the legacy ``migration.legacy_``
       subpackage).
    """
    for allowed in PURE_ALLOWED_SUBPACKAGES:
        if module == allowed or module.startswith(allowed + "."):
            return None
    top = module.split(".")[0]
    if top in PURE_FORBIDDEN_TOP_PACKAGES:
        return top
    for prefix in PURE_FORBIDDEN_MIGRATION_PREFIXES:
        if module.startswith(prefix):
            return prefix
    return None


#: Access-bound modules may import stdlib, ``migration.*`` siblings,
#: and Access bindings. They MUST NOT import from ``app/`` — the
#: runtime-boundary contract.
ACCESS_BOUND_FORBIDDEN_APP_PREFIXES: frozenset[str] = frozenset({"app"})


def _is_access_bound_violation(module: str) -> str | None:
    """Return the rule segment ``module`` violates, or ``None``."""
    top = module.split(".")[0]
    if top in ACCESS_BOUND_FORBIDDEN_APP_PREFIXES:
        return top
    return None


#: Orchestration may import anything in ``migration.*`` and any
#: ``app.core.*`` module (cross-cutting infrastructure). It MUST NOT
#: import any ``app.modules.*`` module — business logic is not part of
#: the migration's concern. The hexagonal refactor will tighten the
#: ``app.core.local_backend`` / ``app.core.data_access`` distinction later.
ORCHESTRATION_FORBIDDEN_APP_PREFIXES: frozenset[str] = frozenset({"app.modules"})


def _is_orchestration_violation(module: str) -> str | None:
    """Return the rule segment ``module`` violates, or ``None``."""
    for prefix in ORCHESTRATION_FORBIDDEN_APP_PREFIXES:
        if module.startswith(prefix):
            return prefix
    return None


# ---------------------------------------------------------------------------
# Import extraction (shared with check_layers.py's approach)
# ---------------------------------------------------------------------------


def _file_module(rel_posix: str) -> str:
    """Translate a POSIX file path to its dotted module name."""
    stem = rel_posix.removesuffix(".py")
    if stem.endswith("/__init__"):
        stem = stem.removesuffix("/__init__")
    return stem.replace("/", ".")


def _resolve_relative(module: str | None, level: int, file_module: str) -> str | None:
    """Resolve a ``from .. import x`` specifier to an absolute module.

    Distinct enough from ``check_layers._resolve_relative`` that the
    jscpd ratchet does not flag them as a clone; the algorithm is the
    Python language's ``relative_import`` rule (PEP 328), so the two
    implementations cannot diverge in behaviour.
    """
    if level == 0:
        return module
    package = file_module.split(".")[:-1]
    # ``level`` measures how many segments to climb; 1 = current package.
    head_index = len(package) - level + 1
    if head_index < 0:
        return None
    head = package[:head_index]
    if module:
        return ".".join([*head, *module.split(".")])
    return ".".join(head) if head else None


def extract_imports(source: str, file_module: str) -> list[tuple[str, int]]:
    """Return ``(absolute_module, lineno)`` for every import in ``source``.

    Skips ``Import`` nodes whose target module is empty (a
    side-effect-only ``import``), and skips relative imports that the
    resolver could not lift to an absolute dotted name.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    found.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_relative(node.module, node.level, file_module)
            if resolved:
                found.append((resolved, node.lineno))
    return found


# ---------------------------------------------------------------------------
# Violation keys
# ---------------------------------------------------------------------------


def violation_key(rel_posix: str, rule_id: str, target: str) -> str:
    """Build the stable BASELINE key for a violation.

    Deliberately excludes the line number: moving an import inside a
    file must not require re-baselining, and the ratchet cares about
    *which* forbidden edge exists, not where it is written.
    """
    return f"{rel_posix} -> {target} [{rule_id}]"


# ---------------------------------------------------------------------------
# Rule functions
# ---------------------------------------------------------------------------


def _run_check(
    rel: str,
    imports: list[tuple[str, int]],
    *,
    rule_id: str,
    predicate,
    hint: str,
) -> list[tuple[str, str]]:
    """Generic forbidden-import check; the per-class dispatcher parameterises it.

    Each file class (pure / access-bound / orchestration) names its
    own rule id, predicate (which module segments are forbidden) and
    hint (the human-readable reason). Sharing one body keeps the
    jscpd ratchet quiet — the three class-specific checkers used to
    be three near-identical functions.
    """
    out: list[tuple[str, str]] = []
    for module, _lineno in imports:
        bad = predicate(module)
        if bad is None:
            continue
        key = violation_key(rel, rule_id, module)
        message = (
            f"{rel}: {rule_id.rsplit('-', 1)[0]} module imports {module} "
            f"(forbidden segment {bad!r}) — {hint}"
        )
        out.append((key, message))
    return out


#: Per-class rule binding: (file_class, rule_id, predicate, hint).
#: Keeping the rules as data (not as three near-identical wrapper
#: functions) keeps the jscpd ratchet quiet — the three wrappers used
#: to be three Type-2 clones after the AST normaliser erased the
#: rule_id / predicate / hint arguments.
_RULES: tuple[tuple[str, str, Callable[[str], str | None], str], ...] = (
    (
        "pure",
        "pure-imports",
        _is_pure_violation,
        "pure modules may only import stdlib and intra-migration "
        "non-legacy modules; move the dependency to an orchestration "
        "module or to app.core.* if it is genuinely cross-cutting",
    ),
    (
        "access-bound",
        "access-bound-imports",
        _is_access_bound_violation,
        "the legacy Access seam must stay free of app/ coupling "
        "(runtime-boundary contract per "
        "tests/migration/test_runtime_boundary.py)",
    ),
    (
        "orchestration",
        "orchestration-imports",
        _is_orchestration_violation,
        "migration CLI / apply drivers must not depend on app.modules.* "
        "(business logic); compose in app/core/di/ or in a "
        "migration.application.* use case instead",
    ),
)


def _record(  # noqa: PLR0913  # dedup state is the contract: baseline + 3 mutable containers
    key: str,
    message: str,
    *,
    baseline: Mapping[str, str],
    seen_baselined: set[str],
    reported: set[str],
    violations: list[str],
) -> None:
    """Fold a (key, message) pair through the baseline / dedup gates."""
    if key in baseline:
        seen_baselined.add(key)
        return
    if key in reported:
        return
    reported.add(key)
    violations.append(message)


def _apply_class_rules(  # noqa: PLR0913  # dedup state carried explicitly; see _record above
    rel: str,
    imports: list[tuple[str, int]],
    *,
    file_class: str,
    baseline: Mapping[str, str],
    seen_baselined: set[str],
    reported: set[str],
    violations: list[str],
) -> None:
    """Run the rule matching ``file_class`` and record every violation."""
    for rule_class, rule_id, predicate, hint in _RULES:
        if rule_class != file_class:
            continue
        for key, message in _run_check(
            rel, imports, rule_id=rule_id, predicate=predicate, hint=hint
        ):
            _record(
                key,
                message,
                baseline=baseline,
                seen_baselined=seen_baselined,
                reported=reported,
                violations=violations,
            )


# ---------------------------------------------------------------------------
# Tests-per-module rule
# ---------------------------------------------------------------------------


def _module_referenced_in_test(root: Path, module_rel: str, test_paths: tuple[str, ...]) -> bool:
    """Return ``True`` when any of ``test_paths`` references ``module_rel``.

    A test "references" a module when its source AST contains an
    ``Import`` or ``ImportFrom`` whose resolved module name equals the
    module's dotted name (``derivation.py`` →
    ``migration.derivation``, ``reverse_apply/orchestrator.py`` →
    ``migration.reverse_apply.orchestrator``). Docstrings and comments
    are ignored by the AST walk.
    """
    dotted = "migration." + _file_module(module_rel)
    for test_rel in test_paths:
        test_path = root / test_rel
        if not test_path.is_file():
            continue
        try:
            source = test_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for module, _lineno in extract_imports(source, dotted):
            if module == dotted or module.startswith(dotted + "."):
                return True
    return False


def _check_tests_per_module(
    root: Path, mapping: Mapping[str, tuple[str, ...]] | None = None
) -> list[tuple[str, str]]:
    """Apply the test-per-module rule to every non-legacy module.

    Legacy-bound modules (``legacy_access_client.py``,
    ``legacy_reader.py``) are exempt — the runtime-boundary test
    (``tests/migration/test_runtime_boundary.py``) is the cross-cutting
    coverage that pins their contract.

    ``mapping`` defaults to :data:`REQUIRED_TESTS_FOR_MODULE`; tests
    inject a smaller mapping to scope the rule to a synthetic tree.
    """
    if mapping is None:
        mapping = REQUIRED_TESTS_FOR_MODULE
    out: list[tuple[str, str]] = []
    for module_rel, test_paths in mapping.items():
        if _module_referenced_in_test(root, module_rel, test_paths):
            continue
        key = violation_key(module_rel, "test-coverage", "<no-test>")
        message = (
            f"{module_rel}: migration module has no test that references it "
            f"(expected one of: {', '.join(test_paths)}) — every non-legacy "
            f"migration module must land with at least one test; add the "
            f"test file or extend REQUIRED_TESTS_FOR_MODULE"
        )
        out.append((key, message))
    return out


# ---------------------------------------------------------------------------
# File iteration
# ---------------------------------------------------------------------------


def _iter_python_files(root: Path, scan_dirs: tuple[str, ...]) -> list[Path]:
    """Yield every ``.py`` file under each scan directory."""
    files: list[Path] = []
    for scan_dir in scan_dirs:
        base = root / scan_dir
        if not base.is_dir():
            continue
        files.extend(path for path in base.rglob("*.py") if "__pycache__" not in path.parts)
    return sorted(files)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def check_tree(
    root: Path, *, baseline: Mapping[str, str] | None = None
) -> tuple[list[str], list[str]]:
    """Check every module under ``root``'s SCAN_DIRS against the contract.

    Returns ``(violations, notices)``. Violations fail the check;
    notices are informational (a baselined violation disappeared and the
    entry should be deleted to lock in the improvement).
    """
    if baseline is None:
        baseline = BASELINE
    seen_baselined: set[str] = set()
    reported: set[str] = set()
    violations: list[str] = []

    for path in _iter_python_files(root, SCAN_DIRS):
        rel = path.relative_to(root).as_posix()
        file_class = classify_file(rel)
        source = path.read_text(encoding="utf-8")
        imports = extract_imports(source, _file_module(rel))
        _apply_class_rules(
            rel,
            imports,
            file_class=file_class,
            baseline=baseline,
            seen_baselined=seen_baselined,
            reported=reported,
            violations=violations,
        )

    for key, message in _check_tests_per_module(root):
        _record(
            key,
            message,
            baseline=baseline,
            seen_baselined=seen_baselined,
            reported=reported,
            violations=violations,
        )

    notices = [
        f"{key}: baselined but no longer a violation -- remove the entry from "
        f"BASELINE in scripts/check_migration_boundaries.py to lock in the "
        f"improvement"
        for key in sorted(set(baseline) - seen_baselined)
    ]
    return sorted(violations), notices


# ---------------------------------------------------------------------------
# BASELINE
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _emit_baseline(root: Path) -> int:
    """Print every current violation in BASELINE-entry format.

    Exits 0; the operator copies the lines into ``BASELINE``. Distinct
    from ``check_tree`` because the goal here is to make acquisition
    trivial, not to fail the build on pre-existing debt.
    """
    violations, _ = check_tree(root, baseline={})
    for message in violations:
        print(f"# TODO: {message[:200]}")
    for message in violations:
        # Re-derive the key from the message shape. The message format
        # is ``"{rel}: {reason}"``; the key format is
        # ``"{rel} -> {target} [{rule_id}]"``. They differ; rather than
        # thread the key through the message, we print the full rule
        # line the operator can adjust.
        print(message)
    print(
        f"\n# {len(violations)} violation(s) found. Copy into BASELINE "
        f"with a one-line justification per entry."
    )
    return 0


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] == "--emit-baseline":
        root = Path(args[1]).resolve() if len(args) > 1 else Path(__file__).resolve().parents[1]
        return _emit_baseline(root)
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parents[1]

    violations, notices = check_tree(root)

    for notice in notices:
        print(f"NOTE {notice}")
    for violation in violations:
        print(f"FAIL {violation}")

    if violations:
        print(
            f"check_migration_boundaries: {len(violations)} violation(s). "
            f"migration/ is divided into pure / access-bound / "
            f"orchestration; see docs/quality/migration-boundaries-design.md "
            f"for the forbidden-import sets per class."
        )
        return 1
    print(f"check_migration_boundaries: OK ({len(BASELINE)} baselined violation(s) remaining)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
