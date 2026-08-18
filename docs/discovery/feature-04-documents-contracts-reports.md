# Feature 04 — Documents, Contracts & Reports

Cross-cutting capabilities for managing attachments, generating contracts, maintaining material catalogs, and producing reports.

## 4.1 Attachments (Anexos)

### What the system does

Stores file attachments linked to any major entity in the system. Each attachment has metadata and a file reference.

### Supported entity links

| Entity | Link field |
|--------|------------|
| Animal | NChip |
| Intake | IDEntrada |
| Foster Home | — |
| Foster Stay | IDAcogida |
| Health Action | — |
| Adoption | IDAdopcion |
| Therapy | — |
| Recommendation | — |

### Attachment data

| Field | Purpose |
|-------|---------|
| Title | Descriptive name; unique per entity type |
| File path | Reference to stored file |
| Description | Additional context |
| Entity references | Which entity this attachment belongs to |

### Health attachment mode

| Mode | Rule |
|------|------|
| Health history | Aggregates all health-related attachments for a single animal view |

## 4.2 Contracts

### What the system does

Generates and manages legal documents for various workflows. Templates are species-specific and include conditional clauses.

### Contract types

| Type | Workflow | Description |
|------|----------|-------------|
| Entrada | Intake | Intake/entry contract |
| Acogida | Foster | Foster care agreement |
| Acogida Judicial | Foster | Judicial foster care agreement |
| Adopción | Adoption | Adoption contract |
| PreAdopción | Adoption | Pre-adoption agreement; runtime registry selects `CONTRATO DE ADOPCIÓN_V02.docx` (shared with Adopción, `Entorno.cls` L793); filled by `RellenarContratoPreAdopcion` (`Plantilla.cls` L620-689) — no runtime timer | <!-- alantyle-ignore:ALAN003 -->
| Cesión por Propietario | Intake | Owner surrender/handoff agreement |
| Reserva de Adopción | Adoption | Adoption reservation |
| Entrega a Propietario | Return | Return to owner contract |

### Contract lifecycle

| Step | Rule |
|------|------|
| 1. Select template | Choose from species-specific templates |
| 2. Generate document | Fill template with entity data |
| 3. Save pending signature | Store unsigned version |
| 4. Register signed contract | Record in `TbContratosAnexos` once signed |

### Business rules

| Rule | Detail |
|------|--------|
| One per type | One contract per type per entity |
| Species-specific | Templates differ by species (CANINA / FELINA) |
| Sex-dependent | Sterilization clause included/excluded based on animal's sex |
| Pre-adoption | Sex-conditional sterilization text (template text only; `RellenarContratoPreAdopcion` L620-689 fills the contract; no runtime timer in src) |

### Contract conditional clauses by type

| Contract type | Species conditional | Sex conditional | Age conditional | Other conditionals |
|---------------|--------------------|-----------------|-----------------|--------------------|
| Entrada | Species-specific template | — | — | — |
| Acogida | Species-specific template | — | — | — |
| Acogida Judicial | Species-specific template | — | — | Judicial oversight clauses |
| Adopción | Species-specific template | Sterilization clause if animal > 6 months | — | — |
| PreAdopción | Species-specific template | — | Sex-conditional sterilization text (template text only; `RellenarContratoPreAdopcion` L620-689) | — |
| Cesión por Propietario | Species-specific template | — | — | Surrender terms |
| Reserva de Adopción | Species-specific template | — | — | Reservation window |
| Entrega a Propietario | Species-specific template | — | — | Return conditions |

> The 20-day decision clause belongs to foster contracts (`Plantilla.cls`, `RellenarContratoAcogida`, L381-391), not pre-adoption. The runtime registry (`Entorno.cls` L793) selects the same `CONTRATO DE ADOPCIÓN_V02.docx` for both Adopción and PreAdopción; `RellenarContratoPreAdopcion` (`Plantilla.cls` L620-689) contains no one-month or other automatic timer. <!-- alantyle-ignore:ALAN003 -->

#### Evidence Source

- **Table:** `TbContratosAnexos`, contract template files
- **Dysflow tool:** `get_schema`
- **Verified:** [x]

## 4.3 Materials

### What the system does

Catalogs physical items used in foster care, adoption, and animal care operations.

### Material data

| Field | Purpose |
|-------|---------|
| IDMaterial | Unique identifier |
| Material | Item name |
| Color | Color attribute |
| Tamaño (Size) | Size attribute |
| Observaciones | Notes |

### Business rules

| Rule | Detail |
|------|--------|
| Uniqueness | Material + Tamaño + Color must be unique |
| Search | Filterable by material name, color, size |
| Export | Exportable to spreadsheet |

## 4.4 Custom Reports

### What the system does

Users can define, save, and execute custom SQL reports.

### Report definition

| Field | Purpose |
|-------|---------|
| IDInforme | Unique identifier |
| Nombre | Report name |
| Descripcion | Description |
| SQL | SQL query defining the report |

### Report lifecycle

| Step | Rule |
|------|------|
| Define | User creates SQL-based report definition |
| Test | Execute against database to verify |
| Export | Results exportable to spreadsheet |

### Dynamic reports as business capability

| Aspect | Detail |
|--------|--------|
| Business value | Users define custom queries to answer ad-hoc operational questions |
| Scope | Report SQL stored in database; executed on demand |
| Security model | **Open question:** Which tables/operations are forbidden for user-defined reports? |
| SQL sandbox | Report SQL must be validated before execution; prevent injection and unauthorized access |
| Safe redesign notes | Web app should use parameterized queries, curated query templates, or a query builder instead of raw SQL |

#### Migration risk

The legacy system stores arbitrary SQL in the database and executes it directly. This is a significant security risk. The web app must implement one of:
1. **Curated templates:** Pre-defined report templates with parameterized inputs
2. **Query builder:** Visual query builder that generates safe SQL
3. **Sandboxed execution:** Validate report SQL against an allow-list of tables and operations

#### Evidence Source

- **Table:** Custom report definition table
- **Dysflow tool:** `get_schema`
- **Verified:** [x]

## 4.5 Quarterly Report (Informe Trimestral)

### What the system does

Formal association activity report generated per quarter. Provides a structured summary of association operations.

### Report sections

| Section | Content | Data source | Calculation |
|---------|---------|-------------|-------------|
| Census | Current animal population by species | `TbAnimales` active records | COUNT by `Especie` where no death date |
| Movements | Intake, foster, adoption, return, death counts for the period | `TbEntradas`, `TbAcogidaAnimal`, `TbAdopcion`, `TbAnimales` | COUNT by type within quarter date range |
| Incidents | Notable events or issues | Free-form or linked records | Manual entry or event-based |
| Additional data | Supplementary statistics | Various tables | Aggregated metrics |

### Species breakdown

All sections broken down by:
- CANINA (dogs)
- FELINA (cats)

### Quarterly report data sources

| Data point | Source table(s) | Filter |
|------------|-----------------|--------|
| Census (current population) | `TbAnimales` | `FDefuncion IS NULL` grouped by `Especie` | <!-- alantyle-ignore:ALAN003 -->
| Intake count | `TbEntradas` | `FechaEntrada` within quarter |
| Foster count | `TbAcogidaAnimal` | `FInicio` within quarter |
| Adoption count | `TbAdopcion` | `FAdopcion` within quarter |
| Return count | `TbAdopcion` | `FDevolucion` within quarter |
| Death count | `TbAnimales` | `FDefuncion` within quarter |
| Euthanasia count | `TbAnimales` | `Eutanasia*` flags set within quarter |

**Migration note:** The quarterly report aggregates data from multiple tables by date range and species. The web app should implement a report-builder service that queries these sources with proper date parameters.

## Web implications

| Concern | Recommendation |
|---------|----------------|
| Object storage | All attachments, contracts, generated documents → S3-compatible storage |
| Document generation | PDF/DOCX generation library; template engine with conditional logic |
| Report definitions | Store report SQL in DB; execute via parameterized queries; never raw string concat |
| Excel/CSV export | Standard export endpoints for reports and material catalog |
| Auth roles | Report creation/execution may require specific roles |
| Quarterly report | Structured report builder; data aggregation service; PDF export |

## Legacy notes not to copy

- Contract generation uses COM automation (Word). Web app should use a document generation library.
- Custom reports use raw SQL stored in the database. Web app must use parameterized queries and validate/report definitions before execution.
- Attachment file paths reference local filesystem. Web app must use object storage with DB references.
- The quarterly report is built through coordinate-mapped form controls. Web app should use a structured report builder.
