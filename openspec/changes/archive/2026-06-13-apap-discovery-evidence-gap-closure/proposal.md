# Proposal: APAP Discovery Evidence Gap Closure

## Intent

The previous SDD change `apap-migration-discovery-docs` archived with PASS WITH WARNINGS. Two warnings remain: (W-1) six evidence source gaps in discovery docs that need Dysflow live validation, and (W-2) acceptance checklist verification summary with empty pass/fail columns. This change closes those gaps by running Dysflow read-only queries, updating docs with validated evidence, and filling the checklist.

## Scope

### In Scope
- Run Dysflow `get_schema` against `TbAuxAnimales` to validate schema/purpose
- Run Dysflow `query_sql` SELECT DISTINCT against `TbOrigenEntrada`, `TbMotivosEntrada`, `TbTamaños` to enumerate catalog values
- Run Dysflow `query_sql` to validate foster capacity query (active foster stays count per home)
- Run Dysflow `query_sql` to validate date validation join (health action date vs animal birth/death)
- Run Dysflow `query_sql` to validate puppy-test threshold logic (DATEDIFF calculation)
- Run Dysflow `get_relationships` to validate FK enforcement across key tables
- Update `data-model-completeness.md` with validated evidence source blocks
- Update `feature-02-intake-foster-adoption.md` with foster capacity evidence
- Update `feature-03-health-care.md` with date validation and puppy-test evidence
- Fill acceptance checklist verification summary pass/fail columns
- Phase 6 — Lifecycle Event Timeline: update `feature-01-animal-lifecycle.md` with mandatory timeline and location traceability section; update `state-machines.md` with audit trail requirement; add acceptance checklist criteria 1.11–1.15; update `open-decisions.md` Decision 1
- Phase 7 — Volunteer Registry: document Volunteer entity model in `data-model-completeness.md`; add Volunteer Registry foundation section to `business-feature-map.md`; update feature docs 02 and 03 with FK relationships; add acceptance checklist criteria CC.11–CC.14
- Phase 8 — Volunteer Business Rules: add 5 mandatory rules (FK-only, active validation, no physical delete, historical preservation, unreferenced deletion) to `data-model-completeness.md`; update feature docs 02 and 03 with enforcement rules; update `open-decisions.md` Decision 7; add acceptance checklist criteria 2.10, 3.9, CC.15, CC.16

### Out of Scope
- Any writes to the Access database
- Web implementation or code changes
- Access/admin mechanic documentation
- Open decision resolution (tracked separately)

## Capabilities

### New Capabilities
None — this is evidence gap closure against existing documentation.

### Modified Capabilities
- `migration-discovery-docs`: Evidence source blocks updated from `[ ] — needs live validation` to `[x]` with actual Dysflow query results; acceptance checklist verification summary filled.

## Approach

1. Execute Dysflow read-only queries against the live Access backend for each gap item
2. Record query results and schema inspection findings
3. Update the relevant discovery docs with validated evidence source blocks
4. Fill the acceptance checklist verification summary table
5. Cross-check all updates for consistency

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `docs/discovery/data-model-completeness.md` | Modified | TbAuxAnimales schema, catalog domain values, FK enforcement evidence |
| `docs/discovery/feature-02-intake-foster-adoption.md` | Modified | Foster capacity query evidence source |
| `docs/discovery/feature-03-health-care.md` | Modified | Date validation and puppy-test evidence sources |
| `docs/discovery/acceptance-checklist.md` | Modified | Verification summary pass/fail columns filled |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Dysflow read-only tools unavailable | Low | User confirmed Dysflow runtime available |
| Query returns unexpected schema | Medium | Document findings as-is; flag discrepancies |
| Evidence blocks require format adjustment | Low | Follow existing evidence source block patterns |

## Rollback Plan

Git revert of the single documentation commit. No database changes involved.

## Dependencies

- Dysflow MCP runtime available and connected
- Access backend database (`Registro_APAP_Alcala_datos_18.accdb`) accessible via Dysflow
- Previous change `apap-migration-discovery-docs` archived and specs synced

## Success Criteria

- [ ] All six evidence source gaps validated via Dysflow and marked `[x]`
- [ ] Acceptance checklist verification summary has pass/fail values
- [ ] No Access/admin mechanics documented as product features
- [ ] All cross-references between docs remain valid
