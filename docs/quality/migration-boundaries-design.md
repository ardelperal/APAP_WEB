# Migration boundary gate — design (issue #420, hardening roadmap Step 3)

**Status.** Design + implementation, hardening roadmap §2 Step 3.
**Issue.** [#420](https://github.com/ardelperal/APAP_WEB/issues/420) (epic).
**Source of the discipline.** `scripts/check_layers.py` is the precedent —
three explicit axes over `app/`, shrink-only `BASELINE`, no rule without a
gate (AGENTS.md §32.P3). This gate is the migration equivalent: a separate
script (NOT extending `check_layers.py`), because the rules are different.

---

## 1. Why a separate gate, not `check_layers.py`

`scripts/check_layers.py` enforces a hexagonal contract over `app/`
(dependency direction between layers, purity of inner layers, vertical-slice
boundaries). `migration/` has a **different architecture**:

- **Pure** modules — `derivation.py`, `diff_engine.py`, `reconcile.py`,
  `lock.py`, `lock_snapshot.py`, `sync_state.py`, `shadow_state.py`,
  `reporting.py`, `semantic_events.py`, `dni_collision.py`, `web_reader.py`,
  the `reverse_apply/` subpackage, and the hexagonal
  `ports/application/adapters/di/` web-reader slice — compute or persist
  state with no third-party DB or HTTP.
- **Access-bound** modules — `legacy_access_client.py`, `legacy_reader.py`
  — own the pyodbc / .accdb seam and run only on Windows.
- **Orchestration** modules — `apply.py`, `cli.py`, `cli_apply_reverse.py`,
  `cli_format.py`, `bootstrap.py`, `__init__.py`, `__main__.py`,
  `volunteer_dedup.py`, `storage_spike.py`, `mappings/__init__.py`, and the
  reverse-apply driver modules (`reverse_apply/orchestrator.py`,
  `reverse_apply/per_row.py`) — drive the workflow and may import from
  both `migration/` backends and `app/core/` cross-cutting utilities.

Forcing `check_layers.py`'s hexagonal axioms on this tree would
manufacture false confidence (AGENTS.md §32.P3): the migration's "ports"
are not the same Protocol class as `app/core`'s, the access-bound seam
is not a FastAPI route, and the orchestration layer is the CLI entry
point rather than a `delivery/` slice. A separate gate with its own
classification, its own forbidden-import lists, and its own baseline
keeps both contracts honest.

## 2. The classification heuristic

`SCAN_DIRS = ("migration",)`. The class of a file is determined by an
explicit allow-list (filename → class), not by AST inspection, because
the class is a property of the **file's role**, not of what it happens
to import today. A future refactor can move an import without changing
the file's class.

| Class         | Files (POSIX relative to repo root)                                                                                                                                                                                                                                                                                                                              |
|---------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **pure**      | `derivation.py`, `diff_engine.py`, `reconcile.py`, `lock.py`, `lock_snapshot.py`, `dni_collision.py`, `sync_state.py`, `shadow_state.py`, `reporting.py`, `semantic_events.py`, `web_reader.py`, `reverse_apply/io_helpers.py`, `reverse_apply/lifecycle.py`, `reverse_apply/lock_context.py`, `reverse_apply/shadow.py`, `reverse_apply/types.py`, `ports/web_reader_port.py`, `application/web_reader/load_web_snapshot.py`, `adapters/insforge/web_reader_insforge_adapter.py`, `di/web_reader_di.py` |
| **access-bound** | `legacy_access_client.py`, `legacy_reader.py`                                                                                                                                                                                                                                                                                                                |
| **orchestration** | everything else under `migration/` (`__init__.py`, `__main__.py`, `apply.py`, `apply_reverse.py`, `cli.py`, `cli_apply_reverse.py`, `cli_format.py`, `cli_volunteer_dedup.py`, `bootstrap.py`, `volunteer_dedup.py`, `storage_spike.py`, `mappings/__init__.py`, `reverse_apply/orchestrator.py`, `reverse_apply/per_row.py`) |

The classifier is the source of truth — adding a new file under
`migration/` requires adding it to the right list here in the same PR.

## 3. Forbidden-import lists per class

### 3.1 Pure modules — `PURE_FORBIDDEN_TOP_PACKAGES`

A pure module's imports must resolve to stdlib OR to a sibling
`migration.<non-legacy>` module. Specifically forbidden:

| Forbidden segment         | Why                                                                                                        |
|---------------------------|------------------------------------------------------------------------------------------------------------|
| `app`                     | Pure modules MUST NOT depend on the application layer. They run in the operator CLI, not in FastAPI.        |
| `migration.legacy_*`      | Keep the Access-bound seam quarantined — a pure module that imports the legacy reader pulls Windows-only code into a Linux-CI-runnable test path. |
| `pyodbc`, `psycopg`, `psycopg2`, `sqlalchemy`, `insforge`, `pymysql` | Third-party DB drivers. A pure module does not talk to a DB.                              |
| `httpx`, `requests`, `aiohttp`, `urllib3` | Third-party HTTP clients. A pure module does not make outbound HTTP.                       |
| `yaml`, `pydantic`, `rapidfuzz` | Project-dep packages that imply a heavier contract than stdlib. The hexagonal sub-slice uses dataclasses; the dedup helper that needs `rapidfuzz` is orchestration, not pure. |
| `win32com`, `win32api`, `pythonwin` | Microsoft Windows bindings; would never import on Linux CI.                                |

The list is closed: it grows when a new external service is added; it
shrinks when a pure module is migrated to stdlib. `check_migration_boundaries.py`
matches the first dotted segment of every `Import`/`ImportFrom`, so
`from app.core.insforge import X` and `from migration.legacy_reader import X`
both surface.

### 3.2 Access-bound modules — `ACCESS_BOUND_FORBIDDEN_APP_PREFIXES`

Access-bound modules may import stdlib, `migration.*` siblings, and
Access bindings (`pyodbc`, `ctypes.wintypes`, etc.). They may NOT
import from `app/` — the entire `app/` tree is forbidden. This protects
the runtime-boundary contract (`tests/migration/test_runtime_boundary.py`)
and keeps the Access seam free of FastAPI / InsForge coupling.

### 3.3 Orchestration modules — `ORCHESTRATION_FORBIDDEN_APP_PREFIXES`

Orchestration modules may import anything in `migration.*` and any
`app.core.*` module (the cross-cutting infrastructure: `app.core.logging`,
`app.core.data_access`, `app.core.insforge`). They MUST NOT import any
`app.modules.*` module — business logic is not part of the migration's
concern, and a route handler pulling `from app.modules.animals import X`
into the CLI would be a layering violation in the opposite direction.

`app.modules.*` is the single forbidden prefix. The hexagonal refactor
will tighten this further (e.g. forbidding the concrete `InsForgeClient`
in favour of the `SqlExecutor` Protocol), but that is a follow-up — the
first cut freezes the existing imports as the baseline and binds the
direction of the build.

### 3.4 Tests-per-module rule

For every non-legacy module under `migration/` (i.e. pure +
orchestration), the gate asserts that at least one test file under
`tests/` references it via `from migration.<module> import` or
`from migration.<subpackage>.<module> import`. The mapping is:

| Module                          | Covered by (at least one of)                                                |
|---------------------------------|------------------------------------------------------------------------------|
| `apply.py`                      | `tests/migration/test_apply.py`, `tests/migration/test_apply_safety.py`      |
| `apply_reverse.py`              | `tests/migration/test_reverse_apply.py`                                       |
| `bootstrap.py`                  | `tests/migration/test_bootstrap.py`                                           |
| `cli.py`                        | `tests/migration/test_cli.py`                                                 |
| `cli_apply_reverse.py`          | `tests/migration/test_cli_apply_safety.py`                                    |
| `cli_format.py`                 | `tests/migration/test_pii_redaction.py`, `tests/migration/test_pii_value_patterns.py` |
| `cli_volunteer_dedup.py`        | `tests/migration/test_cli_volunteer_dedup.py`                                 |
| `derivation.py`                 | `tests/test_derivation.py`, `tests/test_derivation_11cases.py`                |
| `diff_engine.py`                | `tests/migration/test_apply.py`, `tests/migration/test_round_trip.py`         |
| `dni_collision.py`              | `tests/migration/test_dni_collision.py`, `tests/migration/test_dni_collision_counting.py` |
| `lock.py`                       | `tests/migration/test_lock_snapshot.py`, `tests/migration/test_apply.py`     |
| `lock_snapshot.py`              | `tests/migration/test_lock_snapshot.py`                                       |
| `mappings/__init__.py`          | `tests/migration/test_round_trip.py`                                          |
| `reconcile.py`                  | `tests/test_reconcile.py`, `tests/test_reconcile_pr5_followups.py`            |
| `reporting.py`                  | `tests/migration/test_reporting.py`                                           |
| `reverse_apply/*`               | `tests/migration/test_reverse_apply.py`                                       |
| `semantic_events.py`            | `tests/test_semantic_events.py`                                               |
| `shadow_state.py`               | `tests/migration/test_shadow_state.py`                                        |
| `storage_spike.py`              | `tests/migration/test_insforge_storage_methods.py`, `tests/migration/test_storage_contract_evidence.py` |
| `sync_state.py`                 | `tests/migration/test_apply.py`, `tests/migration/test_round_trip.py`         |
| `volunteer_dedup.py`            | `tests/migration/test_volunteer_dedup.py`                                     |
| `web_reader.py`                 | `tests/migration/test_round_trip.py`                                          |

A `test_<module>.py` file is a **hint**, not a hard requirement — the
rule is "at least one test references this module". A test file with a
non-conventional name (`test_derivation_11cases.py`) is fine; so is
indirect coverage (`diff_engine` exercised inside `test_apply.py`).

The test-coverage check is rule #4 of the gate. Modules that currently
lack a covering test get a BASELINE entry — adding a new module without
a covering test fails the build from day one.

## 4. Violation key format

```
{rel_posix} -> {imported_module} [{rule_id}]
```

`rule_id` ∈ `{pure-imports, access-bound-imports, orchestration-imports,
test-coverage}`. The line number is intentionally omitted (same shape as
`check_layers.py::violation_key`) so moving an import inside a file does
not require re-baselining.

## 5. BASELINE — shrink-only ratchet

Every violation that predates the gate lands in `BASELINE`, mapped to a
one-line justification. **Entries may only disappear.** A new violation
of the same shape always fails.

Acquired against `origin/main @c5ad0bc` (the worktree's HEAD before this
PR). The acquisition command:

```
python scripts/check_migration_boundaries.py --emit-baseline
```

prints every current violation in the format the BASELINE expects.
A second pass with the BASELINE filled in exits 0 against the same tree.

## 6. Failure-mode silence (AGENTS.md §32.P3) — every rule's broken mode

| Rule                          | What a broken measurement looks like                                                                  | How the gate fails on it                                                                                  |
|-------------------------------|--------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| Pure-module forbidden imports | A "pure" module silently grows a DB / HTTP dep and the gate misses it.                                | AST walks every `Import`/`ImportFrom`, not just the file's filename. A new `import sqlalchemy` in `derivation.py` fails the build immediately, not via PR review. |
| Access-bound forbidden imports | The legacy seam starts importing FastAPI / InsForge.                                                  | Same AST walk; `from app.core.insforge import ...` in `legacy_access_client.py` fails the build.          |
| Orchestration forbidden imports | A CLI module starts importing business logic (`from app.modules.animals import ...`).                | AST walk restricted to `app.modules.*` prefix; any new import there fails the build.                       |
| Tests-per-module              | A new migration module lands with no test, and the regression gate is silent until something breaks.  | Module-vs-test mapping is checked against the **filesystem** (no skipped modules), so adding `migration/foo.py` without a referencing test fails the build. |

The four rules' failure modes are mutually independent: each one fails
on a different shape, so a silent regression in one cannot hide behind
the others.

## 7. CI wiring

`scripts/check_migration_boundaries.py` runs as a separate step in the
`lint` job of `.github/workflows/ci.yml`, placed **after**
`scripts/check_layers.py` (the rule lands when the architecture refactor
its it belongs to is green). The wiring is pinned by
`tests/test_migration_boundaries.py::test_ci_workflow_lint_job_runs_migration_boundaries_gate`
using the same `_job_executable` slicing rationale as the other
lint-job gates.

Removing the step from `ci.yml` is a **blocked change** (AGENTS.md §32.P3).

## 8. Module-size budget

The script is ≤ 700 lines (AGENTS.md §21). The baseline-acquisition +
test + driver + 3 rule functions + classification + tests-per-module
check fits comfortably.

## 9. What this gate is NOT

- **NOT** a hexagonal gate. The hexagonal refactor lives under
  `app/core/` and `app/modules/`; this gate covers `migration/`, which
  has its own architecture.
- **NOT** a runtime-boundary gate. `tests/migration/test_runtime_boundary.py`
  already pins the no-MCP-at-runtime contract; this gate is static.
- **NOT** a coverage gate. Module-level line coverage lives in the
  pytest coverage run; this gate checks the *structure* of imports and
  the *existence* of a test file per module.

The next gate (hardening-roadmap §2 Step 2 — slice completeness) will
build on this one's classification to verify that the hexagonal sub-slice
under `migration/ports/`, `migration/application/`, `migration/adapters/`,
`migration/di/` is complete (port Protocol + adapter injected via `di/`).
