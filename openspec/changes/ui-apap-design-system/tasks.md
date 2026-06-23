# Tasks: ui-apap-design-system

## Goal

Aplicar el design system APAP (de `docs/features-showcase.html`) a las 9 plantillas existentes y regenerar el bundle CSS. Single PR.

## Tasks

### T1. Design tokens en Tailwind v4 (`@theme` block)

- [x] T1.1 Editar `tailwindcss/styles/app.css` y declarar las variables APAP en un bloque `@theme { … }` siguiendo la sintaxis CSS-first de Tailwind v4 (`--color-primary: #1a5632;` etc.)
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
- [x] T3.3 Tonos APAP: primary en títulos de card, info-box verde si hay mensaje de bienvenida

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
- [x] T6.3 Empty state con info-box verde y CTA al form
- [x] T6.4 Mantener las columnas existentes (NCHIP, Nombre, Especie, Sexo, FNacimiento, Raza) — son los datos del modelo

### T7. Animales — `detail.html`

- [x] T7.1 Header con el nombre del animal grande y los botones Editar (amarillo/dorado APAP) y Borrar (rojo de error) lado a lado
- [x] T7.2 Grid 2-col md:1-col con todos los campos del modelo
- [x] T7.3 Card de "Observaciones" abajo con `border-left primary`
- [x] T7.4 Link "← Volver al listado" como link secundario APAP

### T8. Animales — `form.html`

- [x] T8.1 Inputs con `focus:border-primary` y labels con `text-text` (no `text-gray-700`)
- [x] T8.2 `<details>` de "Campos opcionales (legacy)" con summary `text-text font-semibold` y body con `bg-bg` (beige APAP)
- [x] T8.3 Botón "Guardar" `bg-primary hover:bg-primary-dark`
- [x] T8.4 Banner de error `bg-rose-50 border-rose-200 text-rose-800` (semántico, no branding)

### T9. Voluntarios — `list.html`

- [x] T9.1 Mismo patrón que animales/list.html: header primary, botón primary, empty state APAP
- [x] T9.2 Mantener columnas (Nombre, Email, Tel1, DNI)

### T10. Voluntarios — `detail.html` y `form.html`

- [x] T10.1 Mismo patrón que animales/detail.html y animales/form.html
- [x] T10.2 Mantener los campos del modelo Voluntario sin cambios

### T11. Recompilar CSS y commitear

- [ ] T11.1 `make css` (corre Tailwind v4 con `--minify`)
- [ ] T11.2 Verificar que `app/static/css/output.css` creció y contiene los tokens APAP
- [ ] T11.3 Commitear `tailwindcss/styles/app.css` (input) + `app/static/css/output.css` (output) + los 9 templates modificados en commits separados (1 commit por concern: tokens, base+landing+admin+unauth, animales/*, voluntarios/*)

### T12. Verificación local y visual

- [ ] T12.1 `make all` (css + test + lint) — todos verdes
- [ ] T12.2 `make serve` en background; con Playwright MCP, abrir `http://127.0.0.1:8000/`, `/admin` (sin auth, ver 302), `/animales`, `/animales/new`, `/voluntarios`, `/voluntarios/new`, `/unauthorized`
- [ ] T12.3 Screenshot de cada vista (PNG en `docs/screenshots/ui-apap-design-system/`) — esos PNGs NO se commitean, son solo verificación
- [ ] T12.4 Verificar visualmente: verde APAP en headers/títulos, dorado en badges, beige en background, sin restos de blue-600/gray-200 en producción

### T13. PR

- [ ] T13.1 Branch `feat/ui-apap-design-system` desde `origin/staging`
- [ ] T13.2 4 commits work-unit (T1, T2-T5, T6-T8, T9-T10, T11) — siguiendo `work-unit-commits` skill
- [ ] T13.3 `code-review-expert` antes del push (pre-push policy del proyecto)
- [ ] T13.4 Push + abrir PR a `staging` con título y body siguiendo `branch-pr` skill

## Definition of done

- Todos los tasks [x]
- `make all` verde
- Screenshots de las 6 vistas en `docs/screenshots/ui-apap-design-system/` (no commiteados)
- Code review APPROVE pre-push
- PR mergeado a `staging`
- Coolify redespliega y `https://apap.romancaba.com/` muestra la UI con branding APAP

## Out of scope (recordatorio)

- No se seedan datos — las tablas siguen vacías
- No se implementa ninguna feature nueva
- No se cambia el backend Python
- No se toca `docs/features-showcase.html` (es la fuente de verdad)
