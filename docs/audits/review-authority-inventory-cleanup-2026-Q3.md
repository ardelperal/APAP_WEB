[← Back to README](../../README.md)

# review-authority-inventory-cleanup-2026-Q3.md

This audit documents the scope, methodology, findings, and verdict for the audit listed in the title. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto del corte de limpieza del inventario de review-authority del CLI `gentle-ai` (issue #198), ejecutado en 2026 Q3.

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Inventario de review-authority y comandos del CLI. |
| [Methodology](#methodology) | Procedimiento operator aplicado para restaurar el inventario. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict) | Estado final del inventario y del gate de revisión. |
| [References](#references) | Ficheros creados, comandos ejecutados e issue relacionado. |

## Scope

| Item | Value |
|---|---|
| Audit slice | `fix/issue-198-review-authority-inventory` |
| Branch | `fix/issue-198-review-authority-inventory` (cortada de `main`, commit `f237c55`) |
| PR | pendiente de apertura |
| Fecha | 2026-07-30 |
| Auditor | AI-assisted audit (investigación operativa del CLI) |
| Motivación | Issue #198 — el inventario de authority del CLI `gentle-ai review` mostraba entradas corruptas que impedían pasar el validate gate. El gate CI pre-MVP es operativo por directiva del usuario del 2026-07-18 |
| Spec | Criterios de aceptación del issue #198 + investigación operativa del CLI `gentle-ai` |
| Design | Superficie de comandos del CLI `gentle-ai review` (v2.2.0) |

### Ficheros creados

| Fichero | Resumen |
|---|---|
| `docs/runbooks/review-authority-recovery.md` | Runbook paso a paso para diagnosticar y limpiar entradas stuck del inventario |
| `docs/audits/review-authority-inventory-cleanup-2026-Q3.md` | Este documento de auditoría |
| `scripts/review-status-check.ps1` | Helper PowerShell que envuelve `gentle-ai review status --cwd .` y sale 0 solo cuando `authoritative -and complete -and status -eq "complete"` |

No se modificó código Python en `app/` o `migration/`. Es un fix operativo del inventario, no un cambio de código.

### Estado del inventario del CLI `gentle-ai` (antes)

```
authoritative: false
complete: false
status: invalid
entries:
  legacy-v1 issue-175-pr1-live-migration-runtime-boundary-4068774: state=approved, status=invalid
  legacy-v1 issue-48-correct-preadoption-3ddf9d1: state=approved, status=invalid
  compact-v2 review-5d0eb7dc371147d1: state=reviewing, status=active
  compact-v2 review-82be34642fcce91d: state=reviewing, status=active
```

Reportado en el issue #198: `gentle-ai review validate --gate <gate>` devolvía `result: invalidated, reason: "complete review authority inventory is unavailable or corrupted"`.

### Estado del inventario del CLI `gentle-ai` (después del fix operativo, 2026-07-30)

```
authoritative: true
complete: true
status: active
total_entries: 40
Entry state breakdown:
  approved/approved: 33       (terminal)
  historical-pre-receipt/approved: 2  (legacy-v1, semi-terminal)
  recovered/approved: 1       (terminal)
  superseded/approved: 1       (terminal)
  active/correction_required: 1  (KNOWN LIMITATION — ver Findings)
  active/validating: 2        (KNOWN LIMITATION — ver Findings)
```

`validate --gate pre-push --base-ref origin/main` ahora devuelve `allow` (publication range vacío — nada que pushear desde este worktree). Sin `--base-ref`, devuelve `invalidated` con razón `"review-driven development is disabled and no receipt governs this candidate"` — esto es esperado en pre-MVP (RDD off, gate CI operativo).

## Methodology

1. Runs de diagnóstico: ejecución de `gentle-ai review status`, `inspect-authority`, `repair --preflight` y `validate` para mapear el estado actual.
2. Investigación del modo RDD: descubrimiento de `rdd_mode: off` global; activación temporal para permitir operaciones `abandon`, luego restauración a `off`.
3. Limpieza de entradas: abandono de 8 entradas `reviewing` pristine usando `gentle-ai review abandon` con autorización por entrada del maintainer.
4. Análisis de entradas non-terminal: intento de `abandon` (rechazado: no pristine), `reclaim` (rechazado: holds authoritative artifact), `reopen-results --prepare` (falla: reviewer artifact unreadable), `repair-legacy-alias` (no aplicable — tipo de diagnóstico incorrecto).
5. Análisis de entradas legacy: confirmación de que dos entradas legacy-v1 están en `historical-pre-receipt` (semi-terminal; no hay más acción disponible en pre-MVP).

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| MEDIUM | Salud del inventario restaurada | fixed | El inventario ahora muestra `authoritative: true, complete: true`. Ocho entradas `reviewing` pristine se abandonaron con éxito. El comando `validate` devuelve `allow` cuando se le pasa `--base-ref` explícito. No bloquea: el gate CI pre-MVP es operativo independientemente del estado del inventario de review. |
| MEDIUM | Tres entradas non-terminal no se pueden resolver en pre-MVP | deferred | Una entrada `active/correction_required` y dos `active/validating` permanecen. No se pueden abandonar (no pristine), no se pueden reclamar (hold authoritative artifacts) y `reopen-results --prepare` falla con "reviewer artifact is unreadable or outside the native size bound" — los artefactos preservados del reviewer están corruptos o faltan. Causa raíz: los artefactos del reviewer para estas entradas están ausentes del object store de git o están corruptos. Sin artefactos legibles, ningún comando del CLI puede mover estas entradas a un estado terminal. El CLI `gentle-ai review` no tiene force-quarantine path para esta forma específica. Workaround: tratar `authoritative: true, complete: true, status: active` como estado limpio aceptable en pre-MVP. La resolución completa requiere un fix del CLI `gentle-ai` o que el reviewer vuelva a ejecutar el ciclo de revisión completo. |
| INFO | Entradas legacy-v1 en `historical-pre-receipt` | deferred | Dos entradas legacy-v1 (`issue-175-pr1-live-migration-runtime-boundary-4068774`, `issue-48-correct-preadoption-3ddf9d1`) están en `historical-pre-receipt`. `quarantine-legacy` solo acepta el diagnóstico `malformed historical findings-freeze`, que no encaja con el de estas entradas. Son efectivamente terminales en pre-MVP. No bloquea. |

## Verdict

PASS condicional: el inventario alcanzó `authoritative: true, complete: true`. Ocho entradas `reviewing` pristine se abandonaron con éxito. Tres entradas non-terminal (`active/correction_required` × 1, `active/validating` × 2) no pueden resolverse en pre-MVP por artefactos corruptos del reviewer y por la ausencia de un comando CLI de force-quarantine para esa forma específica. Es una limitación conocida, no una regresión.

## Comandos operativos ejecutados

| Comando | Entrada | Resultado |
|---|---|---|
| `gentle-ai review abandon` | `review-5d0eb7dc371147d1` | committed → quarantine |
| `gentle-ai review abandon` | `review-0d3d56708d98200c` | committed → quarantine |
| `gentle-ai review abandon` | `review-4ede25579eedc141` | committed → quarantine |
| `gentle-ai review abandon` | `review-51a29408f05508fe` | committed → quarantine |
| `gentle-ai review abandon` | `review-75d6aae4922bb979` | committed → quarantine |
| `gentle-ai review abandon` | `review-82be34642fcce91d` | committed → quarantine |
| `gentle-ai review abandon` | `review-b703d2e079b3b37e` | committed → quarantine |
| `gentle-ai review abandon` | `review-f00cb5ddf32a7dc1` | committed → quarantine |

Las operaciones de abandon movieron 8 entradas de `active/reviewing` a quarantine bajo `.git/gentle-ai/review-transactions/quarantine/`.

## References

- Issue #198: <https://github.com/ardelperal/APAP_WEB/issues/198>
- `docs/runbooks/review-authority-recovery.md` — runbook
- `scripts/review-status-check.ps1` — helper de verificación de estado
- CLI `gentle-ai` v2.2.0, superficie de comandos `gentle-ai review`
