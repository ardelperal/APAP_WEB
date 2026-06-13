# Exploration: APAP Migration Discovery Documentation

## Current State

The APAP project has 12 documentation files under `docs/discovery/` covering business features, data model, migration risks, inventory baseline, and Dysflow runtime notes. The documentation is well-structured with a clear feature index and web-implication mapping per feature.

### Existing coverage

| Document | Coverage | Gaps |
|----------|----------|------|
| Business Feature Map | ✅ 4 features indexed | Missing: open decisions, cross-cutting concerns summary |
| Feature 01 — Animal Lifecycle | ✅ State model, chip management, transitions | Missing: state derivation logic validation, search behavior, ARIAC regulatory rules |
| Feature 02 — Intake/Foster/Adoption | ✅ Workflows, foster lifecycle, adoption | Missing: foster capacity validation rules, Entradas Múltiples staging rules, Cesión por Propietario detail |
| Feature 03 — Health & Care | ✅ Actions, therapies, recommendations, periodicity | Missing: date range validation details, batch staging rules, puppy-test logic |
| Feature 04 — Documents/Contracts/Reports | ✅ Attachments, contracts, materials, reports | Missing: contract template conditionals, quarterly report aggregation, report SQL validation |
| Migration Risks | ✅ 4 risk categories | Missing: data migration completeness, backward compatibility during transition |
| Data Model Notes | ✅ Core entities, relationships | Missing: auxiliary tables (TbAcciones, TbVersion), catalog tables (TbOrigenEntrada, TbMotivosEntrada, TbTamaños) |
| Inventory Baseline | ✅ Table list, module counts | Complete for current scope |
| Dysflow Notes | ✅ Runtime verification | Complete for current scope |
| Admin Panel | ✅ Excluded from scope | Complete for exclusion rationale |

## Coverage Dimensions Identified

### 1. Business Processes
**What exists:** Intake, foster, adoption, health, document workflows are documented at feature level.

**What's missing:**
- Cross-feature state machine: how intake → foster → adoption transitions work as a unified lifecycle
- Batch operation rules: Entradas Múltiples staging and commit flow
- Ownership transfer chain: intake → foster → adoption → return → re-intake
- End-of-period processes: quarterly report generation workflow

### 2. Data Model
**What exists:** Core entity relationships, field lists, initial row counts.

**What's missing:**
- Auxiliary/staging tables: `TbActuacionSanitariaAux`, `TbEntradasMultiplesAuxIniciales`, `TbEntradasMultiplesAuxSeleccionados`, `TbAuxAnimales`, `TbAuxAnimalesDesparasitacion`, `TbAuxPruebasPendientes`, `TbFichaSanitariaPrincipalAux`
- Catalog tables: `TbOrigenEntrada`, `TbMotivosEntrada`, `TbTamaños`, `TbNombrePruebas`, `TbPruebasPeridicidad`, `TbVoluntariosParaAutorrellenables`
- State/config tables: `TbOpciones`, `TbVersion`, `TbRIAC`
- FK relationship validation: which tables have formal FK constraints vs. application-enforced joins
- Unique constraint documentation: what combinations are enforced at DB level vs. application level

### 3. State Machines
**What exists:** Computed state model for animal lifecycle with transition rules.

**What's missing:**
- Foster home status state: available → at-capacity → blocked
- Contract lifecycle state: template → generated → pending-signature → signed → archived
- Health action status: due → scheduled → completed (for periodicity engine)
- Adoption follow-up state: pending-delivery → delivered → attached

### 4. Validations
**What exists:** Basic validation rules per feature (duplicate prevention, date ranges).

**What's missing:**
- Cross-field validations: chip number format, DNI format, required field combinations
- Business rule validations: sterilization commitment depends on sex, species-specific template selection
- Data integrity validations: FK consistency between linked entities
- Report SQL validation: allowed tables, forbidden operations, sandboxing rules
- Material catalog uniqueness: `Material + Tamaño + Color` compound uniqueness

### 5. Reports and Documents
**What exists:** Custom report definitions, quarterly report sections, contract types.

**What's missing:**
- Quarterly report data aggregation: exact fields per section, calculation logic
- Report SQL template catalog: what reports are predefined vs. user-created
- Contract template conditionals: exact species/sex/age logic for clause inclusion
- Document storage structure: file naming conventions, folder organization

### 6. Migration Risks
**What exists:** 4 categories of risks with mitigations.

**What's missing:**
- Data migration scope: which tables are production data vs. staging vs. audit
- Backward compatibility plan: read-only legacy access during transition
- Data validation post-migration: how to verify migrated data integrity
- Incremental migration strategy: feature-by-feature vs. big-bang

### 7. Open Decisions
**Currently unresolved:**
- State derivation: exact formula for computing `Situacion` from active records
- Strict mode: what behavior changes besides captions
- Foster capacity enforcement: validate at write time or advisory only
- Report SQL security: sandbox execution vs. curated template approach
- ARIAC regulatory module: include in web app or handle externally
- Photo/attachment volume: estimated storage requirements for object storage sizing

### 8. Acceptance Checklist for Migration Documentation
**Not yet defined.** Need a checklist to validate that documentation is complete enough for web implementation.

## Affected Areas

- `docs/discovery/` — existing documentation to be augmented
- `openspec/changes/apap-migration-discovery-docs/` — SDD change workspace
- `openspec/config.yaml` — project configuration (already correct)
- `src/` — source export referenced for code-level verification (read-only)

## Approaches

### Approach 1: Augment existing docs + add new dimension docs
Add missing sections to existing feature docs and create new dimension-specific docs (state machines, validations, open decisions).

**Pros:** Preserves existing structure; focused additions; reviewable diffs
**Cons:** Multiple files to edit; risk of duplication between feature and dimension docs
**Effort:** Medium

### Approach 2: Create a single migration-readiness document
Consolidate all gaps into one comprehensive `migration-readiness.md` covering all 8 dimensions.

**Pros:** Single file; complete picture; easy to review
**Cons:** Very large file; hard to maintain; duplicates existing feature-level detail
**Effort:** Low

### Approach 3: Feature-augment + supporting docs
Augment each feature doc with missing detail, then create supporting docs for cross-cutting concerns (open decisions, acceptance checklist, data model completeness).

**Pros:** Feature-level detail stays with the feature; cross-cutting concerns separated; maintainable
**Cons:** More files to create; needs coordination to avoid gaps
**Effort:** Medium-High

## Recommendation

**Approach 3** (Feature-augment + supporting docs) is recommended because:

1. The existing feature docs are well-structured and should be the source of truth per feature
2. Cross-cutting concerns (open decisions, acceptance checklist, state machines) belong in separate docs
3. The cognitive-doc-design skill recommends progressive disclosure — feature detail stays local, cross-cutting summary stays separate
4. This approach produces the smallest reviewable diffs per document

### Specific additions needed

**Augment existing feature docs:**
- Feature 01: Add state derivation formula, ARIAC rules, search behavior
- Feature 02: Add foster capacity rules, Cesión por Propietario detail, batch intake staging
- Feature 03: Add date validation details, puppy-test logic, batch staging rules
- Feature 04: Add contract template conditionals, quarterly report aggregation, report SQL validation

**Create new supporting docs:**
- `open-decisions.md` — 6 unresolved decisions with owner and deadline
- `acceptance-checklist.md` — migration-readiness validation criteria
- `data-model-completeness.md` — auxiliary tables, catalog tables, constraints
- `state-machines.md` — all state machines across features (animal, foster home, contract, health, adoption follow-up)

## Risks

- **Incomplete state derivation logic:** The exact formula for computing `Situacion` from active records is not fully documented; may require code inspection
- **Hidden business rules:** Access forms may contain business logic not visible in documentation; source code review needed for validation rules
- **Data volume unknowns:** Attachment storage requirements and health action growth rate not estimated
- **Regulatory uncertainty:** ARIAC/RIAC requirements need stakeholder confirmation for web app scope

## Ready for Proposal

**Yes** — the exploration is complete enough to proceed to proposal. The orchestrator should tell the user:

> Exploration complete. The documentation has good coverage of business features (4 feature docs, risk register, data model notes). Key gaps are: (1) auxiliary/catalog tables not documented, (2) state machines only cover animal lifecycle, not foster home or contract states, (3) validation rules incomplete, (4) 6 open decisions unresolved, (5) no acceptance checklist for migration readiness. Recommended next step: proposal to augment existing docs and create supporting docs for cross-cutting concerns. Ready to proceed?
