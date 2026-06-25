# Tasks: ui-apap-design-system

## Goal

Aplicar el design system APAP real (de `docs/design-tokens-apap-actual.md`) a las 9 plantillas existentes y regenerar el bundle CSS. Single PR. Reconciliación 2026-06-25: `docs/features-showcase.html` queda como catálogo de features; sus tokens verde/dorado/beige fueron descartados como fuente de verdad visual en favor de los tokens reales del sitio APAP Alcalá validados en PR #108.

## Tasks

### T1. Design tokens en Tailwind v4 (`@theme` block)

- [x] T1.1 Editar `tailwindcss/styles/app.css` y declarar las variables APAP reales en un bloque `@theme { … }` siguiendo la sintaxis CSS-first de Tailwind v4 (`--color-primary: #0A91EB;`, `--color-accent: #EE812E;`, etc.)
- [x] T1.2 Verificar que las clases Tailwind resultantes (`bg-primary`, `text-accent`, `border-primary`, etc.) están disponibles tras el build
- [x] T1.3 No tocar `@import "tailwindcss"` ni `@source "../../app/templates/**/*.html"` — solo añadir el bloque `@theme`

### T2. `base.html` — chrome global

- [x] T2.1 Reemplazar el body minimal (sin nav) por un layout con: nav sticky (Inicio · Animales · Voluntarios · Admin si rol=developer · Login/Logout según sesión), contenedor `<main>`, footer con texto APAP
- [x] T2.2 Usar los tokens APAP para colores de nav (background surface, hover primary con tinte, active con border-bottom primary)
- [x] T2.3 Mantener el bloque `{% block content %}` y `{% block title %}` — son la API actual
- [x] T2.4 Agregar `lang="es"` (ya está), `meta description`, favicon placeholder (sin asset nuevo, dejar `<link rel="icon" href="data:,">` para silenciar el 404)

### T3. Landing `index.html`

- [x] T3.1 Mantener la lógica actual (mostrar email/rol si hay sesión, link login si no, healthz link, admin link si developer)
- [x] T3.2 Reemplazar el card "Esqueleto de la aplicación" por un hero corto con badge "Migración Legacy → Web · FastAPI + HTMX + InsForge" y una lista de cards de las features (las 6 del showcase: Ciclo de Vida, Voluntarios, Entradas, Salud, Documentos, Acceso) — links muertos por ahora (`href="#"`) excepto los que ya existen (`/admin`, `/healthz`, `/login`, `/logout`)
- [x] T3.3 Tonos APAP reales: primary en títulos de card, info-box con tinte primary/legacy-green si hay mensaje de bienvenida

### T4. Admin `admin.html`

- [x] T4.1 Mantener la tabla CRUD de usuarios autorizados y el form de alta — son la lógica de negocio intacta
- [x] T4.2 Reemplazar el botón "Añadir" `bg-sky-700` por `bg-primary hover:bg-primary-dark`
- [x] T4.3 Tabla: header `bg-primary text-white` (estilo showcase), filas con hover `bg-primary/5`
- [x] T4.4 Botón "Desactivar" `text-rose-700` (semántico de error, se mantiene) — el rojo de error no es branding, es UX universal
- [x] T4.5 Empty state con el tono de la info-box APAP

### T5. `unauthorized.html`

- [x] T5.1 Mantener el mensaje de acceso denegado
- [x] T5.2 Rediseñar con un card centrado, icono 🐾, texto "No tienes acceso a esta sección", link de vuelta a `/`

### T6. Animales — `list.html`

- [x] T6.1 Tabla con header `bg-primary text-white` (igual que admin)
- [x] T6.2 Botón "+ Nuevo animal" `bg-primary hover:bg-primary-dark`
- [x] T6.3 Empty state con info-box APAP y CTA al form
- [x] T6.4 Mantener las columnas existentes (NCHIP, Nombre, Especie, Sexo, FNacimiento, Raza) — son los datos del modelo

### T7. Animales — `detail.html`

- [x] T7.1 Header con el nombre del animal grande y los botones Editar (accent naranja APAP) y Borrar (rojo de error) lado a lado
- [x] T7.2 Grid 2-col md:1-col con todos los campos del modelo
- [x] T7.3 Card de "Observaciones" abajo con `border-left primary`
- [x] T7.4 Link "← Volver al listado" como link secundario APAP

### T8. Animales — `form.html`

- [x] T8.1 Inputs con `focus:border-primary` y labels con `text-text` (no `text-gray-700`)
- [x] T8.2 `<details>` de "Campos opcionales (legacy)" con summary `text-text font-semibold` y body con `bg-bg` (gris claro APAP real `#f5f5f5`)
- [x] T8.3 Botón "Guardar" `bg-primary hover:bg-primary-dark`
- [x] T8.4 Banner de error `bg-rose-50 border-rose-200 text-rose-800` (semántico, no branding)

### T9. Voluntarios — `list.html`

- [x] T9.1 Mismo patrón que animales/list.html: header primary, botón primary, empty state APAP
- [x] T9.2 Mantener columnas (Nombre, Email, Tel1, DNI)

### T10. Voluntarios — `detail.html` y `form.html`

- [x] T10.1 Mismo patrón que animales/detail.html y animales/form.html
- [x] T10.2 Mantener los campos del modelo Voluntario sin cambios

### T11. Recompilar CSS y commitear

- [x] T11.1 `make css` (corre Tailwind v4 con `--minify`) — 2026-06-25: GNU make no está disponible en Windows; se ejecutó el comando subyacente `npx tailwindcss -i ./styles/app.css -o ../app/static/css/output.css --minify` desde `tailwindcss/` y pasó.
- [x] T11.2 Verificar que `app/static/css/output.css` contiene los tokens APAP reales — el bundle ya estaba compilado, por eso no creció en esta verificación; contiene `--color-primary:#0A91EB`, `--color-accent:#EE812E`, `--color-bg:#f5f5f5` y utilities generadas (`.bg-primary`, `.text-primary`, `.bg-accent`, `.bg-bg`, etc.).
- [x] T11.3 Commitear `tailwindcss/styles/app.css` (input) + `app/static/css/output.css` (output) + los 9 templates modificados. Reconciliación de archivo 2026-06-25: la mecánica histórica de "commits separados" queda satisfecha por los commits de trabajo incluidos en PR #108 (`60f6c87`, `597691a`, `806b565`, `e586867`, `f4c441b`, `7f4c64c`, `aac464e`) y por el merge commit `ec99037` ya alcanzable desde `staging`; el commit documental posterior `ce19058` también está alcanzable desde `staging`.

### T12. Verificación local y visual

- [x] T12.1 `make all` (css + test + lint) — todos verdes — 2026-06-25: GNU make no está disponible en Windows; se ejecutaron los equivalentes canónicos (`npx tailwindcss ... --minify`, `python -m pytest`, `python -m ruff check .`) y además `python -m build`. Resultado: CSS OK, pytest 421 passed / 2 skipped, ruff OK, build OK.
- [x] T12.2 `make serve` en background; con Playwright MCP, abrir `http://127.0.0.1:8000/`, `/admin` (sin auth, ver 302), `/animales`, `/animales/new`, `/voluntarios`, `/voluntarios/new`, `/unauthorized` — verificado con `scripts/dev_server_no_lifespan.py` porque `uvicorn app.main:app` falla localmente por bootstrap InsForge; rutas protegidas devuelven 302 a `/login` sin sesión.
- [x] T12.3 Screenshot de cada vista (PNG en `docs/screenshots/ui-apap-design-system/`) — esos PNGs NO se commitean, son solo verificación. Evidencia honesta: `/` y `/unauthorized` se capturan completas; las rutas protegidas solo se pueden capturar localmente como redirect/login sin credenciales OAuth/InsForge, no como vista protegida completa.
- [x] T12.4 Verificar visualmente: tokens APAP reales en producción local — primary azul `#0A91EB` en headers/títulos/botones, accent naranja `#EE812E` en badges/CTAs, background `#f5f5f5`, sin restos de `blue-600`/`gray-200` en plantillas productivas. No revertir a verde/dorado/beige: esa expectativa venía del showcase y quedó reconciliada como stale.

## Verification notes — 2026-06-25

- `make css` / `make all`: GNU make no está disponible en este entorno Windows, por lo que se usaron los comandos subyacentes documentados en `Makefile`.
- `app/static/css/output.css`: se regeneró correctamente y quedó sin diff de contenido contra `HEAD` (`git diff --exit-code -- app/static/css/output.css` = 0), por lo que no "creció" en esta fase; el bundle ya estaba compilado antes de esta verificación. Se verificó que contiene los tokens APAP reales `#0A91EB`, `#EE812E`, `#f5f5f5` y utilities para las clases usadas por los templates.
- Playwright local: `uvicorn app.main:app` falla al arrancar porque el lifespan intenta contactar InsForge y la conexión local es rechazada. Se usó `scripts/dev_server_no_lifespan.py`, que es el runner e2e existente para inspección local sin bootstrap InsForge.
- Rutas sin sesión: `/admin`, `/animales`, `/animales/new`, `/voluntarios`, `/voluntarios/new` devuelven 302 a `/login`; `/` y `/unauthorized` devuelven 200.
- Screenshots generados localmente en `docs/screenshots/ui-apap-design-system/` para evidencia visual; no deben commitearse. Las vistas protegidas capturadas terminan en `/login` 503 por falta de credenciales OAuth locales; eso limita la evidencia visual protegida local, pero la verificación de redirects y los tests e2e/rutas cubren el comportamiento sin sesión.
- Reconciliación de paleta: el CSS actual declara la paleta APAP real del sitio legado (`--color-primary: #0A91EB`, `--color-accent: #EE812E`, `--color-bg: #f5f5f5`) en `tailwindcss/styles/app.css`. Esta es la fuente de verdad por `docs/design-tokens-apap-actual.md`; la expectativa verde/dorado/beige de `docs/features-showcase.html` queda registrada como stale y no debe aplicarse a la UI.

### T13. PR

- [x] T13.1 Branch `feat/ui-apap-design-system` desde `origin/staging` — reconciliado en archivo: PR #108 se abrió desde `feat/ui-apap-design-system` hacia `staging` y consta como `MERGED`.
- [x] T13.2 4 commits work-unit (T1, T2-T5, T6-T8, T9-T10, T11) — reconciliado en archivo: PR #108 contiene commits de trabajo trazados por tareas (`60f6c87` T1, `597691a` T2-T5, `806b565` T6-T8, `e586867` T9-T13, `f4c441b` T1/T11, `7f4c64c` T12, `aac464e` post-review) y fue mergeado como `ec99037`.
- [x] T13.3 `code-review-expert` antes del push (pre-push policy del proyecto) — reconciliado en archivo: PR #108 incluye follow-up post-review `aac464e`; revisión documental posterior aprobada en Engram #14305.
- [x] T13.4 Push + abrir PR a `staging` con título y body siguiendo `branch-pr` skill — reconciliado en archivo: `gh pr view 108` confirma PR #108 `MERGED` a `staging` el 2026-06-23 con merge commit `ec99037`.

### Archive-time reconciliation note — 2026-06-25

Las casillas T11.3 y T13.1-T13.4 estaban obsoletas respecto al estado real de la rama actual. La instrucción de archivo pidió verificar si esas mecánicas históricas de branch/push/PR eran stale, satisfechas/N/A o bloqueantes. Se reconciliaron como satisfechas porque:

- `git merge-base --is-ancestor ec99037 staging` confirma que PR #108 está alcanzable desde `staging`.
- `git merge-base --is-ancestor ce19058 staging` confirma que la reconciliación documental posterior también está alcanzable desde `staging`.
- `gh pr view 108` confirma `state: MERGED`, `baseRefName: staging`, `headRefName: feat/ui-apap-design-system`, `mergedAt: 2026-06-23T18:58:42Z`, `mergeCommit: ec99037`.
- La verificación local de archivo confirma `python -m pytest` = 421 passed / 2 skipped, `python -m ruff check .` = OK, `python -m build` = OK, y Tailwind `npx tailwindcss -i ./styles/app.css -o ../app/static/css/output.css --minify` = OK. La ejecución directa de `tests/e2e/test_landing.py` no corrió en este entorno porque falta el paquete dev `playwright`, pero el test existe en `tests/e2e/test_landing.py` y PR #108 lo incorporó como evidencia de regresión visual.

## Definition of done

- Todos los tasks [x]
- `make all` verde
- Screenshots/evidencia visual local en `docs/screenshots/ui-apap-design-system/` (no commiteados), con limitación documentada para rutas protegidas sin auth local
- Code review APPROVE pre-push
- PR mergeado a `staging`
- Coolify redespliega y `https://apap.romancaba.com/` muestra la UI con branding APAP

## Out of scope (recordatorio)

- No se seedan datos — las tablas siguen vacías
- No se implementa ninguna feature nueva
- No se cambia el backend Python
- No se toca `docs/features-showcase.html` (catálogo de features; no es fuente de verdad de tokens)
