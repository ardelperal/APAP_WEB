[← Back to README](../../README.md)

# health-data-crud-audit-2026-Q3.md

This audit documents the scope, methodology, findings, and verdict for the audit listed in the title. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto del estudio del CRUD de `actuacion_sanitaria` (HEALTH-01 / issue #50), incluyendo validación D-24, referencias a `animales`, `voluntarios` y `catalogos_pruebas`, renderizado de formularios y manejo de errores de backend, ejecutado en 2026 Q3.

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Módulo sanidad y sus dependencias de catálogos. |
| [Methodology](#methodology) | Procedimiento aplicado para revisar el CRUD. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict) | Estado final del flujo de datos sanitarios. |
| [References](#references) | Ficheros revisados y pruebas de regresión. |

## Scope

| Item | Value |
|---|---|
| Feature | HEALTH-01 — historial sanitario por animal |
| Issue | #50 |
| Datos sensibles | Historial veterinario, observaciones sanitarias, voluntario asociado y material utilizado |
| Ficheros revisados | `app/modules/sanidad/service.py`, `app/modules/sanidad/routes.py`, `app/main.py`, `app/core/domain.py`, `tests/test_sanidad.py`, `tests/test_sanidad_routes.py`, `tests/test_domain.py`, `tests/test_lifespan.py` |
| Controles principales | CSRF en formularios POST, RBAC writer en mutaciones, validación D-24, borrado lógico, logs mediante `log_safe` |
| Fecha | 2026-07-04 |

## Methodology

1. Revisión del SQL de escritura para asegurar que los parámetros del `UPDATE` se enlazan como `$2..$8` después del identificador `$1`, y que la regla D-24 usa una forma SQL ejecutable con `FROM checked_animal`.
2. Revisión del orden de arranque para que los catálogos existan antes de crear tablas de dominio con FKs a `catalogos_pruebas` y `catalogos_tipos_contrato`.
3. Revisión del límite de capas: las rutas de sanidad no importan helpers SQL de catálogos; delegan en `app.modules.sanidad.service`.
4. Separación del tratamiento de errores: `ValueError` vuelve al formulario con 422; `InsForgeError` se registra con `log_safe` y devuelve respuesta 503 en los flujos de escritura afectados.
5. Adición de pruebas de regresión para SQL, D-24, orden de bootstrap y rutas de error.

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| BLOCKER | `UPDATE` enlazaba columnas con placeholders incorrectos y referenciaba `checked_animal.fecha_alta` sin `FROM checked_animal` | fixed | SQL corregido y cubierto por pruebas de forma ejecutable y contrato D-24. |
| BLOCKER | Un backend limpio podía fallar al crear FKs de dominio antes de las tablas de catálogo | fixed | `ensure_catalogs` se ejecuta antes de `ensure_domain_schema`; tests de lifespan actualizados. |
| CRITICAL | La ruta importaba directamente `list_catalogos_pruebas`, saltándose la capa de servicio | fixed | Se añadió wrapper de servicio y las rutas delegan en `sanidad_service`. |
| CRITICAL | `InsForgeError` se trataba como validación 422 o podía escapar sin control en delete | fixed | `ValueError` y `InsForgeError` tienen ramas separadas; backend caído devuelve 503 y queda logueado. |
| MEDIUM | La recuperación por error podía volver a fallar al recargar catálogos | fixed | Carga de catálogos tolerante a fallo, con log y lista vacía como fallback. |
| MEDIUM | El CRUD gestiona datos sanitarios y necesitaba evidencia de auditoría | fixed | Este documento fija alcance, metodología, hallazgos y veredicto. |

## Verdict

PASS: el flujo de datos sanitarios queda alineado con las reglas del proyecto. Las rutas actúan como pegamento HTTP, el servicio es dueño del SQL y la validación, los formularios llevan CSRF, los logs pasan por `log_safe` y la respuesta es resiliente ante indisponibilidad de InsForge. Riesgo residual: si InsForge no está disponible, el usuario no puede guardar ni borrar actuaciones; la respuesta es 503 y debe reintentarse cuando el backend se recupere.

## References

- `app/modules/sanidad/service.py`
- `app/modules/sanidad/routes.py`
- `app/main.py`
- `app/core/domain.py`
- `tests/test_sanidad.py`
- `tests/test_sanidad_routes.py`
- `tests/test_domain.py`
- `tests/test_lifespan.py`
- AGENTS.md §1 (límite de capas), §5 (validación en servicio), §10 (CSRF), §11 (`CRITICAL_HELPERS`).
