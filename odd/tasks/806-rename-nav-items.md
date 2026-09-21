# #806 — Rename long nav items so they fit on one line (Phase B.1)

## Goal

Eliminar el wrap multi-línea del header desktop (Tailwind v4, viewport 1440) sobre tres items que rompen el patrón de altura uniforme del nav. El header queda visualmente parejo y los items no se cortan en mobile fallback (375 px).

Slice B.1 del epic `#817`. Primera mitad de la fase B; sobre el resultado se monta `#808` (icons) y `#809` (grouping).

## Acceptance criteria (del issue #806)

1. Los items «Entradas en lote», «Casas de acogida» y «Estancias de acogida» se renderizan en una sola línea en `1440x900` con `text-sm` default de Tailwind.
2. Ningún `<a>` del header tiene `boundingClientRect().height > 30` (probe Playwright que ya evidencia el bug).
3. La probe Playwright se incorpora como test E2E para pinchar la regresión.
4. Los labels siguen siendo semánticamente claros — un rename a algo como «Lote» es aceptable, pero no se permite algo como «E. lote».
5. `app/core/nav.py` cambia los labels en `NAV_ITEMS`. La tupla pasa de `(href, label)` a `(href, label, title)` (title opcional para tooltip). `resolve_active_nav_href` no necesita cambios (sigue trabajando con `href`).

## Scope (este slice = #806)

- `app/core/nav.py` — editar `NAV_ITEMS` con los nuevos labels. Los tooltips se meten en un dict separado `NAV_TITLES: dict[str, str]` (shape actual = tupla `(href, label)`; preferido mantenerla así y separar titles, en vez de migrar a `(href, label, title)` que obliga a cambiar `resolve_active_nav_href` y todos los tests).
- `app/core/nav.py` — añadir un helper `nav_title(href: str) -> str` que el template consume cuando el dict tiene entrada. Si no tiene entrada, devuelve string vacío.
- Context processor que renderiza `NAV_ITEMS` — pasa también `NAV_TITLES` (o expone el helper) al template.
- `app/templates/base.html` — render del `<a>` añade `title="{{ nav_title(item.href) }}"` cuando no esté vacío.
- `app/templates/base_mobile.html` — idem.
- `tests/e2e/test_nav_no_multiline.py` — nuevo. Probe Playwright que mide altura de cada `<a>` del header y assert `<= 30`.
- `odd/tasks/806-rename-nav-items.md` — este archivo.

Items a renombrar (estado actual confirmado leyendo `app/core/nav.py`):

| href actual | label actual | label nuevo | title |
|---|---|---|---|
| `/entradas/batch/new` | «Entradas en lote» | «Lote» | «Entradas en lote» |
| `/casas-acogida` | «Casas de acogida» | «Casas» | «Casas de acogida» |
| `/acogidas` | «Estancias de acogida» | «Estancias» | «Estancias de acogida» |

Los otros seis items no cambian.

## Out of scope

- Iconos (#808).
- Agrupación / headings (#809).
- Cambios en `resolve_active_nav_href` — sigue trabajando con `href`, no con label.

## Work-unit commits planeados

| WU | Descripción | Estado |
|---|---|---|
| WU-1 | Tracking (este documento) + rama `chore/806-rename-nav-items` | en curso |
| WU-2 | Edit de `app/core/nav.py` con los nuevos labels | pendiente |
| WU-3 | `tests/e2e/test_nav_no_multiline.py` con la probe | pendiente |
| WU-4 | Gates locales + commit + push + CI + merge | pendiente |

## Gates (CI required check, pre-MVP single-branch)

- `ruff check .` sin findings nuevos.
- `python scripts/check_rules.py .` exit code 0.
- `python -m mypy` sin errores nuevos.
- `pytest tests/test_pages.py tests/test_template_selection.py tests/test_template_migration.py -q` verde.
- `pytest tests/e2e/test_nav_no_multiline.py -q` verde bajo chromium (auto-skip si no).
- Issue-spec: el body del #806 ya está en castellano con `### ` H3, pasa el check.
- Budget ≤ 200 líneas (diff esperado: ~10 de nav.py + ~70 de test + ~80 de task file).

## Legacy fidelity (P1)

N/A — el slice sólo toca el helper de nav y el header.

## Estrategia de implementación

1. **Decidir renames** — propuesta:
   - «Entradas en lote» → «Lote» (title="Entradas en lote" como tooltip) — ya hay un link a /entradas/batch/new; el nombre corto «Lote» es el término operativo del usuario.
   - «Casas de acogida» → «Casas» (title="Casas de acogida").
   - «Estancias de acogida» → «Estancias» (title="Estancias de acogida").
2. **Editar `NAV_ITEMS`** — cambiar los labels de los tres items problemáticos a la versión corta. Mantener shape `(href, label)` (53 líneas actuales, no inflar).
3. **Crear `NAV_TITLES`** — dict aparte con los tres titles. Helper `nav_title(href)`.
4. **Verificar render** — `grep -n label app/templates/base.html app/templates/base_mobile.html` para confirmar que ambos templates leen el segundo elemento de la tupla y que el context processor expone `NAV_TITLES` o el helper.
5. **Test E2E** — `tests/e2e/test_nav_no_multiline.py` sigue el patrón de `tests/e2e/test_nav_responsive_structure.py`: preflight del `/`, 3 probes (header altura, mobile burger altura, ningún `<a>` con altura > 30).
6. **Verificación local** — ruff/mypy/check_rules/pytest → commit → push → CI → merge.

## Riesgos identificados

1. **Title redundante** — si el label es «Lote» y el title es «Entradas en lote», algunos usuarios pueden encontrar el title redundante. Mitigación: title sólo si aporta contexto no obvio. «Lote» sin title también es válido; el issue lo deja a discreción.
2. **A11y del title** — el atributo HTML `title` no es accesible para todos los usuarios (no se anuncia consistentemente en screen readers modernos). Para un tooltip verdadero habría que usar `aria-describedby`. Esto queda fuera del slice; el label corto sigue siendo el nombre accesible.
3. **Conflicto con `#805` active-state** — la marca de active-state se aplica por `href`, no por label, así que el rename no toca ese flujo. Verificado en el código de `resolve_active_nav_href`.
4. **Conflict con otros slices** — `#808` y `#809` también tocan `app/core/nav.py`. Por eso la cadencia es secuencial, no paralela.

## Criterios de cierre del slice

- [ ] Branch `chore/806-rename-nav-items` con WU-2 y WU-3 mergeados.
- [ ] `app/core/nav.py` con labels cortos en los tres items problemáticos.
- [ ] `tests/e2e/test_nav_no_multiline.py` verde bajo chromium.
- [ ] Gates locales verdes.
- [ ] PR abierto contra `origin/main`, CI verde, merge con `--admin`.
- [ ] Issue `#806` cerrada vía `Fixes #806`.
- [ ] Worktree local borrado (regla: no merged wts left behind).
- [ ] Memoria de sesión guardada.
<!-- re-trigger CI -->
