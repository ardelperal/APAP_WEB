# #809 — Group nav items under module headings or reduce item count (Phase B.3)

## Goal

Bajar el top-level nav de 9 items a 4-5 agrupando los items que comparten módulo. El header gana jerarquía visual y el usuario puede escanear por sección sin perderse entre items repetidos.

Slice B.3 del epic `#817`. Depende de `#806` (labels estables) y `#808` (iconos en su lugar) — el regrouping se hace sobre el nav ya pulido.

## Acceptance criteria (del issue #809)

1. El top-level nav tiene **a lo sumo 5 items** (excluyendo brand y user chip).
2. Cada item sigue mapeando a una ruta distinta — ningún rename + redirect implícito.
3. Se implementa **dropdown O section-heading** de forma consistente en desktop y mobile.
4. La ruta completa «Casas → Estancias → Adopciones → Actuaciones» queda a un click desde cualquiera de los cuatro entries (sin perderse en sub-rutas).

## Scope (este slice = #809)

- `app/core/nav.py` — `NAV_ITEMS` cambia de shape. Si vamos por dropdown, se introduce un dict `NAV_GROUPS` con `{ group_label: [(href, label, title, icon_svg), ...] }`. Si vamos por section-heading, se mantiene una sola lista pero con un campo `group` opcional.
- `app/templates/base.html` — render del nav con la nueva estructura (dropdown con `<details>` o `<details>` JS-libre, o section headings en CSS grid).
- `app/templates/base_mobile.html` — idem, compatible con el burger JS de `#820`.
- `app/static/js/` — sólo si la decisión es dropdown JS-driven (no `<details>`). El issue lo deja abierto.
- `app/static/css/` — sólo si la decisión es section-heading con CSS distinto al actual.
- `tests/e2e/test_nav_grouping.py` — nuevo. Probe Playwright sobre el header.
- `odd/tasks/809-group-nav-items.md` — este archivo.

## Out of scope

- Phase A (`#812`, `#813`, `#814`, `#818`) — ya mergeada.
- `#806` y `#808` — prerequisitos, ya mergeados antes de este slice.
- Wizard (`#821`, `#822`, `#823`, `#824`) — Phase C, otra umbrella.
- Reorganización de las páginas internas — sólo el nav.

## Work-unit commits planeados

| WU | Descripción | Estado |
|---|---|---|
| WU-1 | Tracking (este documento) + decisión dropdown vs section-heading + rama `feat/809-group-nav-items` | en curso |
| WU-2 | Refactor de `NAV_ITEMS` + render en templates + CSS / JS según decisión | pendiente |
| WU-3 | `tests/e2e/test_nav_grouping.py` con probes (count, paths, accesibilidad) | pendiente |
| WU-4 | Gates locales + commit + push + CI + merge | pendiente |

## Gates (CI required check, pre-MVP single-branch)

- `ruff check .` sin findings nuevos.
- `python scripts/check_rules.py .` exit code 0.
- `python -m mypy` sin errores nuevos.
- `pytest tests/test_pages.py tests/test_template_selection.py tests/test_template_migration.py -q` verde.
- `pytest tests/e2e/test_nav_*.py tests/e2e/test_nav_grouping.py -q` verde bajo chromium (auto-skip si no).
- axe-core `link-name` verde (los nuevos headings no introducen links vacíos).
- Issue-spec: el body del #809 está en inglés. Acción: reescribir a Castellano antes del PR.
- Budget ≤ 400 líneas. Si se excede, split via chained PR (WU-2a templates + WU-2b JS/CSS).

## Legacy fidelity (P1)

N/A — sólo reorganiza el header web.

## Estrategia de implementación

### Decisión dropdown vs section-heading (WU-1)

| Criterio | Dropdown (`<details>` o JS) | Section-heading (CSS) |
|---|---|---|
| Visibilidad sin JS | Sí (`<details>`) | Sí (CSS only) |
| Complejidad de testing | Alta (estado abierto/cerrado, focus trap) | Baja (estática) |
| Coherencia con burger mobile | Requiere sync entre burger JS (`#820`) y dropdown | Trivial — los headings son siempre visibles |
| Mantenibilidad | Media — dropdown JS vs CSS-only divergen | Alta — CSS pura |
| Compatibilidad con `#820` | Hay que decidir si el burger togglea también los dropdowns | El burger sigue togglando el nav entero |

**Recomendación: section-heading (CSS)**. Es coherente con el principio «mobile fallback = mobile burger, desktop = section headings», evita JS extra, y el issue lo acepta.

### Mapeo propuesto (section-heading)

| Heading | Items |
|---|---|
| (top-level) | Inicio, Animales, Voluntarios |
| **Entradas** | Entradas, Lote |
| **Acogida** | Casas, Estancias, Adopciones, Actuaciones |

Esto da 3 items sueltos + 2 grupos = 5 «entradas visuales» en el top-level. Los grupos tienen 2 y 4 hijos. La jerarquía queda:

```
[Inicio] [Animales] [Entradas ▾] [Acogida ▾] [Voluntarios]
                          │              │
                          ├ Entradas     ├ Casas
                          └ Lote         ├ Estancias
                                         ├ Adopciones
                                         └ Actuaciones
```

Si section-heading puro (sin dropdown), los hijos se renderizan como segundo row bajo el heading — eso es factible pero empuja el contenido. Si se prefiere dropdown, se usa `<details>` nativo y CSS para desktop-open + burger JS para mobile.

### Cambios concretos

- `app/core/nav.py` — introducir `NAV_GROUPS = {...}` además de `NAV_ITEMS = [...]`. `resolve_active_nav_href` se mantiene.
- `app/templates/base.html` — render del nav lee `NAV_GROUPS`, no `NAV_ITEMS`.
- `app/templates/base_mobile.html` — idem.
- CSS — añadir una utility `.nav-group` con borde inferior sutil y `.nav-group__items` con gap reducido.

## Riesgos identificados

1. **Body en inglés** — reescribir a Castellano antes del PR.
2. **A11y del grouping** — los `<h2>` o `<h3>` deben tener `aria-label` o contexto que no confunda a screen readers. Si el heading es sólo visual, debe ser `aria-hidden="true"` con un `<span class="sr-only">` que describa el grupo.
3. **Active-state dentro de grupos** — `#805` marca el item activo con `aria-current="page"`. Si el item activo está dentro de un grupo colapsado (dropdown), hay que auto-abrir el grupo. Esto es una decisión de scope.
4. **Conflicto con `#820` burger JS** — si el burger togglea el nav entero y dentro hay dropdowns, hay que decidir si el burger abre/cierra los dropdowns también, o sólo el nav root. Decisión: burger abre el nav, los dropdowns son independientes.
5. **Migración de usuarios** — si un usuario tiene bookmark a `/entradas/batch/new` (lote), sigue funcionando. La ruta no cambia, sólo el lugar en el nav.

## Criterios de cierre del slice

- [ ] Branch `feat/809-group-nav-items` con WU-2 y WU-3 mergeados.
- [ ] `NAV_GROUPS` introducido, `NAV_ITEMS` reducido.
- [ ] Templates re-renderizan con section-heading (o dropdown, según decisión WU-1).
- [ ] `tests/e2e/test_nav_grouping.py` verde bajo chromium.
- [ ] Gates locales verdes.
- [ ] axe-core `link-name` verde.
- [ ] PR abierto contra `origin/main`, CI verde, merge con `--admin`.
- [ ] Issue `#809` cerrada vía `Fixes #809`.
- [ ] Worktree local borrado.
- [ ] Memoria de sesión guardada.
- [ ] Epic `#817` sigue OPEN hasta que Phase C (`#824`) mergee.