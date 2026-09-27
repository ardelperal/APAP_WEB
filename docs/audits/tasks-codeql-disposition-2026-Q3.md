[← Volver a la guía del código](../CODEBASE-GUIDE.md)

# Disposición de las alertas CodeQL del módulo tareas — 2026 Q3

## Alcance

Se revisan las seis alertas CodeQL abiertas contra el slice de tareas
(`app/modules/tasks/routes.py`), agrupadas en dos familias:

| Alerta | Regla | Sitio |
|---|---|---|
| #30, #31, #124, #125 | `py/url-redirection` | Redirección final de `asignar_tarea` y `cerrar_tarea` |
| #122, #123 | `py/reflective-xss` | `filter_estado` y `tarea` en contexto de `TemplateResponse` |

Fuera de alcance: plantillas Jinja2 (`app/templates/tareas/`, solo lectura),
`service.py` y `queries.py` (sin cambios en esta triage).

## Metodología

Para cada alerta se trazó el flujo de datos completo en el código vigente
(revisión de `routes.py`, `service.py` y plantillas) y se decidió
disposición según evidencia ejecutable, no por lectura estática:

- **FIXED** — la alerta describe un defecto real y se corrige en código.
- **FALSE POSITIVE** — el flujo señalado está neutralizado por un control
  existente, demostrado con una prueba de comportamiento.

## Hallazgos y disposición

### FIXED — `py/url-redirection` (#30, #31, #124, #125)

Las redirecciones finales de las rutas de escritura interpolaban el
parámetro de ruta `tarea_id` sin validar: ``RedirectResponse(url=f
"/tareas/{tarea_id}")``. Semánticamente `tarea_id` es un UUID de
PostgreSQL (todas las consultas aplican `::uuid`), de modo que cualquier
valor que no parsee como UUID no tiene destino legítimo.

Corrección: helper de módulo `_tarea_redirect(tarea_id)` que valida con
`uuid.UUID(tarea_id)` (capturando `ValueError`/`TypeError`/
`AttributeError`). Identificador válido → redirección a
`/tareas/{tarea_id}`; inválido → registro con `log_safe` y redirección al
constante `/tareas`. Ambos sitios de redirección usan el helper; no
queda interpolación de un id sin validar. El comportamiento de las
llamadas al servicio (paso de `ValueError`) no cambia.

### FALSE POSITIVE — `py/reflective-xss` (#122, #123)

Los campos `filter_estado` (parámetro de consulta) y `tarea` (modelo de
dominio) llegan a la respuesta exclusivamente a través de
`_templates.TemplateResponse`. Starlette construye el entorno Jinja2 de
`Jinja2Templates` con autoescape activado por defecto para plantillas
`.html`, por lo que todo valor interpolado se escapa a entidades HTML
antes de la respuesta. No existe ruta alternativa por f-string ni
`HTMLResponse` con contenido interpolado en este módulo, y las
plantillas no usan el filtro `|safe`.

Evidencia de comportamiento (tests, no solo lectura de código):

- `tests/test_tasks_redirect_guard.py::TestTareasXssAutoescape::`
  `test_filter_estado_payload_is_entity_escaped` — una petición
  `GET /tareas?estado=<script>alert(1)</script>` responde 200 con
  `&lt;script&gt;` en el cuerpo y sin el `<script>` crudo.
- `test_tareas_templates_autoescape_is_truthy` — fija que el entorno del
  slice mantiene autoescape activado; si una refactorización futura lo
  desactiva, la prueba falla y con ella la disposición.

## Veredicto

Las cuatro alertas de `py/url-redirection` quedan resueltas con el
guardián de UUID en la redirección; las dos de `py/reflective-xss` se
declaran falsos positivos con evidencia de autoescape fijada por pruebas.
Las plantillas del slice permanecen intactas. Riesgo residual: la
disposición XSS depende de que el entorno conserve el autoescape por
defecto; la prueba de regresión lo vigila, pero cualquier cambio a
`autoescape=False` debe reabrir esta revisión.
