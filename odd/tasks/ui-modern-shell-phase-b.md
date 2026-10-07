# UI modern shell — Phase B (desktop nav polish)

## Goal

Take the APAP_WEB desktop nav from "functional but 2020-era" to "modern and a11y-clean" without breaking the routes. Phase B of epic `#817` — the nav polish that builds on top of the a11y baseline already merged in Phase A (`#812`, `#813`, `#814`, `#818`, plus `#805`, `#811`).

## Scope (this umbrella)

| Order | Slice | Title | In / Out | Status |
|---|---|---|---|---|
| 1 | `#806` | rename long nav items so they fit on one line | IN | pending |
| 2 | `#808` | add a small lucide icon next to each top-level nav item | IN | pending |
| 3 | `#809` | group nav items under module headings or reduce item count | IN | pending |

Plus housekeeping done in this umbrella:

- `#804` (hamburger menu root) → close as **superseded by `#819` + `#820`** (PRs #829, #830 already merged).
- `#816` (wizard root) → close as **superseded by `#821` + `#823` + `#824`** (open sub-slices).
- `#817` (epic umbrella) → stays OPEN until `#824` lands. Tracking table refreshed.

## Cadence (user-locked)

- **One PR per session, sequential.** Sergio reviews between sessions.
- After each merge: clean the local worktree (rule: no merged wts left behind).
- Phase B expects 3 sessions, one per slice, in the order above.

## Out of scope (this umbrella)

- Phase A — already merged.
- Phase C wizard (`#821`, `#822`, `#823`, `#824`) — separate feature, separate umbrella.
- Cross-cutting: design tokens for active-state highlight, axe-core CI gate — not yet filed.
- Footer, theme switcher, dark mode, i18n — epic explicitly excludes.

## Per-slice gates (CI required check)

- `ruff check .` — no new findings.
- `python scripts/check_rules.py .` — exit 0.
- `python -m mypy` — no new errors.
- `pytest tests/test_pages.py tests/test_template_selection.py tests/test_template_migration.py -q` — green.
- `pytest tests/e2e/test_nav_*.py tests/e2e/test_login_*.py -q` — green under chromium (auto-skip on 503 preflight).
- Issue-spec check passes (body in Castellano, `### ` H3 sections).
- Diff ≤ 400 lines. If exceeded, split via chained PR (`feat/<N>-<slug>-part-a`).

## Legacy fidelity (P1)

N/A — Phase B only touches the web shell (templates + nav helper + small JS). No backend, no legacy bridge.

## Risk register (Phase B as a whole)

1. **Lucide library choice** — `#808` needs a decision: lucide static SVG sprite vs inline `<svg>` per icon. The project is FastAPI + Jinja2, not React/Vue, so `lucide-react` and `lucide-vue-next` are out. Confirm before opening `#808`.
2. **`#809` invasiveness** — restructuring into modules / headings touches the `NAV_ITEMS` shape in `app/core/nav.py`, both templates, possibly the active-state marker from `#805`. If the active-state class was indexed by position, the slice must also re-derive it from `href`.
3. **Cross-PR conflict on nav template** — `#806`, `#808`, `#809` all touch `app/templates/base.html` and `app/templates/base_mobile.html`. Serial execution avoids partial-state merges.

## Tracking

Each slice owns its own `odd/tasks/<N>-<slug>.md` file. This umbrella file tracks phase-level state and decision log.

## Decision log

- **2026-09-19** — User confirmed: Phase B first, one PR per session, close `#804` and `#816` as superseded now.