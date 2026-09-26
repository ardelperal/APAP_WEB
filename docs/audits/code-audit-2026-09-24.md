[← Back to README](../../README.md)

# code-audit-2026-09-24.md

Este informe documenta la auditoría de código ejecutada el 2026-09-24 sobre `main` en `b048c64`: qué se auditó, qué se encontró, qué se descartó y qué PR corrige cada hallazgo. La épica de seguimiento es [#911](https://github.com/ardelperal/APAP_WEB/issues/911) y cada hallazgo vive en su issue con el label `audit-2026-09-24`.

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Superficie auditada y commit base. |
| [Methodology](#methodology) | Tres pasadas de solo lectura más verificación manual. |
| [Findings](#findings) | Tabla de trazabilidad hallazgo → issue → PR → estado. |
| [Healthy areas](#healthy-areas) | Lo verificado sano, para no perseguir fantasmas. |
| [Discarded findings](#discarded-findings) | Hallazgos descartados o sin issue, con motivo. |
| [Open questions](#open-questions) | Dudas técnicas pendientes de decisión. |
| [Maintenance rule](#maintenance-rule) | Cómo se mantiene viva la tabla. |
| [References](#references) | Issues, PRs y docs relacionadas. |

## Scope

| Item | Value |
|---|---|
| Commit base | `b048c64` (main, 2026-09-24) |
| Superficie | `app/core`, `app/modules`, `migration/`, `tests/`, tooling e infraestructura (CI, Docker, compose, configuración) |
| Fecha | 2026-09-24 |
| Épica de seguimiento | [#911](https://github.com/ardelperal/APAP_WEB/issues/911) (olas 0-3) |

## Methodology

Tres auditorías de solo lectura, cada una con su lente:

1. **Núcleo y seguridad** (`app/core`): auth, sesiones, CSRF, rate limit, cabeceras, secretos, logging, schema provisioning.
2. **Dominio y datos** (`app/modules`, `migration/`): flujos de escritura, atomicidad, SQL, integridad referencial, fidelidad al legacy.
3. **Tests, tooling e infraestructura**: huecos de cobertura, estado global compartido, jobs de CI, imágenes y compose, coherencia documental.

Los hallazgos de severidad alta se verificaron a mano contra el código antes de abrir issue (archivo:línea y escenario de fallo reproducible). El hallazgo sistémico que ordena la épica: `SqlExecutor.execute_sql` abre y confirma una conexión por llamada, de modo que ningún flujo con varias escrituras era atómico aunque el código lo pretendiera.

## Findings

Tabla de trazabilidad. La columna PR queda con el número del PR que fusiona el hallazgo; el estado pasa a `cerrado` solo al fusionar con CI verde.

| ID | Severidad | Resumen | Issue | PR | Estado |
|---|---|---|---|---|---|
| D-00 | — | Este informe: trazabilidad hallazgo → issue → PR y roadmap en docs | #912 | — | en curso |
| A-01 | Crítico | `SqlExecutor.transaction()`: unidad de trabajo sobre una sola conexión (patrón `create_adopcion`) | #913 | #925, #931 | cerrado |
| A-12 | Crítico | `LocalPostgresExecutor` traduce `$N` por posición: consultas con `$N` repetidos o desordenados fallan o enlazan columnas equivocadas | #944 | #946 | cerrado |
| A-13 | Crítico | Cuatro flujos pasan una etiqueta de texto como `created_by` (`UUID NOT NULL`): eventos de adopción y acogida fallan contra Postgres real | #945 | #950, #951, #961, #965 | cerrado |
| A-14 | Crítico | El `CHECK` de `event_type` no admite `INTAKE_CLOSED_BY_FOSTER`: `create_acogida` falla contra Postgres real; `ALTER` idempotente para bases existentes | #947 | #948 | cerrado |
| A-02 | Crítico | Altas de adopción y acogida no atómicas (transacción real + fault injection contra Postgres real) | #914 | #975 | cerrado |
| A-03 | Alto | `close_all_on_death` no atómico (defunción + cierres en una transacción) | #915 | #983 | cerrado |
| A-04 | Crítico | Cambio de chip sobre columnas `chip` inexistentes + transacción simulada con `BEGIN`/`COMMIT` vía `execute_sql`; decisión D-43 (las dependientes resuelven por `animal_id`) | #916 | #996 | cerrado |
| A-05 | Alto | Sesión de magic link sin `csrf_token`/`user_id`/`rol`: escrituras bloqueadas con 403 y auditoría anónima; paridad con la sesión OAuth + fail-closed | #917 | #1001 | cerrado |
| A-06 | Alto | Drift de tooling: pin de cosmic-ray revertido por Dependabot, docker-compose sin MinIO, `APAP_BUILD_SHA` literal, cobertura 80/85 en docs | #918 | — | pendiente (agente del epic CI #935) |
| A-07 | Medio | Borrado cruzado de material de estancia (`junction_id` sin comprobar pertenencia) y redirecciones con parámetros sin codificar | #919 | #1009 | cerrado |
| A-08 | Medio | Identificadores de schema en DDL con f-string, `trust_xff` sin lista de proxies de confianza, `X-Request-ID` entrante sin validar | #920 | #1010 | cerrado |
| A-09 | Bajo | `schema_provisioning` importa `tests/`, `_case_variants` muerto, `assert` como guard en tiempo de ejecución | #921 | — | pendiente |
| A-10 | Medio | `xfail` por estado global en reverse_apply, rate limit sin prueba de concurrencia, reintentos de tasks sin prueba | #922 | — | pendiente |
| A-11 | Medio | Alcance de lectura de los roles legacy en RBAC sin decisión ni test (requiere decisión de producto) | #923 | — | pendiente |

## Healthy areas

Lo verificado sano durante la auditoría, para que ninguna revisión futura lo trate como pendiente:

- Todos los handlers revisados tienen dependencia de auth; el middleware es deny-by-default con `PUBLIC_PATHS` como allowlist.
- Sin SQL concatenado con entrada de usuario en la capa de auth; `migration/` pasa los nombres de tabla por `_safe_table()`.
- `log_safe` redacta PII y es el único punto de logging en `app/` (APAP003).
- El backdoor e2e solo se registra con su flag y compara el secreto con `compare_digest`.
- Sin violaciones de capa: ningún `execute_sql` en routes, ningún `psycopg` en dominio.
- Ningún módulo supera el budget de 700 líneas.

## Discarded findings

| Observación | Motivo de descarte |
|---|---|
| Stubs `assert True` de slice-completeness | Documentados y con cobertura real en `test_self_host_auth.py`; sin efecto sobre el comportamiento |
| `scripts/apap_setup_resend_interactive.sh` en la raíz | Script local no versionado, fuera del árbol del repo |
| `coverage.json` y `docker-compose.yml.bak` | Ignorados por git |
| Fallo del job `mutation` | Tracado en #902, relacionado con A-06 pero no duplicado |

## Open questions

- **A-11 (#923)**: el alcance de lectura de los roles legacy necesita una decisión de producto antes de implementarse; la issue recoge las alternativas.
- **A-06 (#918)**: asignado al epic de CI #935 por solaparse con su territorio (`pyproject.toml`, `.github/dependabot.yml`, compose); decisión del operador de 2026-09-26.
- **Contrato huérfano del redirect de asignar**: `GET /acogidas/new` no consume los query params que le deja el redirect (detectado en el judgment-day de #919); issue de seguimiento #1008.
- **Login CSRF en `/auth/magic/verify`** y **lookup de email case-sensitive**, hallados en el judgment-day de #917: #1004 y #1003; el flag `auth_enable_magic_link` aplazado quedó en #1005 y la propagación del redirect de usuario desactivado en #1002.

## Maintenance rule

Cada PR que cierre un hallazgo actualiza su fila (PR y estado) en esta misma rama o en la siguiente que toque el documento; el revisor no aprueba una fila `cerrado` sin número de PR y CI verde. La épica #911 se cierra cuando su checklist está completa y todas las filas de esta tabla están en `cerrado`.

## References

- Épica: [#911](https://github.com/ardelperal/APAP_WEB/issues/911) — índice de hallazgos y olas.
- Issues por hallazgo: #912, #913, #914, #915, #916, #917, #918, #919, #920, #921, #922, #923, #944, #945, #947.
- Decisiones asociadas: [d-43-chip-cascade-fk-animal-id.md](../architecture/decisiones/d-43-chip-cascade-fk-animal-id.md) (divergencia legacy del hallazgo A-04).
- Runbooks derivados: [trusted-proxies.md](../runbooks/trusted-proxies.md) (A-08).
- Precedentes de formato: [rbac-enforcement-2026-Q3.md](rbac-enforcement-2026-Q3.md), [security-headers-2026-Q3.md](security-headers-2026-Q3.md).
