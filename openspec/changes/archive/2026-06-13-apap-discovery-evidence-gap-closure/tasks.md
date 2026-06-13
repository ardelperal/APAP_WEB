# Tasks: APAP Discovery Evidence Gap Closure

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 80–150 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | force-chained |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Low

## Phase 1: Dysflow Schema & Query Validation

- [x] 1.1 Run Dysflow `get_schema` on `TbAuxAnimales` — document columns, purpose, relationships
- [x] 1.2 Run Dysflow `get_schema` on `TbOrigenEntrada` — confirm PK, description column
- [x] 1.3 Run Dysflow `query_sql` SELECT DISTINCT on `TbOrigenEntrada` — enumerate all origin values
- [x] 1.4 Run Dysflow `get_schema` on `TbMotivosEntrada` — confirm PK, description column
- [x] 1.5 Run Dysflow `query_sql` SELECT DISTINCT on `TbMotivosEntrada` — enumerate all reason values
- [x] 1.6 Run Dysflow `get_schema` on `TbTamaños` — confirm PK, description column
- [x] 1.7 Run Dysflow `query_sql` SELECT DISTINCT on `TbTamaños` — enumerate all size values

## Phase 2: Business Rule Validation Queries

- [x] 2.1 Run Dysflow `query_sql` foster capacity query: `SELECT IDAcogidaCasa, COUNT(*) FROM TbAcogidaAnimal WHERE FFinal IS NULL GROUP BY IDAcogidaCasa`
- [x] 2.2 Run Dysflow `query_sql` date validation join: health action dates vs animal birth/death
- [x] 2.3 Run Dysflow `query_sql` puppy-test threshold: `DATEDIFF('m', FNacimiento, Date()) < 8 AND Especie = 'CANINA'` eligibility check

## Phase 3: FK Enforcement Validation

- [x] 3.1 Run Dysflow `get_relationships` to inspect FK declarations across key tables
- [x] 3.2 Record which relationships are DB-enforced vs application-enforced

## Phase 4: Documentation Updates

- [x] 4.1 Update `data-model-completeness.md` — TbAuxAnimales evidence block with schema findings
- [x] 4.2 Update `data-model-completeness.md` — TbOrigenEntrada, TbMotivosEntrada, TbTamaños evidence blocks with domain values
- [x] 4.3 Update `data-model-completeness.md` — FK enforcement table with validated results
- [x] 4.4 Update `feature-02-intake-foster-adoption.md` — foster capacity evidence block with query result
- [x] 4.5 Update `feature-03-health-care.md` — date validation evidence block with query result
- [x] 4.6 Update `feature-03-health-care.md` — puppy-test evidence block with query result

## Phase 5: Acceptance Checklist & Verification

- [x] 5.1 Fill acceptance-checklist.md verification summary — count pass/fail/not-assessed per category
- [x] 5.2 Cross-check all internal doc references still resolve
- [ ] 5.3 Commit all changes

## Phase 6: Stakeholder Requirement — Lifecycle Event Timeline

- [x] 6.1 Update `feature-01-animal-lifecycle.md` — add mandatory lifecycle event timeline and location traceability section
- [x] 6.2 Update `state-machines.md` — add timeline/audit trail requirement to Animal Lifecycle state machine
- [x] 6.3 Update `acceptance-checklist.md` — add 5 pass/fail criteria for chronological traceability (1.11–1.15)
- [x] 6.4 Update `open-decisions.md` Decision 1 — mark direction decided (event log as source of truth); schema remains implementation decision
- [x] 6.5 Update `business-feature-map.md` — add mandatory foundation section for lifecycle event timeline
- [x] 6.6 Update `specs/migration-discovery-docs/spec.md` — add requirement and scenarios for lifecycle event timeline documentation

## Phase 7: Stakeholder Requirement — Volunteer Registry

- [x] 7.1 Update `data-model-completeness.md` — add § "Volunteer Denormalization in Legacy" documenting current free-text state and target Volunteer entity model
- [x] 7.2 Update `business-feature-map.md` — add mandatory foundation section for Volunteer Registry; update web generation order
- [x] 7.3 Update `feature-02-intake-foster-adoption.md` — add § "Volunteer Registry integration" documenting FK relationships for intake, foster, adoption volunteer fields
- [x] 7.4 Update `feature-03-health-care.md` — document therapy volunteer references Volunteer Registry
- [x] 7.5 Update `open-decisions.md` — add Decision 7 (Volunteer Registry): direction decided, implementation details open
- [x] 7.6 Update `acceptance-checklist.md` — add 4 pass/fail criteria for volunteer registry (CC.11–CC.14); update verification summary totals
- [x] 7.7 Update `specs/migration-discovery-docs/spec.md` — add requirement and scenarios for Volunteer Registry target model documentation

## Phase 8: Volunteer Registry Business Rules — Clarified Requirements

- [x] 8.1 Update `data-model-completeness.md` — add § "Volunteer Registry business rules (target web)" with 5 mandatory rules: FK-only, active validation, no physical delete, historical preservation, unreferenced deletion
- [x] 8.2 Update `data-model-completeness.md` — add volunteer FK/delete constraint rows to business rule constraints table
- [x] 8.3 Update `feature-02-intake-foster-adoption.md` — add § "Volunteer assignment business rules" documenting enforcement rules for intake, foster, adoption workflows
- [x] 8.4 Update `feature-03-health-care.md` — add § "Therapy volunteer business rules" and update therapy data table to show FK requirement
- [x] 8.5 Update `open-decisions.md` Decision 7 — add "Mandatory business rules" section with 5 decided rules (BR1–BR5); mark 4 resolution items resolved
- [x] 8.6 Update `acceptance-checklist.md` — add criteria 2.10, 3.9, CC.15, CC.16 for volunteer business rules; update verification summary totals to 57
- [x] 8.7 Update `business-feature-map.md` — add 5 business rule rows to Volunteer Registry foundation section
- [x] 8.8 Update `specs/migration-discovery-docs/spec.md` — add requirement "Volunteer Registry Business Rules" with 5 scenarios
