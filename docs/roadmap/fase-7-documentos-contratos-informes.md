[← Back to roadmap hub](../roadmap.md)

# Fase 7 — Documentos, Contratos, Informes y Consultas (Feature 04)

Esta página posee el estado de la Fase 7: anexos, motor de plantillas documentales, los ocho tipos de contrato, módulo de Consultas propio e informe trimestral. Fase pendiente. Depende de Fases 3–6.

## Estado

pendiente — pendiente de crear issues (uno por sub-flujo). Próximos: DOC-01..04 (#56–#59), REPORT-01..05 (#60–#64).

## Slices

| Sub-fase | Slice | Estado | Issue |
|---|---|---|---|
| 7a documentos | DOC-01 contract-PDF generation | pendiente | #56 |
| 7a documentos | DOC-02 signed-upload registration | pendiente | #57 |
| 7a documentos | DOC-03 polymorphic attachments | pendiente | #58 |
| 7a documentos | DOC-04 legacy-to-object-storage migration | pendiente | #59 |
| 7b templates | `feat(templates): motor de plantillas y contratos` | pendiente | — |
| 7c consultas | `feat(consultas): módulo Consultas + informe trimestral` | pendiente | — |
| 7c informes | REPORT-01 parameterized query builder | pendiente | #60 |
| 7c informes | REPORT-02 server-side execution con export PDF/Excel | pendiente | #61 |
| 7c informes | REPORT-03 quarterly report | pendiente | #62 |
| 7c informes | REPORT-04 notification engine | pendiente | #63 |
| 7c informes | REPORT-05 live dashboard counters | pendiente | #64 |

## Issues abiertas relacionadas

- #56 DOC-01 contract-PDF generation.
- #57 DOC-02 signed-upload registration.
- #58 DOC-03 polymorphic attachments.
- #59 DOC-04 legacy-to-object-storage migration.
- #60–#64 REPORT-01..05.

## Issues pendientes de crear

- `feat(attachments): anexos e historial documental` (Fase 7a — depende de Fases 3–6).
- `feat(templates): motor de plantillas y contratos` (Fase 7b — depende de Fases 3–6).
- `feat(consultas): módulo Consultas + informe trimestral` (Fase 7c — depende de Fases 3–6).

## Decisiones relacionadas

- [d-05-fidelidad-legacy-superset.md](../architecture/decisiones/d-05-fidelidad-legacy-superset.md) — superset funcional, incluyendo el flujo de contratos.
- [d-21-codegraph-read-path.md](../architecture/decisiones/d-21-codegraph-read-path.md) — CodeGraph como read path (consultas parametrizadas sobre el dominio).

## Documentación de referencia

- [docs/discovery/feature-04-documents-contracts-reports.md](../discovery/feature-04-documents-contracts-reports.md).
- [docs/legacy-signed-contract-flow.md](../legacy-signed-contract-flow.md) — reglas heredadas del flujo ParaFirma → Firmados.
- [docs/architecture/decisiones-proyecto.md](../architecture/decisiones-proyecto.md) § "Motor de plantillas documentales" / "Documentos generados como fuente de verdad" / "Organización de documentos y anexos" / "Flujo de contratos para firma y firmados" / "Consultas como módulo de primer nivel" / "Informe trimestral — alcance core".

## Core invariants

- **Conservar borrador en `ParaFirma` como referencia**: el legacy lo hace implícitamente ([legacy-signed-contract-flow.md §6 columna 1](../legacy-signed-contract-flow.md)).
- **Formato de subida PDF obligatorio, Word opcional**: el usuario típicamente firma y escanea a PDF.
- **Un único contrato por tipo por entidad**: `TbContratosAnexos` con la regla "solo UN contrato por tipo por entidad" ([legacy-signed-contract-flow.md §5](../legacy-signed-contract-flow.md)).
- **Reemplazo siempre con confirmación**: el legacy confirma antes de sobrescribir.
- **Eliminación solo del directorio `Firmados`, nunca de `ParaFirma`**: el legacy no toca `ParaFirma`.
- **Informe trimestral es un módulo de primer nivel**, no un reporte embebido.

## Contributor checklist

- [ ] Si abre un slice de Fase 7, cite la sub-fase (7a/7b/7c) y la issue correspondiente.
- [ ] Si implementa el motor de plantillas o el flujo de contratos, lea primero [legacy-signed-contract-flow.md](../legacy-signed-contract-flow.md) — las reglas heredadas son no negociables.
- [ ] Si diseña el módulo de Consultas, siga el spec en [docs/discovery/feature-04-documents-contracts-reports.md](../discovery/feature-04-documents-contracts-reports.md).
- [ ] Si descubre una discrepancia entre el spec y el código VBA actual del Access, abra issue `type:bug gap:legacy` (P1).

## Batería E2E

Baterías E2E con Playwright para cada sub-slice de Fase 7. Las baterías se escriben al mismo tiempo que el slice; solo se ejecutan en CI en el primer prototipo funcional y en releases ([transversales.md §Batería E2E](transversales.md)).

### 7a — Documentos y anexos

| Fichero E2E | Casos | Slice |
|---|---|---|
| `test_contratos_pdf.py` | Generar PDF desde plantilla; descargar; verificar contenido | `contratos` ❌ pendiente |
| `test_contratos_upload.py` | Upload contrato firmado; registrar en DB; verificar en lista | `contratos` ❌ pendiente |
| `test_anexos_polimorfico.py` | Adjuntar anexo a cesión, adopción, acogida; verificar linking correcto | `anexos` ❌ pendiente |
| `test_legacy_storage_migration.py` | Migrar archivo legacy; verificar acceso vía object storage | `migración` ❌ pendiente |
| `test_contratos_auth.py` | 302 sin sesión, 403 reader en POST/PATCH | `contratos` ❌ pendiente |

### 7b — Motor de plantillas

| Fichero E2E | Casos | Slice |
|---|---|---|
| `test_template_engine.py` | Renderizar plantilla con variables; verificar PDF generado | `templates` ❌ pendiente |
| `test_template_variants.py` | Renderizar variantes (Cesión, Adopción, Acogida); verificar campos correctos | `templates` ❌ pendiente |

### 7c — Consultas y módulo propio

| Fichero E2E | Casos | Slice |
|---|---|---|
| `test_consultas_module.py` | Listado de consultas; crear; editar; soft-delete | `consultas` ❌ pendiente |
| `test_consultas_auth.py` | 302 sin sesión, 403 reader en POST | `consultas` ❌ pendiente |

### Informes (REPORT-01..05)

| Fichero E2E | Casos | Slice |
|---|---|---|
| `test_report_builder.py` | Query builder con plantilla curada; ejecutar; verificar resultado | `reports` ❌ pendiente |
| `test_report_export.py` | Ejecutar informe; exportar PDF; exportar Excel | `reports` ❌ pendiente |
| `test_report_trimestral.py` | Generar informe trimestral; verificar datos agregados; charts | `reports` ❌ pendiente |
| `test_notification_engine.py` | Registrar notificación; verificar envío (o cola) al llegar fecha límite | `tasks` ❌ pendiente |
| `test_dashboard_counters.py` | Verificar que los contadores del dashboard reflejan el estado real de la DB | `dashboard` ❌ pendiente |

**Total pendiente:** 15 ficheros E2E para Fase 7.

## Navigation

Previous: [fase-6-salud-terapias-material.md](fase-6-salud-terapias-material.md) | Next: [transversales.md](transversales.md)
