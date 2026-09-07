# Sync and cloud

[Back to Codebase Guide](../CODEBASE-GUIDE.md)

Esta página posee el aislamiento entre el runtime web y el legacy, más el CLI de reconciliación. No posee el detalle de `migration/` ni las reglas generales de capas.

## Core invariants

- **Runtime web en PostgreSQL**: `app.main` no selecciona Access como backend de requests.
- **Acceso por contrato**: el código de servicio depende de `SqlExecutor` o de un port específico.
- **`migration/` es el único lector cruzado**: rutas y servicios no importan `migration/`; solo el CLI lo usa (AGENTS §18.4).
- **Sync idempotente**: re-ejecutar el reconcile sin cambios no produce diff; usa `web_only_feature_shadow` (AGENTS §18.1).
- **Sync auditable**: cada fila escrita se loguea con `log_safe("sync.applied", table, pk, direction, source_hash, target_hash)` (AGENTS §18.1).
- **Sync con lock concurrente**: el motor retiene un advisory lock para que dos operadores no ejecuten syncs contradictorios (AGENTS §18.1).

## Separación de procesos (§18.4)

| Proceso | Backend | Límite |
|---|---|---|
| `app.main` | PostgreSQL | `LocalPostgresExecutor` creado en el lifespan. |
| `python -m migration ...` | PostgreSQL y Access | Adapters bajo `migration/`; nunca desde una route. |
| `Settings.mode` | Sin selección de datos | Solo distingue `web` y `test` para middleware. |

## CLI de reconciliación (§18.2)

> **Limitación actual**: `migration/cli.py::main` no construye el cliente PostgreSQL. Apply y reconcile requieren un `web_client` inyectado; la factory LocalBackend aún no tiene callers.

| Comando | Efecto |
|---|---|
| `python -m migration reconcile --check-only` | Superficie declarada; requiere composición de `web_client`. |
| `python -m migration reconcile --interactive` | Superficie declarada; requiere composición de `web_client`. |
| `python -m migration reconcile --table <nombre>` | Filtra por tabla (ej. `--table voluntarios`). |
| `python -m migration reconcile --since <ISO8601>` | Filtra por timestamp de divergencia. |
| `apap-migrate reconcile <flags>` | Mismo CLI expuesto como entry point instalable. |

## Failure modes (hard reject, §18.3)

| Anti-patrón | Razón del rechazo |
|---|---|
| Una request que lee ambos backends | Rompe la exclusividad runtime; el test `tests/test_mode_isolation.py` lo caza. |
| Una ruta que escribe en un modo y lee del otro | Mezcla capas y hace la auditoría imposible. |
| Una route que importa `migration/` | Introduce Access en el runtime web y rompe el límite de proceso. |
| Sync que aplica sin idempotency-check | Riesgo de diff destructivo; siempre usar el motor de diff. |
| Sync sin `log_safe` por fila | Rompe el contrato de auditabilidad (§18.1). |

## Cuándo ejecutar un sync

| Escenario | Comando recomendado |
|---|---|
| Verificar el delta antes de un release | `reconcile --check-only` |
| Mover datos nuevos del legacy al web tras una sesión presencial | `reconcile --interactive` filtrando por `--since` reciente |
| Traer cambios del web al legacy (ej. admin actualizó la allowlist) | `reconcile --interactive` con `--table authorized_users` |
| Auditar divergencias de una tabla concreta | `reconcile --check-only --table <nombre>` |

## Contributor checklist

- [ ] Si añade una ruta o un servicio que toca datos, confirme que usa PostgreSQL mediante `SqlExecutor` o el port del slice.
- [ ] Si completa el wiring CLI, elimine la limitación anterior y añada una prueba del entry point real.
- [ ] Si añade una columna nueva que deba sobrevivir al sync, regístrela en el shadow `web_only_feature_shadow` antes del primer reconcile.
- [ ] Si opera un reconcile, anote el SHA del runbook activo en el comentario de cierre y conserve los logs `sync.applied` para la auditoría.
- [ ] Si una route necesita datos de Access, pare la implementación y mueva la coordinación a `migration/`.

## Navigation

Previous: [Maintainer playbook](maintainer-playbook.md) | Next: [Reference map](reference-map.md)
