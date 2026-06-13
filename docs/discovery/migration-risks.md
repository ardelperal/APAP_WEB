# Migration Risks

Business-relevant risks identified during discovery of the legacy Access/VBA system. These affect feature design, data integrity, or security in the future web application.

## Data integrity risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| `Situacion` stored as mutable text | State can drift from actual records; manual overrides create inconsistencies | Compute state in web app from active records; never store as editable field |
| Chip change not atomic | Chip number updates may not cascade to all linked records/files | Implement chip-change saga: single transaction updates all references |
| No concurrency control | Two users editing the same record can overwrite each other | Add version numbers or ETags; reject stale writes |
| Duplicate health actions | Same action type + date can be recorded twice for an animal | Unique constraint on animal + action type + date |

## Security risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Hardcoded database password | Password embedded in VBA code; never expose in web app | Use environment variables and secret management |
| SQL concatenation in queries | Dynamic SQL built via string concatenation; injection risk | Parameterized queries and/or query builder; validate report SQL |
| Per-action passwords instead of RBAC | Button-level password checks, not role-based access | Design proper RBAC model with roles, permissions, and audit trail |

## Architecture risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| COM automation for documents | Word/Excel automation tied to Windows COM; not portable | Use cross-platform document generation library |
| Local filesystem for attachments | File paths point to local/network drives; not cloud-ready | Object storage (S3-compatible) with DB references |
| Pipe-delimited return format | Functions return `status|value|error` strings; fragile contract | REST APIs with proper HTTP status codes and JSON responses |
| Form-level business logic | Business rules embedded in form event handlers; not reusable | Extract into domain services; forms become thin UI layer |
| No API layer | All logic lives in Access forms/modules; no programmatic interface | Design REST/GraphQL API as the primary interface |

## Reporting risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Dynamic SQL reports | Users can write arbitrary SQL; injection and performance risk | Validate report definitions; use views or curated query templates; sandbox execution |
| Quarterly report via form coordinates | Report layout mapped to form control positions; fragile | Structured report builder with data aggregation service |

## Data migration considerations

| Concern | Detail |
|---------|--------|
| Text-encoded states | Several fields encode state as text; need domain catalogs/enums before migration |
| File system references | Attachment/contract files stored on local paths; must migrate to object storage |
| Historical records | Legacy data must be preserved; plan for data migration scripts |
| Backward compatibility | Consider read-only legacy access during transition period |

### Data migration scope

| Table category | Tables | Migration priority | Notes |
|----------------|--------|-------------------|-------|
| Production data | `TbAnimales`, `TbEntradas`, `TbAdopcion`, `TbAcogidaAnimal`, `TbActuacionSanitaria` | High | Core business records; must migrate fully |
| Staging/auxiliary | `TbActuacionSanitariaAux`, `TbEntradasMultiplesAuxIniciales`, `TbAuxAnimales` | Low | Transient data; migrate structure only if needed |
| Audit/history | `TbContratosAnexos`, `TbDocumentosAnexos` | Medium | Legal documents; migrate with file storage migration |
| Catalog/reference | `TbOrigenEntrada`, `TbMotivosEntrada`, `TbTamaños`, `TbNombrePruebas`, `TbPruebasPeridicidad` | High | Domain catalogs; must migrate for validation rules |
| Configuration | `TbConfiguracionBackends`, form metadata | Low | Legacy config; not needed in web app |

### Backward compatibility plan

| Aspect | Approach |
|--------|----------|
| Duration | Read-only legacy access for 3–6 months post-migration (open question on exact duration) |
| Access mode | Legacy Access database opened as read-only; no writes permitted |
| Data sync | Nightly export of new records from legacy to web app during transition |
| Cutover | Full cutover when all users migrated and legacy data is frozen |
| Rollback | Legacy database remains available as fallback during transition |

### Post-migration validation

| Validation | Approach |
|------------|----------|
| Record count | Compare row counts per table between legacy and web app |
| State consistency | Verify computed `Situacion` matches legacy `Situacion` for all animals |
| Chip integrity | Verify all chip references are consistent across migrated records |
| Date range | Verify all dates fall within valid ranges |
| FK integrity | Verify all foreign key relationships resolve correctly |

## Not migration risks (legacy implementation details)

These are noted for completeness but are not business risks:

- `FormularioClave()` per-action password checks → replaced by RBAC
- `FormularioAbierto()` open-form checks → not relevant in web
- `AjustarTamaño Me` runtime resizing → responsive design handles this
- `ColocarTituloEnFiltro` list headers → standard table components
- `Dame()` / `DameID()` lookup helpers → standard API lookups
