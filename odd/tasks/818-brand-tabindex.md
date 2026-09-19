# #818 — Brand + Inicio collapse + `tabindex="-1"` (Phase A.4)

## Goal

Eliminar la duplicación de destino en el header: el brand `<a href="/">` y el primer item del nav `<a href="/">Inicio</a>` apuntan al mismo lugar, así que un usuario de teclado tiene que tabular dos veces para llegar al contenido (una en el brand, otra en «Inicio»). El slice colapsa los dos en un único brand `tabindex="-1"`, de modo que el primer Tab stop en cada ruta autenticada es ya el primer nav item real (Animales, Entradas, …).

Slice A.4 del epic #817. Combina #807 (colapsar brand + Inicio) y #815 (`tabindex="-1"` en brand) en un único PR, según la nota final del issue #818.

## Acceptance criteria (del issue #818)

1. El `<header>` desktop tiene exactamente un `<a href="/">` (el brand).
2. El brand `<a>` lleva `tabindex="-1"`.
3. El primer Tab stop en cada ruta autenticada es un nav item real, no el brand.
4. axe-core / Lighthouse «tabindex» reporta cero violaciones.

## Scope (este slice = #818)

- `app/templates/base.html` — añadir `tabindex="-1"` al brand `<a>`; eliminar el `<a>Inicio</a>` del nav desktop y del burger mobile.
- `app/templates/base_mobile.html` — mismo cambio (UA-selected, sigue activo).
- `tests/e2e/test_a11y_brand_tabindex.py` — nuevo. Verifica que `<header>` tiene exactamente un `<a href="/">`, brand tiene `tabindex="-1"`, y primer Tab stop es nav item real.
- `odd/tasks/818-brand-tabindex.md` — tracking del slice.

## Out of scope

- Renombrar items largos del nav (#806) — slice separado en Phase B.
- `aria-current="page"` en el item activo (#805) — Phase B.
- Burger JS / estructura colapsable (#819, #820) — Phase B.
- Cambios en CSS o en tokens de marca.

## Work-unit commits planeados

| WU | Descripción | Estado |
|---|---|---|
| WU-1 | Tracking (este documento) + rama `chore/818-brand-tabindex` | en curso |
| WU-2 | `tabindex="-1"` en brand + eliminar `<a>Inicio</a>` en `base.html` y `base_mobile.html` | pendiente |
| WU-3 | `tests/e2e/test_a11y_brand_tabindex.py` con 6 tests | pendiente |
| WU-4 | Gates locales + commit + push + CI + merge | pendiente |

## Gates (CI required check, pre-MVP single-branch)

- `ruff check .` sin findings nuevos.
- `python scripts/check_rules.py .` exit code cero.
- `python -m mypy` sin errores nuevos.
- `pytest tests/test_pages.py tests/test_template_selection.py tests/test_template_migration.py -q` verde.
- `pytest tests/e2e/test_a11y_brand_tabindex.py -q` verde bajo chromium.
- `pytest tests/e2e/test_a11y_skip_link.py -q` verde — el skip link de #812 sigue funcionando.
- `pytest tests/e2e/test_a11y_main_landmark.py -q` verde — el labelled `<main>` de #813 sigue funcionando.
- Issue-spec: el body del #818 ya está en castellano (preparado antes de la rama), pasa el check.
- Budget ≤ 250 líneas (diff esperado: ~10 de template + ~140 de test + ~80 de task file).

## Legacy fidelity (P1)

N/A — el slice sólo toca el shell web (templates Jinja y test E2E).

## Estrategia de implementación

1. **Templates** — editar `base.html` y `base_mobile.html`:
   - Añadir `tabindex="-1"` al brand `<a href="/">` en ambos.
   - Eliminar el `<a href="/" ...>Inicio</a>` del nav desktop en `base.html` y del nav burger en `base.html`.
   - Comentario Jinja documentando el contrato WCAG 2.4.3.
2. **E2E** — `tests/e2e/test_a11y_brand_tabindex.py` con el patrón de los archivos anteriores: preflight `/login`, contar `<a href="/">` en `<header>`, verificar `tabindex="-1"`, parametrised sobre rutas autenticadas con skip explícito en redirect a `/login`.
3. **Verificación local** — `make css` no aplica (sin nuevas utilities Tailwind). Edit → ruff/mypy/check_rules/pytest → commit → push → CI → merge.

## Riesgos identificados

1. **Solapamiento con #806 (rename) y #805 (`aria-current`)** — independientes. La nav list queda con sus labels actuales; el rename aplicaría después (Phase B). El `aria-current` se añade cuando el item activo quede marcado.
2. **Brand visible pero no tabbable** — usuarios de ratón siguen viendo y cliqueando el brand. Usuarios de teclado entran vía skip link (#812) o Tab directo al primer nav item. La pérdida del cue visual se compensa con el skip link, que es el mecanismo a11y canónico para «saltar al contenido».
3. **axe-core con `tabindex="-1"`** — `tabindex` negativo es válido HTML y axe-core no lo flaguea como violación. El check `tabindex` del repo (vía Lighthouse / axe) verifica que no haya `tabindex > 0` ni patterns abusivos; `-1` es el patrón correcto para elementos focusables programáticamente pero fuera del orden secuencial.

## Criterios de cierre del slice

- [ ] Branch `chore/818-brand-tabindex` con WU-2 y WU-3 mergeados.
- [ ] `base.html` y `base_mobile.html` con un único `<a href="/">` (brand con `tabindex="-1"`).
- [ ] `tests/e2e/test_a11y_brand_tabindex.py` agregado y verde bajo chromium.
- [ ] Tests E2E de #812 y #813 siguen verdes.
- [ ] Gates locales verdes.
- [ ] PR abierto contra `origin/main`, CI en verde, merge con `--admin`.
- [ ] Issues #807, #815, #818 cerradas vía `Fixes #818` keyword.
- [ ] Memoria de sesión guardada con `mem_session_summary`.


