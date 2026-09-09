---
name: apap-merge-workflow
description: "Trigger: mergear PR, integrar en main, limpiar rama, política de merge. Ejecuta el workflow protegido de APAP_WEB."
license: Apache-2.0
metadata:
  author: ardelperal
  version: "1.0"
  last_verified: 2026-09-09
---

## Activation Contract

Cargue esta skill antes de preparar o ejecutar cualquier merge hacia `main`,
comprobar permisos de merge o limpiar una rama ya integrada.

## Hard Rules

- **Fuentes canónicas** — Lea `docs/codebase/merge-workflow.md` y `.github/branch-protection.md` antes de actuar.
- **Estado vivo** — Verifique la configuración de GitHub; no deduzca permisos desde la documentación.
- **Rol autorizado** — Rechace el merge si el actor no tiene rol `Maintain` o `Admin`.
- **Gate cerrado** — Rechace el merge mientras falte un gate, una conversación siga abierta o CI no esté verde.
- **Historia preservada** — Use merge commit; no use squash, rebase, force-push ni push directo a `main`.
- **Ref remoto retenido** — Conserve la rama remota y elimine únicamente el worktree local tras verificar el merge.
- **Cambios sensibles** — Solicite autorización explícita para cambiar protección, rulesets, hooks, releases o ramas protegidas.

## Decision Gates

| Condition | Action |
|---|---|
| Falta issue aprobada, PR o checks verdes | Detenga el merge y reporte el bloqueo. |
| El actor tiene `Write` sin `Maintain` ni `Admin` | Detenga el merge; ese rol no puede actualizar `main`. |
| Todos los gates pasan y el actor está autorizado | Ejecute el merge commit y verifique el SHA en `main`. |
| El PR ya está mergeado | Verifique el SHA y limpie solo el worktree local. |
| El usuario declara MVP alcanzado | Siga la transición post-MVP del documento canónico. |
| La skill repite todos los jobs de CI | Lea `docs/codebase/ci-cd.md`; no duplique la matriz. |
| Se interpreta `status:approved` como permiso de merge | Verifique el rol efectivo por separado. |
| Se propone eliminar la rama remota | Conserve el ref remoto y pode solo el worktree. |

## Execution Steps

1. Lea los dos documentos canónicos indicados en las reglas anteriores.
2. Verifique issue, PR, rol efectivo, conversaciones y checks requeridos.
3. Confirme que la rama cumple `<type>/<issue>-<slug>` y parte de `main`.
4. Ejecute el merge commit sin borrar la rama remota.
5. Verifique que el SHA resultante pertenece a `main`.
6. Registre la evidencia exigida y elimine el worktree local si existe.

## Output Contract

Devuelva todas estas claves:

| Key | Type | Description |
|---|---|---|
| `status` | `success \| blocked \| failed` | Resultado del workflow. |
| `pr` | `string \| null` | Identidad del PR. |
| `actor_role` | `string \| null` | Rol efectivo verificado. |
| `required_checks` | `string[]` | Checks y estado observado. |
| `merge_sha` | `string \| null` | SHA integrado y verificado. |
| `cleanup` | `string[]` | Limpieza local realizada. |
| `blocking_reasons` | `string[]` | Razones que impidieron el merge. |

## References

- `docs/codebase/merge-workflow.md` — workflow canónico y transición post-MVP.
- `.github/branch-protection.md` — contrato esperado de GitHub.
- `CONTRIBUTING.md` — entrada human-facing para contribuidores.
- `docs/codebase/ci-cd.md` — matriz autoritativa de CI/CD.
