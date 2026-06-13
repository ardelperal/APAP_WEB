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

A `data-model-completeness.md` document SHALL catalog all auxiliary, catalog, and state/config tables missing from current docs. It MUST document FK relationships, compound uniqueness constraints, and which constraints are DB-enforced vs. application-enforced.

#### Scenario: Auxiliary tables documented

- GIVEN tables like `TbActuacionSanitariaAux`, `TbEntradasMultiplesAuxIniciales`, `TbAuxAnimales`
- WHEN the data-model-completeness doc is written
- THEN each table's purpose, columns, and relationships are documented
- AND FK enforcement source (DB vs. application) is specified

#### Scenario: Catalog tables documented

- GIVEN catalog tables like `TbOrigenEntrada`, `TbMotivosEntrada`, `TbTamaños`
- WHEN documented
- THEN valid domain values and uniqueness constraints are listed

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

Each feature doc SHALL include complete validation rules: cross-field validations, business-rule validations, data-integrity validations, and report SQL sandboxing rules.

#### Scenario: Cross-field validations documented

- GIVEN chip number format, DNI format, required field combinations
- WHEN feature docs are augmented
- THEN each validation rule states the constraint, the fields involved, and the error behavior

#### Scenario: Business-rule validations documented

- GIVEN rules like "sterilization commitment depends on sex" or "species-specific template selection"
- WHEN documented
- THEN the conditional logic and affected fields are explicit

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

An `acceptance-checklist.md` document SHALL define migration-readiness validation criteria per feature. Each criterion MUST be verifiable and traceable to a specific doc or requirement.

#### Scenario: Per-feature readiness verified

- GIVEN the acceptance checklist
- WHEN a reviewer checks feature readiness
- THEN each criterion maps to a specific document section
- AND pass/fail is determinable without ambiguity

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
