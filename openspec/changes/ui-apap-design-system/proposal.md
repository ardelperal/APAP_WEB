# Proposal: ui-apap-design-system

## Goal

Aplicar el design system APAP (definido en `docs/features-showcase.html`) a las plantillas existentes de FastAPI/Jinja2 + Tailwind v4. La aplicación tiene la arquitectura, los endpoints y los templates, pero visualmente usa Tailwind defaults (slate/blue/gray) sin branding APAP. Este change sincroniza la UI con el estudio de diseño que el usuario ya completó y validó.

## Scope (in scope)

Templates FastAPI/Jinja2 existentes (9 archivos):
- `app/templates/base.html` (esqueleto: agregar nav sticky + hero + footer)
- `app/templates/index.html` (landing)
- `app/templates/admin.html` (panel admin)
- `app/templates/unauthorized.html` (acceso denegado)
- `app/templates/animales/list.html` (listado)
- `app/templates/animales/detail.html` (ficha)
- `app/templates/animales/form.html` (alta/edición)
- `app/templates/voluntarios/list.html` (listado)
- `app/templates/voluntarios/detail.html` (ficha)
- `app/templates/voluntarios/form.html` (alta/edición)

CSS de entrada (Tailwind v4 CSS-first):
- `tailwindcss/styles/app.css` — definir design tokens APAP con `@theme`

CSS compilado (regenerado por `make css`):
- `app/static/css/output.css` — bundle compilado (cambia como artefacto del build)

## Out of scope

- Nuevas features de negocio (no se agrega nada a la lógica de los modelos `animal` / `voluntario`).
- Datos seed en InsForge (las tablas `animales`, `voluntarios`, `roles_voluntario` siguen vacías — el seed de datos del legacy es otro change).
- Nuevas vistas que no estén ya en el repo.
- Cambios al backend Python (rutas, auth, InsForge client) — solo UI.
- Refactor del showcase `docs/features-showcase.html` — ese archivo es documentación, no se toca.

## Design tokens APAP (fuente de verdad)

Extraídos verbatim de `docs/features-showcase.html` (líneas 8–22):

```css
--primary: #1a5632;       /* verde APAP */
--primary-light: #2d7a4a;
--primary-dark: #0e3d22;
--accent: #e8a838;        /* dorado APAP */
--accent-light: #f0c060;
--bg: #f5f5f0;            /* beige claro */
--surface: #ffffff;
--text: #1a1a1a;
--text-muted: #666;
--border: #ddd;
--radius: 12px;
--shadow: 0 2px 12px rgba(0,0,0,0.08);
--shadow-lg: 0 8px 32px rgba(0,0,0,0.12);
```

Tipografía: `'Segoe UI', system-ui, -apple-system, sans-serif`.

Componentes reutilizables (del showcase): hero con gradiente primario, nav sticky, cards con border-left primary, tables con header primary, info-box (verde), warning-box (dorado), accordion, timeline, footer primary-dark.

## Approach (resumen técnico)

1. **CSS-first en Tailwind v4** (`@theme` block en `tailwindcss/styles/app.css`): declarar las variables APAP como utilities (`bg-primary`, `text-accent`, `border-primary`, etc.) para que los templates usen clases Tailwind nativas en vez de `style="..."` inline.
2. **Reescritura de los 9 templates** con la paleta APAP y los componentes del showcase (sin copy/paste literal: el showcase es documentación interactiva, las plantillas son servidor-rendered).
3. **Recompilar** el CSS con `make css` y commitear `app/static/css/output.css` como artefacto del build.
4. **Verificación visual** con Playwright: tomar screenshots de las 6 vistas principales (landing, admin, animales list, animales detail, animales form, voluntarios list) en viewport desktop y mobile. Comparar con `docs/features-showcase.html` para coherencia de tokens (no pixel-perfect: el showcase tiene layouts distintos).

## Risks

- **Riesgo bajo funcional**: solo cambian clases Tailwind y se recompila CSS. No se toca Python, ni rutas, ni auth, ni InsForge.
- **Riesgo visual bajo**: el showcase es documentación, no hay un "pixel-perfect target" — el objetivo es coherencia de tokens (colores, tipografía, espaciado), no reproducir layouts del showcase.
- **Riesgo medio de regresión visual**: la nav sticky y el hero cambian el layout de TODAS las páginas. Hay que verificar que no rompa la tabla de admin, los formularios largos, etc.
- **Strict TDD NO activo** (es Python, no Access/VBA). No hay TDD atoms para UI en este stack. La verificación es visual con Playwright screenshots, no tests pytest.

## Success criteria

- [ ] `make css` compila sin warnings con los tokens APAP
- [ ] `make all` (css + test + lint) pasa en verde
- [ ] `app/static/css/output.css` cambia solo como artefacto del build
- [ ] Las 9 plantillas usan exclusivamente las clases Tailwind que mapean a tokens APAP (no quedan `blue-600`, `gray-200`, etc. en producción)
- [ ] Playwright captura screenshots de las 6 vistas principales; las screenshots muestran colores verde/dorado/beige APAP
- [ ] PR a `staging`; code review pre-push antes del push
- [ ] Una vez mergeado, `make serve` levanta la app y la landing se ve con el branding APAP

## Dependencies

- **Ninguna de código**: el backend no cambia.
- **Documentación**: `docs/features-showcase.html` (1020 líneas) es la fuente de verdad del diseño. NO se modifica.
- **Infraestructura**: el deploy de Coolify (PR #104 ya mergeó el último cambio de staging; este PR es el siguiente).

## Linked artifacts

- Design source: `docs/features-showcase.html`
- Current templates: `app/templates/**/*.html`
- Current CSS: `tailwindcss/styles/app.css` (input) + `app/static/css/output.css` (output, regenerado)
- Build command: `make css` (Tailwind v4 @tailwindcss/cli)

## PR chain

Single PR (1 chained PR). Estimación: <400 líneas de diff en templates + 1 línea de `@theme` en `app.css` + ~5KB de CSS minificado regenerado. Por debajo del review budget 400.
