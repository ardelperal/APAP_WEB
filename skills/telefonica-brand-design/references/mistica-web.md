# Mística web reference - Telefónica skin

Use this reference when applying Telefónica design to web/React/Next.js products or when mapping a project token layer to Mística semantics.

Verified anchors:
- Mística is Telefónica's Digital Design System and has development repos for web, Android, and iOS.
- The React package is `@telefonica/mistica`.
- `mistica-web` exports `ThemeContextProvider`, `getTelefonicaSkin`, `ButtonPrimary`, `ButtonSecondary`, `ButtonDanger`, `ButtonLink`, `Text1`–`Text10`, `Title1`–`Title4`, layout primitives, form controls, cards, hero, navigation, logo components, and skin utilities.
- Source design tokens live in `Telefonica/mistica-design`, branch `production`, under `tokens/telefonica.json`.

---

## What Mística is

Mística is the official Telefónica Digital Design System: a shared language, guideline set, and component system for digital Telefónica products. It supports multiple skins: Telefónica, Movistar, O2, Vivo, Blau, TU, and eSIM Flag.

---

## Preferred React integration

If the project is React/Next.js and adding dependencies is in scope, prefer official Mística components over custom clones.

```bash
npm install @telefonica/mistica
```

```tsx
import {
  ThemeContextProvider,
  getTelefonicaSkin,
  ButtonPrimary,
  ButtonSecondary,
  Text2,
  Title1,
  Stack,
  Box,
} from '@telefonica/mistica';

export function App() {
  return (
    <ThemeContextProvider
      theme={{
        skin:    getTelefonicaSkin(),
        i18n:    { locale: 'es-ES', phoneNumberFormattingRegionCode: 'ES' },
        colorScheme: 'auto',   // 'light' | 'dark' | 'auto'
      }}
    >
      <Stack space={16}>
        <Title1>Activa tu experiencia digital</Title1>
        <Text2>Te echamos una mano para empezar.</Text2>
        <Box padding={16}>
          <ButtonPrimary onPress={() => {}}>Contactar</ButtonPrimary>
          <ButtonSecondary onPress={() => {}}>Ver detalles</ButtonSecondary>
        </Box>
      </Stack>
    </ThemeContextProvider>
  );
}
```

Important: some examples online use generic `<Button variant="primary" />`; verify against the installed package version before applying. Current exported primitives include explicit button components such as `ButtonPrimary` and `ButtonSecondary`.

---

## Dark mode

Mística handles dark mode via the `colorScheme` prop on `ThemeContextProvider`:

```tsx
// Follow the OS preference automatically
<ThemeContextProvider theme={{ skin: getTelefonicaSkin(), colorScheme: 'auto', i18n: {...} }}>

// Force light
<ThemeContextProvider theme={{ skin: getTelefonicaSkin(), colorScheme: 'light', i18n: {...} }}>

// Force dark
<ThemeContextProvider theme={{ skin: getTelefonicaSkin(), colorScheme: 'dark', i18n: {...} }}>
```

For CSS-only projects (non-Mística), dark tokens are in `brand-guidelines.md` under the `@media (prefers-color-scheme: dark)` block.

---

## Next.js integration

Install and configure as usual; Mística works with App Router and Pages Router.

```bash
npm install @telefonica/mistica
```

Add to `app/layout.tsx` (App Router):

```tsx
import {ThemeContextProvider, getTelefonicaSkin} from '@telefonica/mistica';
import '@telefonica/mistica/css/mistica.css';  // if package exposes CSS

export default function RootLayout({children}: {children: React.ReactNode}) {
  return (
    <html lang="es">
      <body>
        <ThemeContextProvider
          theme={{
            skin:        getTelefonicaSkin(),
            i18n:        { locale: 'es-ES', phoneNumberFormattingRegionCode: 'ES' },
            colorScheme: 'auto',
          }}
        >
          {children}
        </ThemeContextProvider>
      </body>
    </html>
  );
}
```

For SSR components that use hooks, mark them `'use client'` since `ThemeContextProvider` uses React context.

---

## Navigation bar

```tsx
import {
  NavigationBar,
  NavigationBarActionGroup,
  NavigationBarAction,
  Logo,
} from '@telefonica/mistica';

<NavigationBar
  logo={<Logo size={48} type="imagotype" />}
  right={
    <NavigationBarActionGroup>
      <NavigationBarAction
        onPress={() => {}}
        aria-label="Mi cuenta"
        Icon={IconUserAccountRegular}
      />
    </NavigationBarActionGroup>
  }
/>
```

For full header layouts with desktop navigation links, combine `NavigationBar` with the `Header` or `MainNavigationBar` component depending on the installed version.

---

## Responsive / breakpoints

Mística uses an internal breakpoint system (mobile-first). The breakpoints align with the Brand Factory ones documented in `brand-guidelines.md`:

| Name | Width |
|------|------:|
| sm   | 640px |
| md   | 768px |
| lg   | 1024px |
| xl   | 1280px |

Use Mística layout primitives (`GridLayout`, `Stack`, `Box`, `Inline`) for responsive composition instead of custom media queries where possible:

```tsx
import {GridLayout, Stack, Box} from '@telefonica/mistica';

<GridLayout
  template="6"            // 6-column span on desktop
  verticalSpace={16}
>
  <Stack space={16}>
    <Title1>Conectamos tu futuro</Title1>
    <Text2>Descubre nuestros servicios.</Text2>
    <ButtonPrimary onPress={() => {}}>Empezar</ButtonPrimary>
  </Stack>
</GridLayout>
```

---

## Hero component

```tsx
import {Hero, ButtonPrimary, ButtonLink} from '@telefonica/mistica';

<Hero
  headline={<Tag type="promo">Novedad</Tag>}
  title="Conectamos lo que importa"
  description="Servicios digitales para empresas y particulares con la mejor cobertura."
  background="default"
  button={<ButtonPrimary onPress={() => {}}>Descubrir</ButtonPrimary>}
  secondaryButton={<ButtonLink onPress={() => {}}>Saber más</ButtonLink>}
  media={<Image src="/hero.jpg" alt="" aspectRatio="16:9" />}
/>
```

---

## Source token files

Known skin JSON files include:

- `telefonica.json`
- `movistar.json`, `movistar-new.json`
- `o2.json`, `o2-new.json`
- `vivo.json`, `vivo-new.json`
- `blau.json`
- `tu.json`
- `esimflag.json`

When precision matters, read `references/mistica-design-repo.md` and fetch the current JSON from `https://raw.githubusercontent.com/Telefonica/mistica-design/production/tokens/telefonica.json` instead of trusting stale copied values.

---

## Palette - Telefónica skin

```css
:root {
  --mistica-telefonicaBlue:   #0066ff;
  --mistica-telefonicaBlue10: #e5f0ff;
  --mistica-telefonicaBlue20: #b2d1ff;
  --mistica-telefonicaBlue30: #80b3ff;
  --mistica-telefonicaBlue70: #0356c9;
  --mistica-telefonicaBlue80: #002e73;

  --mistica-white: #ffffff;
  --mistica-black: #000000;
  --mistica-grey1: #f7f7ff;
  --mistica-grey2: #d1d5e4;
  --mistica-grey3: #b0b6ca;
  --mistica-grey4: #8f97af;
  --mistica-grey5: #6e7894;
  --mistica-grey6: #58617a;
  --mistica-grey7: #414b61;
  --mistica-grey8: #2b3447;
  --mistica-grey9: #031a34;

  --mistica-darkModeBlack:         #000522;
  --mistica-darkModeGrey:          #00182f;
  --mistica-darkModeGrey6:         #00264d;
  --mistica-darkModeTelefonicaBlue:#227aff;

  --mistica-ambar:   #eac344;
  --mistica-ambar10: #fdf9ec;
  --mistica-ambar40: #f0d57c;
  --mistica-ambar70: #69581f;

  --mistica-yellow:   #e4c35c;
  --mistica-yellow15: #fcf7db;
  --mistica-yellow40: #f3e996;
  --mistica-yellow70: #a7863e;
  --mistica-yellow80: #473515;

  --mistica-coral:   #d6786b;
  --mistica-coral10: #f9eeed;
  --mistica-coral30: #f2b1a5;
}
```

---

## Semantic colors - light mode

Prefer these semantic names in app code. Keep palette aliases internal.

```css
:root {
  --appBarBackground:              #ffffff;
  --background:                    #ffffff;
  --backgroundContainer:           #ffffff;
  --backgroundContainerError:      var(--mistica-coral10);
  --backgroundContainerHover:      rgba(3, 86, 201, 0.05);
  --backgroundContainerPressed:    rgba(3, 86, 201, 0.08);
  --backgroundContainerBrand:      var(--mistica-telefonicaBlue);
  --backgroundContainerAlternative:var(--mistica-grey1);

  --textPrimary:        var(--mistica-grey9);
  --textSecondary:      var(--mistica-grey6);
  --textDisabled:       var(--mistica-grey5);
  --textPrimaryInverse: var(--mistica-white);
  --textLink:           var(--mistica-telefonicaBlue);

  --brand:                var(--mistica-telefonicaBlue);
  --brandHigh:            var(--mistica-telefonicaBlue70);
  --inverse:              var(--mistica-white);
  --neutralHigh:          var(--mistica-grey9);
  --neutralMedium:        var(--mistica-grey5);
  --neutralLow:           var(--mistica-grey2);
  --neutralLowAlternative:var(--mistica-grey1);

  --buttonPrimaryBackground:     var(--mistica-telefonicaBlue);
  --buttonPrimaryBackgroundHover:var(--mistica-telefonicaBlue70);
  --buttonPrimaryText:           var(--mistica-white);
  --buttonPrimaryTextHover:      var(--mistica-white);

  --buttonSecondaryBackground:      transparent;
  --buttonSecondaryBorder:          var(--mistica-telefonicaBlue);
  --buttonSecondaryText:            var(--mistica-telefonicaBlue);
  --buttonSecondaryBackgroundHover: var(--mistica-telefonicaBlue10);
  --buttonSecondaryTextHover:       var(--mistica-telefonicaBlue70);

  --buttonDangerBackground: var(--mistica-coral);
  --buttonDangerText:       var(--mistica-white);
  --buttonLinkText:         var(--mistica-telefonicaBlue);

  --warning:   var(--mistica-ambar70);
  --warningLow:var(--mistica-ambar10);
  --info:      var(--mistica-telefonicaBlue);
  --infoLow:   var(--mistica-telefonicaBlue10);
}
```

### Semantic colors - dark mode

```css
@media (prefers-color-scheme: dark) {
  :root {
    --appBarBackground:               var(--mistica-darkModeBlack);
    --background:                     var(--mistica-darkModeBlack);
    --backgroundContainer:            var(--mistica-darkModeGrey);
    --backgroundContainerAlternative: var(--mistica-darkModeGrey6);
    --backgroundContainerBrand:       var(--mistica-darkModeTelefonicaBlue);

    --textPrimary:        var(--mistica-white);
    --textSecondary:      var(--mistica-grey3);
    --textDisabled:       var(--mistica-grey6);
    --textPrimaryInverse: var(--mistica-grey9);
    --textLink:           var(--mistica-darkModeTelefonicaBlue);

    --brand:     var(--mistica-darkModeTelefonicaBlue);
    --brandHigh: #3d8fff;
    --inverse:   var(--mistica-grey9);

    --buttonPrimaryBackground:      var(--mistica-darkModeTelefonicaBlue);
    --buttonPrimaryBackgroundHover: #3d8fff;
    --buttonSecondaryBorder:        var(--mistica-darkModeTelefonicaBlue);
    --buttonSecondaryText:          var(--mistica-darkModeTelefonicaBlue);
    --buttonSecondaryBackgroundHover:var(--mistica-darkModeGrey6);
    --buttonLinkText:               var(--mistica-darkModeTelefonicaBlue);
  }
}
```

For success/error/promo tokens, use the current official JSON if exact values matter; some are palette-dependent or omitted from the user's extracted snippet.

---

## Radius tokens

For Mística web UI, use these instead of the Brand Factory marketing button radius:

```css
:root {
  --radius-avatar:    50%;
  --radius-bar:       0px;
  --radius-button:    32px;
  --radius-checkbox:  2px;
  --radius-container: 4px;
  --radius-indicator: 24px;
  --radius-chip:      24px;
  --radius-tag:       24px;
  --radius-input:     8px;
  --radius-popup:     4px;
  --radius-sheet:     0px;
  --radius-mediaSmall:2px;
}
```

Rule: Mística Telefónica button radius is `32px`. Brand Factory examples may use `50px`; for web product UI, prefer the skin token.

---

## Spacing tokens

```css
:root {
  --buttonDefaultPadding-left:  20px;
  --buttonDefaultPadding-right: 20px;
  --buttonSmallPadding-left:    14px;
  --buttonSmallPadding-right:   14px;
  --cardDefaultPadding-mobile:  16px;
  --cardDefaultPadding-desktop: 24px;
  --inputPadding-top:           8px;
  --inputPadding-bottom:        8px;
  --tagPadding-top:             4px;
  --tagPadding-bottom:          4px;
  --feedbackScreenPadding-desktop: 64px;
  --feedbackScreenPadding-mobile:  16px;
  --heroPadding-mobile:         24px;
  --heroPadding-desktop:        56px;
  --headerPadding-mobile:       24px;
  --headerPadding-desktop:      48px;
}
```

---

## Typography and text presets

Font family:

```css
:root {
  --mistica-font-family: "Telefonica Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
}
```

Official font files are proprietary/licensed. Do not fabricate or ship them.

Text presets:

| Token | Mobile | Desktop | Line-height M/D | Typical use |
|---|---:|---:|---|---|
| `text1` | 12px | 14px | 16/20 | Captions/legal |
| `text2` | 14px | 16px | 20/24 | Secondary text |
| `text3` | 16px | 18px | 24/24 | Body |
| `text4` | 18px | 20px | 24/28 | Highlighted body |
| `text5` | 20px | 28px | 24/32 | Large body |
| `text6` | 24px | 32px | 32/40 | Display small |
| `text7` | 28px | 40px | 32/48 | Display medium |
| `text8` | 32px | 48px | 40/56 | Display large |
| `text9` | 40px | 56px | 48/64 | Display XL |
| `text10` | 48px | 64px | 56/72 | Display XXL |
| `title1` | 12px | 14px | 16/20 | Labels/tabs |
| `title2` | 16px | 18px | 24/24 | Section titles |
| `title3` | 20px | 28px | 24/32 | Highlight titles |
| `title4` | 24px | 32px | 32/40 | Hero titles |
| `cardTitleDefault` | 18px | 20px | 24/28 | Card title |
| `cardSubtitleDefault` | 14px | 16px | 20/24 | Card subtitle |
| `cardDescriptionDefault` | 14px | 16px | 20/24 | Card body |
| `tabsLabel` | 16px | 18px | 24/24 | Tabs |

Weights by semantic element:

```text
medium:  button, tabsLabel, link, title1, indicator, navigationBar, chipLabel
regular: cardTitle, drawerTitle, rowTitle, title2, title3, title4, text5–text10
```

Caveat: in Mística, large text presets from `text5` upward are skin-defined. Do not freestyle weights for large headings; use the skin/component preset.

---

## Available component families

Mística covers: accordion, avatar, badge, breadcrumbs, buttons, callout, cards, carousel, checkbox, chips, data visualizations, header, hero, input fields, lists, loading/progress, logo, menu, modals/sheets/popovers, mosaic, navigation bars, radio, rating, select, skeletons, skip link, slider, snackbar, spinner, stacking group, stepper, switch, table, tabs/tab bars, tag, text link, timeline, timer, title, tooltip.

Use official components when available; only custom-build when the project is not React, cannot accept the dependency, or needs a thin wrapper around existing components.

---

## Token override / extension pattern

To extend Mística tokens in a React project without mutating the core skin:

```tsx
import {getTelefonicaSkin, applyTheme} from '@telefonica/mistica';

const customSkin = {
  ...getTelefonicaSkin(),
  colors: {
    ...getTelefonicaSkin().colors,
    // extended tokens — project-specific additions
    backgroundHero: '#031a34',
  },
};

<ThemeContextProvider theme={{ skin: customSkin, i18n: {...} }}>
```

Follow the extended-token rules from `mistica-design-repo.md`: keep palette-under-semantic structure; avoid renaming palette tokens that other consumers depend on.

---

## Asset rules

Brand Factory resources include official logos, icons, photos, illustrations, backgrounds, videos, music, and employee material. Do not scrape or recreate them. Ask for approved files or use the official package/component when available.
