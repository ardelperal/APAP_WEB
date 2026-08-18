# APAP Business Feature Map

Overview of business capabilities for the future web application, organized by domain. Each feature doc covers what the system does, business rules, and web implications — not how Access implements it.

## Feature index

| # | Feature | Scope | Primary entities |
|---|---------|-------|------------------|
| 01 | [Animal Lifecycle](feature-01-animal-lifecycle.md) | Master animal record, state model, chip management, search | Animal, chip, photos, state |
| 02 | [Intake, Foster & Adoption](feature-02-intake-foster-adoption.md) | Intake workflows, foster homes/stays, adoption, owner surrender | Intake, foster home, foster stay, adoption, surrender, contracts |
| 03 | [Health & Care](feature-03-health-care.md) | Health actions, therapies, recommendations, upcoming tasks | Health actions, therapies, recommendations, periodicity |
| 04 | [Documents, Contracts & Reports](feature-04-documents-contracts-reports.md) | Attachments, contract generation, materials, custom/quarterly reports | Attachments, contracts, templates, materials, reports |

## Supporting docs

| Document | Purpose |
|----------|---------|
| [Migration Risks](migration-risks.md) | Business-relevant risks from the legacy system |
| [Data Model Notes](data-model-notes.md) | Entity relationships and field inventory (reference) |
| [Inventory Baseline](inventory-baseline.md) | Source export snapshot and table inventory (reference) |

## Cross-cutting docs

| Document | Purpose |
|----------|---------|
| [State Machines](state-machines.md) | Animal lifecycle, foster home, contract, health action, and adoption follow-up state machines |
| [Data Model Completeness](data-model-completeness.md) | Auxiliary tables, catalog tables, FK/constraint documentation |
| [Open Decisions](open-decisions.md) | Unresolved decisions with owner, deadline, and resolution approach |
| [Acceptance Checklist](acceptance-checklist.md) | Migration-readiness validation criteria per feature |

## Mandatory foundation: Volunteer Registry

**The future web application must introduce a first-class Volunteer entity** with a stable identifier. In the legacy system, volunteer names are stored as free-text strings in multiple tables (intake, adoption, foster stay, therapy) with no foreign key, no deduplication, and no single source of truth for who a volunteer is.

| Principle | Requirement |
|-----------|-------------|
| First-class entity | `Volunteer` table with stable ID, name, contact info, active/inactive status |
| Relationship over free-text | Tables that currently store volunteer names as text (e.g., `VoluntarioEntrada`, `VoluntarioSeguimiento`, `VoluntarioAcogida`, `VoluntarioCosasSanitarias`) must reference `Volunteer.ID` via FK |
| Legacy deduplication | Migration must deduplicate free-text volunteer values into distinct `Volunteer` records |
| Roles as data | Volunteer roles/capabilities (intake, follow-up, foster care, health) are modeled as attributes or a role junction table, not as separate text fields per workflow |
| **FK-only references** | No workflow may assign a volunteer unless that volunteer already exists in the Volunteer Registry. Free-text assignment is prohibited. |
| **Active-volunteer validation** | Every create/edit workflow that assigns a volunteer must validate the volunteer exists and is active. |
| **No physical delete** | Volunteers referenced by any business record must not be physically deleted. Only deactivation is permitted. |
| **Historical preservation** | Deactivating a volunteer must preserve all historical FK relationships. The volunteer remains readable for reporting and audit trails. |
| **Unreferenced deletion** | Unreferenced volunteers may be deleted only if product explicitly decides. Default policy: deactivation for all. |

See `data-model-completeness.md` § "Volunteer Denormalization in Legacy" for the current state and migration impact.

## Mandatory foundation: Lifecycle Event Timeline

**Every shelter animal must have a complete, chronological, auditable event timeline** recording where the animal was at every moment and why/how it moved. This is not optional and not an open question.

| Principle | Requirement |
|-----------|-------------|
| Event log as single source of truth | A dedicated event log table stores every lifecycle event (intake, foster, adoption, return, death) with timestamps |
| No timeline gaps | Every interval between events must have a known location/arrangement; gaps are flagged as data-quality defects |
| Edge cases explicit | Multiple foster stays, returns to shelter, adoption returns, re-entries, and death as terminal event are all distinct timeline entries |
| State derived from events | Current state is ALWAYS derived from the most recent event; never stored independently |

See `feature-01-animal-lifecycle.md` § "Lifecycle Event Timeline and Location Traceability" for the full requirement and migration rules.

## Excluded from product scope

| Document | Status |
|----------|--------|
| [Admin Panel](feature-00-admin-panel.md) | Legacy Access administration area — not a product feature |

## Web application generation order

The features above are ordered for incremental web delivery:

1. **Animal Lifecycle** — foundation; all other features reference animals.
2. **Volunteer Registry** — foundation; intake, foster, adoption, and health features all reference volunteers. Must be available before Feature 02.
3. **Intake, Foster & Adoption** — core operational workflows; volunteer fields reference Volunteer entity.
4. **Health & Care** — builds on animal and intake records; therapy volunteer references Volunteer entity.
5. **Documents, Contracts & Reports** — cross-cutting; depends on all prior features.

Each feature doc includes a **Web Implications** section that maps directly to API/service design for the future web application.
