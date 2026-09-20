# Changelog — access-vba-e2e-methodology

All notable changes to this skill. Single source of truth for version history; the SKILL.md body carries no version provenance.

## 1.4 — 2026-06-25

- **Balanced test pyramid via interface seams** (Hard Rule 12): business logic tested with an in-memory fake via `Implements`; sandbox E2E reserved for the data layer. Honest-signature rule (#2) extended to prefer injecting a repository interface over raw `DAO.Database`. Pattern lives in `access-vba-tdd-fundamentos` `assets/interface-seams.md` (corrects that skill's §4.6).
- **Form tiering** (Hard Rule 13 + `references/form-tiering.md`): not every form earns the full refactor. Tier 1 full / Tier 2 logic-only / Tier 3 documented debt. Tier 3 is recorded in cap-doc §6, never a silent skip. Added matching Decision Gate rows.

## 1.3 — 2026-06-25

LLM-first restructure (no rule was weakened; content was relocated and deduplicated).

- **Restructured** SKILL.md to the repo's LLM-first style contract: essence front-loaded (thin forms + decoupled testable helpers + the `db` decision rule), hard rules deduplicated to one canonical statement each.
- **Moved** narrative, playbooks, and war-stories out of SKILL.md into `references/`:
  - `references/preflight-audit.md` — the 4-step mandatory preflight audit.
  - `references/helper-naming.md` — naming uniqueness, per-module prefix, naming playbook, collision audit, compile-error protocol.
  - `references/onboarding-playbook.md` — 5-minute project onboarding + pre-flight A/B/C.
  - `references/agent-anti-patterns.md` — agent's own anti-patterns + TDD compile/test discipline.
  - `references/communication-script.md` — scripted messages with the user.
  - `references/subagent-failure-modes.md` — sub-agent hang/partial/over-delete/wrong-branch/scope-creep.
- **Added** `assets/e2e-canonical-example.md` — one worked example: fat handler → thin form + helper + atom + UAT card.
- **Fixed contract drift with `feature-acceptance-uat`**: developer-axis items now go to the signed **developer validation web** (`docs/uat/uat-dev-<date>.html`), not a flat `dev-internal-changes-<date>.md`. UAT output paths documented.
- **Updated compile discipline**: the agent self-compiles module-only changes via `dysflow.compile_vba`; the user compiles manually only when the change touches forms.
- **Removed** `[DRAFT-1.2]` / `1.3-draft` markers and `review_status`; version provenance now lives here.
- Promoted from draft to stable.

## 1.2 — 2026-06-23 (forms-thin-refactor, GESTION_RIESGOS_staging)

- Added helper naming/collision rules, "form calls helper never form calls form", public-business-methods-in-forms anti-pattern, UI/control contract, onboarding playbook, sub-agent failure modes, communication script.

## 1.x — earlier

- Initial bridge between `access-vba-tdd-fundamentos` and `feature-acceptance-uat`: thin forms, testable helpers, TDD atoms mirror UAT scenarios, traceability template.
