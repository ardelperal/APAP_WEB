# #805 — Nav active-state marker (Phase B.3)

## Goal

Marcar el item del nav cuya ruta matches (longest-prefix) el `pathname` actual con `aria-current="page"` + clase CSS `is-active`, para que el usuario sepa en qué sección está y los lectores de pantalla anuncien «página actual».

Slice B.3 del epic #817.

## Acceptance criteria (del issue #805)

1. El link del nav cuyo `href` matches el `pathname` actual (o su prefijo más largo) recibe `aria-current="page"` y la clase `is-active`.
2. Longest-prefix match: `/entradas/batch/new` activa «Entradas en lote», no «Entradas».
3. Tratamiento visual: `text-primary font-semibold border-b-2 border-primary`. WCAG AA sobre `bg-surface`.
4. Sin flash de unstyled state — el activo se aplica en el primer render.
5. axe-core `aria-current` reporta cero violaciones.
6. Lectores de pantalla anuncian «página actual» al leer el link activo.

## Scope (este slice = #805)

- `app/core/nav.py` — nuevo. Registro `NAV_ITEMS` (lista ordenada por longitud descendente) + función `resolve_active_nav_href(current_path)`.
- `app/core/middleware.py` — nueva función `current_path_context_processor(request)` que expone `current_path` y `nav_active_href` en el contexto Jinja.
- `app/main.py` + 8 routers de módulos — agregan `current_path_context_processor` a las listas `context_processors=[...]` (16 archivos en total).
- `app/templates/base.html` + `app/templates/base_mobile.html` — cada `<a>` del nav incluye `aria-current="page"` + clase `is-active` cuando `href == nav_active_href`.
- `tailwindcss/styles/app.css` — nueva `@layer components { .nav-link { ... } .nav-link.is-active { ... } }` con estilos para el estado base y el activo.
- `app/static/css/output.css` — regenerado vía `make css` para incluir las nuevas component utilities.
- `tests/test_template_migration.py` — regex del sentinel actualizado a multi-line (regex DOTALL) tras el split de imports por ruff.
- `tests/e2e/test_nav_active_state.py` — nuevo. 13 tests Playwright que cubren los ACs.
- `odd/tasks/805-nav-active-state.md` — tracking del slice.

## Out of scope

- Renombrar labels del nav → #806 (Phase B).
- Iconos lucide → #808 (Phase B).
- Agrupar items en dropdowns → #809 (Phase B).

## Work-unit commits planeados

| WU | Descripción | Estado |
|---|---|---|
| WU-1 | Tracking (este documento) + rama `feat/805-nav-active-state` | en curso |
| WU-2 | `app/core/nav.py` + `current_path_context_processor` en middleware | pendiente |
| WU-3 | Agregar `current_path_context_processor` a las 16 instancias de `Jinja2Templates` | pendiente |
| WU-4 | Aplicar `aria-current` + `is-active` en `base.html` y `base_mobile.html` | pendiente |
| WU-5 | Componente CSS `.nav-link.is-active` + `make css` | pendiente |
| WU-6 | Sentinel de imports multi-line en `tests/test_template_migration.py` | pendiente |
| WU-7 | `tests/e2e/test_nav_active_state.py` con 13 tests | pendiente |
| WU-8 | Gates locales + commit + push + CI + merge | pendiente |

## Gates (CI required check, pre-MVP single-branch)

- `ruff check .` sin findings nuevos.
- `python scripts/check_rules.py .` exit code cero.
- `python -m mypy` sin errores nuevos en el scope del diff.
- `pytest tests/test_pages.py tests/test_template_selection.py tests/test_template_migration.py -q` verde (36 tests).
- `pytest tests/e2e/test_nav_active_state.py -q` verde bajo chromium (auto-skip si no).
- `pytest tests/e2e/test_nav_responsive_structure.py tests/e2e/test_nav_burger_toggle.py -q` verde.
- `pytest tests/e2e/test_a11y_skip_link.py tests/e2e/test_a11y_main_landmark.py tests/e2e/test_a11y_brand_tabindex.py -q` verde.
- Issue-spec: el body del #805 ya está en castellano, pasa el check.
- Budget ≤ 500 líneas (diff esperado: ~120 de python + ~80 de CSS + ~180 de templates + ~80 de test sentinels + ~200 de test e2e + ~120 de task file).

## Legacy fidelity (P1)

N/A — el slice sólo agrega lógica de presentación del nav.

## Estrategia de implementación

1. **`app/core/nav.py`** — `NAV_ITEMS` (lista de tuplas `(href, label)`, ordenada por longitud descendente). `resolve_active_nav_href(current_path)` itera y devuelve el primer href que matchea (`==` o `startswith(href + "/")`).
2. **`app/core/middleware.py`** — `current_path_context_processor(request)` devuelve `{"current_path": request.url.path, "nav_active_href": resolve_active_nav_href(...)}`. Lazy-import `resolve_active_nav_href` para evitar ciclo de imports.
3. **Bulk-update 16 routers** — agregar el nuevo processor a cada lista `context_processors=[...]`. Se usó sed + verificación por grep.
4. **Templates** — para cada `<a>` del nav, agregar `{% if nav_active_href == "/X" %}aria-current="page" class="nav-link is-active ..."{% else %}class="nav-link ..."{% endif %}`. La inline-class genera las utilities Tailwind para el JIT scanner.
5. **CSS** — `@layer components { .nav-link { @apply inline-flex items-center text-text-muted; } .nav-link:hover { @apply text-primary; } .nav-link.is-active { @apply text-primary font-semibold border-b-2 border-primary; } .nav-link.is-active:hover { @apply text-primary-dark; } }` en `tailwindcss/styles/app.css`. `make css` regenera el bundle.
6. **Sentinel multi-line** — el regex del test de migración usaba `.` sin DOTALL; el reformat de ruff dejó imports multi-line en algunos archivos. Actualizado a `re.compile(..., re.DOTALL)`.
7. **E2E** — `tests/e2e/test_nav_active_state.py` con 13 tests: 1 public sentinel + 9 parametrised auth routes + 3 unit-style (longest prefix, is-active class hook, exactly-one).
8. **Verificación local** — `make css` + ruff/mypy/check_rules/pytest → commit → push → CI → merge.

## Riesgos identificados

1. **Reformat de imports por ruff** — ruff a veces divide `from app.core.middleware import a, b, c` en multi-line. Esto rompe regex que asume single-line. Mitigación: actualizado a DOTALL. Riesgo futuro: cualquier regex de sentinel debe ser DOTALL.
2. **Longest-prefix edge cases** — `/entradas/batch/preview` activa `/entradas` (no `/entradas/batch/new`, porque el path no empieza con `/entradas/batch/new/`). El unit test confirma el comportamiento; el E2E test cubre el caso explícito de `/entradas/batch/new`.
3. **9 instancias de `Jinja2Templates`** — agregar el processor a cada una. Riesgo de olvidar alguna → grep final para confirmar cobertura completa.
4. **CSS `@apply` con border-b-2** — el border-style se aplica via `--tw-border-style` (Tailwind v4 convention). Sin conflicto con utilities existentes.
5. **Active state en rutas no listadas** — el helper devuelve `""` si no hay match. El template trata `"" == href` como falso (todos los hrefs son no-vacíos), así que ningún item queda activo. Cubierto por el sentinel `test_no_active_state_on_login_route`.
