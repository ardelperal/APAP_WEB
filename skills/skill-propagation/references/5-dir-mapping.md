# Mapeo de directorios consumidores

El origen publicable es `personal-skills/skills/`. Cada carpeta de primer
nivel con `SKILL.md` es una skill publicable; el reconciliador administra
todas salvo las seis externas de ownership Dysflow (ver más abajo).

## Destinos y tipos

| Forma Linux | Forma Windows | Tipo personal | Owner externo |
|---|---|---|---|
| `~/.config/opencode/skills/<n>` | `%USERPROFILE%\.config\opencode\skills\<n>` | SymbolicLink o Junction | Dysflow para sus seis nombres. |
| `~/.opencode/skills/<n>` | `%USERPROFILE%\.opencode\skills\<n>` | SymbolicLink o Junction | Dysflow para sus seis nombres. |
| `~/.claude/skills/<n>` | `%USERPROFILE%\.claude\skills\<n>` | SymbolicLink o Junction | Dysflow para sus seis nombres. |
| `~/.codex/skills/<n>` | `%USERPROFILE%\.codex\skills\<n>` | SymbolicLink o Junction | Dysflow para sus seis nombres. |
| `~/.agents/skills/<n>/` | `%USERPROFILE%\.agents\skills\<n>\` | Carpeta real | Dysflow para sus seis nombres. |

Los cuatro destinos SymbolicLink/Junction apuntan a la copia real
`~/.agents/skills/<n>/`, nunca directamente al repo `personal-skills/skills/<n>/`.

Las seis skills externas son `access-form-ui-builder`, `dysflow-arnes`,
`dysflow-codegraph-update`, `dysflow-examples-sync`,
`dysflow-pointer-rollout` y `dysflow-usage`.

El reconciliador verifica que estén disponibles, pero no modifica su contenido
ni su tipo. La ausencia de cualquiera bloquea el preflight completo.

## Límites de Pi

Pi escanea la copia real de `~/.agents/skills/`. `~/.pi/agent/skills/` queda
reservado para skills exclusivas de Pi y no recibe el catálogo compartido.

Las 50 entradas obsoletas que ya existen en `~/.pi/agent/skills/` no están
gestionadas. Los modos `sync`, `full` y `prune` no las eliminan; requieren una
limpieza dedicada posterior.

## Recuperación

Cada mutación pertenece a un `run-id`. Las rutas sustituidas se conservan en
`~/.local/state/personal-skills/backups/<run-id>/`.

Un fallo revierte todas las creaciones y restaura los originales. El manifest
solo cambia mediante rename atómico al finalizar correctamente.

## Modos

| Modo | Uso |
|---|---|
| `sync` | Reconciliar sin retirar huérfanos. |
| `full` | Reconciliar y retirar huérfanos gestionados a backup. |
| `prune` | Retirar a backup solo los huérfanos gestionados. |
