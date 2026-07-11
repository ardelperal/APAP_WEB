# Data Model Completeness

Cross-cutting reference for auxiliary, catalog, and configuration tables that are missing from the core entity documentation. Covers table purpose, key columns, relationships, and constraint enforcement source.

> **Source:** Core entities (animal, intake, adoption, foster stay, health action, therapy, recommendation, attachments, contracts) are documented in `docs/discovery/data-model-notes.md` and individual feature docs. This document covers the **remaining** tables.

## 1. Auxiliary / Staging Tables

Auxiliary tables hold transient data during batch workflows. They are not part of the production data model and are typically cleared after commit.

### TbActuacionSanitariaAux

| Aspect | Detail |
|--------|--------|
| **Purpose** | Staging table for bulk health action creation. Holds records during the batch entry workflow before validation and commit. |
| **Workflow** | Health action batch entry (Feature 03 § "Batch health action staging") |
| **Lifecycle** | Populated during batch entry → validated → committed to `TbActuacionSanitaria` → cleared |
| **Key columns** | Mirrors `TbActuacionSanitaria` structure (NCHIP, FechaAnotacion, Prueba, TipoAnotacion, etc.) |
| **Relationships** | Maps 1:1 to `TbActuacionSanitaria` on commit; no FK enforcement to production tables |
| **Commit behavior** | All-or-nothing: either all staged records commit or none do |
| **Migration priority** | Low — transient data; migrate structure only if batch workflow is replicated |

#### Evidence Source

- **Dysflow tool:** `get_schema`
- **Verified:** [x]

### TbEntradasMultiplesAuxIniciales

| Aspect | Detail |
|--------|--------|
| **Purpose** | Staging table for batch intake (Entradas Múltiples). Holds initial intake records before batch commit. |
| **Workflow** | Batch intake workflow (Feature 02 § "Batch intake detail") |
| **Lifecycle** | Populated during batch entry → validated → committed to `TbEntradas` → cleared |
| **Key columns** | Mirrors `TbEntradas` structure (NCHIP, intake data, delivery person, etc.) |
| **Relationships** | Maps to `TbEntradas` on commit; no FK enforcement to production tables |
| **Commit behavior** | All-or-nothing batch commit with pre-commit validation |
| **Validation scope** | Chip uniqueness, required fields, species/sex validity, date sanity |
| **Migration priority** | Low — transient data; migrate structure only if batch workflow is replicated |

#### Evidence Source

- **Dysflow tool:** `get_schema`
- **Verified:** [x]

### TbAuxAnimales

| Aspect | Detail |
|--------|--------|
| **Purpose** | Auxiliary animal data table holding pending health test info per animal. Stores chip reference plus flags/text for tests still outstanding. |
| **Workflow** | Health test tracking — tracks which tests are pending for an animal and displays a summary text of missing tests |
| **Key columns** | `NChip` (text/50, required), `ConFichaSanitaria` (text/50), `PruebasPendientes` (text/50), `TextoPruebasFaltan` (memo) |
| **Relationships** | Linked to `TbFichaAnimal` via `NChip`; no DB-enforced FK |
| **Migration priority** | Low — derived/auxiliary data; can be recomputed from health action history |

#### Evidence Source

- **Table:** `TbAuxAnimales`
- **Dysflow tool:** `get_schema`
- **Result:** 4 columns — `NChip` (text/50, required), `ConFichaSanitaria` (text/50), `PruebasPendientes` (text/50), `TextoPruebasFaltan` (memo). No auto-number PK; keyed by `NChip`.
- **Verified:** [x]

## 2. Volunteer Denormalization in Legacy

### Current state

Volunteer names are stored as **free-text strings** in multiple operational tables. There is no `Volunteer` entity, no stable volunteer ID, and no FK relationships. The same volunteer may appear with slightly different spellings across tables, making deduplication and reporting unreliable.

| Table | Volunteer field(s) | Purpose |
|-------|-------------------|---------|
| `TbEntradas` | `VoluntarioEntrada` | Volunteer who performed the intake |
| `TbAdopcion` | `VoluntarioSeguimiento`, `TelMovilVoluntarioSeguimiento`, `emailVoluntarioSeguimiento` | Follow-up volunteer for adoption (name + contact stored inline) |
| `TbAcogidaAnimal` | `VoluntarioSeguimiento1`, `VoluntarioSeguimiento2`, `VoluntarioCosasSanitarias`, `VoluntarioAcogida` | Follow-up volunteer(s), health volunteer, foster care volunteer |

Additionally, `TbVoluntariosParaAutorrellenables` is a legacy convenience table that stores volunteer names for auto-fill dropdowns. It is NOT a normalized entity — it exists only to populate form comboboxes.

### Problems

| Problem | Impact |
|---------|--------|
| No stable ID | Cannot reliably identify "the same volunteer" across intake, adoption, and foster records |
| No deduplication | Free-text entry allows spelling variations (e.g., "María García" vs "Maria Garcia") |
| Inline contact data | Adoption table stores phone and email of follow-up volunteer as separate columns, not linked to a volunteer record |
| No role model | Volunteer capabilities (intake, follow-up, foster care, health) are implicit in which field they appear in, not explicit attributes |

### Target model (Volunteer Registry — new feature)

The future web application MUST introduce a `Volunteer` entity as a first-class registry. This is a **new feature** not present in legacy as a normalized concept.

| Aspect | Target design |
|--------|--------------|
| Entity | `Volunteer` with stable auto-increment or UUID PK |
| Candidate fields | Name, contact phones, emails, active/inactive status, roles/capabilities, notes |
| Relationships | Intake, adoption, foster stay, and therapy tables reference `Volunteer.ID` via FK |
| Role modeling | Roles (intake, follow-up, foster care, health) as attributes or junction table — TBD |
| Migration | Legacy free-text volunteer values must be deduplicated and matched into `Volunteer` records |
| Open decisions | Exact fields, role taxonomy, import deduplication strategy — see `open-decisions.md` Decision 7 |

### Volunteer Registry business rules (target web)

These rules are **mandatory** for the target web application. They govern how volunteers are created, referenced, and maintained across all workflows.

| Rule | Detail |
|------|--------|
| **FK-only references** | No workflow or table in the target web app may use a volunteer unless that volunteer already exists in the Volunteer Registry. Free-text volunteer assignment is prohibited. All volunteer fields MUST be FK references to `Volunteer.ID`. |
| **Existence + active validation** | Any create or edit workflow that assigns a volunteer MUST validate that the referenced volunteer exists AND is in active/usable status. Inactive volunteers cannot be assigned to new records. |
| **No physical delete** | A volunteer that has been referenced by ANY business record (intake, foster stay, adoption, therapy, or any other operational table) MUST NOT be physically deleted. Such volunteers may only be deactivated (soft-deleted / marked inactive). |
| **Historical preservation** | When a volunteer is deactivated, all historical records referencing that volunteer MUST preserve the FK relationship. The volunteer record remains readable for reporting, audit trails, and historical queries even after deactivation. |
| **Unreferenced deletion** | A volunteer that has NEVER been referenced by any business record MAY be deleted, but ONLY if product explicitly decides this behavior. The default policy is deactivation for all volunteers regardless of reference status. |

#### Evidence Source

- **User clarification:** "No se va a poder utilizar un voluntario para ninguna tabla que no esté ya en el registro de voluntarios, y éstos solo se pueden dar de baja no borrar si han pertenicido a algún registro."
- **Verified:** [x]

#### Evidence Source

- **Tables:** `TbEntradas`, `TbAdopcion`, `TbAcogidaAnimal`, `TbVoluntariosParaAutorrellenables`
- **Dysflow tool:** `get_schema`
- **Result:** Volunteer fields confirmed as free-text across 3 operational tables. `TbVoluntariosParaAutorrellenables` is a combobox fill table, not a normalized entity.
- **Verified:** [x]

## 3. Catalog / Reference Tables

Catalog tables define valid domain values used across the application. They are reference data that must be migrated for validation rules to function.

### TbOrigenEntrada

| Aspect | Detail |
|--------|--------|
| **Purpose** | Catalog of animal intake origins (where the animal came from). Used in intake workflow to classify origin type. |
| **Key columns** | `Origen` (text/255) — single-column catalog; no auto-number PK |
| **Used by** | `TbEntradas.Origen` field |
| **Known values** | Acogida, Adopción, Camada, Compra, otros, Recogido de la calle, Regalo (7 values) |
| **Uniqueness** | Each origin string is unique (no duplicates in SELECT DISTINCT) |
| **Migration priority** | High — domain catalog; must migrate for intake validation |

#### Evidence Source

- **Table:** `TbOrigenEntrada`
- **Dysflow tool:** `get_schema`, `query_sql` (SELECT DISTINCT)
- **Query:** `SELECT DISTINCT Origen FROM TbOrigenEntrada`
- **Result:** 7 values — Acogida, Adopción, Camada, Compra, otros, Recogido de la calle, Regalo
- **Verified:** [x]

### TbMotivosEntrada

| Aspect | Detail |
|--------|--------|
| **Purpose** | Catalog of intake reasons (why the animal is being delivered). Used in intake workflow to classify delivery motivation. |
| **Key columns** | `Motivo` (text/255), `Especie` (text/255) — no auto-number PK; species-scoped reasons |
| **Used by** | `TbEntradas.MotivoEntrega` field |
| **Known values** | 21 distinct motives: Abandono, Agresividad, Alergia, Camada que no consigue colocar, Cambio de domicilio, De colonia de gatos, Desalojo (hacinamiento), Enfermedad del propietario, Entregados por otra Asociación, Inadaptación, Lo sacó de perrera para evitar su sacrificio, Maltrato, Motivos desconocidos, Muerte propietario, No se puede hacer cargo, Recogido en la calle, Regalo no deseado, Rescate, Retirado por la Asociación (malas condiciones), Se han cansado del animal, Separación |
| **Uniqueness** | Each reason string is unique; species column suggests reasons may be species-scoped |
| **Migration priority** | High — domain catalog; must migrate for intake validation |

#### Evidence Source

- **Table:** `TbMotivosEntrada`
- **Dysflow tool:** `get_schema`, `query_sql` (SELECT DISTINCT)
- **Query:** `SELECT DISTINCT Motivo FROM TbMotivosEntrada`
- **Result:** 21 distinct intake reasons (see list above). Column is `Motivo` (not `MotivoEntrega` as previously assumed).
- **Verified:** [x]

### TbTamaños

| Aspect | Detail |
|--------|--------|
| **Purpose** | Catalog of animal sizes. Used in animal data and material catalog. |
| **Key columns** | `tamaño` (text/255, required), `Descripcion` (text/255) — no auto-number PK |
| **Used by** | Animal size classification; `TbMateriales.Tamaño` |
| **Known values** | enano, Gigante, Grande, Mediano, Pequeño (5 values) |
| **Uniqueness** | Each size string is unique |
| **Migration priority** | High — domain catalog; must migrate for animal/material validation |

#### Evidence Source

- **Table:** `TbTamaños`
- **Dysflow tool:** `get_schema`, `query_sql` (SELECT DISTINCT)
- **Query:** `SELECT DISTINCT Tamaño FROM TbTamaños`
- **Result:** 5 values — enano, Gigante, Grande, Mediano, Pequeño
- **Verified:** [x]

### TbNombrePruebas

| Aspect | Detail |
|--------|--------|
| **Purpose** | Catalog of health test/procedure names. Used in health action recording and periodicity engine. |
| **Key columns** | `NombrePrueba` (text/50), `Especie` (text/50), `Observaciones` (memo) — no auto-number PK; composite key isNombrePrueba + Especie |
| **Used by** | `TbActuacionSanitaria.Prueba`; periodicity engine input via `TbPruebasPeridicidad` |
| **Known values** | 13 tests across species: Básico (ambos), Desparasitación Externa (ambos), Desparasitación Interna (ambos), EHR (canina), Esterilización (ambos), Heptavalente (canina), IFI (felina), LEUC (felina), Leucemia (felina), LH (canina), Puppy (canina), Rabia (ambos), Trivalente (felina) |
| **Puppy-only test** | "Puppy" test is canina-only; eligible for dogs under 8 months |
| **Uniqueness** | Composite: NombrePrueba + Especie is the effective key |
| **Migration priority** | High — domain catalog; must migrate for health action validation and periodicity engine |

#### Evidence Source

- **Table:** `TbNombrePruebas`
- **Dysflow tool:** `get_schema`, `query_sql` (SELECT DISTINCT)
- **Query:** `SELECT DISTINCT NombrePrueba, Especie FROM TbNombrePruebas`
- **Result:** 13 tests — 5 for "ambos" species, 4 canina-only, 4 felina-only. No auto-number ID column; PK is composite NombrePrueba + Especie.
- **Verified:** [x]

### TbPruebasPeridicidad

| Aspect | Detail |
|--------|--------|
| **Purpose** | Defines periodicity rules (months between actions) for health tests. Drives the upcoming-tasks engine. |
| **Key columns** | `NombrePrueba` (text/255, required), `PeridicidadEnMeses` (integer, required) — links to `TbNombrePruebas` via `NombrePrueba` string (not ID FK) |
| **Used by** | Upcoming health tasks engine (Feature 03 § "Periodicity engine") |
| **Known values** | All 12 tests have 12-month periodicity: Básico, Desparasitación Externa, Desparasitación Interna, EHR, Heptavalente, IFI, LEUC, Leucemia, LH, Puppy, Rabia, Trivalente |
| **Uniqueness** | Each test name appears once (12 rows for 12 tests) |
| **FK enforcement** | No DB-enforced FK to `TbNombrePruebas` — linked via `NombrePrueba` string only |
| **Migration priority** | High — drives the periodicity engine; must migrate for upcoming-tasks computation |

#### Evidence Source

- **Table:** `TbPruebasPeridicidad`
- **Dysflow tool:** `get_schema`, `query_sql`
- **Query:** `SELECT * FROM TbPruebasPeridicidad`
- **Result:** 12 rows — all tests have `PeridicidadEnMeses = 12`. Linked to `TbNombrePruebas` via `NombrePrueba` string, not via ID FK. No DB-enforced referential integrity on this link.
- **Verified:** [x]

## 4. Constraint Enforcement Source

For each significant constraint in the data model, this table specifies whether the constraint is enforced at the database level, the application level, or both. This is critical for migration: DB-enforced constraints must be replicated in the new schema; application-enforced constraints must be replicated in the service layer.

### Identity and uniqueness constraints

| Constraint | Table(s) | DB-enforced | Application-enforced | Migration target |
|------------|----------|-------------|---------------------|------------------|
| Chip uniqueness (one chip → one animal) | `TbFichaAnimal` | **Yes** — NCHIP is primary key (auto-number or indexed) | Yes (form validation) | DB unique constraint + app validation |
| Intake ID unique | `TbEntradas` | Likely (auto-number PK) | Yes | DB PK constraint |
| Adoption ID unique | `TbAdopcion` | Likely (auto-number PK) | Yes | DB PK constraint |
| Foster stay ID unique | `TbAcogidaAnimal` | Likely (auto-number PK) | Yes | DB PK constraint |
| Health action uniqueness (animal + type + date) | `TbActuacionSanitaria` | **No** — no compound unique index found | Yes (SQL query at save) | DB unique constraint on compound key |
| Material uniqueness (name + size + color) | `TbMateriales` | Unknown — needs inspection | Yes (form validation) | DB unique constraint on compound key |
| Contract one-per-type-per-entity | `TbContratosAnexos` | Unknown — needs inspection | Yes (form logic) | App validation + DB constraint |

### Referential integrity (foreign keys)

| Relationship | Parent → Child | DB-enforced FK | Migration target |
|--------------|----------------|----------------|------------------|
| Animal → Intake | `TbFichaAnimal.NCHIP` → `TbEntradas.NChip` | **No** — not declared in Access schema | DB FK constraint |
| Animal → Adoption | `TbFichaAnimal.NCHIP` → `TbAdopcion.NCHIP` | **No** — not declared in Access schema | DB FK constraint |
| Animal → Foster stay | `TbFichaAnimal.NCHIP` → `TbAcogidaAnimal.Nchip` | **No** — not declared in Access schema | DB FK constraint |
| Animal → Health action | `TbFichaAnimal.NCHIP` → `TbActuacionSanitaria.NCHIP` | **No** — not declared in Access schema | DB FK constraint |
| Animal → Therapy | `TbFichaAnimal.NCHIP` → `TbTerapias.NCHIP` | **Yes** — `TbFichaAnimalTbTerapias` relationship | DB FK constraint |
| Animal → Attachments | `TbFichaAnimal.NCHIP` → `TbAnexos.NChip` | **Yes** — `TbFichaAnimalTbAnexos` relationship | DB FK constraint |
| Foster home → Foster stay | `TbAcogidaCasas.IDAcogidaCasa` → `TbAcogidaAnimal.IDAcogidaCasa` | **Yes** — `TbAcogidaCasasTbAcogidaAnimal` relationship | DB FK constraint |
| Foster stay → Attachments | `TbAcogidaAnimal.IDAcogida` → `TbAnexos.IDAcogida` | **Yes** — `TbAcogidaAnimalTbAnexos` relationship | DB FK constraint |
| Foster stay → Contracts | `TbAcogidaAnimal.IDAcogida` → `TbContratosAnexos.IDAcogida` | **Yes** — `TbAcogidaAnimalTbContratosAnexos` relationship | DB FK constraint |
| Foster stay → Materials | `TbAcogidaAnimal.IDAcogida` → `TbAcogidaAnimalMaterial.IDAcogida` | **Yes** — `TbAcogidaAnimalTbAcogidaAnimalMaterial` relationship | DB FK constraint |
| Foster home → Attachments | `TbAcogidaCasas.IDAcogidaCasa` → `TbAnexos.IDAcogidaCasa` | **Yes** — `TbAcogidaCasasTbAnexos` relationship | DB FK constraint |
| Intake → Attachments | `TbEntradas.IDEntrada` → `TbAnexos.IDEntrada` | **Yes** — `TbEntradasTbAnexos` relationship | DB FK constraint |
| Intake → Contracts | `TbEntradas.IDEntrada` → `TbContratosAnexos.IDEntrada` | **Yes** — `TbEntradasTbContratosAnexos` relationship | DB FK constraint |
| Intake → Owner surrender | `TbEntradas.IDEntrada` → `TbCesionPorPropietario.IDEntrada` | **Yes** — `TbEntradasTbCesionPorPropietario` relationship | DB FK constraint |
| Adoption → Attachments | `TbAdopcion.IDAdopcion` → `TbAnexos.IDAdopcion` | **Yes** — `TbAdopcionTbAnexos` relationship | DB FK constraint |
| Adoption → Contracts | `TbAdopcion.IDAdopcion` → `TbContratosAnexos.IDAdopcion` | **Yes** — `TbAdopcionTbContratosAnexos` relationship | DB FK constraint |
| Therapy → Recommendation | `TbTerapias.IdTerapia` → `TbRecomendaciones.IDTerapia` | **Yes** — `TbTerapiasTbRecomendaciones` relationship | DB FK constraint |
| Health test → Periodicity | `TbNombrePruebas.NombrePrueba` → `TbPruebasPeridicidad.NombrePrueba` | **No** — string match only, no Access relationship | DB FK constraint |
| External deworming (parent→detail) | `TbDesparasitacionMultipleExternaPpal` → `TbDesparasitacionMultipleExternaDetalle` | **Yes** — DB relationship | DB FK constraint |
| Internal deworming (parent→detail) | `TbDesparasitacionMultipleInternaPpal` → `TbDesparasitacionMultipleInternaDetalle` | **Yes** — DB relationship | DB FK constraint |

### Business rule constraints

| Constraint | Enforcement | Migration target |
|------------|-------------|------------------|
| State derivation (Situacion computed from active records) | Application-only | Service layer: dedicated state resolver |
| Foster home capacity | Application-only (legacy); **open question** for web | Service layer + optional DB check constraint |
| Date range (health action within animal lifespan) | Application-only (form validation) | Service layer validation |
| Puppy-test eligibility (dogs under 8 months) | Application-only (form logic) | Service layer validation |
| Contract species/sex/age conditionals | Application-only (template logic) | Document generation service |
| Batch all-or-nothing commit | Application-only (transaction logic) | Service layer transaction |
| Volunteer FK-only references | Application + DB FK constraint | DB FK constraint + service-layer validation: reject any volunteer assignment where Volunteer.ID does not exist or is inactive |
| Volunteer no physical delete | Application-only (soft-delete pattern) | Service layer: deactivate (set inactive) instead of DELETE; block DELETE on referenced volunteers |
| Volunteer historical preservation | Application-only | Service layer + DB FK ON DELETE RESTRICT: deactivating a volunteer never cascades to or removes historical records |

> Pre-adoption has no runtime expiry — activity is `FDevolucion IS NULL` (`Adopcion.cls` L2047-2054). The 20-day clause is foster-contract text (`Plantilla.cls` L381-391). The runtime registry (`Entorno.cls` L793) selects the same `CONTRATO DE ADOPCIÓN_V02.docx` for both Adopción and PreAdopción; `RellenarContratoPreAdopcion` (`Plantilla.cls` L620-689) contains no one-month or other automatic timer.

### Configuration / legacy-only constraints

| Constraint | Table | Notes | Migration target |
|------------|-------|-------|------------------|
| Per-action passwords | Form-level | Legacy access control; replaced by RBAC | Do not migrate |
| Open-form checks | Form-level | Prevents duplicate form instances | Do not migrate |
| Runtime form resizing | Form-level | UI layout | Do not migrate |

## 5. Summary: Dysflow validation results

The following items were validated via Dysflow live inspection:

| Item | Status | Finding |
|------|--------|---------|
| `TbAuxAnimales` purpose and columns | **Validated** | 4 columns: NChip (text/50, required), ConFichaSanitaria, PruebasPendientes, TextoPruebasFaltan (memo). Holds pending health test info per animal. |
| `TbOrigenEntrada` domain values | **Validated** | 7 values: Acogida, Adopción, Camada, Compra, otros, Recogido de la calle, Regalo |
| `TbMotivosEntrada` domain values | **Validated** | 21 distinct intake reasons (column is `Motivo`, not `MotivoEntrega`) |
| `TbTamaños` domain values | **Validated** | 5 values: enano, Gigante, Grande, Mediano, Pequeño |
| `TbNombrePruebas` catalog | **Validated** | 13 tests across species (ambos/canina/felina). No auto-number PK; composite key is NombrePrueba + Especie. "Puppy" test is canina-only. |
| `TbPruebasPeridicidad` rules | **Validated** | 12 rows — all tests have 12-month periodicity. Linked via NombrePrueba string, no DB-enforced FK. |
| FK enforcement | **Validated** | 17 DB-enforced relationships found. Critical gap: main animal→event FKs (intake, adoption, foster, health action) are NOT DB-enforced — only therapy, attachments, contracts, and deworming parent→detail are enforced. |
| Chip uniqueness constraint | **Validated** | NCHIP is primary key in TbFichaAnimal (DB-enforced) |
| Health action compound uniqueness | **Not found** | No compound unique index on NCHIP + TipoAnotacion + FechaAnotacion — enforcement is application-only |
