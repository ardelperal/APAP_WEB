# #812 — Skip link «Saltar al contenido principal» (Phase A.1)

## Goal

Eliminar la violación WCAG 2.4.1 (Bypass Blocks) que sufre el shell actual: el primer Tab en el documento aterriza en el brand «APAP», no en un mecanismo para saltar al contenido. La consecuencia es que un usuario de teclado tabula once elementos del header antes de llegar al `<main>`, lo que incumple el criterio de bypass.

Slice A.1 del epic #817. Cambio de a11y baseline — 1 a 30 líneas, sin rediseño visual, mergeable en cualquier momento.

## Acceptance criteria (del issue #812, sin cambios)

1. El primer elemento focusable del documento es un ancla con texto «Saltar al contenido principal» (o equivalente de locale) que lleva el foco a `<main>` (o `<main id="main">`).
2. El skip link permanece visualmente oculto hasta recibir foco, mediante el patrón estándar de Tailwind `sr-only focus:not-sr-only`.
3. El elemento `<main>` lleva `id="main"` y `tabindex="-1"` para que el destino del skip pueda recibir foco sin entrar en el orden de tabulación.
4. La auditoría axe-core / Lighthouse «Bypass Blocks» devuelve cero violaciones en todas las rutas autenticadas.

## Scope (este slice = #812)

- `app/templates/base.html` — añadir el ancla skip link como primer hijo de `<body>`; añadir `id="main"` y `tabindex="-1"` al `<main>` existente.
- `app/templates/base_mobile.html` — mismas dos modificaciones. La plantilla móvil está activa en producción: `UADetectionMiddleware` la selecciona cuando `request.state.is_mobile == True`, y omitirla reintroduce la violación en todas las rutas visitadas desde un User-Agent móvil.
- `tests/e2e/test_a11y_skip_link.py` — nuevo. Cubre el primer Tab + Enter en `/` y `/login` (rutas públicas) y parametriza el resto con skip explícito cuando la ruta redirige a `/login` o devuelve 403 (el eje OAuth del proyecto sigue el patrón ya documentado en `tests/e2e/test_login_form.py`).
- Sin cambios en rutas, lógica de aplicación, CSS compilado ni configuración.

## Out of scope

- Envolver el contenido con `aria-labelledby` sobre el `<main>` — pertenece a #813 (labelled landmark).
- `id="main"` + `tabindex="-1"` ya están en este issue por dependencia funcional (sin ellos el skip link no tiene destino focusable); el labelling queda fuera.
- axe-core en CI como gate automático — pertenece al issue transversal «chore(ci): gate every PR on axe-core + Lighthouse» (ver epic #817, sección Cross-cutting, issue pendiente de crear).
- Cambios en el burger menu (`base.html` `<details id="nav-burger">`) ni en el nav desktop — pertenecen a Phase B (#819, #820).
- `base.html` `<header>` interno — sin cambios; el skip link vive antes del header, que sigue siendo sticky.

## Work-unit commits planeados

| WU | Descripción | Estado |
|---|---|---|
| WU-1 | Tracking (este documento) + rama `chore/812-a11y-skip-link` | en curso |
| WU-2 | Skip link + `id`/`tabindex` en `app/templates/base.html` | pendiente |
| WU-3 | Skip link + `id`/`tabindex` en `app/templates/base_mobile.html` | pendiente |
| WU-4 | Test E2E `tests/e2e/test_a11y_skip_link.py` (Playwright, parametriza rutas) | pendiente |
| WU-5 | Gates: `ruff check .`, `python scripts/check_rules.py .`, `python -m mypy`, `python -m pytest -W error::DeprecationWarning tests/test_pages.py tests/e2e/test_a11y_skip_link.py -q` (e2e con `APAP_E2E_SKIP=1` si no hay chromium) | pendiente |
| WU-6 | Commit de trabajo + push a la rama (decisión del usuario sobre PR / merge) | pendiente |

## Gates (CI required check, pre-MVP single-branch)

- `ruff check .` sin findings nuevos.
- `python scripts/check_rules.py .` exit code cero (linter APAP).
- `python -m mypy` sin errores nuevos en el scope del diff.
- `pytest tests/test_pages.py -q` verde — cubre regresión de los placeholders `{% block content %}` y la presencia de `<main>` en las plantillas.
- `pytest tests/e2e/test_a11y_skip_link.py -q` verde cuando chromium esté instalado (auto-skip si no, igual que el resto del módulo `tests/e2e/`).
- PR ≤ 400 líneas (no `size:exception`); el diff real esperado es ~10 líneas de HTML + ~60 líneas de test E2E.

## Legacy fidelity (P1)

N/A — este slice no toca legacy Access. Cambia exclusivamente el shell web.

## Estrategia de implementación

1. **Resolución del skip link** — patrón estándar: `<a href="#main" class="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-[60] focus:px-4 focus:py-2 focus:bg-primary focus:text-white focus:rounded focus:shadow-card">Saltar al contenido principal</a>`. El `z-[60]` queda por encima del header sticky (`z-50`) para que cuando reciba foco no quede tapado.
2. **Destino focusable** — `<main id="main" tabindex="-1" class="flex-1">` (en `base.html`) y `<main id="main" tabindex="-1" class="flex-1 px-4 py-6">` (en `base_mobile.html`). `tabindex="-1"` permite foco programático sin entrar en el orden de tabulación natural.
3. **Tests** — archivo nuevo `tests/e2e/test_a11y_skip_link.py` siguiendo el patrón de `tests/e2e/test_nav_layout.py`: preflight `/login`, auto-skip del módulo si falta chromium, fixtures del `conftest.py` (`page`, `browser_context`, `base_url`). Cobertura:
   - En `/`: primer Tab → `document.activeElement` es el skip link con texto «Saltar».
   - En `/`: Enter → `document.activeElement.tagName === "MAIN"`.
   - Misma pareja en `/login` (ruta pública, no redirige, siempre sirve `base.html`).
   - Parametrizado sobre `/animales`, `/entradas`, `/voluntarios`, `/admin` con skip explícito cuando la ruta redirige a `/login` (auth requerida); el cubrimiento axe-core en CI cubre la matriz completa cuando ese gate exista (issue transversal del epic #817).
4. **No tocar `base_mobile.html` más allá del mínimo** — el comentario en cabecera del archivo documenta que la duplicación con `base.html` es intencional hasta slice C. El skip link es a11y baseline y debe vivir en ambas plantillas independientemente del plan de unificación.

## Riesgos identificados

1. **Solapamiento con #813** — #813 añade `aria-labelledby` al `<main>`. Si ese slice ya estuviera mergeado, mi cambio a `<main id="main" tabindex="-1">` conviviría sin conflicto (atributos distintos). Si #813 llega antes que #812, este slice se reduce a solo el skip link + `tabindex="-1"` (sin `id`, que ya estaría). Bajo: la epic #817 fija el orden Phase A → Phase B → Phase C y dentro de Phase A enumera #812 antes que #813.
2. **Tests E2E requieren servidor vivo + chromium** — siguen el patrón auto-skip del proyecto. CI tiene ambos; en local sin chromium el módulo entero hace skip y este archivo hereda esa conducta. Documentado en el docstring del test.
3. **Doble render del skip link en mobile** — `base_mobile.html` y `base.html` son excluyentes por UA (un request solo extiende uno), así que en cualquier render hay un único skip link. Sin riesgo de duplicación visible.
4. **Cobertura axe-core como gate transversal aún no existe** — la aceptación «Bypass Blocks = 0 en cada ruta autenticada» la verifica parcialmente el test E2E (mecanismo) y queda completa cuando aterrice el issue transversal de CI del epic #817. Anotado en la descripción del PR para que el revisor lo sepa.

## Criterios de cierre del slice

- [ ] Branch `chore/812-a11y-skip-link` con los work-units WU-2, WU-3, WU-4 mergeados en commits separados y mensajes conventional commit.
- [ ] `base.html` y `base_mobile.html` contienen el skip link + `<main id="main" tabindex="-1">`.
- [ ] `tests/e2e/test_a11y_skip_link.py` agregado y verde bajo chromium.
- [ ] Gates locales verdes: `ruff check .`, `python scripts/check_rules.py .`, `python -m mypy`, `pytest tests/test_pages.py -q`.
- [ ] PR abierto contra `origin/main` (decisión del usuario) con cuerpo que cita el issue, lista los archivos tocados, y nombra el límite del E2E local hasta que exista el gate axe-core transversal.
- [ ] Memoria de sesión guardada con `mem_session_summary` (qué se hizo, archivos, gates, próximos pasos).

