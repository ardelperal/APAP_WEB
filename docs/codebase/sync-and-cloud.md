# Sync and cloud

[Back to Codebase Guide](../CODEBASE-GUIDE.md)

Esta página posee el contrato de exclusividad runtime entre los modos web y legacy, el toggle de modo y el CLI de reconciliación bidireccional. No posee el detalle del paquete `migration/` — eso es [`migration/cli.py`](../../migration/cli.py) y la skill [`apap-migration`](../../skills/apap-migration/SKILL.md) — ni las reglas generales de capas — eso es [AGENTS.md](../../AGENTS.md) §18.

## Core invariants

- **Exclusividad runtime**: APAP_WEB corre como web o como legacy en una sesión, nunca ambos contra el mismo dataset (AGENTS §18).
- **Cliente único por backend**: `LocalBackendClient` para LocalBackend; `LegacyAdapter` para Access; el código de servicio importa uno solo (AGENTS §18.4).
- **`migration/` es el único lector cruzado**: rutas y servicios no importan `migration/`; solo el CLI lo usa (AGENTS §18.4).
- **Sync idempotente**: re-ejecutar el reconcile sin cambios no produce diff; usa `web_only_feature_shadow` (AGENTS §18.1).
- **Sync auditable**: cada fila escrita se loguea con `log_safe("sync.applied", table, pk, direction, source_hash, target_hash)` (AGENTS §18.1).
- **Sync con lock concurrente**: el motor retiene un advisory lock para que dos operadores no ejecuten syncs contradictorios (AGENTS §18.1).

## Mode toggle (§18.4)

| Variable | Valor | Efecto |
|---|---|---|
| `APAP_MODE` | `web` (default) | El servicio habla exclusivamente con LocalBackend. |
| `APAP_MODE` | `legacy` | El servicio habla exclusivamente con el backend Access. |
| `APAP_INSFORGE_URL` + `APAP_LEGACY_ACCDB_PATH` | Ambos alcanzables | Startup falla rápido; un modo y solo uno puede vivir en runtime. |

## CLI de reconciliación (§18.2)

| Comando | Efecto |
|---|---|
| `python -m migration reconcile --check-only` | Enumera divergencias sin escribir. Útil para auditar antes de un merge. |
| `python -m migration reconcile --interactive` | Recorre las divergencias con confirmación por fila. |
| `python -m migration reconcile --table <nombre>` | Filtra por tabla (ej. `--table voluntarios`). |
| `python -m migration reconcile --since <ISO8601>` | Filtra por timestamp de divergencia. |
| `apap-migrate reconcile <flags>` | Mismo CLI expuesto como entry point instalable. |

## Failure modes (hard reject, §18.3)

| Anti-patrón | Razón del rechazo |
|---|---|
| Una request que lee ambos backends | Rompe la exclusividad runtime; el test `tests/test_mode_isolation.py` lo caza. |
| Una ruta que escribe en un modo y lee del otro | Mezcla capas y hace la auditoría imposible. |
| Configuración que habilita ambos backends simultáneos | El startup debe fallar si ambos son alcanzables. |
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

- [ ] Si añade una ruta o un servicio que toca datos, confirme que lee y escribe en el mismo backend (AGENTS §18.3); el test `tests/test_mode_isolation.py` es la red.
- [ ] Si modifica el paquete `migration/`, declare el cambio en `openspec/specs/migration-discovery-docs/spec.md` o cree un change SDD nuevo.
- [ ] Si añade una columna nueva que deba sobrevivir al sync, regístrela en el shadow `web_only_feature_shadow` antes del primer reconcile.
- [ ] Si opera un reconcile, anote el SHA del runbook activo en el comentario de cierre y conserve los logs `sync.applied` para la auditoría.
- [ ] Si sospecha que ambos backends están vivos, pare la operación; el startup debe haber fallado, y si no, hay un bug del Settings (§32.P2).

## Navigation

Previous: [Maintainer playbook](maintainer-playbook.md) | Next: [Reference map](reference-map.md)