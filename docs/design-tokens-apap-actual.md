# Design tokens — APAP Alcalá (current site)

[Back to Codebase Guide](CODEBASE-GUIDE.md)

Esta página posee los tokens visuales (color, tipografía, geometría) extraídos de la web actual de APAP Alcalá. No posee el sistema de componentes ni las decisiones de branding a futuro — esos viven en el código bajo `app/static/` y en cualquier issue `type:design`. La única fuente de verdad para la paleta en producción es este archivo.

Captured from `https://www.apap-alcala.org/quienes_somos.php` with Playwright on 2026-06-13 (#11910) and 2026-06-15 (#12416). These are the visual tokens of the **current** APAP Alcalá website. The new APAP_WEB frontend should inherit this palette so the brand stays recognisable.

## Palette

### Primary — APAP blue (header, nav, primary buttons, links)

| Token        | Hex       | Usage                                        |
|--------------|-----------|----------------------------------------------|
| `primary`    | `#0A91EB` | Header background, primary buttons, link hover |
| `primary-dark` | `#076FB8` | Header gradient end, primary button hover    |

### Accent — APAP orange (dropdown menus, CTAs)

| Token   | Hex       | Usage                                       |
|---------|-----------|---------------------------------------------|
| `accent` | `#EE812E` | Dropdown menu background, side CTA buttons  |

### Legacy green — CTA sidebox (aportes / "Hazte socio")

| Token           | Hex       | Usage                                       |
|-----------------|-----------|---------------------------------------------|
| `legacy-green`  | `#369656` | Sidebox CTA links                           |
| `legacy-green-light` | `#3CA05B` | Hover/active on legacy-green             |

### Neutrals

| Token       | Hex       | Usage                          |
|-------------|-----------|--------------------------------|
| `surface`   | `#ffffff` | Card / content background      |
| `bg`        | `#f5f5f5` | Page background                |
| `border`    | `#e5e5e5` | Card / input borders           |
| `text`      | `#333333` | Body text                      |
| `text-muted`| `#666666` | Captions, helper text          |
| `white`     | `#ffffff` | Nav text on primary background |

## Typography

| Token          | Family                       | Usage                       |
|----------------|------------------------------|-----------------------------|
| `font-logo`    | `Century Gothic, sans-serif` | APAP wordmark / hero titles |
| `font-nav`     | `Abel, sans-serif`           | Top navigation              |
| `font-heading` | `Source Sans Pro, sans-serif`| Section H2 / H3             |
| `font-body`    | `Open Sans, sans-serif`      | Body copy, footer, captions |

## Layout (current site, desktop)

- **Container**: 1170px max width
- **Header height**: 85px
- **Spacing scale**: 0 / 2 / 3 / 5 / 10 / 18 / 20 / 35 / 85 px
- **Border radius**: minimal (Bootstrap-era, mostly sharp corners)

## How this maps to Tailwind v4 `@theme`

```css
@theme {
  /* Primary blue */
  --color-primary: #0A91EB;
  --color-primary-dark: #076FB8;

  /* Accent orange */
  --color-accent: #EE812E;

  /* Legacy green (CTA sidebox) */
  --color-legacy-green: #369656;
  --color-legacy-green-light: #3CA05B;

  /* Neutrals */
  --color-surface: #ffffff;
  --color-bg: #f5f5f5;
  --color-border: #e5e5e5;
  --color-text: #333333;
  --color-text-muted: #666666;

  /* Typography — declared as font stacks so Tailwind keeps
   * class-level override capability while we use the real
   * brand families. */
  --font-sans: 'Open Sans', system-ui, -apple-system, sans-serif;
  --font-heading: 'Source Sans Pro', system-ui, sans-serif;
  --font-nav: 'Abel', system-ui, sans-serif;
  --font-logo: 'Century Gothic', 'Source Sans Pro', sans-serif;

  /* Geometry from the current site */
  --spacing: 0.25rem;        /* 4px base */
  --container-xl: 73.125rem; /* 1170px */
  --radius-card: 0.25rem;    /* sharp, Bootstrap-era */
}
```

## Why we inherit the current site's tokens

The user's brief was "recordá los tokens que extrajimos de la web de apap-alcala".
Inheriting the blue/orange/green palette keeps the brand recognisable for
existing donors, volunteers, and partners visiting the new site. The 2026-06
showcase (`docs/features-showcase.html`) proposed an idealized green/gold
palette; that was an early-direction document and is **not** the source of
truth for the live UI.

The showcase still exists as a feature-catalog document (sections, accordion,
state-machine, timeline, search, tech-stack, migration walkthrough); only
the color/typography tokens are superseded by this file.

## Source

- Obs #11910 — Extracted APAP website design tokens (2026-06-13)
- Obs #12416 — Captured APAP legacy visual tokens (2026-06-15)
- Screenshot artifact: `docs/screenshots/apap-current-quienes-somos.png` (referenced from #11910; restore from git history if missing)

## Core invariants

- **`@theme` se compila desde este doc**: las variables CSS en `tailwindcss/styles/app.css` reflejan las tablas de este archivo. Cambiar un hex aquí sin tocar el `@theme` deja el bundle desincronizado; cambiar el `@theme` sin tocar este doc deja la doc mintiendo.
- **`docs/features-showcase.html` no es fuente de verdad de tokens**: es un catálogo de features; la paleta que muestra está superseded por este archivo desde el commit que introduce este doc.
- **`primary` y `primary-dark` no se reemplazan por colores cálidos**: la marca APAP depende del azul `#0A91EB` como anclaje reconocible. Sustituirlo por verde o dorado rompe la identidad.
- **`legacy-green` se preserva para el CTA sidebox de "Hazte socio"**: es un slot de conversión heredado; moverlo a `accent` naranja cambia el significado histórico del CTA.
- **Geometría Bootstrap-era se mantiene**: radio de tarjeta `0.25rem`, contenedor `1170px`, spacing scale `4px`. Subir el radio a algo "moderno" rompe continuidad visual con la web actual.
- **Captura reproducible**: los hex documentados vienen de la extracción con Playwright sobre la URL canónica. Re-capturar antes de proponer cambios; un hex sin screenshot queda como opinión.

## Contributor checklist

- [ ] Si añade un token nuevo, declararlo en la tabla correspondiente y reflejarlo en `@theme` en la misma sesión.
- [ ] Si cambia un hex, cite el screenshot o el obs que lo respalda; un hex sin captura no entra.
- [ ] Si toca `@theme` en `tailwindcss/styles/app.css`, refresque la tabla de este doc y re-capture la página afectada.
- [ ] Si propone reemplazar la paleta, abra issue con label `type:design` y vincule este archivo como ancla de la decisión actual; no edite in-place.
- [ ] Si descubre que un componente usa un hex fuera de este doc, abra issue de limpieza antes de añadir el hex al inventario.

## Navigation

Previous: [Architecture LocalBackend stack](architecture/architecture-local-backend-stack.md) | Next: [Setup local](setup.md)
