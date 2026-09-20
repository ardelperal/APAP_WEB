---
name: capability-docs
description: Trigger: capability docs, business rules, what the app does, regression-proof specs, migration-ready docs, generate SDDs from docs. Reverse-engineers features into SDD-grade, platform-agnostic docs with code as source of truth.
license: Apache-2.0
metadata:
  author: "Andrés Román"
  version: "0.1"
  last_verified: 2026-09-16
  scope: ['universal', 'docs']
  auto_invoke: ['writing capability docs', 'documenting business capabilities']
  tiers: ['universal', 'docs']
---

# Capability Documentation (generic, stack-agnostic)

## Activation

Use this skill to document features of any project so any AI can understand and reproduce them **without reading code** — for regression recovery, AI pre-code context, release traceability, and **stack-to-stack migration**. Trigger on: "document all features", "business rules", "what the app does", "make it reproducible", "regression-proof", "migrate to <stack>", "release traceability".

This is the documentation baseline for any project with executable code. Each feature gets a capability doc; the doc has two jobs at once: (1) be a regression-proof contract against the live code, and (2) be a **migration-ready, platform-agnostic spec** complete enough that an AI can read it and generate the SDDs (proposal → spec → design → tasks) to rebuild the feature on another stack — without ever reopening the original code.

## Hard Rules

- **HR-1** — Language: follow your project's AGENTS.md language contract (Castellano peninsular for Telefónica, English otherwise).
- **HR-2** — Code is the source of truth for behavior. SDD artifacts and the product owner are the source of truth for *intent* only. Verify every behavioral fact against code before marking it `Verified`.
- **HR-3** — Gate 0 first: before retro-documenting, harvest existing SDD artifacts (`sdd/*`, `openspec/`). Do not reinvent.
- **HR-4** — Surface SDD↔code divergence as `Divergent`, never paper over it.
- **HR-5** — Document business capabilities first, not modules or technical slices.
- **HR-6** — Use your project's canonical source↔binary verification tool as the only path for behavior verification (Dysflow for Access/VBA, pytest/jsdom for web, etc.). Declare the tool in your project's AGENTS.md.
- **HR-7** — Fill one doc per capability against your project's capability template, at its `tier` (critical | standard | minimal).
- **HR-8** — Every business rule — old or new — MUST carry a test. Author it via your project's TDD skill; record `Verified-static` debt explicitly.
- **HR-9** — Never claim `passing` or regression closure without test evidence and release/UAT traceability.
- **HR-10** — Mark every fact in the confidence ledger: `Verified-runtime` (passing test) / `Verified-static` (read in code, no test yet — transient, owes a test) / `Intended` / `Likely` / `Divergent`.
- **HR-11** — Record a tracker reference when known (GH issue / PR / Jira). Tracker-agnostic and optional.
- **HR-12** — Migration-ready by default. Capture the data model in platform-agnostic domain terms. For `critical` capabilities or stated migration goals, the migration spec and SDD seed are required deliverables.
- **HR-13** — The doc MUST be SDD-generative: map each section to a layer of a future SDD so an AI can raise proposal→spec→design→tasks from the doc alone.

## Decision Gates

| Question | Action |
|---|---|
| Existing SDD artifacts for this feature? | Harvest intent, then verify behavior against code. Mark `source: sdd`. |
| Legacy / no SDD? | Reverse-engineer from code; verify via the project's verification tool. Mark `source: reverse-engineered`. |
| SDD says X but code does Y? | Mark `Divergent`, flag for human review. |
| Business rule has no test? | Author one via the project's TDD skill until it reaches `Verified-runtime`. |
| Is this user-visible behavior? | Create/update a capability doc. |
| Is this implementation/test/cache support? | Link it as supporting feature evidence. |
| Goal is stack migration? | Fill data model + migration spec + SDD seed in full. The doc must let an AI generate the port's SDD without the code. |
| Logic lives in a UI-coupled event/handler? | Record it in "lógica a extraer" with its platform-agnostic destination (service/use-case). UI-coupled logic is the migration's main risk. |
| Capability shares data/flows with another? | Record the dependency in the dependency map — it drives migration ordering. |

## Execution Steps

1. **Gate 0** — discover existing SDD artifacts. Harvest proposal→spec→design→tasks into the matching template layers.
2. **Establish truth** — read the real code as source of truth; confirm behavior via the project's verification tool.
3. Build a capability taxonomy by business domain (lifecycle, actions, tasks, documents, reports, notifications, indicators, configuration, security).
4. For each capability, fill your project's capability template at its `tier`. The behavioral contract is the regression anchor; the reconstruction recipe is the rebuild path.
5. For every business rule lacking a passing test, author one via the project's TDD skill so it reaches `Verified-runtime`. Record SDD↔code divergences as findings; set confidence per fact with date + evidence.
6. **Make it migration-ready** — fill the data model in domain terms; for `critical` capabilities or stated migration goals, complete the migration spec (logic to extract, agnostic functional contract, UI/UX intent, integrations, data mapping, non-functional needs) and SDD seed (mapping each section to a proposal/spec/design/tasks layer).
7. Keep two layers — `docs/capabilities/` and `docs/features/` — and maintain a `capabilities-index.md` with the capability dependency/data map.

## Output Contract

| Key | Type | Description |
|---|---|---|
| `capability_docs` | array<object> | Capability docs created/updated, each with `tier` (critical \| standard \| minimal) and `source` (sdd \| reverse-engineered \| hybrid). |
| `divergences` | array<object> | SDD↔code divergences found, each flagged for human review. |
| `verification_evidence` | object | Project verification tool evidence plus the list of facts still `Intended`/`Likely`. |
| `traceability` | object | Release/UAT or regression traceability added per capability. |
| `migration_readiness` | object | For migration goals / `critical` capabilities: data model + migration spec + SDD seed completion status. |
| `evidence_gaps` | array<object> | Open gaps left pending, each with the exact next action to close it. |

## Anti-patterns

| Symptom | Fix |
|---|---|
| Re-documenting an existing SDD artifact instead of harvesting it. | Run Gate 0 first; harvest proposal → spec → design → tasks, then verify behavior against code. |
| Marking a fact `Verified-runtime` without test evidence. | Every `Verified-runtime` row needs a passing test id + date; otherwise downgrade to `Verified-static` and author the test. |
| Writing a `critical` capability without the migration spec and SDD seed. | Data model + migration spec + SDD seed are required deliverables for `critical` and migration goals. |
| Coupling the data model to stack-specific terminology. | The data model is platform-agnostic on purpose; it doubles as the acceptance spec for the migration target. |
| Silently leaving a `Verified-static` fact in the ledger. | `Verified-static` is transient debt; author the test before closing the doc or record the rationale. |

## References

- `access-vba-capability-docs` skill — the Access/VBA-specific instance (use only for VBA projects).
- `<your-stack>-tdd-*` skill — your project's TDD skill for HR-8.
- Project `AGENTS.md` — exact paths, language contract, verification tools, release tags.
