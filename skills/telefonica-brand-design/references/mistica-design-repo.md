# Mística design repository reference

Use this reference when precision matters for official Mística design tokens, when mapping tokens into another design system, or when reviewing token changes.

Official repo: `https://github.com/Telefonica/mistica-design`

## What this repo is

`mistica-design` is the design-only repository for Mística. It contains token JSON files, Figma token synchronization tooling, schema validation, token linting, and contribution guides.

Related official repos:

- `Telefonica/mistica-web`: web/React code libraries for Mística.
- `Telefonica/mistica-icons`: source of truth for digital product icons.

## Token source of truth

Use branch `production` and directory `tokens/`.

Main skin files:

- `tokens/telefonica.json`
- `tokens/movistar.json`
- `tokens/movistar-new.json`
- `tokens/o2.json`
- `tokens/o2-new.json`
- `tokens/vivo.json`
- `tokens/vivo-new.json`
- `tokens/blau.json`
- `tokens/tu.json`
- `tokens/esimflag.json`

Raw URL pattern:

```text
https://raw.githubusercontent.com/Telefonica/mistica-design/production/tokens/<skin>.json
```

For exact values, fetch the JSON instead of relying on copied notes. The local helper can do this:

```bash
python scripts/mistica_tokens.py --skin telefonica --summary
python scripts/mistica_tokens.py --skin telefonica --css --out mistica-telefonica.css
python scripts/mistica_tokens.py --skin telefonica --json --out telefonica.json
```

## Token JSON structure

Each skin JSON follows this top-level structure:

```json
{
  "light": {},
  "dark": {},
  "radius": {},
  "text": {
    "weight": {},
    "size": {},
    "lineHeight": {}
  },
  "spacing": {},
  "themeVariant": {},
  "componentProperties": {},
  "global": {
    "palette": {}
  }
}
```

Important concepts:

- `global.palette` contains raw brand palette values and no light/dark logic.
- `light` and `dark` contain semantic tokens for color scheme behavior.
- Constants should reference palette values using `{palette.name}` or `rgba({palette.name}, alpha)`, not inline hex.
- `description` should match the referenced palette name when the value references `{palette.*}`.
- Gradients can be object values with `angle` and `colors` stops; for component overlays, prefer `rgba()` values even for solid stops when required by Mística overrides.

## Current Telefónica token facts from production

Top-level keys: `light`, `dark`, `radius`, `text`, `spacing`, `themeVariant`, `componentProperties`, `global`.

Radius:

```text
avatar: circle
bar: 0
button: 32
checkbox: 2
container: 4
indicator: 24
chip: 24
tag: 24
input: 8
legacyDisplay: 0
popup: 4
sheet: 0
mediaSmall: 2
```

Text sizes:

```text
text1: mobile 12 / desktop 14, line-height 16 / 20
text2: mobile 14 / desktop 16, line-height 20 / 24
text3: mobile 16 / desktop 18, line-height 24 / 24
text4: mobile 18 / desktop 20, line-height 24 / 28
text5: mobile 20 / desktop 28, line-height 24 / 32
text6: mobile 24 / desktop 32, line-height 32 / 40
text7: mobile 28 / desktop 40, line-height 32 / 48
text8: mobile 32 / desktop 48, line-height 40 / 56
text9: mobile 40 / desktop 56, line-height 48 / 64
text10: mobile 48 / desktop 64, line-height 56 / 72
```

Other useful text sizes:

```text
title1: 12 / 14, line-height 16 / 20
title2: 16 / 18, line-height 24 / 24
title3: 20 / 28, line-height 24 / 32
title4: 24 / 32, line-height 32 / 40
cardTitleDefault: 18 / 20, line-height 24 / 28
drawerTitle: 20 / 28, line-height 24 / 32
inputValue: 16 / 18, line-height 24 / 24
chipLabel: 14 / 16, line-height 20 / 24
```

Text weights:

```text
medium: button, tabsLabel, link, title1, indicator, navigationBar, chipLabel
regular: cardTitle, drawerTitle, rowTitle, title2, title3, title4, text5-text10
```

Spacing:

```text
buttonDefaultPadding: left/right 20 mobile+desktop
buttonSmallPadding: left/right 14 mobile+desktop
cardDefaultPadding: 16 mobile / 24 desktop on all sides
inputPadding: top/bottom 8
tagPadding: top/bottom 4
feedbackScreenPadding: top 64, bottom 16 mobile / 64 desktop, left/right 16 mobile / 64 desktop
heroPadding: top/bottom 24 mobile / 56 desktop
headerPadding: top/bottom 24 mobile / 48 desktop
drawerPadding: top 32 mobile / 40 desktop, bottom 16 / 24, left/right 16 / 40
```

Current Telefónica palette includes:

```text
telefonicaBlue, telefonicaBlue10, telefonicaBlue20, telefonicaBlue30, telefonicaBlue70, telefonicaBlue80
ambar, ambar10, ambar40, ambar70
yellow, yellow15, yellow40, yellow70, yellow80
coral, coral10, coral30, coral60, coral65, coral80, coral90
orchid, orchid10, orchid40, orchid70, orchid80
turquoise, turquoise10, turquoise40, turquoise70, turquoise80
grey1-grey9, white, black
darkModeBlack, darkModeGrey, darkModeGrey6, darkModeTelefonicaBlue
```

## Official validation discipline

The repo has a token linter in `tokens/linter`.

It validates:

- Format: `description` must match `{palette.*}` references and palette references must exist.
- Contrast: foreground/background pairs defined in `contrastPairs.js` are checked against WCAG ratios. It skips gradients and `rgba()` colors.
- CI mode defaults to format checks across all token files.

When copying this discipline to a project, at minimum add a token review checklist:

- No semantic token uses inline hex when a palette alias exists.
- Palette references resolve.
- Description matches referenced palette token.
- Light and dark semantic counterparts are both considered.
- Text/background and UI contrast pairs pass WCAG AA where applicable.

## Extended token rule

Use Mística default tokens first. If a product-specific case is not covered, create extended tokens rather than mutating core Mística semantics casually.

Rules for extended tokens:

- Keep the same brand/color-scheme logic idea: palette values underneath, semantic token on top.
- Avoid breaking direct consumers by renaming/removing palette tokens.
- Review extended tokens when upstream Mística palette names or values change.

## Deprecation rule

When a token is superseded, do not rename it destructively. Add metadata:

```json
{
  "deprecated": true,
  "deprecatedBy": "replacementTokenName"
}
```

Figma sync middleware prefixes deprecated variables with `DEPRECATED_` and tries rename-safe lookup to preserve existing bindings.

## Figma sync facts

The repo no longer uses the old Figma Tokens plugin for syncing. It uses Figma API scripts under `tokens/figma` to update variables and collections for Mode and Brand.

Do not tell agents to use the Figma Tokens plugin as the current source workflow. If a project needs Figma sync, point to the official repo/scripts and require `FIGMA_TOKEN`.
