[← Back to roadmap hub](../roadmap.md)

# Fase 7 — Documentos, Contratos, Informes y Consultas (Feature 04)

Esta página posee el estado de la Fase 7: anexos, motor de plantillas documentales, los ocho tipos de contrato, módulo de Consultas propio e informe trimestral. Fase pendiente. Depende de Fases 3–6.

## Estado

pendiente — pendiente de crear issues (uno por sub-flujo). Próximos: DOC-01..04 (#56–#59), REPORT-01..05 (#60–#64).

## Slices

| Sub-fase | Slice | Estado | Issue |
|---|---|---|---|
| 7a DOCUMENTOS | DOC-01 contract-PDF generation | pendiente | #56 |
| 7a DOCUMENTOS | DOC-02 signed-upload registration | pendiente | #57 |
| 7a DOCUMENTOS | DOC-03 polymorphic attachments | pendiente | #58 |
| 7a DOCUMENTOS | DOC-04 legacy-to-object-storage migration | pendiente | #59 |
| 7b TEMPLATES | `feat(templates): motor de plantillas y contratos` | pendiente | — |
| 7c CONSULTAS | `feat(consultas): módulo Consultas + informe trimestral` | pendiente | — |
| 7c INFORMES | REPORT-01 parameterized query builder | pendiente | #60 |
| 7c INFORMES | REPORT-02 server-side execution con export PDF/Excel | pendiente | #61 |
| 7c INFORMES | REPORT-03 quarterly report | pendiente | #62 |
| 7c INFORMES | REPORT-04 notification engine | pendiente | #63 |
| 7c INFORMES | REPORT-05 live dashboard counters | pendiente | #64 |

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
- **Eliminación solo del directorio `Firmados`, nunca de `ParaFirma`**: el legacy NO toca `ParaFirma`.
- **Informe trimestral es un módulo de primer nivel**, no un reporte embebido.

## Contributor checklist

- [ ] Si abre un slice de Fase 7, cite la sub-fase (7a/7b/7c) y la issue correspondiente.
- [ ] Si implementa el motor de plantillas o el flujo de contratos, lea primero [legacy-signed-contract-flow.md](../legacy-signed-contract-flow.md) — las reglas heredadas son no negociables.
- [ ] Si diseña el módulo de Consultas, siga el spec en [docs/discovery/feature-04-documents-contracts-reports.md](../discovery/feature-04-documents-contracts-reports.md).
- [ ] Si descubre una discrepancia entre el spec y el código VBA actual del Access, abra issue `type:bug gap:legacy` (P1).

## Navigation

Previous: [fase-6-salud-terapias-material.md](fase-6-salud-terapias-material.md) | Next: [transversales.md](transversales.md)
