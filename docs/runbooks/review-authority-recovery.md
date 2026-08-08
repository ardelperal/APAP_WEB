[← Back to README](../../README.md)

# review-authority-recovery.md

Este runbook cubre el diagnóstico y la recuperación del inventario de autoridades de `gentle-ai review` cuando las entradas quedan en estados no terminales. Aplica al issue #198.

## Quick Navigation

| Sección | Propósito |
|---|---|
| Cuándo abrir este runbook | Disparadores que justifican la apertura del runbook |
| Diagnóstico previo al vuelo | Inspección del inventario y del modo RDD |
| Limpieza de entradas `reviewing` | Procedimiento para abandonar entradas limpias |
| Tratamiento de entradas legacy-v1 | Procedimiento de cuarentena para entradas pre-receipt |
| Validación tras la limpieza | Verificación del estado del inventario |
| Limitaciones conocidas | Estados sin camino de resolución en pre-MVP |
| Reversión | Reversión a través del registro de cuarentena |

## Cuándo abrir este runbook

Abra este runbook en las siguientes situaciones:

- `gentle-ai review status --cwd .` devuelve `authoritative: false` o `status: invalid`.
- `gentle-ai review validate --gate <gate> --cwd .` devuelve `result: invalidated, reason: "complete review authority inventory is unavailable or corrupted"`.
- Aparecen entradas con `state: reviewing` o `state: correction_required` que nunca progresan y bloquean `status: complete`.

## Contexto

APAP_WEB se ejecuta en **modo de rama única pre-MVP** (`rdd_mode: off` globalmente). La compuerta de fusión pre-MVP es **CI** (por directiva del usuario, 2026-07-18: "no reviewers in pipeline"). El CLI `gentle-ai review` mantiene un inventario de autoridades compact-v2 en el directorio Git común compartido (`.git/gentle-ai/review-transactions/`).

El estado del inventario vive en el **almacén Git del worktree `00_main`** — todos los worktrees comparten el mismo `.git` mediante `git worktree`. Las operaciones desde cualquier worktree mutan el mismo inventario.

## Diagnóstico previo al vuelo

```powershell
# 1. Compruebe el estado general del inventario
gentle-ai review status --cwd .

# 2. Compruebe el modo RDD (debe ser "off" en pre-MVP)
gentle-ai review mode status --cwd .

# 3. Compruebe los diagnósticos a nivel de entrada
gentle-ai review inspect-authority --cwd .

# 4. Intente la preflight de reparación
gentle-ai review repair --preflight --cwd .
```

Estado esperado en pre-MVP:

- `authoritative: true, complete: true, status: active` (aceptable; `status: complete` requiere todas las entradas en estados terminales — véase Limitaciones conocidas más abajo).
- `repair --preflight` → `status: unsupported, eligible_candidates: 0`.

## Limpieza de entradas `reviewing` atascadas

Las entradas en `state: reviewing` sin resultados de lente capturados son **prístinas** y pueden abandonarse. Una entrada abandonada pasa a cuarentena; el conteo de entradas del inventario disminuye.

### Identificación de entradas en revisión

```powershell
$status = gentle-ai review status --cwd . | ConvertFrom-Json
$status.entries | Where-Object { $_.state -eq 'reviewing' } |
  Select-Object lineage_id, revision, snapshot_identity
```

### Abandono de cada entrada

Plantilla de autorización (seis líneas LF-only, sin nueva línea final):

```
gentle-ai.review-abandon-authorization/v1
lineage=<lineage_id>
revision=<revision>
snapshot_identity=<snapshot_identity>
actor=<actor>
reason=<reason>
```

Auxiliar de PowerShell de ejemplo:

```powershell
function Abandon-ReviewingEntry {
    param([object]$Entry, [string]$Reason, [string]$Actor, [string]$Cwd)
    $auth = @"
gentle-ai.review-abandon-authorization/v1
lineage=$($Entry.lineage_id)
revision=$($Entry.revision)
snapshot_identity=$($Entry.snapshot_identity)
actor=$Actor
reason=$Reason
"@
    $authFile = "$env:TEMP\auth_$($Entry.lineage_id).txt"
    $auth | Out-File -FilePath $authFile -Encoding UTF8 -NoNewline
    gentle-ai review abandon `
        --lineage $Entry.lineage_id `
        --expected-revision $Entry.revision `
        --actor $Actor `
        --reason $Reason `
        --maintainer-authorization (Get-Content $authFile -Raw) `
        --cwd $Cwd
    Remove-Item $authFile
}
```

## Tratamiento de entradas legacy-v1

Las entradas legacy-v1 (IDs de linaje `issue-*-*`) con `status: historical-pre-receipt` ya están en estado semiterminal. **No** bloquean `status: complete`.

Si muestran `status: invalid` con el diagnóstico "terminal legacy authority is missing its receipt", use `quarantine-legacy` con el diagnóstico exacto:

```powershell
gentle-ai review quarantine-legacy `
    --lineage "<lineage_id>" `
    --expected-revision "<revision>" `
    --diagnostic "terminal legacy authority is missing its receipt" `
    --disposition historical-pre-receipt `
    --actor andres `
    --reason "issue-198" `
    --maintainer-authorization "gentle-ai.review-legacy-quarantine-authorization/v1
lineage=<lineage_id>
revision=<revision>
diagnostic=terminal legacy authority is missing its receipt
disposition=historical-pre-receipt
actor=andres
reason=issue-198"
```

Nota: `quarantine-legacy` sólo acepta el diagnóstico `malformed historical findings-freeze`. Para las entradas que ya se encuentran en estado `historical-pre-receipt`, no se requiere acción adicional.

## Validación tras la limpieza

```powershell
# Para un worktree sin seguimiento remoto, proporcione --base-ref explícitamente:
gentle-ai review validate --gate pre-push --base-ref origin/main --cwd .

# Esperado en pre-MVP (rango de publicación vacío: nada que empujar):
# { "result": "allow", "allowed": true, "reason": "the publication range is empty" }

# Si la rama tiene commits por delante de origin/main:
gentle-ai review validate --gate pre-push --base-ref origin/main --cwd .
```

En pre-MVP, `validate` devuelve `result: invalidated` con la razón `"review-driven development is disabled and no receipt governs this candidate"` cuando no se proporciona `--base-ref` y el worktree no tiene seguimiento remoto. Este comportamiento **es esperado**: la compuerta pre-MVP es CI, no recibos de revisión.

## Limitaciones conocidas

### `status: active` en lugar de `status: complete`

El inventario puede mostrar `authoritative: true, complete: true, status: active` incluso después de la limpieza. `status: complete` requiere que **todas** las entradas estén en estados terminales (`approved`, `invalidated`, `superseded`, `quarantined`). Tres formas de entrada no tienen camino de resolución en pre-MVP porque requieren participación de un revisor:

| Forma | Conteo | Bloqueo |
|---|---|---|
| `active/correction_required` | 1 | `reopen-results` falla: "reviewer artifact is unreadable or outside the native size bound" — el artefacto preservado del resultado de la lente está corrupto o ausente. Ningún comando del CLI pone en cuarentena esta forma hoy. |
| `active/validating` | 2 | Mismo problema de artefacto corrupto; `reopen-results --prepare` falla idénticamente. |

Estas entradas no pueden abandonarse (no son prístinas) ni disponerse (no existe un resultado de lente utilizable que disponer). Permanecen como limitaciones conocidas hasta que:

1. El CLI gentle-ai publique un comando para poner en cuarentena forzada entradas con artefactos corruptos, **o**
2. Un revisor vuelva a ejecutar la revisión de extremo a extremo, produciendo artefactos nuevos.

**Workaround pre-MVP**: trate `status: active` con `authoritative: true, complete: true` como el estado limpio aceptable. Las compuertas de CI siguen operativas.

## Reversión

Las operaciones de abandono son **terminales e idempotentes**: reejecutar el abandono sobre una entrada ya en cuarentena converge sin error. No existe reversión para un abandono ya comprometido; la entrada permanece en cuarentena.

Para inspeccionar la cuarentena:

```powershell
# Las rutas de cuarentena viven bajo el directorio .git compartido:
# .git/gentle-ai/review-transactions/quarantine/<lineage_id>-<timestamp>/
```

## Documentos relacionados

- `gentle-ai review mode` — activa/desactiva RDD; `off` es correcto en pre-MVP.
- `gentle-ai review repair --preflight` — clasifica la salud del inventario.
- `gentle-ai review inspect-authority` — inspección profunda del inventario.
- `docs/audits/review-authority-inventory-cleanup-2026-Q3.md` — documento de auditoría.
- Issue #198: https://github.com/ardelperal/APAP_WEB/issues/198