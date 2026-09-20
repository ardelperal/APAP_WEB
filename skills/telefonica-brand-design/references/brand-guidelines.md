# Telefónica Brand Factory-inspired reference

Use this as the canonical local reference for the `telefonica-brand-design` skill. It condenses the user-provided Brand Factory analysis into actionable implementation guidance.

## Brand essence

- Purpose: become the best access route for citizens to digital technologies.
- Mission: offer the best digital experience through connectivity, advanced services, innovation, and service excellence.
- Vision: be a world-reference European operator with profitable scale and leadership in digital transformation.
- Attitudes: give our best, challenge our limits, improve together.
- Personality: challenging, open, trustworthy, inspiring, and close.

## Voice

- Start with action and use active verbs.
- Lead with user benefit and optimism.
- Be transparent, grounded, and reliable; do not overpromise.
- Prefer natural language over corporate phrasing.
- Spanish writing rules:
  - Numbers one to nine in words; 10+ in digits.
  - Percentages, measures, and prices always in digits.
  - Space before units/symbols such as `€` and `%`.
  - Bullet periods only for complete sentences.
  - Use RAE capitalization; avoid unnecessary title case.

---

## Responsive breakpoints (recommended, not official Mística tokens)

These breakpoints are practical recommendations for corporate websites. They are not official Mística skin tokens — Mística handles responsive sizing internally via its components. Use them for custom CSS layouts.

```css
:root {
  --bp-sm: 640px;    /* phone landscape / small tablet */
  --bp-md: 768px;    /* tablet portrait */
  --bp-lg: 1024px;   /* tablet landscape / small desktop */
  --bp-xl: 1280px;   /* desktop */
}
```

Usage in media queries:

```css
/* mobile-first */
@media (min-width: 640px)  { /* sm */  }
@media (min-width: 768px)  { /* md */  }
@media (min-width: 1024px) { /* lg */  }
@media (min-width: 1280px) { /* xl */  }
```

---

## Spacing scale (recommended, not official Mística tokens)

Base unit: 8px. These are practical recommendations for custom CSS layouts. Mística has its own spacing tokens — use `mistica_tokens.py --spacing` for official values.

```css
:root {
  --space-1:  4px;
  --space-2:  8px;
  --space-3:  12px;
  --space-4:  16px;
  --space-5:  24px;
  --space-6:  32px;
  --space-7:  40px;
  --space-8:  48px;
  --space-9:  56px;
  --space-10: 64px;
  --space-12: 80px;
  --space-16: 96px;

  /* Section padding */
  --section-padding-mobile:  40px;
  --section-padding-desktop: 80px;

  /* Container max-width and gutter */
  --container-max:    1280px;
  --container-gutter-mobile:  16px;
  --container-gutter-desktop: 40px;
}
```

---

## Core color tokens — light mode

```css
:root {
  --tf-blue:       #0066ff;
  --tf-blue-70:    #0356c9;
  --tf-blue-10:    #e5f0ff;
  --tf-white:      #f7f7ff;
  --tf-white-pure: #ffffff;
  --tf-navy:       #031a34;

  --tf-text-primary:   #031a34;
  --tf-text-secondary: #58617a;
  --tf-text-disabled:  #8f97af;
  --tf-text-inverse:   #ffffff;
  --tf-text-link:      #0066ff;

  --tf-nav-text:       rgb(103 103 103);
  --tf-nav-text-hover: rgb(65 75 97);
  --tf-nav-category:   rgb(0 102 255);
  --tf-nav-bg-hover:   rgb(242 244 255);

  --tf-background:           #ffffff;
  --tf-background-alt:       #f7f7ff;
  --tf-background-dark:      #031a34;
  --tf-background-brand:     #0066ff;

  --tf-border:       #d1d5e4;
  --tf-border-focus: #0066ff;

  --tf-radius-module: 10px;
  --tf-radius-pill:   50px;
  --tf-radius-card:    8px;
  --tf-radius-input:   8px;
  --tf-radius-button: 32px;  /* Mística product UI */
}
```

### Dark mode overrides (derived from official Mística palette)

These overrides use official Mística `darkMode*` palette values where available. Values marked `/* derived */` are calculated from the official palette and not directly sourced from the token JSON — verify against `mistica_tokens.py --semantic` for production accuracy.

```css
@media (prefers-color-scheme: dark) {
  :root {
    --tf-blue:       #227aff;   /* official: darkModeTelefonicaBlue */
    --tf-blue-70:    #3d8fff;   /* derived — lighter shade for dark backgrounds */
    --tf-blue-10:    #00264d;   /* official: darkModeGrey6 */

    --tf-text-primary:   #ffffff;
    --tf-text-secondary: #b0b6ca;
    --tf-text-disabled:  #58617a;
    --tf-text-inverse:   #031a34;
    --tf-text-link:      #227aff;

    --tf-background:     #000522;   /* darkModeBlack */
    --tf-background-alt: #00182f;   /* darkModeGrey */
    --tf-background-dark: #000522;
    --tf-background-brand: #0066ff; /* keep brand color consistent */

    --tf-border:       #00264d;     /* darkModeGrey6 */
    --tf-border-focus: #227aff;

    --tf-nav-text:       #b0b6ca;
    --tf-nav-text-hover: #ffffff;
    --tf-nav-category:   #227aff;
    --tf-nav-bg-hover:   #00264d;
  }
}
```

---

## Grays

```css
:root {
  --tf-gray-0: #ffffff;
  --tf-gray-1: #d1d5e4;
  --tf-gray-2: #b0b6ca;
  --tf-gray-3: #8f97af;
  --tf-gray-4: #6e7894;
  --tf-gray-5: #58617a;
  --tf-gray-6: #414b61;
  --tf-gray-7: #2b3447;
  --tf-gray-8: #031a34;
}
```

Note: `#031A34` is "Grey 9" in Mística notation and `#58617A` is "Grey 6". Preserve project naming if it already has semantic aliases like `text-primary` and `text-secondary`.

---

## Secondary palettes

```css
:root {
  --tf-teal-very-light: #ebffff;
  --tf-teal-light:      #c5f8f9;
  --tf-teal:            #75c0c7;
  --tf-teal-dark:       #528889;
  --tf-teal-very-dark:  #253d3c;

  --tf-yellow-very-light: #fcf7db;
  --tf-yellow-light:      #f3e996;
  --tf-yellow:            #e4c35c;
  --tf-yellow-dark:       #a7863e;
  --tf-yellow-very-dark:  #473515;

  --tf-orange-very-light: #fff8f3;
  --tf-orange-light:      #fce3cd;
  --tf-orange:            #f4c495;
  --tf-orange-dark:       #c48349;
  --tf-orange-very-dark:  #63442a;

  --tf-red-very-light: #f9eeed;
  --tf-red-light:      #f2b1a5;
  --tf-red:            #d6786b;
  --tf-red-dark:       #843c34;
  --tf-red-very-dark:  #491818;

  --tf-purple-very-light: #fbf0ff;
  --tf-purple-light:      #e1c3f4;
  --tf-purple:            #b86be8;
  --tf-purple-dark:       #7f258e;
  --tf-purple-very-dark:  #471551;
}
```

---

## Elevation / shadows (recommended, not official Mística tokens)

These shadows are practical recommendations for corporate websites. Mística handles elevation through its components internally. Use these for custom CSS layouts only.

```css
:root {
  --tf-shadow-sm:  0 1px 3px rgba(3, 26, 52, .08), 0 1px 2px rgba(3, 26, 52, .06);
  --tf-shadow-md:  0 4px 12px rgba(3, 26, 52, .10), 0 2px 4px rgba(3, 26, 52, .06);
  --tf-shadow-lg:  0 12px 32px rgba(3, 26, 52, .12), 0 4px 8px rgba(3, 26, 52, .06);
  --tf-shadow-xl:  0 24px 48px rgba(3, 26, 52, .14), 0 8px 16px rgba(3, 26, 52, .08);
}

@media (prefers-color-scheme: dark) {
  :root {
    --tf-shadow-sm:  0 1px 3px rgba(0, 0, 0, .30);
    --tf-shadow-md:  0 4px 12px rgba(0, 0, 0, .35);
    --tf-shadow-lg:  0 12px 32px rgba(0, 0, 0, .40);
    --tf-shadow-xl:  0 24px 48px rgba(0, 0, 0, .50);
  }
}
```

---

## Typography

Official family: `Telefonica Sans`. It is exclusive/licensed. Do not fabricate or ship font files.

Recommended CSS stack:

```css
:root {
  --tf-font-family:   "Telefonica Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --tf-font-regular:  400;
  --tf-font-medium:   500;
  --tf-font-demibold: 600;
  --tf-font-bold:     900;
}
```

Hierarchy defaults with fluid sizing:

```css
h1 {
  font-family:  var(--tf-font-family);
  font-weight:  var(--tf-font-regular);
  font-size:    clamp(2.25rem, 5vw + 1rem, 3.75rem);
  line-height:  1.05;
  letter-spacing: -0.01em;
  color:        var(--tf-blue);
}

h2 {
  font-family:  var(--tf-font-family);
  font-weight:  var(--tf-font-regular);
  font-size:    clamp(1.625rem, 3vw + .5rem, 2.25rem);
  line-height:  1.2;
  color:        var(--tf-text-primary);
}

h3 {
  font-family:  var(--tf-font-family);
  font-weight:  var(--tf-font-medium);
  font-size:    clamp(1.25rem, 2vw + .25rem, 1.625rem);
  line-height:  1.3;
  color:        var(--tf-text-primary);
}

h4 {
  font-family:  var(--tf-font-family);
  font-weight:  var(--tf-font-medium);
  font-size:    1.125rem;
  line-height:  1.4;
  color:        var(--tf-text-primary);
}

body, p {
  font-family:  var(--tf-font-family);
  font-weight:  var(--tf-font-regular);
  font-size:    1rem;
  line-height:  1.6;
  color:        var(--tf-text-secondary);
}

.tf-text-sm {
  font-size:   .875rem;
  line-height: 1.5;
}

.tf-text-xs {
  font-size:   .75rem;
  line-height: 1.4;
}

a {
  color:           var(--tf-text-link);
  text-decoration: none;
  font-weight:     var(--tf-font-medium);
  transition:      color .15s ease;
}
a:hover { color: var(--tf-blue-70); text-decoration: underline; }
```

Usage: Regular/Medium for headings; Regular for body; DemiBold/Bold for brief emphasis. Prefer one weight per text block.

---

## Layout grid

```css
.tf-container {
  width:     100%;
  max-width: var(--container-max);
  margin:    0 auto;
  padding:   0 var(--container-gutter-mobile);
}

@media (min-width: 1024px) {
  .tf-container {
    padding: 0 var(--container-gutter-desktop);
  }
}

.tf-grid {
  display:               grid;
  grid-template-columns: repeat(4, 1fr);
  gap:                   var(--space-4);
}

@media (min-width: 768px) {
  .tf-grid { grid-template-columns: repeat(8, 1fr); }
}

@media (min-width: 1024px) {
  .tf-grid {
    grid-template-columns: repeat(12, 1fr);
    gap:                   var(--space-6);
  }
}
```

---

## Buttons

Mística Telefónica product: `border-radius: 32px`.
Brand Factory marketing (non-Mística): `border-radius: 50px` (pill).

### Base

```css
.tf-button {
  display:         inline-flex;
  align-items:     center;
  justify-content: center;
  gap:             .5rem;
  min-height:      2.75rem;
  padding:         .625rem 1.25rem;
  border-radius:   var(--tf-radius-button);    /* 32px for Mística UI */
  border:          2px solid transparent;
  font-family:     var(--tf-font-family);
  font-size:       .875rem;
  font-weight:     var(--tf-font-medium);
  line-height:     1.3;
  text-transform:  none;
  cursor:          pointer;
  text-decoration: none;
  transition:      background .15s ease, color .15s ease, border-color .15s ease;
  white-space:     nowrap;
}

.tf-button:focus-visible {
  outline:        3px solid color-mix(in srgb, var(--tf-blue), white 45%);
  outline-offset: 3px;
}

.tf-button:disabled,
.tf-button[aria-disabled="true"] {
  opacity: .4;
  cursor:  not-allowed;
  pointer-events: none;
}
```

### Primary

```css
.tf-button--primary {
  color:            #ffffff;
  background:       var(--tf-blue);
  border-color:     var(--tf-blue);
}
.tf-button--primary:hover {
  background:   var(--tf-blue-70);
  border-color: var(--tf-blue-70);
}
```

### Secondary (Mística digital product style)

```css
.tf-button--secondary {
  color:        var(--tf-blue);
  background:   transparent;
  border-color: var(--tf-blue);
}
.tf-button--secondary:hover {
  background:   var(--tf-blue-10);
  border-color: var(--tf-blue-70);
  color:        var(--tf-blue-70);
}
```

### Tertiary / ghost

```css
.tf-button--tertiary {
  color:        var(--tf-text-primary);
  background:   transparent;
  border-color: var(--tf-border);
}
.tf-button--tertiary:hover {
  border-color: var(--tf-blue);
  color:        var(--tf-blue);
}
```

### Button sizes

```css
.tf-button--sm {
  min-height: 2rem;
  padding:    .375rem .875rem;
  font-size:  .8125rem;
}
.tf-button--lg {
  min-height: 3.25rem;
  padding:    .875rem 1.75rem;
  font-size:  1rem;
}
```

---

## Header / Navigation

```css
.tf-header {
  position:          sticky;
  top:               0;
  z-index:           100;
  background:        var(--tf-background);
  border-bottom:     1px solid var(--tf-border);
  backdrop-filter:   blur(8px);
}

.tf-nav {
  display:         flex;
  align-items:     center;
  justify-content: space-between;
  height:          64px;
}

.tf-nav__logo {
  display:     flex;
  align-items: center;
  flex-shrink: 0;
}

.tf-nav__links {
  display:    none;
  gap:        var(--space-6);
  list-style: none;
  margin:     0;
  padding:    0;
}

@media (min-width: 1024px) {
  .tf-nav__links { display: flex; }
}

.tf-nav__link {
  font-size:   .9375rem;
  font-weight: var(--tf-font-medium);
  color:       var(--tf-nav-text);
  transition:  color .15s ease;
  white-space: nowrap;
}
.tf-nav__link:hover,
.tf-nav__link--active {
  color:           var(--tf-nav-category);
  text-decoration: none;
}

.tf-nav__cta {
  display:    none;
  gap:        var(--space-3);
  align-items: center;
}
@media (min-width: 768px) {
  .tf-nav__cta { display: flex; }
}

/* Mobile hamburger */
.tf-nav__burger {
  display:     flex;
  flex-direction: column;
  gap:         5px;
  cursor:      pointer;
  padding:     var(--space-2);
  background:  none;
  border:      none;
}
@media (min-width: 1024px) {
  .tf-nav__burger { display: none; }
}

.tf-nav__burger-line {
  width:         24px;
  height:        2px;
  background:    var(--tf-text-primary);
  border-radius: 2px;
  transition:    transform .2s ease, opacity .2s ease;
}

/* Mobile menu */
.tf-nav__mobile {
  display:     none;
  flex-direction: column;
  gap:         var(--space-2);
  padding:     var(--space-4) var(--container-gutter-mobile);
  background:  var(--tf-background);
  border-top:  1px solid var(--tf-border);
}
.tf-nav__mobile--open { display: flex; }
```

---

## Hero section

```css
.tf-hero {
  padding:    clamp(var(--section-padding-mobile), 8vw, var(--section-padding-desktop)) 0;
  background: var(--tf-background);
  overflow:   hidden;
  position:   relative;
}

/* Blue hero variant */
.tf-hero--brand {
  background: var(--tf-background-brand);
  color:      #ffffff;
}
.tf-hero--brand h1 { color: #ffffff; }
.tf-hero--brand p  { color: rgba(255,255,255,.85); }

/* Dark hero variant */
.tf-hero--dark {
  background: var(--tf-background-dark);
  color:      #ffffff;
}
.tf-hero--dark h1 { color: var(--tf-blue); }
.tf-hero--dark p  { color: rgba(255,255,255,.75); }

.tf-hero__inner {
  display:   grid;
  gap:       var(--space-8);
  align-items: center;
}

@media (min-width: 1024px) {
  .tf-hero__inner {
    grid-template-columns: 1fr 1fr;
    gap:                   var(--space-10);
  }
}

.tf-hero__eyebrow {
  font-size:      .875rem;
  font-weight:    var(--tf-font-medium);
  color:          var(--tf-blue);
  text-transform: uppercase;
  letter-spacing: .08em;
  margin-bottom:  var(--space-3);
}

.tf-hero__title {
  margin-bottom: var(--space-4);
}

.tf-hero__body {
  font-size:     clamp(1rem, 1.5vw, 1.125rem);
  line-height:   1.65;
  margin-bottom: var(--space-6);
  max-width:     52ch;
}

.tf-hero__actions {
  display:     flex;
  flex-wrap:   wrap;
  gap:         var(--space-3);
  align-items: center;
}

.tf-hero__media {
  border-radius: var(--tf-radius-card);
  overflow:      hidden;
  position:      relative;
}

.tf-hero__media img {
  width:      100%;
  height:     auto;
  display:    block;
  object-fit: cover;
}
```

---

## Section patterns

```css
.tf-section {
  padding: clamp(var(--section-padding-mobile), 6vw, var(--section-padding-desktop)) 0;
}

.tf-section--alt {
  background: var(--tf-background-alt);
}

.tf-section--brand {
  background: var(--tf-background-brand);
  color:      #ffffff;
}
.tf-section--brand h2,
.tf-section--brand h3 { color: #ffffff; }
.tf-section--brand p   { color: rgba(255,255,255,.85); }

.tf-section--dark {
  background: var(--tf-background-dark);
}
.tf-section--dark h2 { color: #ffffff; }
.tf-section--dark p  { color: var(--tf-text-secondary); }

.tf-section__header {
  max-width:     720px;
  margin-bottom: var(--space-10);
}

.tf-section__eyebrow {
  font-size:      .875rem;
  font-weight:    var(--tf-font-medium);
  color:          var(--tf-blue);
  text-transform: uppercase;
  letter-spacing: .08em;
  margin-bottom:  var(--space-3);
}

.tf-section__title {
  margin-bottom: var(--space-4);
}

.tf-section__subtitle {
  font-size:  1.0625rem;
  max-width:  60ch;
}
```

---

## Cards

```css
.tf-card {
  background:    var(--tf-background);
  border:        1px solid var(--tf-border);
  border-radius: var(--tf-radius-card);
  padding:       var(--space-6);
  transition:    box-shadow .2s ease, transform .2s ease;
}

.tf-card:hover {
  box-shadow: var(--tf-shadow-md);
  transform:  translateY(-2px);
}

.tf-card--flat {
  border:     none;
  background: var(--tf-background-alt);
  box-shadow: none;
}

.tf-card__icon {
  width:            48px;
  height:           48px;
  border-radius:    50%;
  background:       var(--tf-blue-10);
  display:          flex;
  align-items:      center;
  justify-content:  center;
  margin-bottom:    var(--space-4);
  color:            var(--tf-blue);
}

.tf-card__title {
  font-size:     1.125rem;
  font-weight:   var(--tf-font-medium);
  color:         var(--tf-text-primary);
  margin-bottom: var(--space-2);
}

.tf-card__body {
  font-size:   .9375rem;
  line-height: 1.6;
  color:       var(--tf-text-secondary);
}
```

---

## Feature / services grid

```css
.tf-feature-grid {
  display:               grid;
  grid-template-columns: 1fr;
  gap:                   var(--space-5);
}

@media (min-width: 640px) {
  .tf-feature-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (min-width: 1024px) {
  .tf-feature-grid { grid-template-columns: repeat(3, 1fr); }
}
```

---

## Stats / numbers section

```css
.tf-stats-grid {
  display:               grid;
  grid-template-columns: repeat(2, 1fr);
  gap:                   var(--space-6);
}

@media (min-width: 768px) {
  .tf-stats-grid { grid-template-columns: repeat(4, 1fr); }
}

.tf-stat__number {
  font-size:     clamp(2rem, 4vw, 3rem);
  font-weight:   var(--tf-font-bold);
  color:         var(--tf-blue);
  line-height:   1;
  margin-bottom: var(--space-2);
}

.tf-stat__label {
  font-size:   .9375rem;
  color:       var(--tf-text-secondary);
  line-height: 1.4;
}
```

---

## CTA banner

```css
.tf-cta-banner {
  background:    var(--tf-blue);
  border-radius: var(--tf-radius-card);
  padding:       var(--space-10) var(--space-6);
  text-align:    center;
}

@media (min-width: 768px) {
  .tf-cta-banner {
    padding:   var(--space-12) var(--space-10);
    display:   flex;
    align-items: center;
    justify-content: space-between;
    text-align: left;
  }
}

.tf-cta-banner__text h2 {
  color:         #ffffff;
  margin-bottom: var(--space-2);
}
.tf-cta-banner__text p {
  color:      rgba(255,255,255,.85);
  max-width:  50ch;
}
.tf-cta-banner__actions {
  margin-top:  var(--space-5);
  flex-shrink: 0;
}
@media (min-width: 768px) {
  .tf-cta-banner__actions { margin-top: 0; margin-left: var(--space-8); }
}

/* White primary button for use on blue/brand background */
.tf-button--primary-inverse {
  color:        var(--tf-blue);
  background:   #ffffff;
  border-color: #ffffff;
}
.tf-button--primary-inverse:hover {
  background:   var(--tf-blue-10);
  border-color: var(--tf-blue-10);
}
```

---

## Forms

```css
.tf-form-group {
  display:       flex;
  flex-direction: column;
  gap:           var(--space-2);
  margin-bottom: var(--space-5);
}

.tf-label {
  font-size:   .875rem;
  font-weight: var(--tf-font-medium);
  color:       var(--tf-text-primary);
}

.tf-label--required::after {
  content:     " *";
  color:       var(--tf-red);
  font-weight: var(--tf-font-regular);
}

.tf-input,
.tf-select,
.tf-textarea {
  width:         100%;
  height:        2.75rem;
  padding:       .625rem .875rem;
  border:        1.5px solid var(--tf-border);
  border-radius: var(--tf-radius-input);
  font-family:   var(--tf-font-family);
  font-size:     1rem;
  color:         var(--tf-text-primary);
  background:    var(--tf-background);
  transition:    border-color .15s ease, box-shadow .15s ease;
  outline:       none;
  -webkit-appearance: none;
}

.tf-textarea {
  height:     auto;
  min-height: 120px;
  resize:     vertical;
}

.tf-input:focus,
.tf-select:focus,
.tf-textarea:focus {
  border-color: var(--tf-border-focus);
  box-shadow:   0 0 0 3px color-mix(in srgb, var(--tf-blue), white 70%);
}

.tf-input--error,
.tf-select--error,
.tf-textarea--error {
  border-color: var(--tf-red);
}

.tf-field-hint {
  font-size: .8125rem;
  color:     var(--tf-text-secondary);
}

.tf-field-error {
  font-size: .8125rem;
  color:     var(--tf-red-dark);
}
```

---

## Footer

```css
.tf-footer {
  background:   var(--tf-background-dark);
  color:        var(--tf-text-secondary);
  padding:      var(--section-padding-desktop) 0 var(--space-8);
  margin-top:   auto;
}

.tf-footer__grid {
  display:               grid;
  grid-template-columns: 1fr;
  gap:                   var(--space-8);
  margin-bottom:         var(--space-10);
}

@media (min-width: 768px) {
  .tf-footer__grid { grid-template-columns: 2fr 1fr 1fr 1fr; }
}

.tf-footer__brand p {
  font-size:   .9375rem;
  line-height: 1.65;
  color:       var(--tf-gray-2);
  max-width:   36ch;
  margin-top:  var(--space-4);
}

.tf-footer__col-title {
  font-size:     .875rem;
  font-weight:   var(--tf-font-medium);
  color:         #ffffff;
  margin-bottom: var(--space-4);
  text-transform: uppercase;
  letter-spacing: .06em;
}

.tf-footer__links {
  list-style: none;
  margin:     0;
  padding:    0;
  display:    flex;
  flex-direction: column;
  gap:        var(--space-3);
}

.tf-footer__links a {
  font-size:   .9375rem;
  color:       var(--tf-gray-2);
  font-weight: var(--tf-font-regular);
  transition:  color .15s ease;
}
.tf-footer__links a:hover {
  color:           #ffffff;
  text-decoration: none;
}

.tf-footer__bottom {
  border-top:      1px solid rgba(255,255,255,.1);
  padding-top:     var(--space-6);
  display:         flex;
  flex-wrap:       wrap;
  align-items:     center;
  justify-content: space-between;
  gap:             var(--space-4);
}

.tf-footer__legal {
  font-size: .8125rem;
  color:     var(--tf-gray-4);
}

.tf-footer__legal-links {
  display:    flex;
  flex-wrap:  wrap;
  gap:        var(--space-4);
  list-style: none;
  margin:     0;
  padding:    0;
}

.tf-footer__legal-links a {
  font-size:   .8125rem;
  color:       var(--tf-gray-4);
  font-weight: var(--tf-font-regular);
}
.tf-footer__legal-links a:hover { color: #ffffff; text-decoration: none; }
```

---

## Layout

- Concept: circles as a visual metaphor for connection; combine circles with functional boxes.
- Margin formula: `margin = min(width, height) / 16`.
- Email baseline: 640px width; 80×80px modules; 32px gutters; 10px module radius.
- Use clean premium whitespace. Do not overload with circles everywhere.
- Logo height should align to approximately one grid unit when official assets are used.

---

## Logo constraints

- Use official approved assets only.
- Preferred lockup: T + Telefónica wordmark (`imagotype`).
- Do not use the T isotipo standalone.
- Minimum digital width: primary 65px; secondary 45px.
- Reserve area: at least two logo circles around the mark.
- Approved color combinations: Telefónica Blue on white/Telefónica White; white on Telefónica Blue or dark navy.

---

## Digital accessibility

- Text colors `#031A34` and `#58617A` are intended for white/Telefónica White backgrounds.
- Interactive elements use Telefónica Blue on white/Telefónica White/blue contexts; still verify state contrast.
- Functional icons need at least 3:1 contrast in normal, hover, and focus states.
- Decorative icons do not require contrast but must not carry required meaning.
- Provide alt text when image text is not repeated outside the image.
- Avoid flashes over three times per second.
- Support reduced motion:

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration:  .01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .01ms !important;
    scroll-behavior:     auto !important;
  }
}
```

---

## Practical review checklist

- Tokens centralized, not scattered.
- Blue is present but not overused.
- Typography falls back safely if official font is unavailable.
- Buttons are rounded and have visible hover/focus states.
- Text is left-aligned except valid logo-centered compositions.
- No standalone T isotipo was introduced.
- Spanish copy uses active voice, natural wording, and correct number/punctuation rules.
- Dark mode overrides cover all semantic tokens.
- Responsive: layout adapts at all four breakpoints.
- Navigation accessible by keyboard; skip link present.
- All forms have associated labels and visible error states.
