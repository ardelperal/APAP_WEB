# Mística icons and resource reference

Use this reference when a task needs Telefónica/Mística icons or visual resources.

Official icons repo: `https://github.com/Telefonica/mistica-icons`

## What exists

Mística has a dedicated multibrand icon repository. It is the source of truth for digital product icons and supports Brand Factory icons.

Repo structure on the `production` branch:

```text
animated-icons/
icons/
  blau/
  o2/
  o2-new/
  telefonica/
  vivo-new/
  icons-keywords.json
resources/
  illustrator-template.ai
ICON_TABLE.md
README.md
```

The repo includes `.svg` and `.pdf` icon assets. For web usage, prefer Mística web components/exports when available instead of copying raw SVG files into product code.

## Current repo counts verified from production

```text
telefonica: 2054 SVG icons
o2-new: 947 SVG icons
o2: 924 SVG icons
vivo-new: 1312 SVG icons
blau: 81 SVG icons
```

The README reports icon equivalence across brands and distinguishes:

- `Concepts`: unique icon names excluding style/weight variants.
- `Total`: full icon count including light, regular, and filled weights.
- `All Equivalence`: icon present in all sets.
- `Some Equivalence`: icon present in some sets.
- `Unique`: icon only exists in that set.
- `Missing`: icon missing compared with other sets.

## Icon weights and naming

Common weights/styles in filenames:

```text
light
regular
filled
```

Typical filename format:

```text
icons/telefonica/<weight>/<name>-<weight>.svg
icons/telefonica/<weight>/<name>-<weight>.pdf
```

Examples:

```text
2g-regular.svg
5g-filled.svg
chevron-right-regular.svg
```

## Web usage rule

In React projects with `@telefonica/mistica`, prefer package exports. Mística web exports many generated icon components with names like:

```tsx
Icon5GRegular
IconAddMoreRegular
IconUserAccountFilled
```

Import from `@telefonica/mistica` after checking the installed version exports the needed component.

```tsx
import {IconUserAccountRegular} from '@telefonica/mistica';
```

If the icon is not exported or the project is not using Mística web, use the SVG from the official `mistica-icons` repo only if licensing and asset policy allow it for the project.

## Selection workflow

1. Identify brand/skin: `telefonica`, `o2`, `o2-new`, `vivo-new`, or `blau`.
2. Search by concept in `icons/icons-keywords.json` or `ICON_TABLE.md`.
3. Prefer equivalent icons available across brands when building multimarca UI.
4. Choose weight by use:
   - `regular`: default functional UI icon.
   - `light`: low-emphasis or larger decorative icon.
   - `filled`: selected/active states or strong emphasis.
5. Ensure functional icons meet at least 3:1 contrast in normal, hover, and focus states.
6. Use `aria-hidden="true"` for decorative icons; provide accessible names for icon-only buttons.

## Animated icons

Animated icons live under `animated-icons/` by brand/global category. Use sparingly and respect reduced-motion preferences.

## Brand Factory resources beyond icons

Brand Factory also has official logos, photos, illustrations, backgrounds, videos, music, and employee materials. Do not scrape or recreate them. Ask for approved files or access via Brand Factory. In product code, prefer official Mística package assets/components where available.
