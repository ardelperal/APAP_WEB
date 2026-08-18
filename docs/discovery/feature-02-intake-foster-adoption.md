# Feature 02 — Intake, Foster & Adoption

Core operational workflows: how animals enter the system, where they live, and how they find permanent homes.

## 2.1 Intake (Entrada)

### What the system does

Registers an animal entering the association's care. Captures the animal's origin, the person delivering it, intake context, and initial documentation.

### Intake data

| Category | Fields |
|----------|--------|
| Animal identity | NCHIP, animal data (name, species, sex, DOB, breed) |
| Intake event | Intake date, delivery person, DNI/contact/address |
| Pickup | Pickup location, owner status, reason for surrender |
| Veterinary | Vet info at intake |
| Financial | Donations from delivery person |
| Regulatory | RIAC registration, ARIAC communication |
| Documentation | Observations, anamnesis (medical history), physical state assessment |
| Staff | Volunteer responsible for intake (references Volunteer Registry) |

### Intake workflows

| Workflow | Description |
|----------|-------------|
| Single intake | Standard new-animal registration with full data capture |
| Entradas Múltiples | Batch intake: register multiple animals in one session with initial data staged |
| Edición (edit) | Modify intake record with change detection (compare at-start vs at-save values) |
| Búsqueda (search) | Filter by chip, name, volunteer, contract number |

### Batch intake (Entradas Múltiples) detail

| Concept | Rule |
|---------|------|
| Staging table | `TbEntradasMultiplesAuxIniciales` holds staged intake records before commit |
| Pre-commit validation | All staged records validated against business rules before batch commit |
| Validation scope | Chip uniqueness, required fields, species/sex validity, date sanity |
| Commit behavior | All-or-nothing: either all staged records commit or none do |
| Rollback | If any record fails validation, entire batch is rejected with error details |

#### Evidence Source

- **Table:** `TbEntradasMultiplesAuxIniciales`
- **Dysflow tool:** `get_schema`
- **Verified:** [x]

### Owner surrender (Cesión por Propietario)

A variant of intake where the owner formally hands over the animal. This is a distinct workflow that produces both an intake record and a surrender contract.

| Concept | Rule |
|---------|------|
| Representative data | Captures who is surrendering (may differ from original owner); includes name, DNI, contact |
| Veterinary data | Vet information at surrender (health status at handoff) |
| Contract | Generates a surrender contract document (`Cesión por Propietario` template) |
| Linked to intake | Creates an intake record linked to the surrender event |
| Animal data | Full animal identity captured (chip, species, sex, DOB, breed) |
| Observations | Free-text field for surrender context and notes |

#### Evidence Source

- **Table:** `TbEntradas`, `TbContratosAnexos`
- **Dysflow tool:** `get_schema`
- **Verified:** [x]

## 2.2 Foster Homes & Foster Stays

### Foster homes (Casa de Acogida)

Registered foster caregivers with their capacity and preferences.

| Field | Purpose |
|-------|---------|
| Address, contact info | How to reach the foster home |
| Car availability | Transport capability |
| Species preference | Which species the home accepts |
| Capacity | Number of animals the home can accept |

### Foster capacity validation

| Rule | Detail |
|------|--------|
| Capacity tracking | System tracks current occupied slots vs. max capacity per foster home |
| Species filter | Capacity check considers species preference (CANINA / FELINA) |
| Enforcement point | **Open question:** Validate at assignment time (hard block) or advisory only? |
| Over-capacity | Legacy system does not enforce capacity at write time; web app should validate on assignment |
| Capacity computation | Current count = active foster stays (`TbAcogidaAnimal`) with no end date for that home |

#### Evidence Source

- **Table:** `TbAcogidaCasa`, `TbAcogidaAnimal`
- **Dysflow tool:** `get_schema`, `query_sql`
- **Query:** `SELECT IDAcogidaCasa, COUNT(*) AS ActiveStays FROM TbAcogidaAnimal WHERE FFinal IS NULL GROUP BY IDAcogidaCasa`
- **Result:** 38 foster homes have active stays. Max active stays in a single home: 3 (IDAcogidaCasa=131). Most homes have 1–2 active stays. Capacity computation confirmed: count of rows in TbAcogidaAnimal where FFinal IS NULL, grouped by IDAcogidaCasa.
- **Verified:** [x]

### Foster stays (Acogida Animal)

Temporary placement of an animal in a foster home.

| Field | Purpose |
|-------|--------|
| Animal (NCHIP) | Which animal is placed |
| Foster home (IDAcogidaCasa) | Where the animal goes |
| Start/end dates | Duration of foster stay |
| Volunteers | Tracking volunteer, health volunteer, foster volunteer (all reference Volunteer Registry) |
| Foster type | Classification of foster arrangement |
| Contract | Foster contract generated |
| RIAC | Regulatory registration |

### Foster lifecycle

| Event | Rule |
|-------|------|
| Assignment | Animal placed with foster home; starts with a contract |
| End of foster | Returns animal to Pendiente de Nueva Situación state |
| Foster parent adoption | Foster parent may adopt the animal directly (shortcut to adoption) |
| Capacity | System should track current vs max capacity per foster home |

## 2.3 Adoption

### What the system does

Records the permanent placement of an animal with an adopter. Captures adopter identity, financial details, follow-up assignments, and contract generation.

### Adoption data

| Category | Fields |
|----------|--------|
| Adopter identity | Name, surname, DNI, address, province, contact |
| Animal | NCHIP |
| Staff | Responsible staff, follow-up volunteer(s) (reference Volunteer Registry) |
| Adoption details | Type, sterilization commitment, RIAC |
| Financial | Payment method, receipt number, donations |
| Documentation | Contract, vouchers, follow-up documents |
| Clinic | Assigned veterinary clinic |
| Follow-up tracking | Document delivered date, document attached date |

### Adoption from intake vs from foster

| Origin | Flow |
|--------|------|
| From intake | Direct adoption from shelter |
| From foster | Adoption from foster stay; foster stay ends, adoption record created |

### Foster-to-adoption state links

| Transition | State effect | Record effect |
|------------|-------------|---------------|
| Foster → Adoption | Animal: Acogida → Adoptado | Foster stay gets end date; adoption record created |
| Foster → Return | Animal: Acogida → Pendiente de Nueva Situación | Foster stay gets end date; no adoption record |
| Adoption → Return | Animal: Adoptado → Pendiente de Nueva Situación | Adoption gets return date; animal re-enters lifecycle |
| Foster parent adopts | Foster stay ends; adoption record created directly | Shortcut: skips shelter phase |

**Migration note:** State transitions must be implemented as atomic operations. The legacy system handles these across multiple form events; the web app should use a single transaction per state change.

### Volunteer Registry integration

All volunteer references across intake, foster, and adoption must resolve to the `Volunteer` entity (see `data-model-completeness.md` § "Volunteer Denormalization in Legacy"). In legacy, volunteer names are free-text strings with no stable ID. The web app replaces these with FK relationships to the Volunteer Registry.

| Workflow | Legacy field | Target behavior |
|----------|-------------|-----------------|
| Intake | `VoluntarioEntrada` (text) | FK to `Volunteer.ID` |
| Foster stay | `VoluntarioSeguimiento1/2`, `VoluntarioAcogida`, `VoluntarioCosasSanitarias` (text) | FK to `Volunteer.ID` per role |
| Adoption | `VoluntarioSeguimiento` (text), plus inline phone/email | FK to `Volunteer.ID`; contact info sourced from Volunteer record |

#### Volunteer assignment business rules

These rules are **mandatory** for all intake, foster, and adoption workflows in the target web application:

| Rule | Workflow impact |
|------|----------------|
| **No free-text assignment** | Volunteer fields accept only `Volunteer.ID` FK references. Operators cannot type a volunteer name; they must select from the registry. |
| **Active-volunteer validation** | On every create/edit of intake, foster stay, or adoption, the system validates the volunteer exists and is active. Rejected: assignment of inactive or nonexistent volunteers. |
| **No physical delete** | Volunteers referenced by any intake, foster, or adoption record cannot be deleted. Only deactivation is permitted. |
| **Historical preservation** | Deactivating a volunteer does not affect existing intake, foster, or adoption records. The FK relationship is preserved; the volunteer remains visible in historical views and reports. |

**Open decisions:** Volunteer role taxonomy (intake, follow-up, foster care, health), whether roles are attributes or a junction table, legacy deduplication strategy, and whether unreferenced volunteers may be deleted. See `open-decisions.md` Decision 7.

### Adoption lifecycle

| Event | Rule |
|-------|------|
| Registration | Creates adoption record, generates contract |
| Follow-up | Tracks whether follow-up documents have been delivered and attached |
| Return (devolución) | If adoption fails, records return date; animal re-enters lifecycle |
| Sterilization | Commitment to sterilize is recorded; may affect contract terms |

### Contract outputs per workflow

| Workflow | Contract type generated | Template |
|----------|------------------------|----------|
| Intake | Entrada | Species-specific intake template |
| Foster | Acogida | Foster care agreement template |
| Judicial foster | Acogida Judicial | Judicial foster template (additional court language) |
| Adoption | Adopción | Adoption contract template |
| Pre-adoption | PreAdopción | `CONTRATO DE ADOPCIÓN_V02.docx` (shared template with Adopción per `Entorno.cls` L793 registry); filled by `RellenarContratoPreAdopcion` (`Plantilla.cls` L620-689) with sex-conditional sterilization text and donor data — no runtime timer |
| Owner surrender | Cesión por Propietario | Surrender agreement template |
| Adoption reservation | Reserva de Adopción | Reservation template |
| Return to owner | Entrega a Propietario | Return contract template |

**Rule:** One contract per type per entity. Contract generation is species-specific (CANINA / FELINA) and includes conditional clauses based on sex and age.

## 2.4 Cross-cutting concerns

| Concern | Rule |
|---------|------|
| NCHIP central | Every workflow (intake, foster, adoption) is linked by microchip |
| RIAC | Regulatory registration appears in intake, foster, and adoption |
| Contracts | Template-generated; stored per entity; one contract per type per entity |
| Species-specific | Templates and rules vary by species (CANINA / FELINA) |
| Concurrency | Optimistic concurrency pattern: detect changes between at-start and at-save |

## Web implications

| Concern | Recommendation |
|---------|----------------|
| REST filters | Intake, foster, adoption lists need chip, name, volunteer, date range, state filters |
| Optimistic concurrency | Return version/timestamp on read; reject stale writes on update |
| Contract generation | PDF/DOCX endpoint; template engine with species/sex conditional logic |
| Blob storage | Contracts, attachments, follow-up documents → object storage |
| Foster capacity API | Real-time capacity check per foster home; available slots, species constraints |
| Batch intake | Staging endpoint for Entradas Múltiples; validate all before committing |
| Search | Unified search across intake, foster, adoption by chip, name, date, volunteer |

## Legacy notes not to copy

- Pipe-delimited return format (`status|successValue|errorValue`) is a legacy convention, not a web API pattern.
- Optimistic concurrency is implemented via comparing field values at form open vs save. Web app should use version numbers or ETags.
- Contract templates are generated via COM automation (Word). Web app should use a document generation library.
- Foster home capacity is tracked but not enforced at write time. Web app should validate capacity on assignment.
