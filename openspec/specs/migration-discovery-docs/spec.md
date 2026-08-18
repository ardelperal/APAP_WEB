# Migration Discovery Documentation Specification

## Purpose

Cross-cutting business documentation that fills gaps in APAP's existing 12 discovery docs to make them migration-ready. Covers business-only features, data model completeness, state machines, validations, reports/documents, open decisions, acceptance checklist, and migration-risk traceability. All artifacts describe WHAT the system does, not how Access implements it.

## Requirements

### Requirement: Business-Only Feature Augmentation

Each feature doc (01–04) shall be augmented with validated business details discovered via Dysflow read-only source inspection. Documentation must cover business rules only; Access/admin mechanics must not appear as product features.

#### Scenario: Feature doc augmented with source-validated details

- given an existing feature doc (e.g., `feature-01-animal-lifecycle.md`)
- when Dysflow read-only inspection reveals undocumented business rules
- then the doc is augmented with those rules in the existing section structure
- and no Access/VBA implementation details are added

#### Scenario: Business-only boundary enforced

- given a discovery doc under `docs/discovery/`
- when a reader reviews it for migration planning
- then every requirement describes business behavior, not Access mechanics
- and Access-specific concepts appear only as migration-risk footnotes

### Requirement: Data Model Completeness

A `data-model-completeness.md` document shall catalog all auxiliary, catalog, and state/config tables missing from current docs. It must document FK relationships, compound uniqueness constraints, and which constraints are DB-enforced vs. application-enforced. All evidence source blocks must be validated via Dysflow live inspection.
(Previously: Evidence source blocks marked `[ ] — needs live validation` for TbAuxAnimales, catalog tables, and FK enforcement)

#### Scenario: Auxiliary tables documented

- given tables like `TbActuacionSanitariaAux`, `TbEntradasMultiplesAuxIniciales`, `TbAuxAnimales`
- when the data-model-completeness doc is written
- then each table's purpose, columns, and relationships are documented
- and FK enforcement source (DB vs. application) is specified

#### Scenario: Catalog tables documented

- given catalog tables like `TbOrigenEntrada`, `TbMotivosEntrada`, `TbTamaños`
- when documented
- then valid domain values and uniqueness constraints are listed
- and all catalog evidence source blocks are marked `[x]` with actual values

### Requirement: State Machine Completeness

A `state-machines.md` document shall define all state machines across features: animal lifecycle, foster home status, contract lifecycle, health action status, and adoption follow-up. Each machine must include states, allowed transitions, and trigger events.

#### Scenario: Cross-feature state machines defined

- given foster home, contract, health, and adoption follow-up states
- when `state-machines.md` is written
- then each machine has a state table and transition rules table
- and integration points with the animal lifecycle state are noted

#### Scenario: State derivation formula documented

- given the computed `Situacion` field on the animal master record
- when documented
- then the exact derivation logic from active records is specified

### Requirement: Validation Completeness

Each feature doc shall include complete validation rules: cross-field validations, business-rule validations, data-integrity validations, and report SQL sandboxing rules. All evidence source blocks must be validated via Dysflow live queries.
(Previously: Date validation and puppy-test evidence source blocks marked `[ ] — needs live validation`)

#### Scenario: Cross-field validations documented

- given chip number format, DNI format, required field combinations
- when feature docs are augmented
- then each validation rule states the constraint, the fields involved, and the error behavior

#### Scenario: Business-rule validations documented

- given rules like "sterilization commitment depends on sex" or "species-specific template selection"
- when documented
- then the conditional logic and affected fields are explicit

#### Scenario: Evidence source validated via Dysflow

- given an evidence source block in a feature doc referencing Dysflow queries
- when the validation queries are executed against the live backend
- then the evidence source block is updated with actual results and marked `[x]`

### Requirement: Reports and Documents Completeness

Feature 04 shall be augmented with contract template conditionals, quarterly report data aggregation logic, and report SQL validation rules.

#### Scenario: Contract conditionals documented

- given species/sex/age-dependent clause inclusion in contracts
- when documented
- then the exact conditional logic per contract type is specified

#### Scenario: Quarterly report aggregation documented

- given quarterly report sections and data sources
- when documented
- then field mappings per section and calculation logic are explicit

### Requirement: Open Decisions Registry

An `open-decisions.md` document shall track all unresolved decisions with owner, deadline, and resolution status. It must cover: state derivation formula, strict mode behavior, foster capacity enforcement, report SQL security model, ARIAC regulatory scope, and photo/attachment storage volume.

#### Scenario: Decision tracked with ownership

- given an unresolved decision (e.g., foster capacity enforcement)
- when recorded in `open-decisions.md`
- then it includes decision statement, options considered, owner, deadline, and current status

### Requirement: Acceptance Checklist

An `acceptance-checklist.md` document shall define migration-readiness validation criteria per feature. Each criterion must be verifiable and traceable to a specific doc or requirement. The verification summary must have filled pass/fail/not-assessed columns.
(Previously: Verification summary columns empty)

#### Scenario: Per-feature readiness verified

- given the acceptance checklist
- when a reviewer checks feature readiness
- then each criterion maps to a specific document section
- and pass/fail is determinable without ambiguity

#### Scenario: Verification summary populated

- given the acceptance checklist verification summary table
- when evidence gap closure is complete
- then each category row has pass/fail/not-assessed counts
- and the total row sums correctly

### Requirement: Migration-Risk Traceability

`migration-risks.md` shall be updated with data migration scope (production vs. staging vs. audit tables), backward compatibility plan, post-migration data validation approach, and incremental migration strategy.

#### Scenario: Data migration scope defined

- given all APAP tables
- when migration risks are updated
- then each table is classified as production-data, staging, or audit
- and migration priority/order is specified

#### Scenario: Backward compatibility plan documented

- given a transition period requirement
- when documented
- then read-only legacy access approach and duration are specified

### Requirement: Lifecycle Event Timeline and Location Traceability

The discovery documentation shall define a mandatory requirement for a complete, chronological, auditable event timeline for every shelter animal. This is a business requirement for the future web project, not an open question.
(Previously: Not documented; lifecycle traceability was only implied by state derivation logic)

#### Scenario: Timeline requirement documented

- given the animal lifecycle feature doc
- when the lifecycle event timeline section is written
- then it specifies mandatory event types (intake, foster, adoption, return, death, etc.)
- and it defines the continuity principle (no gaps between events)
- and it enumerates edge cases (multiple foster stays, returns, adoption returns, death as terminal)

#### Scenario: State machine linked to event log

- given the state machines doc
- when the timeline/audit trail requirement is added
- then it states that every state transition must be recorded as a timestamped event
- and current state is derived from the most recent event, never stored independently

#### Scenario: Acceptance criteria for traceability

- given the acceptance checklist
- when traceability criteria are added
- then there are pass/fail criteria for timeline documentation, continuity principle, edge cases, and legacy migration behavior

#### Scenario: Open decision updated

- given Decision 1 (State Derivation Formula) in open-decisions.md
- when the stakeholder requirement is incorporated
- then the status changes from "Open" to "Direction decided; schema is implementation decision"
- and the decided direction states that the event log is the single source of truth

### Requirement: Volunteer Registry Target Model

The discovery documentation shall introduce a Volunteer Registry as a mandatory new feature for the target web application. The documentation must define the Volunteer entity as first-class with stable ID, document the denormalized legacy state across affected tables, specify that free-text volunteer fields become FK relationships, and document the migration deduplication impact.
(Previously: Volunteer names are free-text strings across intake, adoption, and foster tables; no normalized volunteer entity exists)

#### Scenario: Volunteer denormalization documented

- given the data-model-completeness doc
- when the volunteer denormalization section is written
- then it lists every table and field where volunteer names appear as free-text
- and it documents the problems: no stable ID, no deduplication, inline contact data, no role model

#### Scenario: Volunteer Registry target model documented

- given the data-model-completeness doc
- when the target model section is written
- then it specifies Volunteer entity fields (name, contact, status, roles, notes)
- and it specifies FK relationships replacing free-text fields in intake, foster, and adoption
- and it documents the migration deduplication requirement

#### Scenario: Business feature map updated

- given the business-feature-map.md
- when the Volunteer Registry foundation is added
- then it appears as a mandatory foundation with principles and requirements
- and the web generation order places it before Feature 02

#### Scenario: Feature docs reference Volunteer Registry

- given feature-02 (intake/foster/adoption) and feature-03 (health/care)
- when volunteer fields are documented
- then each volunteer field states it references the Volunteer Registry (FK to Volunteer.ID)
- and open decisions about role taxonomy and deduplication are referenced

#### Scenario: Acceptance criteria for volunteer registry

- given the acceptance checklist
- when volunteer registry criteria are added
- then there are pass/fail criteria for denormalization documentation, target model, foundation requirement, and open decision

### Requirement: Volunteer Registry Business Rules

The discovery documentation shall define mandatory business rules for the Volunteer Registry in the target web application. These rules govern volunteer lifecycle: creation, assignment, deactivation, and deletion across all workflows.
(Previously: Volunteer registry was documented as a target model but without explicit lifecycle/business rules)

#### Scenario: FK-only references documented

- given the data-model-completeness doc and feature docs
- when volunteer business rules are documented
- then it states that no workflow may assign a volunteer unless the volunteer exists in the Volunteer Registry
- and free-text volunteer assignment is explicitly prohibited

#### Scenario: Active-volunteer validation documented

- given feature-02 and feature-03 docs
- when volunteer assignment rules are documented
- then every create/edit workflow that assigns a volunteer validates the volunteer exists and is active

#### Scenario: No-physical-delete rule documented

- given the data-model-completeness doc
- when volunteer deletion rules are documented
- then it states that volunteers referenced by any business record cannot be physically deleted
- and only deactivation (soft-delete) is permitted for referenced volunteers

#### Scenario: Historical preservation documented

- given the data-model-completeness doc and open-decisions.md
- when deactivation behavior is documented
- then it states that deactivating a volunteer preserves all historical FK relationships
- and the volunteer remains readable for reporting and audit trails

#### Scenario: Unreferenced deletion policy documented

- given the open-decisions.md Decision 7
- when volunteer deletion policy is documented
- then it states that unreferenced volunteers may be deleted only if product explicitly decides
- and the default policy is deactivation for all volunteers
