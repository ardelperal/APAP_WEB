# Repository map

[Back to Codebase Guide](../CODEBASE-GUIDE.md)

Esta página posee el mapa de ownership por paquete y la regla de §33 para colocar código nuevo. No posee detalle de comportamiento — eso es [interfaces](interfaces.md) y [integrations](integrations.md) — ni reglas operativas — eso es [AGENTS.md](../../AGENTS.md).

## Core invariants

- **Regla §33.2**: dos consumidores o más sin razón de cambio propia → `app/core/<layer>/<slice>/`. Razón de negocio propia → `app/modules/<slice>/`. En la duda, módulo.
- **Layout hexagonal (§33.3)**: dentro de un slice convertido, `domain/`, `ports/`, `application/`, `adapters/insforge/`, `di/`. SQL solo en `adapters/insforge/<slice>_insforge_queries.py`.
- **API pública por paquete (§27)**: cross-module imports llegan a `app.modules.<B>` por su `__init__.py`, nunca a un submódulo.
- **Ratchets shrink-only**: módulos sobre 700 líneas (§21) y handlers sobre 50 líneas (§28) viven en `BASELINE` que solo decrece.

## Ownership por paquete

| Path | Owns |
|---|---|
| [`app/main.py`](../../app/main.py) | Composition root del servidor FastAPI, registro de routers, ciclo de vida. |
| [`app/core/`](../../app/core/) | Capacidades transversales convertidas a hexagonal: auth, oauth, catalogos, schema_bootstrap, admin. |
| [`app/modules/animals/`](../../app/modules/animals/) | Slice hexagonal completo: las once capacidades y todas las rutas usan `AnimalsPort`; no quedan shims legacy. |
| [`app/core/insforge.py`](../../app/core/insforge.py) | Cliente HTTP único hacia InsForge; nadie más lo importa fuera de `adapters/` y `di/`. |
| `app/core/auth*.py`, `csrf.py`, `session.py` | Defensa en profundidad: allowlist, CSRF, cookies firmadas. |
| [`app/core/migration/`](../../app/core/migration/) | Sync bidireccional web ↔ legacy; único paquete que lee ambos backends. |
| [`app/modules/<slice>/`](../../app/modules/) | Capacidades de negocio en layout legacy `routes.py / service.py / queries.py` mientras esperan conversión. |
| `app/modules/<slice>/__init__.py` | API pública del módulo (regla §27); aquí se reexportan nombres consumidos por otros módulos. |
| [`app/templates/`](../../app/templates/) | Plantillas Jinja2; cada `<form method="post">` lleva `csrf_token` (regla §10). |
| [`app/static/`](../../app/static/) | Assets compilados (Tailwind v4 CSS-first). |
| [`tests/`](../../tests/) | Unit + integration + E2E (Playwright); el E2E es la red de QA-through-UI (§23). |
| [`scripts/`](../../scripts/) | Linters, gates, arnés de calidad, herramientas de medición; ver [quality/hardening-roadmap](../quality/hardening-roadmap.md). |
| [`docs/`](../../docs/) | Documentación navegable: hub, radiales, auditorías, runbooks, decisiones. |
| [`openspec/specs/`](../../openspec/specs/) | Especificaciones delta por capacidad (lo que el código debe cumplir). |
| [`openspec/changes/`](../../openspec/changes/) | Cambios SDD activos y archivados. |
| [`.codegraph/`](../../.codegraph/) | Índice de inteligencia de código; ver [integrations](integrations.md). |

## Dónde va código nuevo (§33.2)

| Pregunta | Si la respuesta es sí | Ubicación |
|---|---|---|
| ¿Lo consumen dos o más slices? | No | `app/modules/<slice>/` (default) |
| ¿Tiene razón de negocio propia para cambiar? | No | Considere `app/core/` solo si hay ≥ 2 consumidores |
| ¿Ejecuta SQL? | — | `queries.py` (legacy) o `adapters/insforge/<slice>_insforge_queries.py` (hexagonal) |
| ¿Importa `InsForgeClient`? | — | Solo bajo `adapters/insforge/` y `di/` del slice, o `app/main.py` (§33.4) |
| ¿Es infra transversal nueva (auth, catalogos, schema)? | — | `app/core/<layer>/<slice>/` con los cinco subpaquetes del §33.3 |

## Linter → regla → detector

| Script | Regla AGENTS | Detector | What it bans |
|---|---|---|---|
| [`check_rules.py`](../../scripts/check_rules.py) | §20, §25, §26, §27 | APAP001, APAP003, Detectores 2–12 | SQL en routes, `logger.*` y `print(...)` en `app/`, auth default-allow, redirects vía `HTTPException`, helpers duplicados, lazy-imports sin marcador, imports cross-module a submódulo |
| [`check_module_size.py`](../../scripts/check_module_size.py) | §21 | Ratchet `BASELINE` | Módulos `app/` o `migration/` sobre 700 líneas |
| [`check_route_size.py`](../../scripts/check_route_size.py) | §28 | Ratchet `BASELINE` | Handlers de route sobre 50 líneas |
| [`check_layers.py`](../../scripts/check_layers.py) | §33 | Gate de capas y slices | Transporte filtrado a `domain/`, `ports/` o `application/` |
| [`check_slice_completeness.py`](../../scripts/check_slice_completeness.py) | §33.4 | Pin por slice | Slice hexagonal sin port, sin adapter o sin use case |
| [`check_migration_boundaries.py`](../../scripts/check_migration_boundaries.py) | §18.3 | Gate de paquete `migration/` | Sync que lee o escribe en backends cruzados fuera del paquete |
| [`check_docstring_coverage.py`](../../scripts/check_docstring_coverage.py) | §30 | Ratchet de cobertura | Módulos sin docstrings sincronizados con tests |
| [`check_complexity.py`](../../scripts/check_complexity.py) | — | Ratchet ciclomático | Complejidad ciclomática sobre el baseline |
| [`check_ruff_ratchet.py`](../../scripts/check_ruff_ratchet.py) | — | Ratchet de reglas ruff | Reglas ruff extendidas aún no exigibles en bloque |
| [`check_vulture_guard.py`](../../scripts/check_vulture_guard.py) | — | Detector de código muerto | Funciones o clases no usadas |
| [`check_jscpd.py`](../../scripts/check_jscpd.py) | — | Ratchet de duplicación | Copias literales entre archivos |
| [`check_mutation_sites.py`](../../scripts/check_mutation_sites.py) | — | Conteo de sitios | Recuento que crece sin justificación |
| [`check_import_cycles.py`](../../scripts/check_import_cycles.py) | — | Detector de ciclos | Ciclos en el grafo de imports |
| [`check_crap.py`](../../scripts/check_crap.py) (job `test`) | — | Ratchet CRAP | Funciones con alta complejidad y baja cobertura |
| [`check_mutation.py`](../../scripts/check_mutation.py) (job `mutation`) | — | Cosmic Ray | Mutantes sobrevivientes sobre el baseline |

## Contributor checklist

- [ ] Si añade un módulo a `app/modules/`, defina su `__init__.py` con la API pública antes de que otro módulo lo consuma (regla §27).
- [ ] Si convierte un módulo a hexagonal, reemplace `service.py` por `application/<use_case>.py` y mueva el SQL a `adapters/insforge/<slice>_insforge_queries.py` (§33.3).
- [ ] Si añade un módulo a `app/`, verifique que está dentro del presupuesto de 700 líneas (§21) y que ningún handler supera 50 líneas (§28).
- [ ] Si añade un linter nuevo, declárelo en `ci.yml` dentro del job `lint` y agregue un test en `tests/` que pinea el gate.
- [ ] Si añade un script de seed o backfill, declárelo en `scripts/` y agregue el prefijo `seed*` o `backfill*` (mapa de `judgment-day` en AGENTS §17.2).

## Navigation

Previous: [Mental model](mental-model.md) | Next: [Interfaces](interfaces.md)
