# Feature 03 — Health & Care

Tracks all health-related actions, therapy sessions, recommendations, and upcoming care tasks for animals in the system.

> **Detailed Legacy Workflow:** For the complete analysis of the legacy Access/VBA health UI (all forms, business logic, data model, and navigation flows), see [`legacy-health-ui-workflow.md`](../legacy-health-ui-workflow.md).

## 3.1 Health Actions (Actuaciones Sanitarias)

### What the system does

Records individual health events for each animal: vaccinations, deworming, sterilization, lab tests, and general health notes.

### Action subtypes

| Subtype | Description |
|---------|-------------|
| Vacuna | Vaccination record |
| Desparasitación | Deworming (internal and external) |
| Esterilización | Sterilization surgery |
| Analítica común | Standard lab test / blood work |
| Otras anotaciones | General health notes |

### Health action data

| Field | Purpose |
|-------|---------|
| NCHIP | Animal reference |
| FechaAnotacion | Date of the health action |
| Prueba | Test/procedure type |
| Resultado | Result or outcome |
| Lote | Batch/lot number (e.g., for vaccines) |
| CodVeterinario | Veterinarian code |
| TipoAnotacion | Action subtype |
| Clinica | Veterinary clinic |
| Producto | Product used |
| Title | Descriptive title |

### Validation rules

| Rule | Detail |
|------|--------|
| Date range | Must be between animal's birth date and death date (strict mode) |
| Duplicate prevention | No duplicate actions per animal + type + date |
| Batch staging | Bulk health actions are validated against same rules before commit |

#### Date validation detail

| Validation | Rule | Error behavior |
|------------|------|----------------|
| Birth date bound | `FechaAnotacion` ≥ `FNacimiento` (animal's birth date) | Reject action; display "date before birth" error |
| Death date bound | `FechaAnotacion` ≤ `FDefuncion` (if death recorded) | Reject action; display "date after death" error |
| Strict mode | Both bounds enforced when animal has death date | Hard block; no override |
| Open question | What happens when death date is unknown? Is date-after-today allowed? | Needs clarification |

#### Evidence Source

- **Table:** `TbActuacionSanitaria`, `TbFichaAnimal`
- **Dysflow tool:** `query_sql`
- **Query:** `SELECT h.NCHIP, h.FechaAnotacion, f.FNacimiento, f.FDefuncion FROM TbActuacionSanitaria AS h INNER JOIN TbFichaAnimal AS f ON h.NCHIP = f.NCHIP WHERE h.FechaAnotacion < f.FNacimiento OR (f.FDefuncion IS NOT NULL AND h.FechaAnotacion > f.FDefuncion)`
- **Result:** Existing violations found in legacy data — health actions with dates BEFORE animal birth (5+ records) and AFTER animal death (5+ records). This confirms: (1) date bounds are NOT DB-enforced, (2) legacy application enforcement is inconsistent, (3) the web app must implement strict date validation as a service-layer rule.
- **Verified:** [x]

## 3.2 Health Summary

### What the system does

Provides a per-animal dashboard showing the latest date and result for each test type.

| Concept | Rule |
|---------|------|
| Summary view | Latest action per test type for the animal |
| Coverage | All action subtypes (vaccines, deworming, tests, etc.) |
| Purpose | Quick health status overview without scrolling through full history |

## 3.3 Therapies

### What the system does

Records therapy sessions for animals. Therapies are higher-level health interventions that may generate follow-up recommendations.

### Therapy data

| Field | Purpose |
|-------|---------|
| NCHIP | Animal reference |
| Date | Session date |
| Volunteer | Responsible volunteer (FK to Volunteer Registry; see business rules below) |
| Description | Therapy description |

### Therapy volunteer business rules

| Rule | Detail |
|------|--------|
| **FK-only reference** | Therapy volunteer field MUST be a FK to `Volunteer.ID`. Free-text volunteer assignment is prohibited. |
| **Active-volunteer validation** | On create/edit of a therapy, the system validates the volunteer exists AND is active in the Volunteer Registry. Inactive or nonexistent volunteers are rejected. |
| **No physical delete** | A volunteer referenced by any therapy record cannot be deleted; only deactivation is permitted. |
| **Historical preservation** | Deactivating a volunteer does not remove or alter existing therapy records. The FK relationship is preserved for audit and reporting. |

### Business rules

| Rule | Detail |
|------|--------|
| Delete restriction | Cannot delete a therapy that has recommendations linked to it |
| Volunteer assignment | Therapy volunteer MUST reference an active volunteer in the Volunteer Registry (FK to `Volunteer.ID`); see "Therapy volunteer business rules" above |
| Recommendations | Child records under therapy; each is a dated note |

## 3.4 Recommendations

### What the system does

Stores follow-up notes under a therapy session. Each recommendation is a dated text entry tracking what should be done next.

| Field | Purpose |
|-------|---------|
| IDTerapia | Parent therapy reference |
| Date | Recommendation date |
| Text | Description of recommended action |

## 3.5 Upcoming Health Tasks

### What the system does

Computes which health actions are due based on periodicity rules by species and test type.

### Periodicity engine

| Input | Source |
|-------|--------|
| Species | Animal's species (CANINA / FELINA) |
| Test type | From `TbNombrePruebas` catalog |
| Periodicity | Months between actions, defined in `TbPruebasPeridicidad` |
| Last action date | Most recent action of that type for the animal |

### Due date calculation

```
nextDue = lastActionDate + periodicityMonths
```

### Filtering rules

| Rule | Detail |
|------|--------|
| Living animals only | Only animals without death date appear in due tasks |
| Puppy tests | Some tests only apply to dogs under 8 months |
| Species-specific | Different periodicity per species |

### Puppy-test age threshold logic

| Concept | Rule |
|---------|------|
| Applicability | Tests marked as "puppy-only" in `TbNombrePruebas` catalog |
| Age threshold | 8 months from `FNacimiento` (date of birth) |
| Calculation | If `FechaAnotacion` or current date is within 8 months of `FNacimiento`, puppy tests are eligible |
| Species scope | Dogs only (CANINA); puppy tests excluded for cats (FELINA) |
| After threshold | Once animal exceeds 8 months, puppy tests are excluded from due-task list |

#### Evidence Source

- **Table:** `TbNombrePruebas`, `TbPruebasPeridicidad`, `TbFichaAnimal`
- **Dysflow tool:** `get_schema`, `query_sql`
- **Query:** `SELECT f.NCHIP, f.FNacimiento, f.Especie, DATEDIFF('m', f.FNacimiento, Date()) AS MonthsOld FROM TbFichaAnimal AS f WHERE f.Especie = 'CANINA' AND DATEDIFF('m', f.FNacimiento, Date()) < 8`
- **Result:** Puppy-test eligibility confirmed. "Puppy" test exists in `TbNombrePruebas` with `Especie = 'canina'`. Query found 1 dog under 8 months eligible. Formula `DATEDIFF('m', FNacimiento, Date()) < 8` works against live data. Periodicity for all tests (including Puppy) is 12 months per `TbPruebasPeridicidad`.
- **Verified:** [x]

### Batch health action staging

| Concept | Rule |
|---------|------|
| Staging table | `TbActuacionSanitariaAux` holds staged health actions before commit |
| Pre-commit validation | Each staged record validated: date range, duplicate prevention, puppy-test eligibility |
| Commit behavior | All-or-nothing batch commit; any validation failure rejects entire batch |
| Data mapping | Staging records map to `TbActuacionSanitaria` on commit |
| Business batch creation | Legacy batch is a "health action batch creation" workflow: user selects animal(s), enters multiple actions, validates, then commits as a group |

#### Evidence Source

- **Table:** `TbActuacionSanitariaAux`, `TbActuacionSanitaria`
- **Dysflow tool:** `get_schema`
- **Verified:** [x]

## Web implications

| Concern | Recommendation |
|---------|----------------|
| Health action CRUD | REST endpoints per subtype; shared validation layer |
| Summary endpoint | Per-animal health summary: latest action per type |
| Therapy/recommendation module | Nested resources: `/animals/{nchip}/therapies/{id}/recommendations` |
| Due-task engine | Background job or on-demand computation; cache results for performance |
| Attachment upload | Health actions may have attached documents (lab results, certificates) |
| Batch endpoint | Bulk health action staging with pre-commit validation |
| Therapy volunteer | Therapy `Volunteer` field references Volunteer Registry (FK to `Volunteer.ID`), not free-text |
| Optional: status/due dates | If product decides, add status tracking (pending/done) and due date fields |

## Business validations

| Validation | Fields | Rule | Error behavior |
|------------|--------|------|----------------|
| Date range | FechaAnotacion, FNacimiento, FDefuncion | Must be within animal lifespan | Reject action |
| Duplicate prevention | NCHIP + TipoAnotacion + FechaAnotacion | No duplicate actions per animal + type + date | Reject action |
| Puppy-test eligibility | FNacimiento, Especie, Prueba | Puppy tests only for dogs under 8 months | Exclude from due-task list |
| Batch validation | All staged records | All records must pass before commit | Reject entire batch |
| Therapy delete restriction | IDTerapia, recommendations | Cannot delete therapy with linked recommendations | Block delete; display error |

## Legacy notes not to copy

- The legacy system uses a batch staging table (`TbActuacionSanitariaAux`) for bulk health actions. Web app should use a proper staging endpoint with validation.
- Duplicate detection is done via SQL queries at save time. Web app should use a unique constraint or domain validation.
- The periodicity engine computes due tasks on-demand in form events. Web app should pre-compute or cache for performance.
