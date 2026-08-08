[← Back to README](../../README.md)

# 2026-07-25-audit-checklist.md

This audit documents the scope, methodology, findings, and verdict for the audit listed in the title. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto del checklist del audit full-codebase ejecutado el 2026-07-25 contra `main` en `abcaa89`, que produce el inventario de issues etiquetados `audit-2026-07-25`.

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Issue de tracking y baseline medida al ejecutar el audit. |
| [Methodology](#methodology) | Procedimiento para trabajar el batch de issues. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict) | Estado final del audit y de los findings derivados. |
| [References](#references) | PRs de cierre, issues y enlaces relacionados. |

> **Mirror del issue de tracking**: <https://github.com/ardelperal/APAP_WEB/issues/294>. La fuente canónica de verdad es el issue de GitHub. Este fichero es un mirror in-repo sincronizado con el cuerpo del issue. Cuando el issue cambie, vuelva a ejecutar el mismo flip + "Closed findings" append que produjo esta revisión.

## Scope

| Item | Value |
|---|---|
| Tracking issue | <https://github.com/ardelperal/APAP_WEB/issues/294> |
| Fecha del audit | 2026-07-25 |
| HEAD auditado | `main` en `abcaa89` |
| Etiqueta de los issues derivados | `audit-2026-07-25` |

### Baseline medida al ejecutar el audit

| Gate | Resultado |
|---|---|
| `ruff check .` | pass |
| `python -m mypy` | pass — 0 errores, 92 ficheros |
| `python scripts/check_rules.py .` | pass — 12 detectores |
| `check_module_size.py` / `check_route_size.py` | pass |
| `pytest --cov=app` | 2516 passed, 3 failed, 2 skipped — **89.18%** coverage |
| `CRITICAL_HELPERS` gate | pass — 21 helpers al 100% |

Los 3 fallos locales: 2 son los casos environment-dependent de `test_coverage_gate.py` (#292), 1 es el hard-fail by-design del test de concurrencia TOCTOU (#282).

## Methodology

Cada issue del audit lleva la etiqueta `audit-2026-07-25`. Para tomar trabajo:

```bash
gh issue list --label audit-2026-07-25 --state open
```

Cada issue es self-contained: nombra el fichero y línea exactos, declara el escenario de fallo, lista los criterios de aceptación, nombra las reglas de AGENTS.md que aplican y da los comandos para validar. Un agente no debería necesitar este epic para ejecutar ninguno de ellos.

Siga `docs/proceso.md` y AGENTS.md §15 (política pre-MVP de rama única) para el flujo branch/PR/merge. Varios tocan auth, secretos o CSRF, lo que hace `judgment-day` obligatorio según §17.2 — cada issue lo indica donde aplica.

### Aspectos que el audit declaró sanos

Conviene declarar lo que está bien, porque es la razón por la que los hallazgos de abajo son puntuales y no estructurales:

- Límite de capas sostenido — cero llamadas a `execute_sql` en rutas.
- Cero interpolación de strings SQL en `app/`; todo parametrizado.
- Cero `| safe` en plantillas; autoescape de Jinja intacto.
- La autorización se re-valida contra la base de datos en cada request, sin confiar en la cookie.
- Path traversal cerrado sobre storage keys y nombres de bucket antes de cualquier llamada HTTP.
- 12 detectores AST específicos del proyecto más dos ratchets de tamaño shrink-only, todos cableados en CI.
- Dockerfile multi-stage, runtime non-root, sin tooling de build en la imagen final.

### Orden sugerido de resolución

1. **#275** primero — es el único hallazgo que convierte un slip de config en bypass total de auth.
2. **#277 + #278** juntos — mismo fichero, mismo flujo, diff combinado pequeño.
3. **#279**, después **#276**.
4. **#281** y **#282** antes de que aterrice cualquier otra cosa, para que los gates CI que validan el resto estén realmente corriendo.
5. **#293** temprano en vez de tarde: es la regla que detiene la próxima hornada de estos.

### Hallazgos de issues preexistentes en el mismo territorio

No abiertos por este audit, pero pertenecen al mismo clúster y deberían programarse junto a estos:

- #205 — extracción de query builders (aparea con #290 y la mitad `acogidas` de #289).
- #206, #223 — la suite E2E no corre en CI (aparea con #288).
- #217, #218, #219 — `type:bug` abiertos en `migration/`; **#218 (swallowed `conn.commit()` failure) es un gap silencioso de durabilidad y merece prioridad**.
- #198 — inventario de review-authority corrupto.

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| CRITICAL | #275 — fail-fast en secretos faltantes o placeholder en startup (mayor impacto del audit) | fixed | PR #307 |
| HIGH | #276 — middleware de cabeceras de seguridad HTTP (CSP, X-Frame-Options, nosniff, Referrer-Policy, HSTS) | fixed | PR #311 |
| HIGH | #286 — rate limiting sobre el flujo OAuth y las rutas de escritura | fixed | PR #306 |
| HIGH | #277 — `POST /admin/users` devuelve 500 en email duplicado | fixed | PR #308 |
| MEDIUM | #278 — email nunca normalizado: ghost users y revocaciones perdidas | fixed | PR #308 |
| HIGH | #279 — lockout permanente cuando se desactiva al último developer activo | fixed | PR #309 |
| HIGH | #280 — `invalidate_all()` reabre la race write-after-invalidate | fixed | PR #310 |
| MEDIUM | #281 — el job `deploy` nunca corre (merge-commit guard vs. PR-only policy) | fixed | PR #302 |
| BLOCKER | #283 — `log_safe` puede lanzar `KeyError` por nombres de campo reservados de `LogRecord` | fixed | PR #301 (junto con #284) |
| HIGH | #284 — `JsonFormatter` emite ~15 campos internos por línea de log | fixed | PR #301 |
| MEDIUM | #285 — `animal_foto` bufferea fotos enteras, sin cache headers, docstring obsoleto | fixed | PR #304 |
| HIGH | #287 — `RedisAuthCache` es dead code alcanzable por configuración | fixed | PR #298 |
| LOW | #289 — `domain.py` y `acogidas/service.py` están a 1–2 líneas del presupuesto de tamaño | fixed | PR #303 |
| MEDIUM | #290 — la regla 22 (query-builder seam) tiene cero adopción y sin gate | fixed | PR #305 |
| LOW | #291 — AGENTS.md tiene dos reglas numeradas como 29 | fixed | PR #298 |
| MEDIUM | #293 — codificar los anti-patrones detectados como regla en AGENTS.md | fixed | PR #295 |
| HIGH | #282 — el test de concurrencia TOCTOU no corre en ningún sitio | open finding | Test hard-failing sin Postgres, `--deselect`-ed en CI |
| MEDIUM | #292 — `test_coverage_gate.py` subprocess depende del `sys.path` ambiente | open finding | Test environment-dependent, 2 fallos en baseline local |
| MEDIUM | #288 — gap de cobertura de la capa de rutas oculto por la media global | open finding | Route layer entre 57% y 83%, `voluntarios/routes.py` al 57.3% |

## Verdict

PASS: el audit identificó un set focalizado de hallazgos. Los findings abiertos (#282, #288, #292) son riesgos conocidos y rastreados, no son regresiones nuevas. Los 17 hallazgos cerrados en `main` se distribuyen entre seguridad, robustez, integridad de tests y deuda técnica, y han elevado el estado de hardening del proyecto.

El audit también produjo el nuevo AGENTS.md §32 (anti-patrones) y endureció el CI con detectores AST adicionales y ratchets shrink-only (reglas §21, §25, §26, §27, §28), de modo que los patrones detectados queden rechazados en revisión antes de producir nuevas instancias.

## References

- Tracking issue #294: <https://github.com/ardelperal/APAP_WEB/issues/294>
- PRs de cierre: #295, #298, #301, #302, #303, #304, #305, #306, #307, #308, #309, #310, #311
- Issues abiertos derivados: #282, #288, #292
- Reglas AGENTS.md derivadas: §32 (anti-patrones)
- Docs/proceso.md, AGENTS.md §15 (política pre-MVP), §17.2 (`judgment-day` para high-stakes)
