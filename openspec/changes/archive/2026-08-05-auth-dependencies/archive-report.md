# Archive Report: auth-dependencies

## Status

Archived on 2026-08-05. Change merged to main at commit `74c31aa` (PR #427).

## Change summary

The `auth-dependencies` slice extracted `app/core/auth_dependencies.py` into a new DI module (`app/core/di/auth_dependencies_di.py`) and replaced the original with a minimal shim (≤50 lines) that re-exports the same 9 public symbols. The primary motivation was fixing §32.P4: `require_authorized_user` now catches `InsForgeError` and returns `/unauthorized` 302 instead of propagating an unhandled 500.

## Spec delta synced

The delta spec was promoted as a new main spec (no prior `openspec/specs/auth-dependencies/` existed):

- `openspec/specs/auth-dependencies/spec.md` — new; captures R01–R10 plus non-functional requirements.

Delta contained 10 requirements (R01–R10), all marked ADDED.

## Archive contents

| Artifact | Status |
|----------|--------|
| `proposal.md` | ✅ moved |
| `spec.md` | ✅ moved |
| `design.md` | ✅ moved |
| `explore.md` | ✅ moved |
| `tasks.md` | ✅ moved (14/14 tasks, all checked) |

## Task completion gate

`tasks.md` showed 14 tasks (T01–T14), all checked. No stale unchecked implementation tasks found. The change was fully implemented and verified at merge commit `74c31aa`.

## Implementation commits

| Commit | Summary |
|--------|---------|
| `74c31aa` | Merge PR #427 — auth-dependencies slice (shim + di + §32.P4 fix) |

## Verification evidence (per PR #427 CI run)

All six CI jobs were green on the branch head before merge:
- `ruff check .` ✅
- `scripts/check_rules.py` ✅ (Detectors 5, 6, 11, 12 clean)
- `python -m mypy` ✅
- `pytest -W error::DeprecationWarning` ✅
- `python -m build` ✅

## Engram traceability

| Topic key | Description |
|-----------|-------------|
| `sdd/auth-dependencies/decisions` | Locked design decisions |
| `sdd/auth-dependencies/gate-review` | Gate review artifact |
| `sdd/auth-dependencies/pr-427-gate-review` | PR-specific gate review |
| `sdd/auth-dependencies/apply-progress` | Apply-phase progress snapshot |
| `sdd/auth-dependencies/archive` | This archive closure note |

## Risks / notes

- The §32.P4 fix (bare `except InsForgeError:`) intentionally does not bind `as exc` per the existing code style at the surrounding lines — the variable is unused.
- The lazy-import cycle (`get_user_by_email` inside `require_authorized_user`) is documented with `# lazy-import:` marker per §26; the cycle was not resolved, only documented.
- 11 module slices remain out of scope: acogidas, adopciones, animals, cesiones, entradas, foster, materiales, salud, sanidad, tasks, voluntarios.
