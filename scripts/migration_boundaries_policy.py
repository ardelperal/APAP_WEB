"""Policy data for the migration boundary gate (issue #490).

Split out of ``scripts/check_migration_boundaries.py``: at 699 lines against the 700-line
module cap that file had one line of headroom and could no longer accept a change. What it
held was 160 lines of policy tables mixed into 330 lines of mechanism.

The rule bindings stay in the checker: they reference its predicate functions, so moving
them here would make the two modules import each other.
"""

from __future__ import annotations

from collections.abc import Mapping

#: Directories subject to the rules. ``tests/`` is read-only for the
#: tests-per-module question but never classified.
SCAN_DIRS = ("migration",)

TEST_SEARCH_DIRS = ("tests/migration", "tests")

#: Files whose role is "derive or persist state without I/O". A pure
#: module's imports must resolve to stdlib OR to a sibling migration
#: module — never to ``app/``, never to a third-party DB / HTTP, never
#: to the Access seam. The list is the source of truth; adding a new
#: file under ``migration/`` requires adding it here in the same PR.
#:
#: The hexagonal sub-slice splits along the same seam as the ``app/``
#: hexagon — the **port** and **application** layers are pure (they
#: speak in domain types and the port Protocol only), but the
#: **adapter** and **di** layers legitimately need the
#: ``app.core.data_access.SqlExecutor`` Protocol. The latter are
#: orchestration; the former are pure.
PURE_FILENAMES: frozenset[str] = frozenset(
    {
        "derivation.py",
        "diff_engine.py",
        "reconcile.py",
        "lock.py",
        "lock_snapshot.py",
        "dni_collision.py",
        "sync_state.py",
        "shadow_state.py",
        "reporting.py",
        "semantic_events.py",
        "web_reader.py",
        "reverse_apply/io_helpers.py",
        "reverse_apply/lock_context.py",
        "reverse_apply/shadow.py",
        "reverse_apply/types.py",
        "ports/web_reader_port.py",
        "application/web_reader/load_web_snapshot.py",
    }
)

#: The subpackage of ``migration`` that holds the Access seam.
#: A pure module importing anything under this prefix is a violation —
#: the Access seam must stay quarantined so a Linux-CI test path can
#: never import Windows-only code transitively.
LEGACY_SUBPACKAGE = "migration.legacy_"

#: Top-level (first dotted segment) packages a pure module MUST NOT
#: import. The list is closed: it grows when a new external service is
#: added; it shrinks when a pure module is migrated to stdlib.
PURE_FORBIDDEN_TOP_PACKAGES: frozenset[str] = frozenset(
    {
        # Cross-cutting application layer. A pure module runs in the
        # operator CLI, not in FastAPI; it must not know about app/.
        "app",
        # Third-party DB drivers. Pure = no I/O to a DB.
        "pyodbc",
        "psycopg",
        "psycopg2",
        "sqlalchemy",
        "local_backend",
        "pymysql",
        # Third-party HTTP clients. Pure = no outbound HTTP.
        "httpx",
        "requests",
        "aiohttp",
        "urllib3",
        # Project-dep packages that imply a heavier contract than
        # stdlib. The hexagonal sub-slice uses dataclasses; the dedup
        # helper that needs rapidfuzz is orchestration, not pure.
        "yaml",
        "pydantic",
        "rapidfuzz",
        # Microsoft Windows bindings; would never import on Linux CI.
        "win32com",
        "win32api",
        "pythonwin",
    }
)


#: Positive allowlist of pure ``app.*`` subpackages a pure module MAY
#: import. The default rule (AGENTS.md §33.4 / Q6 in
#: ``openspec/changes/lifecycle-state-resolver-33/specs/lifecycle/spec.md``)
#: forbids every ``app.*`` import; this list is the only escape hatch
#: and is symmetric with the existing
#: ``app.core.data_access.SqlExecutor`` Protocol-import pattern
#: documented at line 50-51 above — the domain layer is pure
#: (Protocol-typed, no I/O), and importing it from the migration
#: layer is the same shape as importing a Protocol from ``app.core``.
#:
#: ``app.modules.lifecycle.domain`` is the only entry today: the
#: lifecycle slice's domain cascade (``calculate_state``) is the
#: single source of truth for the DameSituacion priority cascade;
#: ``migration/derivation.py`` redirects to it so the two
#: implementations cannot drift (AGENTS.md §22 single-seam rule).
#:
#: Adding an entry here requires a one-line rationale comment in the
#: PR description — the checker does NOT scan this file's prose, so
#: reviewers must enforce the rationale contract.
PURE_ALLOWED_SUBPACKAGES = (
    # Domain-as-source-of-truth: the lifecycle cascade lives in the
    # app domain layer; the migration layer imports it to prevent
    # drift between the legacy-shape replication and the web cascade.
    "app.modules.lifecycle.domain",
)

#: Mapping ``module POSIX path`` → ``tuple of acceptable test POSIX
#: paths``. A test file is considered to "cover" a module if it imports
#: that module (the test file's source AST imports the module's dotted
#: name). The list is the contract: a new migration module without any
#: of these test files referencing it fails the gate from day one.
#:
#: Convention: ``tests/migration/test_<module>.py`` for module-shaped
#: tests; ``tests/test_<topic>.py`` for the few migration concerns that
#: historically live at the top level (``test_derivation.py``,
#: ``test_reconcile.py``, ``test_semantic_events.py``).
REQUIRED_TESTS_FOR_MODULE: Mapping[str, tuple[str, ...]] = {
    "apply.py": ("tests/migration/test_apply.py", "tests/migration/test_apply_safety.py"),
    "apply_reverse.py": ("tests/migration/test_reverse_apply.py",),
    "bootstrap.py": ("tests/migration/test_bootstrap.py",),
    "cli.py": ("tests/migration/test_cli.py",),
    "cli_apply_reverse.py": ("tests/migration/test_cli_apply_safety.py",),
    "cli_format.py": (
        "tests/migration/test_pii_redaction.py",
        "tests/migration/test_pii_value_patterns.py",
    ),
    "cli_volunteer_dedup.py": ("tests/migration/test_cli_volunteer_dedup.py",),
    "derivation.py": ("tests/test_derivation.py", "tests/test_derivation_11cases.py"),
    "diff_engine.py": (
        "tests/migration/test_apply.py",
        "tests/migration/test_round_trip.py",
    ),
    "dni_collision.py": (
        "tests/migration/test_dni_collision.py",
        "tests/migration/test_dni_collision_counting.py",
    ),
    "lock.py": (
        "tests/migration/test_lock_snapshot.py",
        "tests/migration/test_apply.py",
    ),
    "lock_snapshot.py": ("tests/migration/test_lock_snapshot.py",),
    "mappings/__init__.py": ("tests/migration/test_round_trip.py",),
    "reconcile.py": (
        "tests/test_reconcile.py",
        "tests/test_reconcile_pr5_followups.py",
    ),
    "reporting.py": ("tests/migration/test_reporting.py",),
    "reverse_apply/io_helpers.py": ("tests/migration/test_reverse_apply.py",),
    "reverse_apply/lifecycle.py": ("tests/migration/test_reverse_apply.py",),
    "reverse_apply/lock_context.py": ("tests/migration/test_reverse_apply.py",),
    "reverse_apply/orchestrator.py": ("tests/migration/test_reverse_apply.py",),
    "reverse_apply/per_row.py": ("tests/migration/test_reverse_apply.py",),
    "reverse_apply/shadow.py": ("tests/migration/test_reverse_apply.py",),
    "reverse_apply/types.py": ("tests/migration/test_reverse_apply.py",),
    "semantic_events.py": ("tests/test_semantic_events.py",),
    "shadow_state.py": ("tests/migration/test_shadow_state.py",),
    "storage_spike.py": (
        "tests/migration/test_storage_methods.py",
        "tests/migration/test_storage_contract_evidence.py",
    ),
    "sync_state.py": (
        "tests/migration/test_apply.py",
        "tests/migration/test_round_trip.py",
    ),
    "volunteer_dedup.py": ("tests/migration/test_volunteer_dedup.py",),
    "web_reader.py": ("tests/migration/test_round_trip.py",),
}

#: Violations that predate the gate being switched on (issue #420).
#: RATCHET: entries may only disappear. When you fix one, delete its
#: entry in the same PR -- tests/test_migration_boundaries.py::
#: test_baseline_entries_are_still_real_violations fails on a stale entry,
#: and any violation not listed here fails the gate. Never add a new entry:
#: fix the import instead.
#:
#: Acquired against the worktree HEAD at c5ad0bc (origin/main). The
#: comments explain each cluster. ``--emit-baseline`` is the acquisition
#: tool; the entries below are the result.
_BASELINE_TESTS_NO_REFERENCE = (
    "Module has no test referencing it at the time the gate landed. "
    "Add a test in a follow-up PR or extend REQUIRED_TESTS_FOR_MODULE "
    "if the module is exercised indirectly by a non-conventional test "
    "name (e.g. legacy files were renamed in module_rename_smoke)."
)

BASELINE: Mapping[str, str] = {
    # ------------------------------------------------------------------
    # Test-per-module: modules that have no test referencing them today.
    # Most of these are exercised by indirect coverage (e.g.
    # ``diff_engine`` is imported by ``test_apply.py``); the check
    # looks for an actual ``from migration.<x> import ...`` line, which
    # the indirect-import path does not produce. Add a direct-import
    # test in a follow-up to delete each entry.
    # ------------------------------------------------------------------
    "bootstrap.py -> <no-test> [test-coverage]": _BASELINE_TESTS_NO_REFERENCE,
    "cli_apply_reverse.py -> <no-test> [test-coverage]": _BASELINE_TESTS_NO_REFERENCE,
    "diff_engine.py -> <no-test> [test-coverage]": _BASELINE_TESTS_NO_REFERENCE,
    "mappings/__init__.py -> <no-test> [test-coverage]": _BASELINE_TESTS_NO_REFERENCE,
    "reverse_apply/io_helpers.py -> <no-test> [test-coverage]": _BASELINE_TESTS_NO_REFERENCE,
    "reverse_apply/lifecycle.py -> <no-test> [test-coverage]": _BASELINE_TESTS_NO_REFERENCE,
    "reverse_apply/lock_context.py -> <no-test> [test-coverage]": _BASELINE_TESTS_NO_REFERENCE,
    "reverse_apply/per_row.py -> <no-test> [test-coverage]": _BASELINE_TESTS_NO_REFERENCE,
    "reverse_apply/shadow.py -> <no-test> [test-coverage]": _BASELINE_TESTS_NO_REFERENCE,
    "reverse_apply/types.py -> <no-test> [test-coverage]": _BASELINE_TESTS_NO_REFERENCE,
    "sync_state.py -> <no-test> [test-coverage]": _BASELINE_TESTS_NO_REFERENCE,
    "web_reader.py -> <no-test> [test-coverage]": _BASELINE_TESTS_NO_REFERENCE,
}
