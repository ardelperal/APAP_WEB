# Design: APAP Migration Discovery Documentation

## Technical Approach

Feature-augment + cross-cutting docs. Each feature doc (01–04) gains missing details via Dysflow read-only source inspection. Four new docs cover cross-cutting concerns: state machines, data model completeness, open decisions, acceptance checklist. `migration-risks.md` and `business-feature-map.md` are updated to reference new documents.

All artifacts are Markdown in `docs/discovery/`. No code, no tests, no Access/admin mechanics. Business rules only.

## Architecture Decisions

### Decision: Documentation structure

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Single mega-doc | Easy to write; hard to review; duplicates feature detail | Rejected |
| Feature-augment + cross-cutting docs | More files; reviewable diffs; feature truth stays local | **Chosen** |
| Separate dimension docs per feature | Maximum granularity; excessive fragmentation | Rejected |

**Rationale:** Existing feature docs are well-structured. Cross-cutting concerns (state machines, open decisions) belong in separate files per cognitive-doc-design progressive disclosure. Each doc produces a small, reviewable diff.

### Decision: Evidence sourcing

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Dysflow read-only inspection | Live evidence; requires Access runtime | **Chosen** |
| Static source export review | No runtime needed; may miss runtime-only behavior | Rejected |
| Both cross-verified | Maximum confidence; highest effort | Overkill for docs |

**Rationale:** Dysflow read-only queries (`query_sql`, `get_schema`) give direct evidence against the live database. Source export inspection misses runtime-derived state (computed fields, form logic). The proposal explicitly scoped to Dysflow read-only.

### Decision: Business-only boundary

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Include Access mechanics | Complete; couples docs to legacy platform | Rejected |
| Business rules only; Access notes where migration-relevant | Focused; may omit some constraints | **Chosen** |
| Strictly business-only; zero Access references | Clean; loses risk context | Rejected |

**Rationale:** The `openspec/config.yaml` rules and proposal scope both require business-only documentation. Access-specific details are included only when they affect migration risk (e.g., mutable `Situacion` field, per-action passwords).

### Decision: Verification strategy

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Dysflow query cross-check per doc | High confidence; runtime required | **Chosen** |
| Manual review only | Fast; no runtime dependency | Rejected for critical gaps |
| Automated validation | Reliable; no test framework exists | Not applicable |

**Rationale:** No test runner or linter exists for documentation. Verification is manual cross-check: read doc section, verify claim against Dysflow query output or source export, mark verified. Each doc section gets an explicit evidence source.

## Data Flow

    Dysflow MCP (read-only)
         │
         ├── query_sql ──→ Auxiliary table schemas, FK constraints
         ├── get_schema ──→ Column types, required fields
         └── query_sql ──→ State derivation data, validation logic
              │
              ▼
    Feature doc augmentation (01–04)
         │
         ├── feature-01: +state derivation, ARIAC, search
         ├── feature-02: +foster capacity, batch staging, Cesión
         ├── feature-03: +date validation, puppy-test, batch
         └── feature-04: +contract conditionals, report aggregation
              │
              ▼
    Cross-cutting docs (new)
         │
         ├── state-machines.md
         ├── data-model-completeness.md
         ├── open-decisions.md
         └── acceptance-checklist.md
              │
              ▼
    Updated references
         │
         ├── business-feature-map.md (+4 cross-cutting refs)
         └── migration-risks.md (+data migration scope)

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `docs/discovery/feature-01-animal-lifecycle.md` | Modify | Add state derivation formula, ARIAC rules, search behavior |
| `docs/discovery/feature-02-intake-foster-adoption.md` | Modify | Add foster capacity validation, batch staging rules, Cesión detail |
| `docs/discovery/feature-03-health-care.md` | Modify | Add date validation, puppy-test logic, batch staging |
| `docs/discovery/feature-04-documents-contracts-reports.md` | Modify | Add contract conditionals, quarterly report aggregation |
| `docs/discovery/migration-risks.md` | Modify | Add data migration scope, backward compatibility plan |
| `docs/discovery/business-feature-map.md` | Modify | Reference 4 new cross-cutting docs |
| `docs/discovery/state-machines.md` | Create | All state machines: animal, foster home, contract, health action, adoption follow-up |
| `docs/discovery/data-model-completeness.md` | Create | Auxiliary tables, catalog tables, FK/constraints, uniqueness |
| `docs/discovery/open-decisions.md` | Create | 6 unresolved decisions with owner, deadline, resolution approach |
| `docs/discovery/acceptance-checklist.md` | Create | Migration-readiness validation per feature |

## Interfaces / Contracts

No code interfaces. Documentation contracts:

```markdown
## Doc section contract (applied to every augmented section)

### Evidence Source
- **Table:** TbXxx
- **Dysflow tool:** `get_schema` / `query_sql`
- **Query:** (actual SQL or "(form logic)")
- **Verified:** [x] or [ ]

### Business Rule
- Rule statement in plain language
- Applies to: feature domain
- Migration impact: how this affects web app design
```

Each augmented section MUST include an Evidence Source block. This is the traceability contract between documentation and the live database.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Content accuracy | Each business rule matches source evidence | Dysflow read-only query cross-check per section |
| Completeness | All gaps from exploration are covered | Checklist against `exploration.md` dimensions 1–8 |
| Cross-references | All internal links resolve; no orphaned references | Manual link check |
| Boundary compliance | No Access/admin mechanics leaked into business docs | Review against `config.yaml` rules |

No automated test infrastructure exists. Verification is manual review with Dysflow as evidence source.

## Migration / Rollout

No data migration required. Documentation-only change.

**Delivery strategy:** Each feature doc augmentation is an independent reviewable unit. Cross-cutting docs are independent of each other. Recommend sequential delivery:

1. Feature 01 augmentation (smallest, foundation)
2. Feature 02 augmentation (core workflows)
3. Feature 03 augmentation (health domain)
4. Feature 04 augmentation (documents/reports)
5. Cross-cutting docs (4 new files, independent)
6. Reference updates (business-feature-map, migration-risks)

Total estimated changed lines: ~400–600 (under chained PR threshold if delivered as one unit; within budget if split by feature).

## Open Questions

- [ ] Exact state derivation formula for `Situacion` — is it a single query or multi-step logic? Needs Dysflow source inspection.
- [ ] Puppy-test logic in Feature 03 — is it a date-based calculation or a lookup?
- [ ] Foster capacity enforcement — validate at write time or advisory only? (listed in `open-decisions.md`)
- [ ] Report SQL sandbox rules — which tables/operations are forbidden for user-defined reports?
- [ ] ARIAC regulatory module scope — include in web app or external handling?
- [ ] Photo/attachment volume estimation — needed for storage sizing but not blocking documentation.
