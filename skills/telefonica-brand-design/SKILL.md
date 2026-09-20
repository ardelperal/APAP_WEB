---
name: telefonica-brand-design
description: Trigger: Telefonica brand, Mistica tokens, design system. Apply Telefónica Brand Factory and Mística design-system guidance to frontend projects, React apps, Next.js apps, static HTML/CSS corporate websites, landing pages, design systems, emails, decks, or documentation. Use when asked to make a project look like Telefónica, create a Telefónica/corporate website or página web corporativa, apply Telefónica/Telefonica/Mística/Mistica brand tokens, configure @telefonica/mistica with the Telefónica skin, create CSS variables/theme tokens, style components with Telefónica colors/typography/buttons/cards/forms/nav/hero/footer, review Spanish copy against Telefónica tone of voice, or implement dark mode with Telefónica tokens.
metadata:
  author: Andrés Román
  version: 1.0
  last_verified: 2026-09-05
  scope: ['universal', 'design']
  auto_invoke: ['applying Telefonica brand tokens']
  tiers: ['universal', 'design']
license: Apache-2.0
---



# Telefónica Brand Design

Use this skill to apply a Telefónica/Mística design language consistently across projects — whether a full React product, a static corporate website, a marketing landing page, or a document.

## Operating rules

1. Verify the target stack before editing: CSS, Tailwind, Sass, design-token JSON, React/Vue/Svelte, Next.js/SSR, native app, email, slides, or docs.
2. Load `references/brand-guidelines.md` for brand identity, voice, logo constraints, non-Mística fallback tokens, and corporate website layout patterns.
3. Load `references/mistica-web.md` when the target is a web app, React/Next.js app, component library, or token system that can map to Mística.
4. Load `references/mistica-design-repo.md` when exact current token values, token JSON structure, Mística validation rules, Figma sync behavior, or extended-token strategy matters.
5. Load `references/mistica-icons.md` when selecting, importing, searching, or validating Mística/Telefónica icons.
6. Load `references/mistica-logos-assets.md` when selecting or implementing Telefónica/Mística logos or locating official asset repositories.
7. Load `references/corporate-web-templates.md` when building a static HTML/CSS corporate website, landing page, or when the project cannot use `@telefonica/mistica` and needs full page-level patterns (header, hero, features, footer, contact form).
8. Prefer official Mística implementation for React/Next.js projects: `@telefonica/mistica` + `getTelefonicaSkin()` before hand-rolling components.
9. Prefer design tokens over hardcoded styles. Add variables at the lowest shared theme layer available.
10. Preserve existing architecture and naming conventions. Adapt token names to the project if it already has a system.
11. Do not invent or embed Telefónica proprietary font files, logos, photos, icons, or Brand Factory assets. If assets are missing, use safe fallbacks and leave integration notes.
12. Keep implementation accessible: WCAG AA contrast, visible focus, reduced-motion support, semantic controls, and alt text for meaningful images.
13. Do not use the standalone Telefónica "T" isotipo. If logo usage is needed, require official approved assets or Mística's exported logo component where available; for React prefer `TelefonicaLogo`/`Logo` from `@telefonica/mistica`.
14. Dark mode: implement using CSS `prefers-color-scheme` media query and token overrides; for React use `ThemeContextProvider` with the `colorScheme` prop or system detection. Always pair light tokens with their dark counterparts.
15. Responsive: use the four standard breakpoints from `brand-guidelines.md`. Prefer `clamp()` for fluid typography and `min()`/`max()` for fluid spacing.

## Decision rule: Mística vs Brand Factory fallback

| Context | Approach |
|---------|----------|
| React/Next.js product app | `@telefonica/mistica` + `getTelefonicaSkin()` if dependency is acceptable |
| React/Next.js static/marketing site | `@telefonica/mistica` or Brand Factory tokens; see note on button radius |
| Existing design system or non-React frontend | Map Mística semantic tokens into the project token layer; fetch official token JSON with `scripts/mistica_tokens.py` |
| Static HTML/CSS corporate website | Use `references/corporate-web-templates.md` + Brand Factory tokens from `brand-guidelines.md` |
| Email / deck / docs | Brand Factory visual guidance + compatible Mística tokens where useful |
| No package install desired | Implement CSS variables from the references; document that official Mística components were not installed |

**Button radius note**: Mística web skin uses `32px`. Brand Factory marketing pages may use `50px` pill. Use Mística radius for product UI; Brand Factory pill for pure marketing/landing contexts when not using the Mística library.

## Application workflow

### 1. Discover

- Find theme entrypoints (`tokens`, `theme`, `globals.css`, `tailwind.config`, design-system package, etc.).
- Identify the page-level shell: header/nav, hero, content sections, footer.
- Identify affected components: buttons, links, headings, cards, nav, hero, forms, tags/chips, feedback states, icons, and asset usage.
- Note the target languages (Spanish/English), locale, and copy tone requirements.

### 2. Tokenize

- Add semantic colors first (`textPrimary`, `brand`, `buttonPrimaryBackground`, etc.), then palette aliases.
- Add responsive breakpoints: `--bp-sm: 640px`, `--bp-md: 768px`, `--bp-lg: 1024px`, `--bp-xl: 1280px`.
- Add spacing scale (base 8px grid) and grid variables.
- If exact values matter, fetch current production tokens: `python references/../scripts/mistica_tokens.py --skin telefonica --summary` or `--css` or `--semantic`.
- Use Mística radii for web product UI: button `32px`, container `4px`, input `8px`, chip/tag `24px`.
- Use Brand Factory `50px` button radius only for non-Mística brand/marketing contexts.
- For dark mode: add `@media (prefers-color-scheme: dark) { :root { … } }` overrides for every semantic color.

### 3. Apply components

For React projects:
- Prefer official Mística components (`ButtonPrimary`, `ButtonSecondary`, `Text1`–`Text10`, `Title1`–`Title4`, `Stack`, `Box`, `Card`, `TextField`, `NavigationBar`, `Hero`, exported `Icon*` components).
- Wrap the app in `ThemeContextProvider` with `getTelefonicaSkin()`.

For static/HTML projects:
- Use the patterns from `references/corporate-web-templates.md` as starting point.
- Build header, hero, features grid, CTA section, and footer using the CSS variable system from `brand-guidelines.md`.
- Custom components: mirror Mística semantics instead of copying arbitrary screenshots.

Typography:
- Use `clamp()` for fluid headings.
- Keep text left-aligned and benefit-led.
- One weight per text block; DemiBold/Bold only for brief emphasis.

### 4. Voice and copy

- Use active verbs and user benefit first.
- Prefer natural, close wording over corporate jargon.
- Spanish copy follows RAE capitalization and the number/punctuation rules from the reference.
- Never overpromise; be transparent and grounded.

### 5. Review

**Accessibility**
- Check contrast for text and interactive states (WCAG AA).
- Check hover/pressed/focus/disabled states.
- Verify reduced-motion support for animations.

**Icons**
- Verify correct brand, weight, functional/decorative accessibility, and 3:1 contrast for functional icons.

**Logos**
- Verify approved component/source, lockup type, minimum size, clear space, and no standalone T/isotype unless explicitly permitted.

**Tokens**
- Check palette references, description/reference consistency, light/dark counterparts, and contrast pairs.
- No semantic token uses inline hex when a palette alias exists.

**Corporate site checklist**
- Responsive at all four breakpoints.
- Navigation is accessible (keyboard, ARIA landmarks, skip link).
- Hero CTA button has proper hover/focus state.
- Footer includes legal/privacy links.
- Forms have associated labels and error states.
- All images have meaningful alt text or `alt=""` if decorative.

## Output expectations

Return a short summary with:
- Files changed.
- Whether official Mística, mapped Mística tokens, or Brand Factory fallback was used.
- Whether dark mode was implemented.
- Any missing official assets, font licensing caveats, or dependency notes.
- Accessibility notes and any known contrast gaps.
