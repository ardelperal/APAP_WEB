# Parámetros del patrón de CI

Todo lo que varía de un repo a otro vive en esta tabla. Adopte el patrón
extrayendo estos valores primero; ninguna regla de la skill depende de los
valores concretos de este repo, que figuran solo como ejemplo verificado.

## Los ocho parámetros

| # | Parámetro | Valor en este repo (ejemplo verificado) | Dónde vive | Quién lo lee |
|---|---|---|---|---|
| 1 | Regex de rama | `^(feat\|fix\|chore\|docs\|refactor\|test)/<N>-<kebab-slug>$` | Protección de rama + gate de nombre de rama | El gate deriva la issue del número `<N>` |
| 2 | Presupuesto de revisión | `400` líneas (adiciones + eliminaciones, sin lockfiles) | Constante del gate de tamaño | `scripts/check_pr_size.py` |
| 3 | Etiquetas canónicas | `chain:partial`, `size:exception`, `type:*`, `status:approved` | Configuración de labels del repo | Gates de issue-spec y de tamaño |
| 4 | Contextos de estado por SHA | `release/smoke-production`, `release/e2e-production` | Lista cerrada de contextos | `scripts/check_release_evidence.py` |
| 5 | Rutas sensibles | Globs de auth, sesión, CSRF, migraciones y runtime (49 líneas) | `.github/release-e2e-paths.txt` | `scripts/check_release_e2e_required.py` |
| 6 | URL de salud | `https://<host>/healthz` (expone `.revision` del deploy) | Constante del smoke | `scripts/production_smoke.py` |
| 7 | User-Agent del smoke | Agente propio con reintentos y host de la redirección | Constante del smoke | `scripts/production_smoke.py` (403 de Cloudflare sin él) |
| 8 | Política de merge | Commit de fusión, rama remota conservada, auto-merge + update-branch activados, `strict: true` | Settings del repo | Gate de evidencia del deploy |

Parámetros secundarios documentados en las fuentes: host de producción, versión
de Python y lista de checks requeridos (tres en este repo: `branch-name`,
`required`, `pr-size / pr-size`).

## Policy file de gates dormibles (HR-18)

Un gate que pierde su justificación se duerme tras un policy file versionado;
nunca se elimina el candado construido. Forma mínima del fichero (JSON), una
entrada por gate dormible:

```json
{
  "policy_version": 1,
  "gates": {
    "<nombre-del-gate>": {
      "enforcement": "dormant",
      "activation_snapshot": null,
      "grandfathered_entries": []
    }
  }
}
```

Contrato del policy file:

- `enforcement` admite exactamente `dormant` y `enforcing`; cualquier otro valor
  invalida el fichero completo.
- `activation_snapshot` se escribe una sola vez, en la transición a
  `enforcing`, y queda inmutable a partir de entonces.
- `grandfathered_entries` lista lo que el gate acepta sin aplicar al activarse.
- La re-activación es un cambio de datos de este fichero (una línea:
  `dormant` → `enforcing`) que pasa por review como cualquier PR.
- El workflow lee el fichero del branch por defecto y distingue tres
  veredictos: `pass` (en política), `warning` (dormant o grandfathered) y
  `failure` (enforcing y fuera de política).

Fuente del patrón: `grandfather-size-exceptions.json` de
Gentleman-Programming/gentle-ai (idea T1 del benchmark); regla R15 de
`odd/skill-ci-portable/source-notes.md`.

## Scripts de implementación de referencia

Versionados en este repo; adáptelos a los parámetros de arriba, no al revés:

| Script | Función |
|---|---|
| `scripts/preflight.py` | Lee el job de lint del workflow y lo reproduce en local, paso a paso |
| `scripts/check_pr_size.py` | Presupuesto de revisión con excepción declarada en el cuerpo |
| `scripts/check_issue_specs.py` | Trazabilidad determinista: rama, etiquetas, cierre de issue |
| `scripts/check_required_jobs.py` | Agregador fail-closed con matriz de skips esperados |
| `scripts/check_release_evidence.py` | Evaluador fail-closed de un contexto de estado por SHA |
| `scripts/check_release_e2e_required.py` | Decide si el rango toca rutas sensibles |
| `scripts/production_smoke.py` | Smoke sin autenticación, con User-Agent propio y reintentos |
| `.github/release-e2e-paths.txt` | Lista de rutas sensibles, un glob por línea |
