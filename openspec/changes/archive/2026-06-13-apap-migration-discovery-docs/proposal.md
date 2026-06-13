# Proposal: APAP Migration Discovery Documentation

## Intent

APAP has 12 discovery docs with good feature coverage but critical gaps: auxiliary tables undocumented, state machines incomplete, validations partial, 6 open decisions unresolved, no acceptance checklist. This fills gaps for migration-ready business documentation.

## Scope

### In Scope

- Augment feature docs 01–04 via Dysflow read-only source inspection
- Create `open-decisions.md` — 6 unresolved decisions with owner/deadline
- Create `acceptance-checklist.md` — migration-readiness validation per feature
- Create `data-model-completeness.md` — auxiliary/catalog tables, FK/constraints
- Create `state-machines.md` — foster home, contract, health, adoption follow-up states
- Update `migration-risks.md` — data migration scope, backward compatibility
- Update `business-feature-map.md` — reference new cross-cutting docs

### Out of Scope

- Web application implementation
- Access UI/admin/navigation mechanics as product features
- Secrets, binaries, `.accdb` commits
- Data writes via Dysflow

## Capabilities

### New Capabilities

- `migration-discovery-docs`: Cross-cutting business documentation for web migration

### Modified Capabilities

None.

## Approach

Feature-augment + supporting docs. Augment each feature doc via Dysflow read-only inspection. Create 4 cross-cutting docs. Business rules only — Access details excluded unless affecting migration risk.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `docs/discovery/feature-01-animal-lifecycle.md` | Modified | State derivation, ARIAC rules, search behavior |
| `docs/discovery/feature-02-intake-foster-adoption.md` | Modified | Foster capacity, Cesión detail, batch staging |
| `docs/discovery/feature-03-health-care.md` | Modified | Date validation, puppy-test, batch staging |
| `docs/discovery/feature-04-documents-contracts-reports.md` | Modified | Contract conditionals, quarterly report aggregation |
| `docs/discovery/migration-risks.md` | Modified | Data migration scope, backward compatibility |
| `docs/discovery/business-feature-map.md` | Modified | Reference new cross-cutting docs |
| `docs/discovery/open-decisions.md` | New | 6 unresolved decisions with owners |
| `docs/discovery/acceptance-checklist.md` | New | Migration-readiness validation |
| `docs/discovery/data-model-completeness.md` | New | Auxiliary/catalog tables, constraints |
| `docs/discovery/state-machines.md` | New | All state machines across features |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Incomplete state derivation logic | Medium | Dysflow read-only source inspection |
| Hidden business rules in forms | Medium | Systematic source inspection per feature |
| Data volume unknowns | Low | Document as open decision |
| ARIAC regulatory uncertainty | Medium | Document as open decision; stakeholder input |

## Rollback Plan

Documentation-only. Revert via `git checkout` or delete files. No data/binary impact.

## Dependencies

- Dysflow MCP (read-only) for source inspection
- Existing `docs/discovery/` structure

## Success Criteria

- [ ] All 4 feature docs augmented with validated details
- [ ] 4 new cross-cutting docs created and cross-referenced
- [ ] Each doc verified against legacy source via Dysflow
- [ ] `business-feature-map.md` updated with new references
- [ ] Open decisions documented with owner and resolution
- [ ] Acceptance checklist covers all 4 features
