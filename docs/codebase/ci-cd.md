[← Volver a Codebase Guide](../CODEBASE-GUIDE.md)
# CI/CD de APAP_WEB

Esta página describe el pipeline ejecutable de GitHub Actions. No sustituye el
runbook de Coolify ni explica los ratchets individuales.
## Qué es

| Es | Evidencia en el repositorio |
|---|---|
| CI aislada y fail-closed | [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) |
| Entrega de una imagen `OCI` inmutable | [`.github/workflows/deploy.yml`](../../.github/workflows/deploy.yml) |
| Política de merge aplicada por GitHub | [`.github/branch-protection.md`](../../.github/branch-protection.md) |

## Qué no es

| No es | Use este límite |
|---|---|
| Una garantía de bytes idénticos en Coolify | El recurso actual reconstruye el commit y publica `SOURCE_COMMIT`. |
| Una réplica íntegra en `make verify` | Los servicios, Docker y Chromium se ejecutan en GitHub Actions. |
| Un permiso para omitir checks | Solo `required` decide si la matriz del evento es válida. |

## Flujo de entrega

```text
pull request
  └─ ci.yml: issue spec + checks aislados → required
       └─ protección de main permite merge commit
            └─ deploy.yml prueba la evidencia del PR
                 └─ build ARM64 → digest OCI → Trivy → smoke PostgreSQL
                      └─ deploy-current → webhook Coolify → SOURCE_COMMIT
                           └─ /healthz confirma el commit o activa rollback
```

## Eventos

| Evento | Comportamiento |
|---|---|
| Pull request | Ejecuta los checks obligatorios. `e2e` corre solo cuando `ui-detection` marca cambio de UI en la revisión; con `ui_changed=false` el job se omite de forma explícita y `required` acepta ese skip únicamente porque el run lleva el marcador (issue #895). |
| Push a `staging` | Mismo contrato de e2e que el pull request: corre solo si el diff contra `github.event.before` (con fallback al commit padre) declara cambio de UI (issue #895). |
| Tag `v*` | Ejecuta controles profundos y la matriz de release; `e2e` debe terminar en `success` y el marcador de no-UI no lo exime. |
| Push a `main` | Ejecuta `deploy.yml`; no reconstruye una segunda CI. |
| Ejecución manual | Permite validar CI o despliegue sin cambiar el contrato de evidencia; también sirve como ensayo previo a un tag para `mutation`, `security-deep` y `e2e`. |

`ci.yml` no declara ningún trigger `schedule`: los controles pesados
(`mutation`, `security-deep`) se reservan para el push de un tag `v*`
o para `workflow_dispatch` (issue #780). `e2e` corre en esos eventos de
release y, además, en cualquier pull request o push cuya revisión
declare cambio de UI según la detección fail-closed del issue #895.

## Superficie de UI

La detección de cambios de UI es **fail-closed invertida** (fix round 1
del issue #895): una revisión es relevante para UI salvo que todos los
ficheros cambiados estén en la lista blanca de no-UI
(`NON_UI_PATH_PREFIXES` en `scripts/check_required_jobs.py`: `docs/`,
`tests/`, `skills/`, `migration/`, `openspec/`, `scripts/`, `.github/`,
resto de directorios de tooling, y ficheros raíz como `README.md`,
`AGENTS.md`, `Makefile` o `pyproject.toml`). Todo `app/**` y
`tailwindcss/` quedan fuera de la lista por diseño: FastAPI renderiza
Jinja desde Python (routes, `_form_render`, templates, static afectan al
navegador), de modo que ninguna lista positiva de rutas UI llega a ser
exhaustiva. En push el diff base es `github.event.before` — el SHA que
el push reemplazó, que cubre commits múltiples — con fallback al commit
padre solo para el push inicial (SHA cero) y `workflow_dispatch`.

**Peaje anti-autoexención.** Editar el código fuente del
propio gate — `scripts/check_required_jobs.py`, `ci.yml` o `deploy.yml`
— fuerza `ui_changed=true` en ambos consumidores (`ui-detection` y
`ui-e2e-gate`): el gate no puede editarse sin pagar el e2e, de modo que
un cambio de la lista blanca nunca puede reclasificar cambios de UI
futuros sin evidencia.

Los consumen `ci.yml` (`ui-detection`) y `deploy.yml` (`ui-e2e-gate`)
mediante `python scripts/check_required_jobs.py --print-ui-paths` (la
lista) y `--ui-changed` (el clasificador fail-closed), de modo que las
tres piezas no pueden divergir.

## Jobs de CI

| Job | Responsabilidad |
|---|---|
| `pr-size` | Presupuesto de 400 líneas por PR (AGENTS.md §15.1); primer job, el resto depende de él vía `needs`. Delega la implementación a `pr-size.yml` como workflow reusable (`uses:`) — única fuente del cálculo (issue #890). |
| `lint` | Ruff, reglas APAP, límites de arquitectura y ratchets. |
| `issue-spec` | Issue vinculada, aprobada y con las seis secciones obligatorias. |
| `security` | Auditoría de dependencias, secretos y Dockerfile. |
| `security-deep` | Análisis profundo reservado a release o ejecución manual. |
| `mutation` | Mutación reservada a release o ejecución manual. |
| `typecheck` | Mypy sobre `app/` y `migration/`. |
| `test` | Suite principal, cobertura del 85 % y CRAP. |
| `integration` | SQL real contra PostgreSQL efímero. |
| `verify-fallback-ready` | Condiciones automáticas del fallback legacy. |
| `build` | Wheel, sdist y Dockerfile reproducible. |
| `ui-detection` | Calcula `ui_changed` (diff contra la base del PR o contra `github.event.before` con fallback al commit padre) aplicando la detección fail-closed del checker; fuerza `ui_changed=true` si se edita el código fuente del gate; publica el marcador que condiciona `e2e` y que `required` verifica (issue #895). |
| `e2e` | Aplicación real, PostgreSQL y Chromium sin skips implícitos; corre en eventos de release y cuando la revisión cambia UI (issue #895). |
| `required` | Valida resultados según el evento y produce el veredicto único. |

El contexto visible es `ci / required`. La API de protección de ramas usa el
nombre real del check, `required`; no use el nombre compuesto de la interfaz.

El job `issue-spec` comprueba que cada referencia de cierre apunta a una
[spec de issue](issue-specifications.md) completa y aprobada. `required` agrega su resultado.
## Dependencias y artefacto

Python 3.12.11, `uv==0.9.28`, `uv.lock` y `npm ci` fijan el entorno. El setup
compartido vive en [`.github/actions/setup-python`](../../.github/actions/setup-python/action.yml).

El deploy construye una imagen ARM64 candidata. Publica el digest con `SBOM` y
provenance, escanea ese digest y ejecuta el smoke sobre esos mismos bytes.
`deploy.yml` separa la prueba `evidence` de la ejecución privilegiada `deploy`.
El job `release-e2e-gate` ancla la validación e2e de producción al proceso de
release: falla si la variable de repositorio `APAP_E2E_GATE_EVIDENCE` no
registra la evidencia del runbook
[e2e-production](../runbooks/e2e-production.md). El operador debe sustituir el
valor de la variable en cada release (o registrar
`APAP_E2E_GATE_EVIDENCE=skipped:<motivo>` como bypass auditable); el gate
garantiza que la evidencia quedó registrada, no su frescura por release.

El job `ui-e2e-gate` (issue #895) bloquea el despliegue de una revisión
que declara cambio de UI sin evidencia e2e de esa misma revisión:
recalcula `ui_changed` con la misma detección fail-closed de
`scripts/check_required_jobs.py` (lista blanca de no-UI + peaje de
ficheros del gate, diff base `github.event.before` con fallback al
commit padre) y, si hay cambio de UI, verifica vía API de check-runs
(solo lectura, con `GITHUB_TOKEN`, `filter=latest` y acotada a la app
`github-actions`) que un run de CI sobre la SHA revisada tuvo el job
`e2e` con conclusión `success`. Un `e2e` fallido, cancelado, omitido
inesperadamente, incompleto o ausente hace fallar el gate y bloquea el
deploy. Una revisión sin cambios de UI pasa con una línea de exención
explícita en el log.

**Recuperación del fallo "main moved".** Si el árbol del
merge commit difiere del árbol de la rama revisada (`HEAD^2`), el gate
falla cerrado: la evidencia e2e ya no binda a esta revisión. La vía de
recuperación es actualizar la rama sobre la nueva `main` (merge o
rebase), dejar que `ci.yml` corra en verde sobre la rama actualizada y
volver a mergear. Despachar `ci.yml` manualmente sobre el merge commit
existente *no* satisface el gate, porque los check-runs de pull_request se
reportan sobre la SHA de la rama, no sobre el merge.

**Riesgo residual del peaje (disposición).** La autoexención adversarial
— un actor editando el gate para saltarse el e2e a propósito — está
fuera del modelo de amenazas: el repo opera con una credencial
compartida de administrador, con la que cualquier actor puede saltarse
cualquier control. El gate protege contra el accidente, y el peaje sobre
los ficheros del gate cierra esa vía accidental: ninguna edición del
gate pasa inadvertida para el e2e.
## Protección y runners

Los pull requests usan runners efímeros de GitHub. Ningún código de un pull
request se ejecuta en el host de producción ni accede a su Docker daemon.

El deploy usa el runner dedicado con label `deploy`. `main` exige pull request,
conversaciones resueltas, `required`, `branch-name` y `pr-size`; prohíbe
force-push y borrado, y conserva merge commits.

## Fallos y recuperación

Un resultado ausente, malformado, fallido o cancelado hace fallar `required`.
Solo la matriz versionada permite un job omitido para un evento concreto.

Coolify reconstruye el mismo commit verde e inyecta `SOURCE_COMMIT` en runtime.
El workflow exige ese SHA en `/healthz`; si falla, solicita el commit anterior.

Consulte el [runbook de despliegue](../runbooks/operator-deploy-2026.md) para la
configuración inicial, la operación manual y la recuperación de base de datos.

El gate de validación e2e contra producción (épica #909) se ejecuta fuera de
la CI, desde una estación: el ciclo de encendido, pruebas y apagado del flag
de e2e está documentado en el [runbook e2e de producción](../runbooks/e2e-production.md).

## Comprobación del contribuidor

- [ ] Ejecute `uv sync --frozen --extra dev` antes de validar.
- [ ] Ejecute `make verify`; trate el resultado como subconjunto local.
- [ ] No relaje un job, un timeout, un lock ni el agregador `required`.
- [ ] Enlace una issue completa y aprobada; `required` incluye ese veredicto.
- [ ] Actualice esta página y su test ancla si cambia la matriz de jobs.
- [ ] Espere todos los checks aplicables en verde antes del merge.

## Navegación

Anterior: [Maintainer playbook](maintainer-playbook.md) | Siguiente: [Sync and cloud](sync-and-cloud.md)
