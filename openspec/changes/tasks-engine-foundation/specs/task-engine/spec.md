# Especificación: task-engine

## Propósito

Definir el contrato común de lectura para que APAP_WEB proyecte pendientes manuales y automáticos hacia el dashboard y futuras colas operativas, sin implantar aún un workflow completo.

## Requirements

### Requirement: Contrato común de tarea

El sistema DEBE exponer cada pendiente como `TaskItem` producido por un `TaskSource`, con identificador estable, origen manual o automático, tipo de clasificación, prioridad, vencimiento opcional, estado, vínculo de dominio, responsable opcional y clave de deduplicación.

#### Scenario: Pendiente normalizado

- DADO un dominio con un pendiente documentado
- CUANDO el motor lo proyecta como tarea
- ENTONCES el resultado contiene todos los campos obligatorios del contrato
- Y conserva el vínculo que permite volver al dominio de origen

#### Scenario: Responsable no disponible

- DADO un pendiente válido sin persona responsable cerrada
- CUANDO el motor lo proyecta
- ENTONCES la tarea sigue siendo visible con responsable vacío

### Requirement: Clasificación operativa

El sistema DEBE distinguir contadores, colas de trabajo y tareas asignables, y NO DEBE mezclar sus totales como si fueran la misma unidad operativa.

#### Scenario: Separación de métricas

- DADO un mismo dominio con conteo agregado y acciones humanas
- CUANDO se generan los resúmenes
- ENTONCES el contador se informa como métrica
- Y las acciones aparecen como cola o tarea asignable, sin doble conteo

### Requirement: Fuentes del primer MVC

El sistema DEBE cubrir inicialmente solo fuentes de alta confianza: periodicidad sanitaria, seguimientos de acogida/adopción y documentación/RIAC. Otras fuentes PUEDEN añadirse después mediante nuevas `TaskSource`.

#### Scenario: Fuentes iniciales visibles

- DADO datos con una revisión sanitaria vencida, un seguimiento pendiente y un RIAC pendiente
- CUANDO se consulta el motor
- ENTONCES devuelve pendientes para esas tres familias
- Y no exige jobs, realtime ni notificaciones

### Requirement: Alimentación del dashboard

El sistema DEBE alimentar `/` con resúmenes derivados del motor sin sustituir el dashboard ni romper sus accesos operativos existentes.

#### Scenario: Dashboard con resúmenes filtrables

- DADO una persona autorizada en la home
- CUANDO existen pendientes derivados por el motor
- ENTONCES la home muestra resúmenes accionables
- Y cada resumen enlaza a una vista filtrable del dominio correspondiente

### Requirement: Compatibilidad con tareas manuales

El sistema DEBE aceptar tareas manuales dentro del mismo contrato de lectura, pero NO DEBE requerir estados avanzados, SLA, comentarios, reasignaciones ni historial completo en este cambio.

#### Scenario: Tarea manual mínima

- DADO una tarea manual creada por una persona autorizada en una fase posterior
- CUANDO se proyecta junto a tareas automáticas
- ENTONCES comparte prioridad, vencimiento, estado, vínculo y deduplicación
- Y no necesita workflow avanzado para ser listable

### Requirement: Frontera de capa de servicios

Las reglas de derivación, deduplicación, clasificación y validación DEBEN vivir en servicios del motor o de dominio. Las rutas DEBEN limitarse a autenticación, parámetros HTTP, renderizado y redirecciones.

#### Scenario: Ruta sin lógica de derivación

- DADO una ruta que necesita pendientes del dashboard o de una cola
- CUANDO responde a la petición
- ENTONCES delega la obtención y derivación en servicios
- Y no ejecuta SQL ni calcula reglas de tarea directamente

### Requirement: Señales de aceptación UAT

El sistema DEBE permitir validar en UAT que los pendientes sanitarios, seguimientos y documentación/RIAC son visibles, accionables, deduplicados y trazables a su dominio.

#### Scenario: Validación por Virginia

- DADO datos de prueba con un caso por cada fuente inicial
- CUANDO Virginia revisa la home y las colas enlazadas
- ENTONCES puede confirmar qué pendiente existe, por qué aparece y dónde actuar
- Y no observa duplicados para la misma clave de deduplicación
