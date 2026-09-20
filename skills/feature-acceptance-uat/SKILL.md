---
name: feature-acceptance-uat
description: Trigger: staging acceptance, feature intake, acceptance criteria, criterios de aceptación, UAT, client sign-off, dev validation, acceptance web. Drive everything in staging that is not yet in the latest main release to a signed acceptance: clarifying questions, testable criteria, the contract, derived validation cases, and self-contained Telefónica-branded acceptance webs for BOTH user-validatable changes and developer-only (infra) validation.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 2.0
  last_verified: 2026-09-05
  scope: ['universal']
  auto_invoke: ['preparing acceptance UAT for a feature']
  tiers: ['universal']
---



# Feature Acceptance & UAT

## Activation Contract

Use this skill when an app is in **staging** and not yet in the latest **main** production release. Scope is whatever is in staging but not in prod — read `git log <latest-main-release-tag>..HEAD --oneline` (or `origin/main..HEAD`) and group commits by change. Every such change is subject to this acceptance contract, whether the client asked for it or it surfaced during the work. For each change: generate clarifying questions, propose testable criteria, pact them (the "contract"), derive validation cases, and produce self-contained Telefónica-branded acceptance webs. Automates phases 0 (intake), 4 (validation) and 5 (sign-off) of the team workflow.

## Two Axes (classify every change)

Tag each change on both axes — they are independent and drive routing, not just metadata.

- **`validador`** — who can actually validate it:
  - `usuario`: observable through the UI; the product/quality team validates by clicking. Goes in the **user acceptance web**.
  - `desarrollo`: infra / not user-observable (performance, migration, indexes, encoding, backup, cache, sync). Only the developer can validate it, **with proposed test steps**. Goes in the **developer validation web** — its own signed instrument, NOT a flat list.
- **`origen`** — where it came from (traceability only, does not change routing):
  - `solicitado`: a feature/fix the client requested. Pact criteria with the client before UAT.
  - `derivado`: surfaced during the work (indirect). Criteria are dev-authored; inform the client, but it still needs validation and a record.

Both `usuario` and `desarrollo` items get the SAME instrument shape: `pasos` + `esperado` + PASA/FALLA + observations + a downloadable, checksum-signed record. Promotion to production requires BOTH records closed when both axes are present.

## Hard Rules

- **Be product-aware first.** Read each change's capability doc + index via the `access-vba-capability-docs` skill before asking. New feature → §1 is greenfield. Change → load the existing §2 contract so pacted rules are not broken.
- **Start from the problem, not the solution.** Generate clarifying questions and get answers before proposing any criteria. Never accept a solution disguised as a requirement.
- **Acceptance criteria MUST be testable** (DADO/CUANDO/ENTONCES). Reject vague criteria ("que sea rápido"). The agreed criteria are the single contract that threads intake → tests → validation → sign-off.
- **Every case carries `pasos`** — step-by-step "cómo probarlo". A criterion without reproducible steps is not validatable; do not emit it.
- **Derive validation cases ONLY from agreed criteria** — never from assumptions.
- **Classify every change on both axes** before generating webs. Route `usuario` cases to the user web, `desarrollo` cases to the developer web.
- **No jargon in the user web.** No `BR-x`, no `Verified-runtime`, no `Form_FormX`. Plain Spanish, validatable by a non-technical person. Internal identifiers live only in the downloaded record (for audit/traceability), not in the user-facing card.
- **Multiple signers, name only.** The quality team is usually >1 person: dynamic list of name rows, "+ Agregar firmante", remove per row, at least one name to enable download. **No "cargo / área" / role field** — too formal for non-technical staff.
- **Generate webs from `assets/uat-acceptance-web.template.html`.** Set `audience` (`usuario` | `desarrollo`); the template filters cases and adapts copy. Each web MUST stay self-contained (one `.html`, no server, no external deps), so it can live beside the staging app icon in the launcher.
- **Brand it via the `telefonica-brand-design` skill, static-HTML path** (Brand Factory tokens from its `brand-guidelines.md`). Do not invent Telefónica fonts, logos, or the standalone "T" isotipo; use safe fallbacks and leave integration notes. Keep WCAG AA, focus states, reduced motion, dark mode.
- **Wordmark oficial embebido.** El template incluye el wordmark oficial de Telefónica como `LOGO_B64_TELEFONICA` (PNG base64, ~27 KB inline). Override opcional vía `UAT_META.logo_path` (URL o ruta relativa) o `UAT_META.logo_b64` (string base64 alternativo). El default es inline para respetar el contrato de "un solo archivo, sin servidor ni dependencias" del template — un `<img src="...">` externo se rompe al mover, copiar, mandar por mail o servir desde un share de red. Cambiar `--tf-header-height` y `--tf-wordmark-height` (tokens CSS en `:root`) para redimensionar; los tres lugares que los consumen (`.tf-header__inner`, `.tf-progress sticky top`, `.tf-wordmark--img height`) leen del mismo token.
- **The web outputs proof:** a downloadable acceptance record (feature id + criteria version + checksum + date + signers + per-case pass/fail + observations + traceability ref) AND a pre-filled `mailto:`. A static HTML cannot send mail itself — never claim it does.
- **Pin the criteria version** (checksum) in the record. An acceptance against old criteria must never pass for a changed feature.
- **Write all produced documentation and UI copy in Spanish (Spain / castellano de España).**

## Decision Gates

| Question | Action |
|---|---|
| New feature or change? | New → fresh intent. Change → load capability doc §2 first. |
| Who validates this change? | `usuario` → user web. `desarrollo` → developer web. Both → both webs. |
| Requested or derived? | `solicitado` → pact criteria with client first. `derivado` → dev-authored criteria; inform client. |
| Criteria not testable / no `pasos`? | Re-ask; do not proceed to validation cases. |
| Any case `failed`? | Send feedback back to implementation; do not sign off. |
| All cases `passed` + signed (both webs, where applicable)? | Record in capability doc §5 ledger (staging version, prod release). |
| Branding asset missing? | Use Brand Factory fallback; leave an integration note. |

## Execution Steps

1. **Scope staging.** `git log <latest-main-release-tag>..HEAD --oneline` (fallback `origin/main..HEAD`); group commits by change; cross-check open GitHub issues + capability docs.
2. **Classify** each change on both axes (`validador`, `origen`).
3. For each change, read its capability doc/index for product context (new vs change branch).
4. **Clarifying questions** (problem, users, business rules, edge cases, non-goals); ask the user and iterate until clear. For `solicitado`, pact with the client; for `derivado`, dev-author and inform.
5. **Propose acceptance criteria** in DADO/CUANDO/ENTONCES plus the contract text.
6. **Derive validation cases** from agreed criteria — one case per observable expectation, each WITH `pasos` and a traceability `ref` (commit hash / issue / criterion id).
7. **Generate the user web** (`audience: "usuario"`) from the template with `usuario` cases → `docs/uat/uat-staging-<YYYY-MM-DD>.html`.
8. **Generate the developer web** (`audience: "desarrollo"`) with `desarrollo` cases → `docs/uat/uat-dev-<YYYY-MM-DD>.html`. Same instrument, signed by the developer.
9. Fill metadata (feature id, criteria version + checksum, staging link, recipient), wire download + `mailto:` for each.
10. **On outcome**, update the capability doc §5 ledger (staging version, validation status per axis; on full sign-off, prod release + date). No merge to main without the applicable records closed.

## Output Contract

Return:
- Staging scope (changes grouped) and per-change classification (`validador`, `origen`).
- Clarifying questions asked and the agreed answers.
- The agreed acceptance criteria and the client contract text.
- The derived validation cases (with `pasos` and `ref`).
- Path to the generated user web and, if applicable, the developer web.
- Branding approach used (Brand Factory fallback) and any missing-asset notes.
- The capability doc §5 ledger update to apply.

## Branding & Logo

El wordmark Telefónica y los tokens de tamaño viven en el template, no en cada HTML generado.

**Wordmark** — `LOGO_B64_TELEFONICA` (PNG oficial en base64, ~27 KB) embebido en el `<script>` del template. Resolución de fuente en `resolveWordmarkSrc()` con este orden de precedencia:

1. `UAT_META.logo_path` — URL absoluta o ruta relativa (`"./assets/mi-logo.png"`, `"https://cdn.../x.svg"`).
2. `UAT_META.logo_b64` — string base64 de un asset alternativo.
3. `LOGO_B64_TELEFONICA` — default inline (contrato "un solo archivo, sin dependencias").

Para override, descomentar las líneas `logo_path` / `logo_b64` en `UAT_META` y setear el valor. Útil cuando:
- Otro producto quiere su propio logo (mismo template, distinta marca).
- Hay un asset específico del producto (ej. CADETE tiene `Telefonica_cadete.png`).
- Hay un SVG propio más liviano que el PNG base64.

**No usar** el isotipo "T" suelto — solo wordmark completo (`T de 4 puntos + "Telefónica"`).

**Tamaños** — dos tokens CSS en `:root`:

```css
--tf-header-height: 96px;     /* alto del header + sticky progress top */
--tf-wordmark-height: 84px;   /* alto del <img> del wordmark */
```

Cambiarlos de un solo punto: los tres consumidores (`.tf-header__inner height`, `.tf-progress top`, `.tf-wordmark--img height`) leen del mismo token. Si la imagen se ve pixelada al subir el alto, regenerar el base64 desde un PNG con mayor resolución; el actual (1920×1080) soporta hasta ~120px de alto sin pérdida visible.

**Filter CSS** — `.tf-wordmark--img` aplica un filter SVG (`brightness → invert → sepia → hue-rotate`) para teñir el asset blanco al `--tf-blue` de marca. Si se reemplaza el asset por una versión ya en color, quitar el filter o el wordmark se verá azul-oscuro.

## References

- `assets/uat-acceptance-web.template.html` — self-contained, audience-aware (`usuario` | `desarrollo`), Telefónica-branded acceptance web template. Incluye `LOGO_B64_TELEFONICA` y los tokens `--tf-header-height` / `--tf-wordmark-height`.
- `access-vba-capability-docs` skill — product knowledge and the §5 release/UAT ledger.
- `telefonica-brand-design` skill — branding; use its `brand-guidelines.md` (static-HTML path).
- Global `AGENTS.md` (`gentle-ai:staging-acceptance-contract`) — the cross-project staging→UAT→prod contract this skill implements.
- Project `AGENTS.md` — recipient email, staging launcher path, release tags. Follow it first.
