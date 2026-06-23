# Design tokens — APAP Alcalá (current site)

Captured from `https://www.apap-alcala.org/quienes_somos.php` with Playwright
on 2026-06-13 (#11910) and 2026-06-15 (#12416). These are the visual tokens of
the **current** APAP Alcalá website. The new APAP_WEB frontend should inherit
this palette so the brand stays recognisable.

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
