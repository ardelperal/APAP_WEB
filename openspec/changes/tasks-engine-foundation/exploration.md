# Exploración: motor común de tareas manuales y automáticas

### Estado actual
- La home actual ya funciona como bandeja operativa, pero con **tarjetas estáticas** definidas en `app/main.py` (`_DASHBOARD_PENDING_CARDS` y `_DASHBOARD_SHORTCUTS`), no con un motor de tareas.
- No existe aún una entidad o servicio de tareas en `app/`; el estado visible del dashboard se alimenta hoy de copy y navegación fijos.
- El legado y la discovery ya separan varias fuentes de pendiente: `TbFichaAnimal` (estado e incoherencias), `TbEntradas`, `TbAdopcion`, `TbAcogidaAnimal`, `TbActuacionSanitaria`, `TbTerapias`, `TbPruebasPeridicidad`, `TbNombrePruebas`, `TbContratosAnexos` y `TbRIAC`.
- La doc de decisiones ya fija que la home debe seguir siendo una bandeja operativa y que el motor de tareas es transversal (`docs/architecture/decisiones-proyecto.md` + `docs/roadmap.md` #7).
- El legacy muestra tres patrones distintos: **contadores** del dashboard inicial, **bandejas/colas** de seguimiento (salud, adopción, documentos) y **acciones asignables** ligadas a personas/roles.

### Áreas afectadas
- `app/main.py` — hoy inyecta tarjetas fijas; mañana debería consumir resúmenes derivados del motor de tareas.
- `app/modules/*` — los dominios de animal, entrada, acogida, adopción, salud, terapias, documentos y voluntarios son las fuentes reales de tarea.
- `docs/architecture/decisiones-proyecto.md` — ya contiene la decisión de producto y debe ampliarse con la clasificación de tareas/contadores/colas.
- `docs/roadmap.md` — #7 ya está registrado como slice transversal.
- `docs/discovery/feature-01-animal-lifecycle.md` — estado derivado, timeline e incoherencias.
- `docs/discovery/feature-02-intake-foster-adoption.md` — seguimientos de acogida/adopción y contratos.
- `docs/discovery/feature-03-health-care.md` + `docs/discovery/data-model-completeness.md` — periodicidad y tareas sanitarias pendientes.
- `docs/legacy-initial-dashboard.md` / `docs/legacy-health-ui-workflow.md` / `docs/legacy-lifecycle-transition-rules.md` / `docs/legacy-signed-contract-flow.md` — evidencia de los pendientes heredados.
- `docs/features/registro-de-voluntarios.md` — base para la asignación humana (roles `intake`, `seguimiento`, `acogida`, `salud`).

### Enfoques
1. **Read model común + generadores por dominio** — una capa de proyección unifica manuales y automáticas; cada dominio publica candidatos con una clave de deduplicación común.
   - Pros: encaja con la arquitectura FastAPI; permite que el dashboard consuma el mismo contrato; reduce duplicación.
   - Cons: requiere definir bien la identidad de tarea y la deduplicación entre fuentes.
   - Esfuerzo: Medio.

2. **Tabla de tareas única desde el inicio** — persistir todas las tareas manuales y automáticas en una tabla y alimentarla con jobs/reglas.
   - Pros: modelo simple para UI y asignación; fácil de listar/filtrar.
   - Cons: más riesgo de mezclar “contador”, “cola” y “tarea asignable”; puede duplicar datos de dominio demasiado pronto.
   - Esfuerzo: Alto.

### Recomendación
Empezar con **read model común + generadores por dominio**. Para el primer MVC, el motor debe ser una infraestructura de lectura y clasificación, no un sistema pesado de workflow.

**Clasificación propuesta**
- **Contadores**: incoherencias, fallecidos sin RIAC, chips pendientes, impresos por entregar, impresos entregados no recibidos, totales de seguimiento.
- **Colas de trabajo**: próximas vacunas/pruebas, analíticas pendientes, revisiones veterinarias, hitos sanitarios, documentación pendiente.
- **Tareas asignables**: seguimientos de acogida, seguimientos post-adopción, incidencias sanitarias con responsable, avisos administrativos que requieren cierre humano.

**Primer MVC**
- Crear un contrato común `TaskItem`/`TaskSource` con origen manual o automático, prioridad, vencimiento, estado, vínculo al dominio y responsable opcional.
- Incluir solo fuentes de alta confianza ya documentadas: periodicidad sanitaria, seguimientos de acogida/adopción y documentación/RIAC.
- Mantener la home como dashboard; el motor solo alimenta sus cards y las vistas de trabajo.

### Riesgos
- Doble conteo entre contadores del dashboard y tareas derivadas si no se separa bien la semántica.
- Algunas reglas legacy están repartidas en forms/queries y no en un único modelo; puede haber ambigüedad al materializar candidatos.
- La asignación humana depende de la taxonomía de voluntarios/roles, que aún no está cerrada del todo para todos los casos.
- Si se intenta cubrir demasiado en el primer MVC, el motor se convierte en un workflow completo y se pierde el objetivo de foundation.

### Listo para propuesta
Sí. El siguiente paso es `sdd-propose` para cerrar el contrato de tarea común, decidir qué entra en el primer MVC y fijar cómo se alimenta el dashboard sin sustituirlo.
