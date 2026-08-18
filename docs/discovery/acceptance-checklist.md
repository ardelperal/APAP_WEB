# Acceptance Checklist

Migration-readiness validation criteria for each feature. Each criterion is pass/fail determinable and maps to a specific document section. Use this checklist to verify that discovery documentation is complete enough for web application implementation.

## How to use

1. Review each criterion against the referenced document section.
2. Mark **Pass** if the criterion is fully met; **Fail** if not.
3. For **Fail** items, note the specific gap and reference the open decision or action needed.
4. All criteria must pass before feature implementation begins.

---

## Feature 01 — Animal Lifecycle

| # | Criterion | Reference | Pass/Fail |
|---|-----------|-----------|-----------|
| 1.1 | State derivation rules are documented with exact priority cascade | `feature-01-animal-lifecycle.md` § "Derivation rules" | Pass |
| 1.2 | All 9 states are defined with meaning and terminal/non-terminal classification | `state-machines.md` § 1 "States" | Pass |
| 1.3 | All allowed transitions are documented with trigger events | `state-machines.md` § 1 "Transition rules" | Pass |
| 1.4 | ARIAC/RIAC notification requirements are documented | `feature-01-animal-lifecycle.md` § "ARIAC and RIAC regulatory notes" | Pass |
| 1.5 | Chip change cascade behavior is documented | `feature-01-animal-lifecycle.md` § "Central identity: microchip" | Pass |
| 1.6 | Search filter behavior and scope are documented | `feature-01-animal-lifecycle.md` § "Search behavior detail" | Pass |
| 1.7 | Business validations (chip uniqueness, birth/death date sanity) are complete | `feature-01-animal-lifecycle.md` § "Business validations" | Pass |
| 1.8 | Legacy notes section identifies what not to copy | `feature-01-animal-lifecycle.md` § "Legacy notes not to copy" | Pass |
| 1.9 | Open decision 1 (state derivation formula) has owner and deadline | `open-decisions.md` § Decision 1 | Pass |
| 1.10 | Open decision 5 (ARIAC/RIAC scope) has owner and deadline | `open-decisions.md` § Decision 5 | Pass |
| 1.11 | Lifecycle event timeline and location traceability requirement is documented as mandatory | `feature-01-animal-lifecycle.md` § "Lifecycle Event Timeline and Location Traceability" | Pass |
| 1.12 | Timeline continuity principle (no gaps, unbroken intervals) is defined | `feature-01-animal-lifecycle.md` § "Continuity requirement" | Pass |
| 1.13 | Timeline edge cases (multiple foster stays, returns, adoption returns, death as terminal) are enumerated | `feature-01-animal-lifecycle.md` § "Continuity requirement" | Pass |
| 1.14 | Legacy migration timeline behavior (complete, partial, conflicting, missing) is specified | `feature-01-animal-lifecycle.md` § "Legacy data migration behavior" | Pass |
| 1.15 | State machine timeline/audit trail requirement links to event log | `state-machines.md` § "Timeline and audit trail requirement" | Pass |

---

## Feature 02 — Intake, Foster & Adoption

| # | Criterion | Reference | Pass/Fail |
|---|-----------|-----------|-----------|
| 2.1 | Batch intake staging rules are documented | `feature-02-intake-foster-adoption.md` § "Batch intake detail" | Pass |
| 2.2 | Foster capacity validation rules are documented | `feature-02-intake-foster-adoption.md` § "Foster capacity validation" | Pass |
| 2.3 | Cesión (owner surrender) workflow is documented | `feature-02-intake-foster-adoption.md` § "Owner surrender" | Pass |
| 2.4 | Foster lifecycle (assignment, end, parent adoption) is documented | `feature-02-intake-foster-adoption.md` § "Foster lifecycle" | Pass |
| 2.5 | Adoption lifecycle (registration, follow-up, return) is documented | `feature-02-intake-foster-adoption.md` § "Adoption lifecycle" | Pass |
| 2.6 | Contract types per workflow are documented | `feature-02-intake-foster-adoption.md` § "Contract outputs per workflow" | Pass |
| 2.7 | Foster-to-adoption state links are documented | `feature-02-intake-foster-adoption.md` § "Foster-to-adoption state links" | Pass |
| 2.8 | Legacy notes section identifies what not to copy | `feature-02-intake-foster-adoption.md` § "Legacy notes not to copy" | Pass |
| 2.9 | Open decision 3 (foster capacity enforcement) has owner and deadline | `open-decisions.md` § Decision 3 | Pass |
| 2.10 | Volunteer Registry business rules (FK-only, active validation, no delete, historical preservation) are documented in Feature 02 | `feature-02-intake-foster-adoption.md` § "Volunteer assignment business rules" | Pass |

---

## Feature 03 — Health & Care

| # | Criterion | Reference | Pass/Fail |
|---|-----------|-----------|-----------|
| 3.1 | Date validation rules (birth–death bounds) are documented | `feature-03-health-care.md` § "Date validation detail" | Pass |
| 3.2 | Puppy-test age threshold logic is documented | `feature-03-health-care.md` § "Puppy-test age threshold logic" | Pass |
| 3.3 | Batch health action staging rules are documented | `feature-03-health-care.md` § "Batch health action staging" | Pass |
| 3.4 | Periodicity engine inputs and calculation are documented | `feature-03-health-care.md` § "Periodicity engine" | Pass |
| 3.5 | Therapy delete restriction is documented | `feature-03-health-care.md` § "Therapies" | Pass |
| 3.6 | Health action duplicate prevention rule is documented | `feature-03-health-care.md` § "Validation rules" | Pass |
| 3.7 | Legacy notes section identifies what not to copy | `feature-03-health-care.md` § "Legacy notes not to copy" | Pass |
| 3.8 | Open decision 2 (strict mode / date validation) has owner and deadline | `open-decisions.md` § Decision 2 | Pass |
| 3.9 | Therapy volunteer business rules (FK-only, active validation, no delete, historical preservation) are documented in Feature 03 | `feature-03-health-care.md` § "Therapy volunteer business rules" | Pass |

---

## Feature 04 — Documents, Contracts & Reports

| # | Criterion | Reference | Pass/Fail |
|---|-----------|-----------|-----------|
| 4.1 | Contract conditional clauses by type are documented | `feature-04-documents-contracts-reports.md` § "Contract conditional clauses by type" | Pass |
| 4.2 | Quarterly report data sources and aggregation are documented | `feature-04-documents-contracts-reports.md` § "Quarterly report data sources" | Pass |
| 4.3 | Dynamic report SQL security risk is documented | `feature-04-documents-contracts-reports.md` § "Dynamic reports as business capability" | Pass |
| 4.4 | Attachment entity links are documented | `feature-04-documents-contracts-reports.md` § "Supported entity links" | Pass |
| 4.5 | Materials catalog uniqueness constraint is documented | `feature-04-documents-contracts-reports.md` § "Materials" | Pass |
| 4.6 | Legacy notes section identifies what not to copy | `feature-04-documents-contracts-reports.md` § "Legacy notes not to copy" | Pass |
| 4.7 | Open decision 4 (dynamic report SQL security) has owner and deadline | `open-decisions.md` § Decision 4 | Pass |

---

## Cross-Cutting Documentation

| # | Criterion | Reference | Pass/Fail |
|---|-----------|-----------|-----------|
| CC.1 | State machines document all 5 machines with states, transitions, integration points | `state-machines.md` | Pass |
| CC.2 | Data model completeness documents auxiliary tables, catalog tables, FK/constraints | `data-model-completeness.md` | Pass |
| CC.3 | Open decisions registry has 7 decisions with owner, deadline, options, status | `open-decisions.md` | Pass |
| CC.4 | Migration risks include data migration scope table | `migration-risks.md` § "Data migration scope" | Pass |
| CC.5 | Migration risks include backward compatibility plan | `migration-risks.md` § "Backward compatibility plan" | Pass |
| CC.6 | Migration risks include post-migration validation | `migration-risks.md` § "Post-migration validation" | Pass |
| CC.7 | Business feature map links to all cross-cutting docs | `business-feature-map.md` § "Cross-cutting docs" | Pass |
| CC.8 | README index links to all docs including cross-cutting | `README.md` § "Cross-cutting docs" | Pass |
| CC.9 | All internal cross-references resolve (no broken links) | All docs | Pass |
| CC.10 | No Access/admin mechanics appear as product features | All feature docs | Pass |
| CC.11 | Volunteer denormalization in legacy is documented with affected tables and fields | `data-model-completeness.md` § "Volunteer Denormalization in Legacy" | Pass |
| CC.12 | Volunteer Registry target model is documented as new feature with entity, relationships, and migration impact | `data-model-completeness.md` § "Volunteer Denormalization in Legacy" target model | Pass |
| CC.13 | Volunteer Registry foundation requirement is in business feature map | `business-feature-map.md` § "Mandatory foundation: Volunteer Registry" | Pass |
| CC.14 | Open decision 7 (Volunteer Registry) has owner, deadline, and implementation options | `open-decisions.md` § Decision 7 | Pass |
| CC.15 | Volunteer Registry business rules (FK-only, active validation, no physical delete, historical preservation) are documented in data-model-completeness.md | `data-model-completeness.md` § "Volunteer Registry business rules (target web)" | Pass |
| CC.16 | Open decision 7 reflects clarified business rules (5 decided rules marked resolved) | `open-decisions.md` § Decision 7 "Mandatory business rules" | Pass |

---

## Verification summary

| Category | Total criteria | Passed | Failed | Not assessed |
|----------|---------------|--------|--------|--------------|
| Feature 01 | 15 | 15 | 0 | 0 |
| Feature 02 | 10 | 10 | 0 | 0 |
| Feature 03 | 9 | 9 | 0 | 0 |
| Feature 04 | 7 | 7 | 0 | 0 |
| Cross-cutting | 16 | 16 | 0 | 0 |
| **Total** | **57** | **57** | **0** | **0** |

## Next step

Assign reviewers for each feature section. All criteria must pass before the corresponding feature begins web implementation.
