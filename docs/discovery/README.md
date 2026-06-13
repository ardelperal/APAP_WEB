# APAP Discovery Workspace

Business discovery documentation for the future web application replacement of the legacy Access/VBA system.

## Goals

- Capture business domain, workflows, validations, and reporting needs.
- Separate business rules from Access-specific implementation details.
- Produce migration-ready documentation for a future web architecture.

## Working rule

APAP uses Dysflow as the canonical Access automation runtime. Legacy Access sync/query tooling is intentionally excluded from this project workflow.

## Current database targets

- Frontend: `Registro_APAP_Alcala_181.accdb`
- Backend: `Registro_APAP_Alcala_datos_18.accdb`
- Dysflow project id: `apap`

## Documentation index

### Business features (web application scope)

| # | Document | Description |
|---|----------|-------------|
| — | [Business Feature Map](business-feature-map.md) | Overview and generation order |
| 01 | [Animal Lifecycle](feature-01-animal-lifecycle.md) | Animal master record, state model, chip management |
| 02 | [Intake, Foster & Adoption](feature-02-intake-foster-adoption.md) | Intake workflows, foster homes/stays, adoption, surrender |
| 03 | [Health & Care](feature-03-health-care.md) | Health actions, therapies, recommendations, upcoming tasks |
| 04 | [Documents, Contracts & Reports](feature-04-documents-contracts-reports.md) | Attachments, contract generation, materials, reports |
| — | [Migration Risks](migration-risks.md) | Business-relevant risks from legacy system |

### Cross-cutting docs

| Document | Description |
|----------|-------------|
| [State Machines](state-machines.md) | Animal lifecycle, foster home, contract, health action, and adoption follow-up state machines |
| [Data Model Completeness](data-model-completeness.md) | Auxiliary tables, catalog tables, FK/constraint documentation |
| [Open Decisions](open-decisions.md) | Unresolved decisions with owner, deadline, and resolution approach |
| [Acceptance Checklist](acceptance-checklist.md) | Migration-readiness validation criteria per feature |

### Reference docs

| Document | Description |
|----------|-------------|
| [Data Model Notes](data-model-notes.md) | Entity relationships and field inventory |
| [Inventory Baseline](inventory-baseline.md) | Source export snapshot and table inventory |
| [Dysflow Notes](dysflow-notes.md) | Dysflow runtime verification notes |

### Excluded from product scope

| Document | Status |
|----------|--------|
| [Admin Panel](feature-00-admin-panel.md) | Legacy Access administration area — not a product feature |

## Web application generation order

1. **Animal Lifecycle** — foundation; all features reference animals
2. **Volunteer Registry** — foundation; intake, foster, adoption, and health features all reference volunteers
3. **Intake, Foster & Adoption** — core operational workflows; volunteer fields reference Volunteer entity
4. **Health & Care** — builds on animal and intake records; therapy volunteer references Volunteer entity
5. **Documents, Contracts & Reports** — cross-cutting; depends on all prior features
