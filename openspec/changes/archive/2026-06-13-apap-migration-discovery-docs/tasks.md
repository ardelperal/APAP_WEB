# Tasks: APAP Migration Discovery Documentation

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 540–795 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 → PR 3 (feature-branch-chain) |
| Delivery strategy | force-chained |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Augment feature docs 01–04 + update reference docs | PR 1 | Base = feature/tracker branch; ~180–265 changed lines; Dysflow evidence inline |
| 2 | Create state-machines.md + data-model-completeness.md | PR 2 | Base = PR 1 branch; ~220–330 changed lines; new cross-cutting docs |
| 3 | Create open-decisions.md + acceptance-checklist.md | PR 3 | Base = PR 2 branch; ~140–200 changed lines; final cross-cutting docs |

## Phase 1: Feature Doc Augmentation via Dysflow Inspection

- [x] 1.1 Dysflow `get_schema` + `query_sql` inspection for `TbEntradas`, `TbAcogidaAnimal`, `TbAdopcion` — extract state derivation formula for `Situacion` field
- [x] 1.2 Augment `docs/discovery/feature-01-animal-lifecycle.md`: add state derivation logic (exact query/formula), ARIAC notification rules, search filter behavior; include Evidence Source blocks per section
- [x] 1.3 Dysflow inspection for foster home capacity enforcement, `TbEntradasMultiplesAuxIniciales` staging rules, Cesión contract details
- [x] 1.4 Augment `docs/discovery/feature-02-intake-foster-adoption.md`: add foster capacity validation rules, batch staging pre-commit validation, Cesión workflow detail; Evidence Source blocks
- [x] 1.5 Dysflow inspection for date validation logic (birth–death range), puppy-test threshold calculation, `TbActuacionSanitariaAux` batch staging
- [x] 1.6 Augment `docs/discovery/feature-03-health-care.md`: add date validation rules, puppy-test age threshold logic, batch staging validation; Evidence Source blocks
- [x] 1.7 Dysflow inspection for contract template conditionals (species/sex/age clause logic), quarterly report data sources and aggregation queries
- [x] 1.8 Augment `docs/discovery/feature-04-documents-contracts-reports.md`: add contract conditional clause table per type, quarterly report field mappings, report SQL sandbox rules; Evidence Source blocks

## Phase 2: Reference Doc Updates

- [x] 2.1 Update `docs/discovery/migration-risks.md`: add data migration scope table (production vs. staging vs. audit per table), backward compatibility plan (read-only legacy access duration), post-migration validation approach
- [x] 2.2 Update `docs/discovery/business-feature-map.md`: add cross-cutting docs section referencing state-machines.md, data-model-completeness.md, open-decisions.md, acceptance-checklist.md

## Phase 3: Cross-Cutting Doc — State Machines

- [x] 3.1 Create `docs/discovery/state-machines.md`: define animal lifecycle state machine (states, transitions, triggers) — reference Feature 01 derivation
- [x] 3.2 Add foster home status state machine (active, inactive, capacity-exceeded) with transition rules
- [x] 3.3 Add contract lifecycle state machine (draft, pending-signature, signed, expired) per contract type
- [x] 3.4 Add health action status and adoption follow-up state machines; note integration points with animal lifecycle

## Phase 4: Cross-Cutting Doc — Data Model Completeness

- [x] 4.1 Create `docs/discovery/data-model-completeness.md`: catalog auxiliary tables (`TbActuacionSanitariaAux`, `TbEntradasMultiplesAuxIniciales`, `TbAuxAnimales`) with purpose, columns, FK relationships
- [x] 4.2 Add catalog tables section (`TbOrigenEntrada`, `TbMotivosEntrada`, `TbTamaños`, `TbNombrePruebas`, `TbPruebasPeridicidad`) with valid domain values and uniqueness constraints
- [x] 4.3 Add constraint enforcement source table: for each constraint, specify DB-enforced vs. application-enforced

## Phase 5: Cross-Cutting Doc — Open Decisions

- [x] 5.1 Create `docs/discovery/open-decisions.md`: register 6 decisions (state derivation formula, strict mode, foster capacity enforcement, report SQL security, ARIAC scope, photo/attachment volume) with owner, deadline, options, and status

## Phase 6: Cross-Cutting Doc — Acceptance Checklist

- [x] 6.1 Create `docs/discovery/acceptance-checklist.md`: define per-feature migration-readiness criteria; each criterion maps to a specific doc section and is pass/fail determinable

## Phase 7: Verification

- [x] 7.1 Cross-check each augmented feature doc section against Dysflow query output — verify evidence source accuracy
- [x] 7.2 Verify all internal cross-references resolve (feature docs ↔ cross-cutting docs ↔ migration-risks ↔ business-feature-map)
- [x] 7.3 Boundary review: confirm no Access/admin mechanics appear as product features; Access notes limited to migration-risk footnotes only

## Implementation commits

| Commit | Work unit | SDD tasks | Verification | Access sync |
|---|---|---|---|---|
| _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |
