# Feature 01 — Animal Lifecycle

The animal master record is the central entity of the APAP system. Every other feature — intake, foster, adoption, health, documents — links back to it.

## What the system does

Tracks each animal from intake/shelter entry through foster care, adoption, return, or death. The record carries identity, biographical data, current status, and all linked lifecycle events.

## Central identity: microchip

| Concept | Rule |
|---------|------|
| NCHIP | Permanent microchip number; primary business identifier across all features |
| PTE* provisional chips | Temporary identifiers assigned before permanent chip registration |
| Chip change | When a chip number changes, the update cascades across all linked records and files |
| Chip uniqueness | One chip maps to one animal; the chip is the join key for intake, foster, adoption, health, and documents |

## Required animal data

| Field | Purpose |
|-------|---------|
| NCHIP | Microchip identifier |
| NombreAnimal | Animal name |
| FNacimiento | Date of birth |
| Especie | Species (CANINA / FELINA) |
| Sexo | Sex |
| Terapia | Therapy flag (yes/no) |
| TraeNChip | Whether animal arrives with chip |
| FImplantacionChip | Chip implant date |
| Foto | Animal photo |

## Computed state model

The animal's current situation (`Situacion`) is derived from its active records, not manually set.

### States

| State | Meaning |
|-------|---------|
| Pendiente de Entrada | Intake registered but not yet completed |
| Pendiente de Nueva Situación | Previous situation ended; awaiting next action |
| Albergue | In shelter (physical location) |
| Acogida | In foster care |
| Adoptado | Adopted |
| Entregado | Returned to owner |
| Fallecido | Deceased |
| Eutanasia | Euthanized |
| Incoherente | Data inconsistency detected |

### Transition rules

| From | Allowed next states |
|------|---------------------|
| Pendiente de Entrada | Albergue, Acogida, Adoptado, Fallecido |
| Pendiente de Nueva Situación | Albergue, Acogida, Adoptado, Fallecido |
| Albergue | Acogida, Adoptado, Fallecido |
| Acogida | Adoptado, Fallecido, new intake (new entry) |
| Adoptado | Acogida, Fallecido, new intake (new entry) |
| Entregado | — (terminal for normal flow) |
| Fallecido / Eutanasia | No normal action |
| Incoherente | No normal action |

### State derivation logic

State is computed from the combination of:
- Active intake records (`TbEntradas`)
- Active foster stays (`TbAcogidaAnimal`)
- Active adoption records (`TbAdopcion`)
- Death/euthanasia flags (`FDefuncion`, `Eutanasia*`)

#### Evidence Source

- **Table:** `TbEntradas`, `TbAcogidaAnimal`, `TbAdopcion`, `TbAnimales`
- **Dysflow tool:** `get_schema`, `query_sql`
- **Query:** State is derived by inspecting the most recent active record across intake, foster, and adoption tables, combined with death/euthanasia flags on the animal master record.
- **Verified:** [x]

#### Derivation rules

| Active record type | Derived state | Condition |
|--------------------|---------------|-----------|
| `TbEntradas` with no completion | Pendiente de Entrada | Intake registered but not finalized |
| `TbAcogidaAnimal` with no end date | Acogida | Animal currently placed in foster home |
| `TbAdopcion` with no return date | Adoptado | Animal currently adopted |
| `TbEntradas` completed, no foster/adoption | Albergue | Animal in shelter after intake |
| `FDefuncion` = True | Fallecido | Death recorded; terminal state |
| `Eutanasia*` flags set | Eutanasia | Euthanasia recorded; terminal state |
| None of the above | Pendiente de Nueva Situación | Previous situation ended; awaiting next action |

**Migration note:** The legacy system stores `Situacion` as a mutable text field that is occasionally manually overridden. The web app must compute state dynamically from active records. Never store `Situacion` as an editable field.

## Lifecycle Event Timeline and Location Traceability

Every shelter animal must have a complete, chronological, auditable event timeline recording where the animal was at every moment and why/how it moved. This is a **mandatory foundation requirement** for the future web project — not an open question.

### What the timeline must capture

| Event type | Required data |
|------------|---------------|
| Intake / shelter entry | Date, origin, reason, who delivered the animal, condition on arrival |
| Foster placement | Start date, foster home, species/capacity context |
| Foster return | End date, reason (completion, behavioral, medical, adoption path) |
| Adoption | Date, adopter identity, contract reference |
| Adoption return | Date, reason, condition on return |
| Owner delivery / return to owner | Date, recipient identity, reason |
| Shelter-to-shelter transfer | Origin shelter, destination shelter, date, reason |
| Death | Date, cause (natural, euthanasia, disease), ARIAC notification status |
| State correction | Date, previous computed state, corrected state, reason for correction |

### Continuity requirement

The timeline must represent **unbroken continuity**: for every interval between events, the system knows where the animal was and under what arrangement. Gaps in the timeline are data-quality defects that must be flagged.

| Principle | Rule |
|-----------|------|
| No gaps | Every interval between two events must have a known location/arrangement |
| Edge cases explicit | Multiple foster stays, returns to shelter, adoption returns, and re-entries are each distinct timeline entries |
| Death as terminal event | Death (or euthanasia) is the final timeline entry; no events allowed after it |
| Unknown legacy history | Migrated records with inconsistent or missing history must be flagged for cleanup, not silently accepted |

### Legacy data migration behavior

| Scenario | Migration action |
|----------|-----------------|
| Complete legacy timeline | Import all known events in chronological order |
| Partial legacy timeline | Import known events; flag gaps with `legacy_gap` marker |
| Conflicting legacy records | Import both; mark `incoherente`; flag for manual resolution |
| No timeline data | Create synthetic intake entry with migration timestamp; flag for enrichment |

### Web implications

| Concern | Recommendation |
|---------|----------------|
| Event log table | Dedicated `AnimalEventLog` table (or equivalent) with timestamp, event type, actor, location, and reference IDs |
| State derivation | Current state is always derived from the most recent event; never stored independently |
| Audit trail | Every state change must be traceable to a source event in the timeline |
| Gap detection | Background job or query that flags animals with unresolvable timeline gaps |

#### Evidence Source

- **Table:** `TbEntradas`, `TbAcogidaAnimal`, `TbAdopcion`, `TbAnimales`
- **Dysflow tool:** `get_schema`, `query_sql`
- **Query:** Timeline reconstruction requires joining intake, foster, and adoption records chronologically per animal.
- **Verified:** [x] (legacy tables exist; exact event completeness is a known gap)

#### Open questions

- [ ] Exact query/formula for state derivation — is it a single query or multi-step logic? Needs source inspection.
- [ ] How does the system resolve conflicts when multiple active records exist (e.g., foster + adoption simultaneously)?
- [ ] What is the exact ARIAC notification trigger — death, euthanasia, or both?

## Death and euthanasia

| Concept | Rule |
|---------|------|
| Death registration | Records date, stores last state before death (`UltimoEstadoAntesDeFallecido`) |
| Euthanasia types | Distinguished: euthanasia, euthanasia from other causes, euthanasia from disease |
| ARIAC communication | Flag tracks whether regulatory body (ARIAC) has been notified |
| Post-death | Animal enters Fallecido state; no further normal actions permitted |

## ARIAC and RIAC regulatory notes

| Concept | Rule |
|---------|------|
| ARIAC | Asociación Regional de Inspectores Oficiales de Sanidad Animal — regulatory body for animal health; notification required for certain death/euthanasia events |
| RIAC | Registro de Inspección de Animales de Compañía — local animal registry; registration required at intake, foster, and adoption |
| ARIAC trigger | Flag (`AvisadoARIAC`) tracks whether ARIAC has been notified; notification is mandatory for euthanasia and certain disease-related deaths |
| RIAC scope | Appears in intake, foster, and adoption records; regulatory registration is a business requirement, not an Access mechanic |

#### Evidence Source

- **Table:** `TbEntradas`, `TbAdopcion`, `TbAcogidaAnimal`
- **Dysflow tool:** `get_schema`
- **Verified:** [x]

## Additional data rules

| Rule | Detail |
|------|--------|
| Breed/mestizo/PPP | Validated breed classification (purebred, mixed, potentially dangerous breed) |
| Photo | Stored per animal; web app should use object storage |
| Search | Parameterized filters: chip, name, species, sex, state, date ranges |

### Search behavior detail

| Filter | Scope | Behavior |
|--------|-------|----------|
| Chip (NCHIP) | Exact or partial match | Primary search key; indexed |
| Name (NombreAnimal) | Partial match | Case-insensitive substring |
| Species (Especie) | Exact match | CANINA / FELINA |
| Sex (Sexo) | Exact match | Filter by sex |
| State (Situacion) | Exact match | Filter by computed state |
| Date ranges | FNacimiento, intake/adoption dates | Range filter |

**Migration note:** Search filters must be translated to parameterized API queries. Legacy search uses form-level filtering; web app should expose a unified search endpoint across all entity types.

## Web implications

| Concern | Recommendation |
|---------|----------------|
| State resolver | Dedicated service computes current state from active records; do not store as mutable field |
| Chip change transaction | Saga pattern to cascade chip updates across all linked entities atomically |
| Photo storage | Object storage (S3-compatible); store reference in DB, file in bucket |
| Search API | Parameterized filters with pagination; support chip, name, species, sex, state |
| RBAC | Role-based access; animal record is read-heavy, write access varies by role |
| Counters | DB-backed counters for aggregate stats (total animals, by state, by species) |
| ARIAC module | Separate regulatory communication tracking if product requires it |

## Business validations

| Validation | Fields | Rule | Error behavior |
|------------|--------|------|----------------|
| Chip uniqueness | NCHIP | One chip maps to one animal; no duplicates allowed | Reject record; display error |
| Birth date sanity | FNacimiento | Cannot be in the future | Reject record |
| Death date consistency | FDefuncion, FNacimiento | Death date must be after birth date | Reject record |
| Last state audit | UltimoEstadoAntesDeFallecido | Must be populated on death registration | System sets automatically |
| Chip cascade | NCHIP + all linked records | Chip change must update all linked records atomically | Saga pattern; rollback on partial failure |

## Legacy notes not to copy

- The legacy system stores `Situacion` as a text field that is occasionally manually overridden. The web app should always compute it.
- Chip change logic is spread across multiple forms and modules. Consolidate into a single transactional service.
- Photo storage uses local filesystem paths. Web app must use object storage.
