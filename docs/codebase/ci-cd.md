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
| Pull request | Ejecuta todos los checks obligatorios, incluido el smoke Playwright. |
| Tag `v*` | Ejecuta controles profundos y la matriz de release. |
| Programación | Ejecuta el control asignado por la matriz; los demás quedan omitidos de forma válida. |
| Push a `main` | Ejecuta `deploy.yml`; no reconstruye una segunda CI. |
| Ejecución manual | Permite validar CI o despliegue sin cambiar el contrato de evidencia. |

## Jobs de CI

| Job | Responsabilidad |
|---|---|
| `lint` | Ruff, reglas APAP, límites de arquitectura y ratchets. |
| `issue-spec` | Issue vinculada, aprobada y con las seis secciones obligatorias. |
| `security` | Auditoría de dependencias, secretos y Dockerfile. |
| `security-deep` | Análisis profundo reservado a release o programación. |
| `mutation` | Mutación programada o de release. |
| `typecheck` | Mypy sobre `app/` y `migration/`. |
| `test` | Suite principal, cobertura del 85 % y CRAP. |
| `integration` | SQL real contra PostgreSQL efímero. |
| `verify-fallback-ready` | Condiciones automáticas del fallback legacy. |
| `build` | Wheel, sdist y Dockerfile reproducible. |
| `e2e` | Aplicación real, PostgreSQL y Chromium sin skips implícitos. |
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

## Comprobación del contribuidor

- [ ] Ejecute `uv sync --frozen --extra dev` antes de validar.
- [ ] Ejecute `make verify`; trate el resultado como subconjunto local.
- [ ] No relaje un job, un timeout, un lock ni el agregador `required`.
- [ ] Enlace una issue completa y aprobada; `required` incluye ese veredicto.
- [ ] Actualice esta página y su test ancla si cambia la matriz de jobs.
- [ ] Espere todos los checks aplicables en verde antes del merge.

## Navegación

Anterior: [Maintainer playbook](maintainer-playbook.md) | Siguiente: [Sync and cloud](sync-and-cloud.md)
