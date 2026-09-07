# Slice-completeness gate — design

Step 2 of the hardening roadmap:
`scripts/check_layers.py` proves "no forbidden import"; this gate proves
"slice is complete". Closed by Epic #420.

---

## Scope

A **vertical slice** in APAP_WEB lives in either:

- `app/core/<layer>/<slice>/` — cross-cutting capability, layer-by-layer column
- `app/modules/<slice>/` — delivery-only vertical module

Per AGENTS.md §33.1, §33.3. The gate scans both trees (same `SCAN_DIRS`
contract as `check_layers.py`; `migration/` is explicitly **out of
scope** — that is Step 3 of the hardening roadmap).

A slice is **in scope** of the completeness gate when it has at least
one python file under any of:

- `app/core/application/<slice>/`
- `app/core/ports/<slice>_port.py`
- `app/core/adapters/local-backend/<slice>_*local_backend*`
- `app/core/di/<slice>_di.py`
- `app/modules/<slice>/`

A bare `app/core/domain/<slice>/` (domain entities only) does not make
the slice in scope — domain is always optional. The check runs only
when there is something to wire, otherwise it would force empty
slices to grow a port they do not need.

## The four assertions

For every in-scope slice, all four must hold (subject to BASELINE):

### 1. `port-declared` — at least one `Protocol` in `ports/`

For a core slice, the file `app/core/ports/<slice>_port.py` must
contain a top-level `class X(Protocol)` (or
`@runtime_checkable Protocol`).

Detection: AST-walk the file. Accept either explicit
`typing.Protocol` base or a Protocol annotated by a `@runtime_checkable`
decorator. **Path-only resolution** — we look for the file by stem,
not by trying every ports file, because the file boundary is the
contract (Issue #420: ports live in a single module per slice).

For a module slice (`app/modules/<slice>/`), look in
`app/core/ports/<slice>_port.py` for a Protocol named like
`<PascalSlice>Port` or `<PascalSlice>Repository`. The slice prefix is
the PascalCase form of the directory name (`animals` → `Animals`).

**Failure mode (silence risk, AGENTS.md §32.P3):** if the ports file
exists but the Protocol is `class X: ...` without `Protocol` in its
bases, we miss it. Mitigation: also accept `@runtime_checkable`
on a class that does not list `Protocol` in its bases (a degenerate
but documented alternative idiom).

### 2. `adapter-in-di` — the concrete adapter is wired from `di/`

For every concrete adapter file under
`app/core/adapters/local-backend/<slice>_local_backend_*.py`, the file
`app/core/di/<slice>_di.py` must reference that adapter's module
(import or string name appears in source).

Detection: AST-walk `app/core/di/<slice>_di.py` imports; flag any
adapter file in `local_backend/<slice>_*` that no `di/<slice>_di.py` import
list contains. For non-LocalBackend adapters
(`app/core/adapters/admin_template_adapter.py` etc.) the matching
`di/<slice>_di.py` must reference the module too.

Module slices have no own adapter by definition (they may use
core-injected ports). For module slices the assertion is **skipped**,
because there is no adapter to wire.

**Failure mode (silence risk):** a `di` file that imports the adapter
for type-checking only (under `if TYPE_CHECKING:`) but never actually
constructs it would still pass. The 1-line doctype-by-construction
discount is acceptable: any slice whose adapter is *used* in `di` is
wired, and unused adapters are caught by the linter/`vulture`.

### 3. `application-adapter-free` — `application/<slice>/*.py` does not import a concrete adapter

For every file under `app/core/application/<slice>/`, walk its
imports and flag any `from app.core.adapters.local_backend.<slice>_local_backend_*
import ...` (or other concrete-adapter submodule).

Detection: AST-walk, match against the slice's concrete-adapter path.
Module slices have no `application/` by definition — assertion skipped.

This is a **explicit** re-assertion of `check_layers.py`'s `application
must not import adapters` rule (`ALLOWED_IMPORTS`), scoped to
per-slice naming so a passing-with-baseline scenario can identify
which slice consumes the violation without grepping across 53 keys.
Same logic, finer key, dedicated ratchet.

**Failure mode (silence risk):** symbol-name drift. If a file imports
`from app.core.adapters.local_backend.<slice>_local_backend_adapter import
LocalBackendXAdapter as _Adapter`, the import line still resolves to the
adapter module — AST-walk detects the target module regardless of alias.

### 4. `tests-per-layer` — at least one test file per layer

For every layer that the slice actually occupies, there must be at
least one `tests/test_<slice>_<layer>.py` (or `tests/test_<slice>*.py`
as a fallback when naming varies).

Layers detected by re-using `check_layers.classify_layer`:

| Layer | Files in the slice |
|---|---|
| `domain` | under `app/core/domain/<slice>/` (or `app/core/<slice>.py` / `app/core/<slice>*.py` for flat-domain slices like `catalogos`) |
| `ports` | `app/core/ports/<slice>_port.py` |
| `application` | under `app/core/application/<slice>/` |
| `adapters` | under `app/core/adapters/local-backend/<slice>_*` (or `app/core/adapters/<slice>_*` for non-LocalBackend) |
| `di` | `app/core/di/<slice>_di.py` |
| `delivery` | under `app/modules/<slice>/` |

For each (layer, slice) we choose one or more candidate test paths:

- `tests/test_<slice>_<layer>.py` (preferred)
- `tests/test_<layer>_<slice>.py` (existing pattern — e.g. `test_domain_lifecycle.py`)
- `tests/test_<slice>_slice.py` (slices test — e.g. `test_admin_slice.py`, `test_oauth_slice.py`, `test_catalogos_slice.py`)
- `tests/test_<slice>.py` (only acceptable when the slice has exactly one layer)
- `tests/test_<slice>_*` glob (when tests are split, e.g. `test_auth_dependencies.py`, `test_auth_flow.py`)

The "one test file per layer" requirement is intentionally loose — we
accept either an exact match, a `<slice>_<layer>` filename, a
`<slice>_slice` filename, or a `<slice>_*` glob that has at least one
real file. The intent is "any test that exercises the layer exists",
not "every layer has a dedicated single test module".

**Failure mode (silence risk):** a test file that does not actually
import the layer (e.g. `tests/test_admin.py` could in principle cover
admin delivery without importing domain). The acceptance is that the
file's source contains an import statement targeting that layer's
files — partial defence only, a weak file-existence + import-resolves
check. A stronger check would require AST-import resolution.

## BASELINE

Shrink-only, same contract as `check_module_size.py`
(`scripts/check_module_size.py:46`). Keys are
`<slice>::<rule>::<detail>` where detail varies per rule:

| Rule | key form |
|---|---|
| `port-declared` | `port-declared::<slice>` (the slice name) |
| `adapter-in-di` | `adapter-in-di::<slice>::<rel-adapter>` |
| `application-adapter-free` | `application-adapter-free::<rel-app-file>` |
| `tests-per-layer` | `tests-per-layer::<slice>::<layer>` |

Test pinning: `tests/test_slice_completeness.py::test_baseline_entries_are_still_real_violations`
mirrors `tests/test_layers.py:67` (same pattern, different file).

Acquisition: `--emit-baseline` writes the current violation set as a
TOML snippet to stdout, mirroring `check_layers.py`'s own
calibration-on-main pattern. The measured violations land in the
script on a *separate* PR run by the human (or the orchestrator) — the
script's first CI run must be green.

A baseline entry whose condition is no longer met is reported as a
notice (`NOTE`) by the checker, mirroring `check_layers.py:668`. <!-- alantyle-ignore:ALAN003 -->

## Doctype alignment with AGENTS.md §32.P3

Every metric must document its broken-measurement failure mode. Each
rule's failure mode is noted above. None of them are silent
collectors:

- Rule 1: bounded — there is exactly one `ports/<slice>_port.py` per
  slice, so the resolution is deterministic.
- Rule 2: also bounded — exactly one `di/<slice>_di.py` per slice.
- Rule 3: bounded — `application/<slice>/` is enumerable.
- Rule 4: filesystem-only, well-defined lookup; a missing test file
  produces a violation, no false-positive ambiguity.

## Out of scope

- `migration/` — Step 3 of the roadmap.
- Coverage / mutation / docstring-ratchet concerns — orthogonal to
  "slice is complete" and already covered elsewhere.
- Non-LocalBackend adapter modules other than the
  `<slice>_*_adapter.py` stem pattern — accepted but rare
  (`admin_template_adapter.py` is the one example).
