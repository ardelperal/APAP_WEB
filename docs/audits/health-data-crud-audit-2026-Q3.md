# Auditoría: CRUD de datos sanitarios — 2026 Q3

**Scope**: HEALTH-01 / issue #50 — creación, edición, consulta y borrado lógico de `actuacion_sanitaria`, incluyendo validación D-24, referencias a `animales`, `voluntarios` y `catalogos_pruebas`, renderizado de formularios y manejo de errores de backend.

**Methodology**: revisión del flujo ruta → servicio → InsForge; pruebas de regresión sobre SQL de `UPDATE`, contrato D-24 y rutas HTTP; comprobación de bootstrap en backend limpio; revisión de recuperación ante fallos de catálogo y errores `InsForgeError`.

**Date**: 2026-07-04

**Verdict**: **PASS con seguimiento operativo**. El CRUD mantiene la validación de negocio en la capa de servicio, evita SQL directo desde rutas, diferencia errores de validación frente a caída del backend y documenta los riesgos residuales de disponibilidad.

---

## Scope

| Item | Value |
|---|---|
| Feature | HEALTH-01 — historial sanitario por animal |
| Issue | #50 |
| Datos sensibles | Historial veterinario, observaciones sanitarias, voluntario asociado y material utilizado |
| Ficheros revisados | `app/modules/sanidad/service.py`, `app/modules/sanidad/routes.py`, `app/main.py`, `app/core/domain.py`, `tests/test_sanidad.py`, `tests/test_sanidad_routes.py`, `tests/test_domain.py`, `tests/test_lifespan.py` |
| Controles principales | CSRF en formularios POST, RBAC writer en mutaciones, validación D-24, borrado lógico, logs mediante `log_safe` |

## Methodology

1. Se revisó el SQL de escritura para asegurar que los parámetros del `UPDATE` se enlazan como `$2..$8` después del identificador `$1`, y que la regla D-24 usa una forma SQL ejecutable con `FROM checked_animal`.
2. Se revisó el orden de arranque para que los catálogos existan antes de crear tablas de dominio con FKs a `catalogos_pruebas` y `catalogos_tipos_contrato`.
3. Se revisó el límite de capas: las rutas de sanidad no importan helpers SQL de catálogos; delegan en `app.modules.sanidad.service`.
4. Se separó el tratamiento de errores: `ValueError` vuelve al formulario con 422; `InsForgeError` se registra con `log_safe` y devuelve respuesta 503 en los flujos de escritura afectados.
5. Se añadieron pruebas de regresión para SQL, D-24, orden de bootstrap y rutas de error.

## Findings

| Severity | Finding | Mitigation | Status |
|---|---|---|---|
| BLOCKER | El `UPDATE` enlazaba columnas con placeholders incorrectos y referenciaba `checked_animal.fecha_alta` sin `FROM checked_animal`. | SQL corregido y cubierto por pruebas de forma ejecutable y contrato D-24. | Cerrado |
| BLOCKER | Un backend limpio podía fallar al crear FKs de dominio antes de las tablas de catálogo. | `ensure_catalogs` se ejecuta antes de `ensure_domain_schema`; tests de lifespan actualizados. | Cerrado |
| CRITICAL | La ruta importaba directamente `list_catalogos_pruebas`, saltándose la capa de servicio. | Se añadió wrapper de servicio y las rutas delegan en `sanidad_service`. | Cerrado |
| CRITICAL | `InsForgeError` se trataba como validación 422 o podía escapar sin control en delete. | `ValueError` y `InsForgeError` tienen ramas separadas; backend caído devuelve 503 y queda logueado. | Cerrado |
| WARNING | La recuperación por error podía volver a fallar al recargar catálogos. | Carga de catálogos tolerante a fallo, con log y lista vacía como fallback. | Cerrado |
| WARNING | El CRUD gestiona datos sanitarios y necesitaba evidencia de auditoría. | Este documento fija alcance, metodología, hallazgos y veredicto. | Cerrado |

## Verdict

**PASS**. El flujo de datos sanitarios queda alineado con las reglas del proyecto: rutas como pegamento HTTP, servicio como dueño de SQL y validación, CSRF en formularios, logs seguros y respuesta resiliente ante indisponibilidad de InsForge. Riesgo residual: si InsForge no está disponible, el usuario no puede guardar ni borrar actuaciones; la respuesta es 503 y debe reintentarse cuando el backend se recupere.
