# Migration Discovery Documentation Specification

## Purpose

Cross-cutting business documentation that fills gaps in APAP's existing 12 discovery docs to make them migration-ready. Covers business-only features, data model completeness, state machines, validations, reports/documents, open decisions, acceptance checklist, and migration-risk traceability. All artifacts describe WHAT the system does, not how Access implements it.

## Requirements

### Requirement: Business-Only Feature Augmentation

Each feature doc (01–04) SHALL be augmented with validated business details discovered via Dysflow read-only source inspection. Documentation MUST cover business rules only; Access/admin mechanics MUST NOT appear as product features.

#### Scenario: Feature doc augmented with source-validated details

- GIVEN an existing feature doc (e.g., `feature-01-animal-lifecycle.md`)
- WHEN Dysflow read-only inspection reveals undocumented business rules
- THEN the doc is augmented with those rules in the existing section structure
- AND no Access/VBA implementation details are added

#### Scenario: Business-only boundary enforced

- GIVEN a discovery doc under `docs/discovery/`
- WHEN a reader reviews it for migration planning
- THEN every requirement describes business behavior, not Access mechanics
- AND Access-specific concepts appear only as migration-risk footnotes

### Requirement: Data Model Completeness

A `data-model-completeness.md` document SHALL catalog all auxiliary, catalog, and state/config tables missing from current docs. It MUST document FK relationships, compound uniqueness constraints, and which constraints are DB-enforced vs. application-enforced. All evidence source blocks MUST be validated via Dysflow live inspection.
(Previously: Evidence source blocks marked `[ ] — needs live validation` for TbAuxAnimales, catalog tables, and FK enforcement)

#### Scenario: Auxiliary tables documented

- GIVEN tables like `TbActuacionSanitariaAux`, `TbEntradasMultiplesAuxIniciales`, `TbAuxAnimales`
- WHEN the data-model-completeness doc is written
- THEN each table's purpose, columns, and relationships are documented
- AND FK enforcement source (DB vs. application) is specified

#### Scenario: Catalog tables documented

- GIVEN catalog tables like `TbOrigenEntrada`, `TbMotivosEntrada`, `TbTamaños`
- WHEN documented
- THEN valid domain values and uniqueness constraints are listed
- AND all catalog evidence source blocks are marked `[x]` with actual values

### Requirement: State Machine Completeness

A `state-machines.md` document SHALL define all state machines across features: animal lifecycle, foster home status, contract lifecycle, health action status, and adoption follow-up. Each machine MUST include states, allowed transitions, and trigger events.

#### Scenario: Cross-feature state machines defined

- GIVEN foster home, contract, health, and adoption follow-up states
- WHEN `state-machines.md` is written
- THEN each machine has a state table and transition rules table
- AND integration points with the animal lifecycle state are noted

#### Scenario: State derivation formula documented

- GIVEN the computed `Situacion` field on the animal master record
- WHEN documented
- THEN the exact derivation logic from active records is specified

### Requirement: Validation Completeness

Each feature doc SHALL include complete validation rules: cross-field validations, business-rule validations, data-integrity validations, and report SQL sandboxing rules. All evidence source blocks MUST be validated via Dysflow live queries.
(Previously: Date validation and puppy-test evidence source blocks marked `[ ] — needs live validation`)

#### Scenario: Cross-field validations documented

- GIVEN chip number format, DNI format, required field combinations
- WHEN feature docs are augmented
- THEN each validation rule states the constraint, the fields involved, and the error behavior

#### Scenario: Business-rule validations documented

- GIVEN rules like "sterilization commitment depends on sex" or "species-specific template selection"
- WHEN documented
- THEN the conditional logic and affected fields are explicit

#### Scenario: Evidence source validated via Dysflow

- GIVEN an evidence source block in a feature doc referencing Dysflow queries
- WHEN the validation queries are executed against the live backend
- THEN the evidence source block is updated with actual results and marked `[x]`

### Requirement: Reports and Documents Completeness

Feature 04 SHALL be augmented with contract template conditionals, quarterly report data aggregation logic, and report SQL validation rules.

#### Scenario: Contract conditionals documented

- GIVEN species/sex/age-dependent clause inclusion in contracts
- WHEN documented
- THEN the exact conditional logic per contract type is specified

#### Scenario: Quarterly report aggregation documented

- GIVEN quarterly report sections and data sources
- WHEN documented
- THEN field mappings per section and calculation logic are explicit

### Requirement: Open Decisions Registry

An `open-decisions.md` document SHALL track all unresolved decisions with owner, deadline, and resolution status. It MUST cover: state derivation formula, strict mode behavior, foster capacity enforcement, report SQL security model, ARIAC regulatory scope, and photo/attachment storage volume.

#### Scenario: Decision tracked with ownership

- GIVEN an unresolved decision (e.g., foster capacity enforcement)
- WHEN recorded in `open-decisions.md`
- THEN it includes decision statement, options considered, owner, deadline, and current status

### Requirement: Acceptance Checklist

An `acceptance-checklist.md` document SHALL define migration-readiness validation criteria per feature. Each criterion MUST be verifiable and traceable to a specific doc or requirement. The verification summary MUST have filled pass/fail/not-assessed columns.
(Previously: Verification summary columns empty)

#### Scenario: Per-feature readiness verified

- GIVEN the acceptance checklist
- WHEN a reviewer checks feature readiness
- THEN each criterion maps to a specific document section
- AND pass/fail is determinable without ambiguity

#### Scenario: Verification summary populated

- GIVEN the acceptance checklist verification summary table
- WHEN evidence gap closure is complete
- THEN each category row has pass/fail/not-assessed counts
- AND the total row sums correctly

### Requirement: Migration-Risk Traceability

`migration-risks.md` SHALL be updated with data migration scope (production vs. staging vs. audit tables), backward compatibility plan, post-migration data validation approach, and incremental migration strategy.

#### Scenario: Data migration scope defined

- GIVEN all APAP tables
- WHEN migration risks are updated
- THEN each table is classified as production-data, staging, or audit
- AND migration priority/order is specified

#### Scenario: Backward compatibility plan documented

- GIVEN a transition period requirement
- WHEN documented
- THEN read-only legacy access approach and duration are specified

### Requirement: Lifecycle Event Timeline and Location Traceability

The discovery documentation SHALL define a mandatory requirement for a complete, chronological, auditable event timeline for every shelter animal. This is a business requirement for the future web project, not an open question.
(Previously: Not documented; lifecycle traceability was only implied by state derivation logic)

#### Scenario: Timeline requirement documented

- GIVEN the animal lifecycle feature doc
- WHEN the lifecycle event timeline section is written
- THEN it specifies mandatory event types (intake, foster, adoption, return, death, etc.)
- AND it defines the continuity principle (no gaps between events)
- AND it enumerates edge cases (multiple foster stays, returns, adoption returns, death as terminal)

#### Scenario: State machine linked to event log

- GIVEN the state machines doc
- WHEN the timeline/audit trail requirement is added
- THEN it states that every state transition MUST be recorded as a timestamped event
- AND current state is derived from the most recent event, never stored independently

#### Scenario: Acceptance criteria for traceability

- GIVEN the acceptance checklist
- WHEN traceability criteria are added
- THEN there are pass/fail criteria for timeline documentation, continuity principle, edge cases, and legacy migration behavior

#### Scenario: Open decision updated

- GIVEN Decision 1 (State Derivation Formula) in open-decisions.md
- WHEN the stakeholder requirement is incorporated
- THEN the status changes from "Open" to "Direction decided; schema is implementation decision"
- AND the decided direction states that the event log is the single source of truth

### Requirement: Volunteer Registry Target Model

The discovery documentation SHALL introduce a Volunteer Registry as a mandatory new feature for the target web application. The documentation MUST define the Volunteer entity as first-class with stable ID, document the denormalized legacy state across affected tables, specify that free-text volunteer fields become FK relationships, and document the migration deduplication impact.
(Previously: Volunteer names are free-text strings across intake, adoption, and foster tables; no normalized volunteer entity exists)

#### Scenario: Volunteer denormalization documented

- GIVEN the data-model-completeness doc
- WHEN the volunteer denormalization section is written
- THEN it lists every table and field where volunteer names appear as free-text
- AND it documents the problems: no stable ID, no deduplication, inline contact data, no role model

#### Scenario: Volunteer Registry target model documented

- GIVEN the data-model-completeness doc
- WHEN the target model section is written
- THEN it specifies Volunteer entity fields (name, contact, status, roles, notes)
- AND it specifies FK relationships replacing free-text fields in intake, foster, and adoption
- AND it documents the migration deduplication requirement

#### Scenario: Business feature map updated

- GIVEN the business-feature-map.md
- WHEN the Volunteer Registry foundation is added
- THEN it appears as a mandatory foundation with principles and requirements
- AND the web generation order places it before Feature 02

#### Scenario: Feature docs reference Volunteer Registry

- GIVEN feature-02 (intake/foster/adoption) and feature-03 (health/care)
- WHEN volunteer fields are documented
- THEN each volunteer field states it references the Volunteer Registry (FK to Volunteer.ID)
- AND open decisions about role taxonomy and deduplication are referenced

#### Scenario: Acceptance criteria for volunteer registry

- GIVEN the acceptance checklist
- WHEN volunteer registry criteria are added
- THEN there are pass/fail criteria for denormalization documentation, target model, foundation requirement, and open decision

### Requirement: Volunteer Registry Business Rules

The discovery documentation SHALL define mandatory business rules for the Volunteer Registry in the target web application. These rules govern volunteer lifecycle: creation, assignment, deactivation, and deletion across all workflows.
(Previously: Volunteer registry was documented as a target model but without explicit lifecycle/business rules)

#### Scenario: FK-only references documented

- GIVEN the data-model-completeness doc and feature docs
- WHEN volunteer business rules are documented
- THEN it states that no workflow may assign a volunteer unless the volunteer exists in the Volunteer Registry
- AND free-text volunteer assignment is explicitly prohibited

#### Scenario: Active-volunteer validation documented

- GIVEN feature-02 and feature-03 docs
- WHEN volunteer assignment rules are documented
- THEN every create/edit workflow that assigns a volunteer validates the volunteer exists AND is active

#### Scenario: No-physical-delete rule documented

- GIVEN the data-model-completeness doc
- WHEN volunteer deletion rules are documented
- THEN it states that volunteers referenced by any business record cannot be physically deleted
- AND only deactivation (soft-delete) is permitted for referenced volunteers

#### Scenario: Historical preservation documented

- GIVEN the data-model-completeness doc and open-decisions.md
- WHEN deactivation behavior is documented
- THEN it states that deactivating a volunteer preserves all historical FK relationships
- AND the volunteer remains readable for reporting and audit trails

#### Scenario: Unreferenced deletion policy documented

- GIVEN the open-decisions.md Decision 7
- WHEN volunteer deletion policy is documented
- THEN it states that unreferenced volunteers may be deleted only if product explicitly decides
- AND the default policy is deactivation for all volunteers
