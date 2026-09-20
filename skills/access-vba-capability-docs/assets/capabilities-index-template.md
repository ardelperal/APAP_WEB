<!--
ÍNDICE DE CAPACIDADES — registro maestro para navegación.
Vive en docs/capabilities/index.md (o la ruta del AGENTS.md del proyecto). Una fila por capacidad.
Una IA lee ESTO primero para encontrar una capacidad y luego abre su documento.
Mantenlo sincronizado siempre que se añada, retire o cambie de tier/estado/confianza una capacidad.
Idioma: castellano de España. Los enums (tier/status/source/confianza) se mantienen tal cual.
-->

# Índice de capacidades

> Recordatorio de fuente de verdad: código + tests de Dysflow. Este índice es un mapa, no evidencia.

| ID capacidad | Nombre | Dominio | Tier | Estado | Source | Confianza global | ¿Pruebas en verde? | ¿Migración lista? (§3/§6/§8) | Última release de producción | Documento |
|---|---|---|---|---|---|---|---|---|---|---|
| CAP-001 | <nombre de negocio> | <ciclo de vida/acciones/informes/...> | critical \| standard \| minimal | active \| deprecated \| broken | sdd \| reverse-engineered \| hybrid | Verified-runtime \| mixta \| Likely | <n/total reglas con test> | sí \| parcial \| no | <tag de producción o —> | [enlace](./CAP-001-<slug>.md) |

## Lagunas de cobertura (obligaciones abiertas)
> Reglas que aún no están en `Verified-runtime`. Cada una es un test que crear con `access-vba-tdd-fundamentos`.

| Capacidad | Regla | Confianza actual | Acción |
|---|---|---|---|
| CAP-001 | BR-3 | Verified-static | Crear test con access-vba-tdd-fundamentos |

## Divergencias pendientes de revisión humana
| Capacidad | Hallazgo | Detectada |
|---|---|---|
| CAP-001 | <el spec dice X, el código hace Y> | <YYYY-MM-DD> |

## Mapa de dependencias / datos (para ordenar la migración)
> Qué capacidades comparten datos o flujos. Una IA usa esto para secuenciar el porte legacy→web: migrar primero las entidades compartidas y las capacidades de las que dependen otras.

| Capacidad | Depende de | Entidades compartidas | Orden de migración sugerido |
|---|---|---|---|
| CAP-001 | <CAP-009 (tareas)> | <TbExpedientes, TbTareas> | <p. ej. 2 — después de su modelo de datos base> |
