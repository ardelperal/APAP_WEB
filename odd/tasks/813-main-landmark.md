# #813 — `<main>` landmark labelling (Phase A.2)

## Goal

Eliminar la segunda violación WCAG que sufre el shell: el `<main>` del documento no tiene `aria-label` ni `aria-labelledby`, y los `<header class="mb-8">` que varias páginas de módulo renderizan dentro del `<main>` colisionan con el `<header>` de página (landmark duplicado). Un usuario de lector de pantalla que pide la lista de landmarks (NVDA `D`, JAWS `Ctrl+F8`, VoiceOver `VO+U`) recibe un `<main>` anónimo más varios `<header>` anónimos sin forma de distinguir cuál es cuál.

Slice A.2 del epic #817. Encadenado a #812 (que dejó `<main id="main" tabindex="-1">`): el destino del skip link es el mismo `<main>` que este slice etiqueta.

## Acceptance criteria (del issue #813, sin cambios)

1. El `<main>` de página lleva `aria-labelledby="main-title"` referenciando el H1 visible, que también recibe `id="main-title"`.
2. Los encabezados de sección a nivel de módulo dentro del `<main>` se renderizan como `<section aria-labelledby="...">` en lugar de `<header>`.
3. axe-core / Lighthouse «Landmark» reporta: exactamente un `<main>`, exactamente un `<nav>` (o uno por región con `aria-label` distintos), cero landmarks `<header>` duplicados.

## Scope (este slice = #813)

- `app/templates/base.html` — añadir `aria-labelledby="main-title"` al `<main>` existente.
- `app/templates/base_mobile.html` — mismo cambio (UA-selected, sigue activo en producción).
- `app/templates/admin.html`, `app/templates/tareas/detail.html`, `app/templates/tareas/list.html` — convertir `<header class="mb-8...">` a `<section aria-labelledby="main-title">` para evitar el landmark collision. La H1 interna recibe `id="main-title"`.
- Resto de templates con `<h1>` (animales, entradas, sanidad, adopciones, voluntarios, casas de acogida, materiales, acogidas, cesiones, salud, etc.) — añadir `id="main-title"` a la H1 existente. Estas páginas ya envuelven la H1 en `<div>` (no `<header>`), así que no sufren colisión de landmark pero igualmente deben etiquetar el `<main>`.
- `tests/e2e/test_a11y_main_landmark.py` — nuevo. Cubre el snapshot de landmarks en `/` (pública) + parametrizado en las autenticadas (`/animales`, `/entradas`, `/voluntarios`, `/admin`, `/tareas`).
- Sin cambios en routes, lógica de aplicación, ni configuración.

## Out of scope

- Convertir TODOS los `<div>` envolventes de H1 en `<section>` (queda para un slice posterior si la auditoría axe-core lo requiere). El acceptance del issue pide específicamente evitar el collision con `<header>`, no cambiar la estructura semántica completa.
- Renombrar el `<header>` de página (sticky nav en `base.html`) — está fuera de `<main>` y es el landmark correcto.
- `aria-current="page"` en los items de nav activos — issue #805 (Phase B).
- axe-core como gate transversal — issue pendiente en epic #817.

## Work-unit commits planeados

| WU | Descripción | Estado |
|---|---|---|
| WU-1 | Tracking (este documento) + rama `chore/813-main-landmark` | en curso |
| WU-2 | `aria-labelledby` en `<main>` de `base.html` y `base_mobile.html` | pendiente |
| WU-3 | `id="main-title"` en H1 de los 40 templates con `<h1>` | pendiente |
| WU-4 | Convertir `<header>` → `<section aria-labelledby="main-title">` en `admin.html`, `tareas/detail.html`, `tareas/list.html` | pendiente |
| WU-5 | `tests/e2e/test_a11y_main_landmark.py` (8 tests Playwright) | pendiente |
| WU-6 | Gates locales (ruff, mypy, check_rules, pytest templates) + commit + push + CI + merge | pendiente |

## Gates (CI required check, pre-MVP single-branch)

- `ruff check .` sin findings nuevos.
- `python scripts/check_rules.py .` exit code cero.
- `python -m mypy` sin errores nuevos en el scope del diff.
- `pytest tests/test_pages.py tests/test_template_selection.py tests/test_template_migration.py -q` verde.
- `pytest tests/e2e/test_a11y_main_landmark.py -q` verde bajo chromium (auto-skip si no).
- Issue-spec: el body del #813 ya está en H3 (preparado antes del slice), pasa el check sin re-trigger.
- Budget ≤ 400 líneas; diff esperado ~200 líneas (40 templates × 1 línea de id + 3 conversiones + 2 base + tests).

## Legacy fidelity (P1)

N/A — el slice toca sólo el shell web (templates Jinja y test E2E).

## Estrategia de implementación

1. **H1 ids en bulk** — un solo `sed -i 's/<h1 /<h1 id="main-title" /g'` aplicado a los 40 templates que tienen `<h1 class="...">`. Cada H1 en este codebase tiene class attribute inmediatamente después del tag (verificado), así que el patrón es estable. Sed es preferible a edit manual aquí porque la edición es repetitiva y mecanizable.
2. **Base templates** — añadir `aria-labelledby="main-title"` al `<main>` existente (`<main id="main" tabindex="-1" class="flex-1">` → `<main id="main" tabindex="-1" aria-labelledby="main-title" class="flex-1">`). Edit manual por template.
3. **Header → Section** — los tres templates con `<header class="mb-8 flex items-start justify-between gap-6 flex-wrap">` se convierten a `<section class="..." aria-labelledby="main-title">` y la H1 interna ya recibió `id="main-title"` en el paso 1. Edit manual por template.
4. **E2E** — `tests/e2e/test_a11y_main_landmark.py` con el patrón del archivo de #812: preflight de `/login` (503 → skip), snapshot de landmarks (`page.evaluate(() => Array.from(document.querySelectorAll('main,nav,header,section,h1')).map(...))`), assert sobre el count y los labels. Cubre `/`, `/login`, `/admin`, `/animales`, `/entradas`, `/voluntarios`, `/tareas`.
5. **Verificación local** — `make css` no aplica (no hay cambios de clases Tailwind), así que el flujo es: edit → ruff/mypy/check_rules/pytest → commit → push → CI → merge.

## Riesgos identificados

1. **Solapamiento con #812** — #812 dejó `<main id="main" tabindex="-1">`; este slice añade `aria-labelledby="main-title"` adyacente. Sin conflicto. El skip link y el labelledby coexisten: el skip link mueve foco a `<main>`; el labelledby le da nombre al landmark.
2. **Issue body H2 vs H3** — el checker `scripts/check_issue_specs.py` busca `### ` (H3) por sección, no `## ` (H2). El body original del #813 venía con `## Problem` (H2); arreglado proactivamente vía `gh api PATCH` antes de la rama, así el check pasa sin re-trigger manual.
3. **Plantilla `index.html`** — `/` (landing) tiene H1 propia. Si el H1 dice algo como «APAP Alcalá», ese texto se convierte en el label audible del `<main>`. Verificar que el texto del H1 es semánticamente correcto para nombrar la página, no un placeholder.
4. **Patrón `id="main-title"` repetido** — técnicamente el id es único por página (cada página tiene una sola H1), pero múltiples páginas tienen el mismo id="main-title". Esto es HTML válido per-page. La especificación HTML5 dice que los ids deben ser únicos en el documento, no cross-document — así que es válido. axe-core lo aceptará.
5. **Tests e2e con auth** — `/admin` y `/tareas` requieren sesión. Mismo patrón que #812: preflight `/login`, skip con razón clara cuando redirige a `/login`. Cobertura axe-core completa queda pendiente del gate transversal del epic #817.

## Criterios de cierre del slice

- [ ] Branch `chore/813-main-landmark` con WU-2 a WU-5 mergeados en commits separados.
- [ ] `base.html` y `base_mobile.html` con `<main aria-labelledby="main-title">`.
- [ ] 40+ H1 con `id="main-title"`.
- [ ] 3 templates con `<section aria-labelledby="main-title">` en lugar de `<header>`.
- [ ] `tests/e2e/test_a11y_main_landmark.py` agregado y verde bajo chromium.
- [ ] Gates locales verdes.
- [ ] PR abierto contra `origin/main`, CI en verde, merge con `--admin` (bypass de branch protection, según delegación recibida).
- [ ] Issue #813 cerrada vía `Fixes #813` keyword.
- [ ] Memoria de sesión guardada con `mem_session_summary`.

