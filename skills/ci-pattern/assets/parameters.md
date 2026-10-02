# Parámetros del patrón de CI

Todo lo que varía de un repo a otro vive en esta tabla. Adopte el patrón
extrayendo estos valores primero; ninguna regla de la skill depende de los
valores concretos del consumer de origen (`ardelperal/APAP_WEB`), que figuran
solo como ejemplo verificado.

## Los quince parámetros

| # | Parámetro | Valor en ardelperal/APAP_WEB (consumer de origen; ejemplo verificado) | Dónde vive | Quién lo lee |
|---|---|---|---|---|
| 1 | Regex de rama | `^(feat\|fix\|chore\|docs\|refactor\|test)/<N>-<kebab-slug>$` | Protección de rama + gate de nombre de rama | El gate deriva la issue del número `<N>` |
| 2 | Presupuesto de revisión | `400` líneas (adiciones + eliminaciones, sin lockfiles) | Constante del gate de tamaño | `scripts/check_pr_size.py` |
| 3 | Etiquetas canónicas | `chain:partial`, `size:exception`, `type:*`, `status:approved` | Configuración de labels del repo | Gates de issue-spec y de tamaño |
| 4 | Contextos de estado por SHA | `release/smoke-production`, `release/e2e-production` | Lista cerrada de contextos | `scripts/check_release_evidence.py` |
| 5 | Rutas sensibles | Globs de auth, sesión, CSRF, migraciones y runtime (49 líneas) | `.github/release-e2e-paths.txt` | `scripts/check_release_e2e_required.py` |
| 6 | URL de salud | `https://<host>/healthz` (expone `.revision` del deploy) | Constante del smoke | `scripts/production_smoke.py` |
| 7 | User-Agent del smoke | Agente propio con reintentos y host de la redirección | Constante del smoke | `scripts/production_smoke.py` (403 de Cloudflare sin él) |
| 8 | Política de merge | Commit de fusión, rama remota conservada, auto-merge + update-branch activados, `strict: true` | Settings del repo | Gate de evidencia del deploy |
| 9 | Ruta de post-mortems | `docs/postmortems/<date>-<slug>.md` | Convención de docs del repo | HR-21 (post-mortem blameless); HR-19 (notas de release) |
| 10 | Playbook de release | `RELEASE-<TAG>.md` en la raíz del repo | Raíz del repo | HR-22 |
| 11 | Runbook e2e de producción | `docs/runbooks/e2e-production.md` | `docs/runbooks/` | Exclusión de §1; registro del veredicto (HR-10) |
| 12 | Skills locales de testing y seguridad | `apap-testing-strategy`, `apap-security` | Catálogo local del consumer | Exclusiones de §1 |
| 13 | Runner de tests | `pytest` | Configuración de la suite local | HR-4 (paridad de preflight); §6 |
| 14 | Eventos autorizados a publicar checks requeridos | `pull_request` (el único evento que evalúa el PR); `push`, `workflow_dispatch` y `schedule` publican bajo otro nombre de contexto o fallan | Disparadores del workflow de cada gate | HR-30 (publicación de nombres requeridos); HR-17 (fallback manual) |
| 15 | Dato mutable → disparador o reevaluación en merge | Cuerpo del PR → sin disparador (editar el cuerpo no dispara el gate); etiquetas del PR → `labeled`/`unlabeled`; estado y etiquetas de la issue enlazada → sin disparador en el host: reevaluar en el momento del merge | Disparadores de los workflows de los gates + procedimiento de merge | HR-31 (verde sobre datos mutables); HR-6 (higiene del autor) |

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
Gentleman-Programming/gentle-ai (idea T1 del benchmark); regla R15 destilada
en la auditoría de origen (veredicto por gate en
`references/gate-verdicts.md`).

## Scripts de implementación de referencia

El agregador de jobs requeridos ya está distribuido como asset portátil de
esta skill: `assets/required-jobs/` (gate fail-closed + política de ejemplo
+ suite con test de paridad; véase su `README.md`). El resto sigue
versionado en el repositorio de origen del patrón, `ardelperal/APAP_WEB`
(bajo `scripts/` y `.github/`), pendiente de publicarse como asset portátil;
adáptelos a los parámetros de arriba, no al revés:

| Script | Función |
|---|---|
| `scripts/preflight.py` | Lee el job de lint del workflow y lo reproduce en local, paso a paso |
| `scripts/check_pr_size.py` | Presupuesto de revisión con excepción declarada en el cuerpo |
| `scripts/check_issue_specs.py` | Trazabilidad determinista: rama, etiquetas, cierre de issue |
| `scripts/check_release_evidence.py` | Evaluador fail-closed de un contexto de estado por SHA |
| `scripts/check_release_e2e_required.py` | Decide si el rango toca rutas sensibles |
| `scripts/production_smoke.py` | Smoke sin autenticación, con User-Agent propio y reintentos |
| `.github/release-e2e-paths.txt` | Lista de rutas sensibles, un glob por línea |
