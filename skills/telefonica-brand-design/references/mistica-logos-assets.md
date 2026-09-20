# Mística logos and official asset locations

Use this reference when a task needs Telefónica/Mística logos or raw resource locations.

## Important legal/brand rule

Do not scrape, redraw, or casually copy Telefónica logos into a product. Logos are trademarks. For production brand usage, prefer official Mística components or approved Brand Factory asset downloads.

The official package/repo can provide implementation source, but that does not replace brand approval for external/commercial use.

## Where logos are in the repos

### React/product logos: `Telefonica/mistica-web`

The usable web implementation lives in `mistica-web`, not in `mistica-design` and not as a simple `/logos` asset folder.

Relevant source files:

```text
src/logo.tsx
src/logo-common.tsx
src/logo.css.ts
src/logo-telefonica.tsx
src/logo-telefonica-shell.tsx
src/logo-movistar.tsx
src/logo-movistar-new.tsx
src/logo-o2.tsx
src/logo-o2-new.tsx
src/logo-vivo.tsx
src/logo-blau.tsx
src/logo-tu.tsx
src/logo-esimflag.tsx
```

Package exports include:

```tsx
Logo
TelefonicaLogo
MovistarLogo
MovistarNewLogo
VivoLogo
O2Logo
O2NewLogo
BlauLogo
TuLogo
EsimflagLogo
```

Usage pattern:

```tsx
import {TelefonicaLogo, Logo} from '@telefonica/mistica';

<TelefonicaLogo size={48} type="imagotype" />
<Logo size={{mobile: 40, desktop: 48}} />
```

Logo type values:

```ts
type LogoType = 'isotype' | 'imagotype' | 'vertical';
```

Caution: Brand Factory says not to use the Telefónica standalone T/isotype independently in normal brand communications. Even though the component supports `isotype`, prefer `imagotype` or the approved lockup unless the use case explicitly allows the compact mark.

### Mística/product icons: `Telefonica/mistica-icons`

Raw icons live in the `mistica-icons` repo:

```text
icons/telefonica/<weight>/<name>-<weight>.svg
icons/telefonica/<weight>/<name>-<weight>.pdf
icons/icons-keywords.json
ICON_TABLE.md
animated-icons/
resources/illustrator-template.ai
```

Verified current SVG counts:

```text
telefonica: 2054
o2-new: 947
o2: 924
vivo-new: 1312
blau: 81
```

Use raw SVG/PDF only when a project cannot use Mística web exports or when a design workflow specifically needs the source assets.

### Brand Factory resources

Brand Factory is still the official place for approved downloadable brand resources like logos, photos, illustrations, backgrounds, videos, music, and employee material. In GitHub, I found Mística implementation assets and icon sources, not a general public Brand Factory resource dump of all official logos/photos/backgrounds.

## How to find a needed icon

1. Clone/open `Telefonica/mistica-icons` on `production`.
2. Search `icons/icons-keywords.json` first for concepts.
3. Check `ICON_TABLE.md` for cross-brand equivalence.
4. Pick brand folder and weight: `light`, `regular`, or `filled`.
5. Prefer `regular` for functional UI, `filled` for selected/active states, and `light` for low-emphasis/decorative cases.

## How to find a needed logo

1. In React, import from `@telefonica/mistica`.
2. Use `TelefonicaLogo` for explicit Telefónica brand, or `Logo` to follow the active skin.
3. Use `type="imagotype"` as the safe default for Telefónica lockup.
4. Use `type="vertical"` only when layout calls for it.
5. Avoid `type="isotype"` unless there is explicit brand permission for that specific context.

## What NOT to do

- Do not extract path data from `src/logo-telefonica.tsx` and paste it into arbitrary files unless the project has a clear reason not to use the package component.
- Do not use GitHub README/Mística logos (`img/mistica-logo.svg`, `.github/resources/...`) as Telefónica corporate logos.
- Do not treat `simple-icons` or third-party logo repositories as official Telefónica brand sources.
