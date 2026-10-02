# #808 — Lucide icons next to each top-level nav item (Phase B.2)

## Goal

Parear cada item del nav con un icono lucide (16-18 px) a la izquierda del label, `aria-hidden="true"` para que screen readers sigan anunciando sólo el label. El header gana una segunda dimensión de escaneo (silueta + texto) y se alinea con el patrón de admin shells modernos (Linear, Vercel, Stripe, Notion).

Slice B.2 del epic `#817`. Depende de `#806` (los labels deben estar estables antes de tocar el template).

## Acceptance criteria (del issue #808)

1. Cada nav item renderiza un icono lucide (16×16) a la izquierda del label.
2. El `<svg>` tiene `aria-hidden="true"`; el texto accesible del link sigue siendo sólo el label.
3. El color del icono hereda el token de texto existente (sin nuevos colores introducidos).
4. Lighthouse / axe `link-name` sigue verde (los iconos no cuentan como texto).
5. Probe Playwright: cada `<a>` del header tiene exactamente un `<svg>` hijo con `aria-hidden="true"` y bounding box `~16×16`.

## Scope (este slice = #808)

- Decidir la **estrategia de packaging** de los iconos (ver Riesgos).
- `app/static/icons/` o sprite SVG inline — según la decisión.
- `app/templates/base.html` y `app/templates/base_mobile.html` — añadir el icono a la izquierda del label.
- `app/core/nav.py` — `NAV_ITEMS` extiende a `(href, label, title, icon_key)` o se mantiene separado en un dict de iconos por href.
- `tests/e2e/test_nav_icons.py` — nuevo. Probe Playwright sobre el header autenticado.
- `odd/tasks/808-lucide-icons.md` — este archivo.

## Out of scope

- Rename de labels (`#806`).
- Agrupación / headings (`#809`).
- Iconos dentro del contenido de las páginas — sólo en el nav.
- Iconos custom del proyecto — sólo stock de lucide.

## Work-unit commits planeados

| WU | Descripción | Estado |
|---|---|---|
| WU-1 | Tracking (este documento) + decisión de packaging + rama `feat/808-lucide-icons` | en curso |
| WU-2 | Asset path / sprite + icono en `base.html` y `base_mobile.html` | pendiente |
| WU-3 | `tests/e2e/test_nav_icons.py` con la probe | pendiente |
| WU-4 | Gates locales + commit + push + CI + merge | pendiente |

## Gates (CI required check, pre-MVP single-branch)

- `ruff check .` sin findings nuevos.
- `python scripts/check_rules.py .` exit code 0.
- `python -m mypy` sin errores nuevos.
- `pytest tests/test_pages.py tests/test_template_selection.py tests/test_template_migration.py -q` verde.
- `pytest tests/e2e/test_nav_icons.py -q` verde bajo chromium (auto-skip si no).
- Issue-spec: el body del #808 está en inglés (es el issue original) — Castellano check puede fallar. Acción: abrir sub-issue de Castellano o reescribir el body antes de mergear.
- Budget ≤ 350 líneas (depende de la estrategia de packaging).

## Legacy fidelity (P1)

N/A — sólo agrega iconos al header web.

## Estrategia de implementación

### Decisión de packaging (a resolver en WU-1)

El proyecto es FastAPI + Jinja2, sin React/Vue. Candidatos:

1. **Inline `<svg>` por icono en el template** — cero dependencias, copy-paste desde lucide.dev. 9 iconos ≈ 9 SVGs inline, ~30 líneas cada uno. Riesgo: si se reescribe el nav a futuro, hay que mantener los SVGs.
2. **Lucide static sprite** — `lucide-static` (pip) genera un sprite SVG en build time. Se referencia con `<svg><use href="/static/icons/sprite.svg#house"/></svg>`. Limpio pero requiere build step o generación on-import.
3. **Lucide CDN** — `<script src="https://unpkg.com/lucide@latest"></script>` + `lucide.createIcons()`. El repo declara `script-src 'self'` en CSP — CDN externo lo viola.

**Recomendación: opción 1 (inline)** — sin nuevas deps, sin build step, sin violaciones de CSP, perfectamente testeable por bounding box. El issue `#808` lo permite («lucide-react or lucide-vue-next» son sugerencias del autor del issue, no restricciones).

Si se prefiere opción 2, requiere decisión de scope: ¿se agrega un build step al repo? Eso es una decisión de scope mayor.

### Mapeo sugerido (del body del issue)

| Nav item | Icon |
|---|---|
| Inicio | `house` |
| Animales | `paw-print` |
| Entradas | `package-plus` |
| Lote | `layers` |
| Casas | `home` |
| Estancias | `bed` |
| Adopciones | `heart-handshake` |
| Actuaciones | `stethoscope` |
| Voluntarios | `users-round` |

### Cambios concretos (opción 1)

- `app/core/nav.py` — `NAV_ITEMS` extiende a `(href, label, title, icon_svg)` donde `icon_svg` es el bloque `<svg ...>…</svg>` literal. Esto mantiene un solo lugar donde editar el nav.
- `app/templates/base.html` y `app/templates/base_mobile.html` — el loop sobre `NAV_ITEMS` ahora emite el icono + label. Verificar que el cambio no rompe `#805` active-state (la clase `[aria-current="page"]` debe seguir aplicándose al `<a>`, no al `<svg>`).

## Riesgos identificados

1. **Castellano check en el body del issue** — el body original está en inglés. El check `scripts/check_issue_specs.py` exige Castellano peninsular + secciones `### `. Mitigación: reescribir el body a Castellano en la misma sesión, antes de abrir el PR. Esto ya lo hicimos proactivamente en issues previos.
2. **Peso del HTML** — 9 SVGs inline suman ~3-5 KB al header. Acceptable para una admin shell interna; no es una página pública.
3. **Iconos que no existen en lucide** — `paw-print`, `heart-handshake`, `users-round`, `package-plus` son iconos reales de lucide, pero hay que confirmar nombres exactos en https://lucide.dev/icons antes de mergear.
4. **Color heredado** — el icono debe usar `currentColor` para heredar el color del texto. Verificar que los SVGs copiados de lucide tienen `stroke="currentColor"` (no `stroke="#000"`).
5. **Conflicto con `#809`** — el siguiente slice reorganiza el nav. Los iconos deben sobrevivir al regrouping; si `#809` cambia el shape de `NAV_ITEMS`, este slice tiene que poder extenderse sin romperse.

## Criterios de cierre del slice

- [ ] Branch `feat/808-lucide-icons` con WU-2 y WU-3 mergeados.
- [ ] `NAV_ITEMS` extendido con `icon_svg`.
- [ ] Templates renderizan icono + label.
- [ ] `tests/e2e/test_nav_icons.py` verde bajo chromium.
- [ ] Gates locales verdes.
- [ ] PR abierto contra `origin/main`, CI verde, merge con `--admin`.
- [ ] Issue `#808` cerrada vía `Fixes #808`.
- [ ] Worktree local borrado.
- [ ] Memoria de sesión guardada.