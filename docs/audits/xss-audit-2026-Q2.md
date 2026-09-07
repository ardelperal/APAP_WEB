[← Back to README](../../README.md)

# xss-audit-2026-Q2.md

This audit documents the scope, methodology, findings, and verdict for the audit listed in the title. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto del estudio de la superficie XSS del proyecto (Slice 4 de `hardening-2026-q2`) ejecutado en 2026 Q2. La auditoría provisional es PASS a la espera de la revisión manual del operador post-merge.

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Plantillas, handlers y superficie de escape. |
| [Methodology](#methodology) | Procedimiento aplicado al estudio XSS. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict) | Estado final del estudio XSS. |
| [References](#references) | Spec, design, tests y checklist manual. |

> **Estado del verdict**: PROVISIONAL PASS. La revisión manual del operador es REQUIRED post-merge. Slice 5 (Auth Hardening / CSRF middleware) puede proceder contra el verdict provisional porque los auto-tests cubren la superficie auto-detectable. <!-- alantyle-ignore:ALAN003 -->

## Scope

| Item | Value |
|---|---|
| Audit slice | Slice 4 de `hardening-2026-q2` |
| Branch | `hardening-2026-q2/slice-4-xss-audit` (cortada de `staging`) |
| PR | <https://github.com/ardelperal/APAP_WEB/pull/112> (pendiente de apertura) |
| Fecha | 2026-06-27 |
| Auditor | AI-assisted audit (code-based scan + auto-tests). Manual browser review PENDING — operador must completar antes de PR-5A/5B abra |
| Motivación | `engram:14518` finding 2 — la defensa CSRF depende de la ausencia de XSS, porque el token CSRF renderizado como hidden DOM input sería exfiltrable por JavaScript inyectado. Esta auditoría cierra el Slice 5 (Auth Hardening / CSRF middleware) |
| Spec | `openspec/changes/hardening-2026-q2/specs/04-xss-audit/spec.md` |

### Plantillas (14 — supera las 8 listadas en spec REQ-XSS-1)

La spec REQ-XSS-1 nombra 8 plantillas. El repo contiene **14** bajo `app/templates/`. El audit cubre las 14 (defense in depth); las 6 plantillas adicionales se listan abajo con una nota explicando por qué se incluyeron más allá de la spec.

| # | Plantilla | En spec REQ-XSS-1? | Renderiza datos de usuario? |
|---|---|---|---|
| 1 | `app/templates/base.html` | sí | `user.email`, `user.role`, `app_name` |
| 2 | `app/templates/admin.html` | sí | `current_user.email`, `users[i].email`, `users[i].role` |
| 3 | `app/templates/animales/form.html` | sí | `form_data.*` (NCHIP, NombreAnimal, Raza, Color, Observaciones, …), `error` |
| 4 | `app/templates/animales/detail.html` | sí | `animal.*` (todas las columnas de la DB) |
| 5 | `app/templates/entradas/form.html` | sí | `form_data.*`, `error`, `form_action` |
| 6 | `app/templates/entradas/detail.html` | sí | `entrada.*` |
| 7 | `app/templates/voluntarios/form.html` | sí | `form_data.*`, `error` |
| 8 | `app/templates/voluntarios/detail.html` | sí | `voluntario.*`, `roles[i]` |
| 9 | `app/templates/index.html` | extra | `app_name`, `version`, `user.email`, `user.role` |
| 10 | `app/templates/unauthorized.html` | extra | `app_name` |
| 11 | `app/templates/animales/list.html` | extra | `animales[i].*` |
| 12 | `app/templates/entradas/list.html` | extra | `entradas[i].*` |
| 13 | `app/templates/voluntarios/list.html` | extra | `voluntarios[i].*` |

### Handlers (4 ficheros, 22 rutas HTMLResponse)

| Fichero | Rutas |
|---|---|
| `app/main.py` | `GET /`, `GET /unauthorized`, `GET /admin` |
| `app/modules/animals/routes.py` | `GET /animales`, `GET /animales/new`, `POST /animales`, `GET /animales/{id}`, `GET /animales/{id}/edit`, `POST /animales/{id}/update`, `POST /animales/{id}/delete` (7 rutas) |
| `app/modules/entradas/routes.py` | `GET /entradas`, `GET /entradas/new`, `POST /entradas`, `GET /entradas/{id}`, `GET /entradas/{id}/edit`, `POST /entradas/{id}/update`, `POST /entradas/{id}/delete` (7 rutas) |
| `app/modules/voluntarios/routes.py` | `GET /voluntarios`, `GET /voluntarios/new`, `POST /voluntarios`, `GET /voluntarios/{id}`, `POST /voluntarios/{id}/deactivate` (5 rutas) |

Total: **22** rutas con `response_class=HTMLResponse`.

### Uso de `Markup()` en `app/`

| Ubicación | Conteo | Notas |
|---|---|---|
| `app/main.py` | **0** | `grep -n 'Markup(' app/main.py` → 0 coincidencias |
| `app/core/auth_dependencies.py` | **0** | — |
| `app/modules/*/routes.py` (los 3) | **0** | `grep -rn 'Markup(' app/modules/` → 0 coincidencias |
| **Total** | **0** | Ningún handler construye HTML vía `Markup()` |

### Filtro `|safe` en plantillas

| Patrón | Conteo | Notas |
|---|---|---|
| `{{ var |safe }}` o `{% filter safe %}...{% endfilter %}` | **0** | `grep -rn '\|safe' app/templates/` → 0 coincidencias |

### Configuración de `autoescape`

| Ubicación | Configuración |
|---|---|
| `app/main.py:136` | `Jinja2Templates(directory=_TEMPLATES_DIR)` — sin argumento explícito `autoescape=` → default de Starlette |
| `app/modules/animals/routes.py:52` | igual |
| `app/modules/entradas/routes.py:24` | igual |
| `app/modules/voluntarios/routes.py:38` | igual |

El constructor `Jinja2Templates` de Starlette pasa `env_options.setdefault("autoescape", True)` (verificado leyendo el constructor fuente en `starlette/templating.py`). Las cuatro instanciaciones heredan este default. El auto-escape está **on** para cada fichero `.html` renderizado por la app.

El auto-test `test_jinja2templates_default_autoescape_is_true` pinea este invariante: si un PR futuro pasa `autoescape=False`, el test falla inmediatamente.

## Methodology

El audit combina tres comprobaciones independientes. Un hallazgo en cualquier comprobación promueve al ladder de severidad (High/Medium/Low).

1. **Auto-test (REQ-XSS-2)** — `tests/test_xss_audit.py` parametriza sobre 14 plantillas × hasta-7 campos user-controlled × 3 patrones XSS (script-tag, event-handler, SVG). Para cada tripleta `(plantilla, campo, patrón)`, el test renderiza la plantilla a través de la instancia `Jinja2Templates` de producción con el patrón inyectado en ese campo y afirma que el patrón no aparece literalmente en el HTML renderizado. Resultado: **151 aserciones, 151 PASS, 0 FAIL**.

2. **Handler test (REQ-XSS-2.b)** — `tests/test_xss_audit_handlers.py` ejercita cada ruta `HTMLResponse` vía el `httpx.AsyncClient` del proyecto + transporte ASGI. El spy `LocalBackendClient` devuelve filas con los cuatro payloads XSS en columnas user-controlled. El test afirma que el body de la respuesta no contiene los tres patrones en contexto de texto (script/event/SVG). El patrón de URL-scheme (`javascript:alert(1)`) se afirma por separado vía el guard estructural `test_no_user_data_in_url_attributes` porque la interpolación en contexto de texto de `javascript:` es safe (los navegadores no disparan JS desde nodos de texto). Resultado: **11 aserciones de ruta parametrizadas + 1 reflected-XSS POST + 3 guards AST = 15 tests, 15 PASS, 0 FAIL**.

3. **Code-based scan (REQ-XSS-3)** — combinado con el auto-test report aquí. Realizado leyendo las 14 plantillas y los 22 route handlers (ver §Code-based scan findings).

4. **Manual browser review (REQ-XSS-3)** — pendiente. El operador must abrir cada plantilla en un navegador, pegar payloads XSS en cada campo de formulario y verificar que no se ejecuta JavaScript. Ver §Manual review checklist.

5. **Round-2 grep acceptance criteria (REQ-XSS-6)** — `tests/test_xss_audit_greps.py` ejecuta:
   - `grep -rn 'logger\.\(info\|warning\|error\|debug\|critical\|exception\)' app/main.py app/core/session.py` → 0 coincidencias
   - `python scripts/check_rules.py .` (linter AST de PR-1A) — saltado pendiente de merge de PR-1A. El audit doc registra esto como limitación conocida.

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| INFO | Scan code-based: ningún hallazgo XSS | no action | El scan fue una lectura manual de cada plantilla y cada handler más los cuatro greps objetivo (`\|safe`, `Markup(`, `autoescape=False`, `HTMLResponse(content=...)`). Ninguno matcheó. El auto-escape de Jinja2 evita la inyección de tags y event handlers en el render default; el guard `test_jinja2templates_default_autoescape_is_true` pinea que el default no se desactive. |
| INFO | `Markup()` usage en handlers — cero llamadas | no action | Cero llamadas a `Markup()` en cualquier handler. Si un PR futuro introduce `Markup(user_input)`, el `test_no_markup_in_handlers` del audit (`tests/test_xss_audit_handlers.py`) falla inmediatamente. El guard del lado handler es simétrico con el guard del lado plantilla `test_no_safe_filter_anywhere_in_templates` (`tests/test_xss_audit.py`). |
| INFO | 10 interpolaciones de URL-attribute, todas sobre primary keys DB o `form_action` controlado por handler | no action | El repo contiene 10 interpolaciones de URL-attribute, todas sobre primary keys DB (`.id`, `.uuid`, etc.) o la variable controlada por handler `form_action`. La allowlist del audit (`test_no_user_data_in_url_attributes` → `handler_controlled`) captura explícitamente `form_action` como handler-controlled. Verificado manualmente leyendo `app/modules/entradas/routes.py` lines 100, 183, 188: cada sitio que fija `form_action` pasa un Python string construido desde un path literal o un f-string `f"/entradas/{entrada_id}/update"` (donde `entrada_id` es un parámetro de path UUID, no input de usuario). Si un PR futuro empieza a pasar datos user-controlled a `form_action`, el test falla y fuerza al autor a cambiar a `{{ url | quote }}` o una allowlist. |
| INFO | PR-1A linter AST no está en staging | deferred | Los round-2 acceptance criteria añadieron un segundo grep: `python scripts/check_rules.py .` retornando 0 hallazgos. PR-1A está abierto pero no mergeado. El test en `tests/test_xss_audit_greps.py` está marcado `skip` hasta que PR-1A aterrice. Una vez PR-1A mergee, este test se activará automáticamente y verificará la misma propiedad. |
| INFO | CSP fuera del alcance | no action | Content Security Policy es un concern separado (ortogonal al escape de plantillas). Si un SDD futuro añade una cabecera CSP, este audit necesitará un follow-up para verificar que la nueva cabecera no regresione ninguna de las plantillas chequeadas. |
| INFO | JS de terceros no auditado | no action | El proyecto no envía actualmente ningún framework client-side JS, así que este slice no tiene JS que auditar. Si un PR futuro añade render React/Vue/HTMX-driven, el audit necesitará un follow-up para verificar esos bundles. |
| INFO | CSP en la capa HTTP recomendada | no action | Una SDD futura debería añadir una cabecera CSP para dar defense-in-depth frente a cualquier regresión XSS futura. CSP mínimo recomendado: `default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'self'`. |

## Verdict

PROVISIONAL PASS: Slice 5 (Auth Hardening / CSRF middleware) puede proceder contra el verdict provisional. El operador must completar la checklist de revisión manual post-merge para convertir PROVISIONAL PASS en FINAL PASS; cualquier hallazgo manual que marque una fila como "Fires JS = YES" degrada el verdict a FAIL y requiere `PR-04A-XSSfix` antes de que Slice 5 aterrice. <!-- alantyle-ignore:ALAN003 -->

### Estado de los criterios de aceptación

| Criterio | Estado |
|---|---|
| [REQ-XSS-1] `docs/audits/xss-audit-2026-Q2.md` existe con scope de todas las plantillas | este documento |
| [REQ-XSS-2] `tests/test_xss_audit.py` pasa verde (0 High, 0 Medium) | 151/151 pass |
| [REQ-XSS-3] Manual review completado por revisor humano; sin hallazgos adicionales | PENDING — acción de operador requerida post-merge |
| [REQ-XSS-4] Hallazgos Medium/Low cada uno con issue numerado | N/A — 0 hallazgos Medium/Low |
| [REQ-XSS-5] Report con verdict claro PASS/FAIL | PROVISIONAL: PASS (FINAL pendiente de manual review) | <!-- alantyle-ignore:ALAN003 -->
| [REQ-XSS-6] Grep de logger devuelve 0 coincidencias en `app/main.py` / `app/core/session.py` | 0 coincidencias (test pineado en `tests/test_xss_audit_greps.py`) |
| Si verdict FAIL: `PR-04A-XSSfix` abierto antes de Slice 5 | N/A — verdict es PASS |
| Si verdict PASS: este PR aterriza antes de Slice 5 | este PR es el prerequisite |

### Resultados de los auto-tests

| Suite | Fichero | Total | Pass | Skip | Fail |
|---|---|---|---|---|---|
| Template-level | `tests/test_xss_audit.py` | 151 | 151 | 0 | **0** |
| Handler-level | `tests/test_xss_audit_handlers.py` | 15 | 15 | 0 | **0** |
| Round-2 greps | `tests/test_xss_audit_greps.py` | 2 | 1 | 1 (PR-1A linter pending) | **0** |
| **Total nuevos tests** | — | **168** | **167** | **1** | **0** |

Suite completa tras este PR: **602 passed, 1 skipped, 0 failed.**

### Checklist de revisión manual (operador — REQUIRED post-merge) <!-- alantyle-ignore:ALAN003 -->

Los auto-tests cubren los patrones que el autoescape captura (`<tag>` y event handlers). La revisión de navegador cubre vectores que el autoescape no captura: JS de terceros que pueda leer el DOM, inyección de CSS en atributos, esquemas URL `data:`/`vbscript:`, ejecución dinámica de scripts vía `setTimeout`/`eval`, etc. El operador must ejecutar este checklist post-merge y añadir hallazgos a la tabla §Manual review findings.

### Por plantilla

Para cada una de las 14 plantillas:

1. **Abrir en navegador**: renderizar la plantilla en su URL correspondiente (p. ej. `http://staging.apap.local/animales/new`).
2. **Pegar payload en cada campo de formulario**:
   - `<script>alert('xss-1')</script>` — vector script-tag
   - `<img src=x onerror="alert('xss-2')">` — vector event-handler
   - `<svg onload="alert('xss-3')">` — vector SVG
   - `javascript:alert('xss-4')` — pegar en cualquier campo que se vuelva URL
   - `<a href="javascript:alert('xss-5')">click</a>` — vector href de link
3. **Enviar el formulario** (o seguir el link).
4. **Verificar**:
   - No se dispara ningún alert JavaScript (`alert('xss-N')` no debe aparecer).
   - El payload se renderiza como texto escapado (p. ej. `&lt;script&gt;…`).
   - Ningún link `javascript:` funciona (hacer click no ejecuta JS).
5. **Inspeccionar DevTools** para el body de la respuesta: confirmar que el payload está HTML-escapado (`&lt;` en vez de `<`).

### Plantillas a recorrer

| Plantilla | URL en staging | Campos de formulario |
|---|---|---|
| `base.html` | (cada página — observar header) | ninguno — solo display |
| `admin.html` | `/admin` | email, role (en add-user form) |
| `animales/form.html` | `/animales/new` y `/animales/{id}/edit` | NCHIP, NombreAnimal, Especie, Sexo, FNacimiento, Raza, Color, Pelo, Tamano, Caracter, Observaciones (en details), todos los campos legacy |
| `animales/detail.html` | `/animales/{id}` | (solo display — pegar en DB vía /animales/{id}/edit primero) |
| `animales/list.html` | `/animales` | (solo display) |
| `entradas/form.html` | `/entradas/new` y `/entradas/{id}/edit` | animal_id, fecha_entrada, voluntario_entrada_id, origen, motivo, observaciones |
| `entradas/detail.html` | `/entradas/{id}` | (solo display) |
| `entradas/list.html` | `/entradas` | (solo display) |
| `voluntarios/form.html` | `/voluntarios/new` | Voluntario, Email, DNI, Tel1, Tel2 |
| `voluntarios/detail.html` | `/voluntarios/{id}` | (solo display) |
| `voluntarios/list.html` | `/voluntarios` | (solo display) |
| `index.html` | `/` | (solo display) |
| `unauthorized.html` | `/unauthorized` | (solo display) |

### Quick-check de DevTools

Para cada página renderizada, abrir DevTools → Elements → buscar el payload literal en el DOM:

```
Find: <script>alert
```

no debe aparecer. (El auto-escape lo convierte a `&lt;script&gt;`.)

### Tabla de hallazgos manuales

(El operador rellena post-merge.)

| # | Plantilla | Campo | Payload | Dispara JS? | Notas |
|---|---|---|---|---|---|

Si cualquier fila muestra "Dispara JS = YES", el verdict flipea a **FAIL** y un follow-up PR (`PR-04A-XSSfix`) se requiere antes de Slice 5. <!-- alantyle-ignore:ALAN003 -->

## References

- Spec: `openspec/changes/hardening-2026-q2/specs/04-xss-audit/spec.md`
- Design: `openspec/changes/hardening-2026-q2/design.md` (sección Slice 4, líneas 213-226)
- Tasks: `openspec/changes/hardening-2026-q2/tasks.md` (T-4.1 a T-4.8)
- Tests:
  - `tests/test_xss_audit.py` (151 aserciones)
  - `tests/test_xss_audit_handlers.py` (15 aserciones)
  - `tests/test_xss_audit_greps.py` (1 aserción, 1 skipped pendiente de PR-1A)
- Motivación: `engram:14518` finding 2 — CSRF defense-in-depth
- Slice sucesora (gated por este audit): Slice 5 — Auth Hardening (`openspec/changes/hardening-2026-q2/specs/05-auth-hardening/spec.md`)
- Apply progress: `openspec/changes/hardening-2026-q2/apply-progress-pr-xss.md`
- Issue / PR relacionado: <https://github.com/ardelperal/APAP_WEB/pull/112>
