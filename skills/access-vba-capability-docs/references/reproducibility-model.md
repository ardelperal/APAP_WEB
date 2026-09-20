# Reproducibility & Truth Model

Conceptual background for `access-vba-capability-docs`. The runtime contract lives in `SKILL.md`; this file explains *why* the doc is shaped the way it is. Read it once; do not duplicate it into `SKILL.md`.

## 1. Layered source of truth

A capability doc mixes two kinds of statement, and they do NOT share an authority:

| Statement | Source of truth | Why |
|---|---|---|
| WHAT it does / HOW it is built (behavior, data, rules-as-enforced) | **The code**, confirmed via Dysflow (`test_vba`, `verify_code`) | Only the binary reflects executable reality |
| WHY it exists (intent, rules-as-intended, non-goals) | **SDD artifacts + product owner** | The code cannot tell you intent; you cannot infer a business rule from a module name |

A pre-code SDD spec is a **hypothesis** about the code, not a verified fact. Treat it as `Intended` until reconciled with the code.

## 2. The divergence signal

The gap between **rule-as-intended** (SDD/owner) and **rule-as-enforced** (code) is the most valuable output of this skill. It is the literal answer to "was it done well or not":

- Intent and code agree → `Verified`.
- Intent exists, code unconfirmed → `Intended`.
- Intent and code disagree → `Divergent` ⚠️ → bug, debt, or undocumented change → flag for human.

Never silently pick a winner. Surface the divergence.

## 3. Confidence semantics

- `Verified-runtime` — a passing `dysflow.test_vba` proves it, with a date. The only fully trustworthy state, and the target for every rule.
- `Verified-static` — confirmed by reading the code, but no test exists yet. **Transient**: it is a debt, not a destination. Static reading can be wrong at runtime, so this state owes a test.
- `Intended` — from SDD/owner, not yet confirmed in code.
- `Likely` — inferred from the app surface (filenames, labels), not confirmed.
- `Divergent` — SDD and code contradict each other.

Freshness rule: a `Verified-runtime` fact whose test has not been re-run and may be stale degrades back toward `Verified-static`. A doc that lies with confidence is worse than no doc.

### Proof-of-works mandate

Every feature and business rule — legacy or new — must carry a test that proves it works. A rule sitting at `Verified-static` or weaker is an **open obligation**: author the test following the `access-vba-tdd-fundamentos` skill (which runs on `dysflow.test_vba`) until the rule reaches `Verified-runtime`. Producing those missing tests is part of documenting the capability, not a separate project. This is what turns a description into a contract.

## 4. Detect-and-reconstruct (regression-proof)

Regression resilience needs two complementary pieces, both in the template:

- **Detection** — §2 acceptance/presence signals define what the running app *must* produce. If those signals are absent, the feature has regressed or vanished.
- **Reconstruction** — §4 recipe is the ordered rebuild path. All source↔binary steps go through the Dysflow MCP (`import_modules`, `verify_code`, `test_vba`), never ad-hoc skills.

Detection tells you it's gone; reconstruction tells you how to bring it back.

## 4b. Tracker references — history, not truth

When known, link the tracker item (GH issue / PR) that originated a feature (§1) or that shipped/fixed/regressed a version event (§5 ledger). Keep it tracker-agnostic and optional — legacy features predate the tracker and have none. A tracker item carries intent and discussion, and can be as stale or wrong as an old spec; it never overrides the code.

## 5. Gate 0 — harvest before reverse-engineering

Features born from SDD already have proposal/spec/design/tasks. Harvest them into the matching template layers (§1 from proposal, §2 from spec, §3 from design, §4 from tasks) — then verify against code. Reverse-engineer from code only for legacy features or harvested gaps. This avoids duplicating work SDD already did and keeps going-forward SDD output flowing into the docs naturally.

## 6. Tiers — proportionality

Not every feature deserves full depth. `tier` controls effort:

- `minimal` — trivial/low-risk: identity, short intent, rules + acceptance signals, confidence ledger.
- `standard` — most features: §0–§5 + ledger.
- `critical` — high-value/high-risk: all sections, fully, including migration notes.

This is what keeps SDD-grade documentation from collapsing under its own maintenance cost.

## 7. The doc as a migration spec and SDD seed

A capability doc is not only a regression contract against the Access binary — it is also the **platform-agnostic specification** of the feature. That second role is what makes leaving the Access legacy possible.

The split mirrors section 1: the **WHAT** (behavior, rules, data, UX intent) is platform-independent and survives a rewrite; the **HOW-in-Access** (forms, VBA, `getdb()`, linked backends) does not. The migration sections separate them deliberately:

- **§3 data model** captures the domain entities/fields/relationships in logical terms, so a web data model (SQL/ORM/NoSQL) can represent them without inheriting Access types.
- **§6 migration spec** extracts the logic that today hides inside form events (humble-object), states the agnostic functional contract (inputs→outputs/errors), the UI/UX intent, the integrations, the data mapping, and the non-functional needs (e.g. server-side auth that Access did client-side or skipped).
- **§8 SDD seed** is the bridge: it maps each doc section to a layer of a future SDD (proposal←§1+§6, spec←§2, design←§3+§6, tasks←ordered slices), so an AI can raise the port's SDD straight from the doc. The §2 behavioral contract is the acceptance spec the rebuilt web version must pass — same scenarios, new platform.

Why this matters: a description tells you what a feature did; a migration spec lets someone rebuild it elsewhere. The code remains the source of truth, but the doc becomes the medium through which the feature can move off Access — verified by parity with §2, not by trust.

## Lineage

The template synthesizes established industry practice rather than inventing a format: arc42 / C4 (§3 architecture map), BDD / Specification by Example (§2 scenarios), ADR (§3 design assessment), Requirements Traceability Matrix from regulated software — DO-178C / IEC 62304 / ISO 26262 (§5 traceability), and Living Documentation (the freshness discipline in §3 above).
