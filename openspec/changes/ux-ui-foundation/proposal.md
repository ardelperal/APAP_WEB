# Propuesta: base UX/UI de APAP

## Intención

Resolver #6 definiendo una base UX/UI profesional para APAP Web: producto autónomo, operativo desde el inicio y sin lenguaje interno. La home debe funcionar como bandeja de pendientes para Virginia y el equipo, no como portada técnica.

## Alcance

### Incluido
- Dirección visual, tokens base y patrón responsive mobile-first.
- Shell global: navegación por áreas operativas, cabecera, estados y copy visible.
- Home interna con tarjetas de pendientes, accesos a módulos y estados normal/pendiente/crítico/vacío.
- Contrato de componentes base: tarjetas, badges, botones, formularios, alertas y tablas/listados.
- Criterios de accesibilidad y preparación UAT para validar la experiencia.

### Excluido
- API real de contadores en tiempo real (#64 / dashboard posterior).
- Implementación completa de módulos aún pendientes: acogidas, adopciones, salud, terapias, documentos, material.
- Landing pública comercial o clon visual del Access.

## Capacidades

### Nuevas capacidades
- `ux-ui-foundation`: base visual, navegación, componentes, copy y estados de UI para APAP Web.

### Capacidades modificadas
- Ninguna. `intake-entries` conserva su contrato funcional; solo heredará el shell visual cuando se implemente.

## Enfoque

Aplicar el enfoque recomendado en exploración: diseño propio + shell incremental. Access aporta reglas, contadores y prioridades operativas; la web rediseña la experiencia. Supuestos: las áreas futuras pueden mostrarse como destinos preparados si no prometen funcionalidad activa; Animal sigue siendo el pivote aunque la navegación sea por trabajo.

## Áreas afectadas

| Área | Impacto | Descripción |
|---|---|---|
| `app/templates/base.html` | Modificado | Shell, navegación, cabecera y pie. |
| `app/templates/index.html` | Modificado | Dashboard operativo y estados de tarjetas. |
| `app/templates/login.html`, `unauthorized.html`, `admin.html` | Modificado | Coherencia visual. |
| `app/static/css/output.css` | Modificado | Tokens y utilidades visuales. |
| `tests/test_pages.py` | Modificado | Contratos de copy, navegación y dashboard. |
| `docs/decisiones-proyecto.md` | Referencia | D-01, D-02, D-10, D-11, D-12. |

## Riesgos

| Riesgo | Prob. | Mitigación |
|---|---|---|
| Navegación promete módulos no listos | Media | Estados/descripciones claras sin enlaces rotos. |
| Copiar demasiado el Access | Media | Usar legacy solo como semántica operativa. |
| Diff >400 líneas | Media | Dividir en PRs encadenadas. |

## Plan de rollback

Revertir los commits de shell/templates/CSS/tests de la cadena `ux-ui-foundation`; no hay migración de datos.

## Dependencias

- Issue #6, `docs/legacy-initial-dashboard.md`, `docs/decisiones-proyecto.md`, `docs/discovery/*`.

## Criterios de éxito

- [ ] Home como panel operativo con tarjetas y accesos.
- [ ] Navegación cubre áreas operativas documentadas.
- [ ] UI sin términos internos, históricos ni stack técnico.
- [ ] Estados normal/pendiente/crítico/vacío definidos y testeables.
- [ ] Criterios UAT listos para validación de usuario.
