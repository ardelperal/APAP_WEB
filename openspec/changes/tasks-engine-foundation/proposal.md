# Propuesta: motor común de tareas

## Intención

Issue #7 crea la base común para que APAP_WEB deje de depender de tarjetas estáticas y pueda mostrar pendientes reales. El objetivo es una bandeja operativa que unifique contadores, colas y tareas asignables sin convertir el primer MVC en un workflow completo.

## Alcance

### Incluido
- Definir el contrato `TaskItem` / `TaskSource`: origen manual o automático, prioridad, vencimiento, estado, vínculo de dominio, responsable opcional y clave de deduplicación.
- Cubrir el primer MVC con fuentes documentadas y de alta confianza: periodicidad sanitaria, seguimientos de acogida/adopción y documentación/RIAC.
- Mantener `/` como dashboard; el motor alimenta resúmenes/cards y futuras vistas de trabajo.
- Fijar criterios UAT: el usuario ve pendientes accionables, sin doble conteo y con enlaces filtrables al dominio.

### Fuera de alcance
- Automatización por jobs/cron, realtime y notificaciones.
- Workflow avanzado de estados, SLA, comentarios, reasignaciones o historial completo de tareas.
- Resolver toda la taxonomía de roles de voluntario o deduplicación legacy.
- Implementación de código en esta fase.

## Capacidades

### Nuevas capacidades
- `task-engine`: contrato común para proyectar pendientes manuales y automáticos desde dominios legacy/web hacia dashboard y colas operativas.

### Capacidades modificadas
- Ninguna: no existe spec vigente de dashboard/tareas; los specs actuales no cambian sus requisitos.

## Decisiones de producto/dominio

- La home sigue siendo bandeja de pendientes (D-02), no una copia de la UX Access.
- El legacy distingue contadores, colas y acciones humanas; el motor debe preservar esa semántica.
- Los roles de responsable deben apoyarse en `voluntarios`/`roles_voluntario`, pero el primer MVC acepta responsable opcional.
- `TaskItem` es una proyección de lectura: no debe duplicar datos de dominio antes de tiempo.

## Enfoque

Usar read model común + generadores por dominio. Cada fuente produce candidatos normalizados con deduplicación; el dashboard consume agregados y las listas consumen items filtrados. Las reglas viven en servicios, no en rutas.

## Áreas afectadas

| Área | Impacto | Descripción |
|---|---|---|
| `app/main.py` | Modificado | Sustituir cards fijas por resúmenes del motor en fase apply. |
| `app/core/` o `app/modules/tasks/` | Nuevo | Contratos y servicios de tareas. |
| `docs/decisiones-proyecto.md` | Modificado | Registrar clasificación contadores/colas/asignables. |
| `openspec/specs/task-engine/spec.md` | Nuevo | Contrato SDD de la capacidad. |

## Riesgos

| Riesgo | Prob. | Mitigación |
|---|---:|---|
| Doble conteo | Media | Separar contador, cola y tarea asignable. |
| Reglas legacy ambiguas | Media | Usar discovery primero y Dysflow si falta evidencia. |
| Sobreingeniería | Alta | Primer MVC solo lectura/proyección; sin workflow persistente. |

## Plan de reversión

Revertir el spec/diseño/tareas y, si se implementa después, restaurar las cards estáticas de `app/main.py` sin cambiar datos de dominio.

## Dependencias

- Fase 2/5 de voluntarios para responsables opcionales.
- Docs legacy/discovery de salud, acogida/adopción, RIAC y dashboard inicial.

## Criterios de éxito

- [ ] Spec `task-engine` listo para `sdd-spec` con escenarios DADO/CUANDO/ENTONCES.
- [ ] Primer slice cabe en PRs encadenadas bajo 400 líneas.
- [ ] UAT puede validar tres casos: pendiente sanitaria, seguimiento y documentación/RIAC.

## Siguiente fase recomendada

`sdd-spec`, después `sdd-design`.
