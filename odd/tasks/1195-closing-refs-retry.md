# 1195 — retry con backoff para la carrera de closingIssuesReferences (B11)

Branch: `chore/1195-closing-refs-retry` (worktree `apap-app-worktrees/chore-1195-closing-refs-retry`)
Issue: #1195. Fricción B11 vivida 3 veces en sesión (#1119/#1145/#1150) y en el rerun de #1158.

## Objective
Un PR recién creado no debe necesitar rerun de issue-spec porque GitHub registra `closingIssuesReferences` segundos después de la creación. El reintento vive DENTRO del gate, determinista, acotado en tiempo.

## Problem
`scripts/check_issue_specs.py` lanza una única query GraphQL; si la ref aún no está registrada falla con "add Closes #N" aunque el body la tenga verbatim. Sub-caso B11: algunos PRs nunca registran la ref (#1119) — esos usan `chain:partial` y NO deben reintentarse hacia un falso positivo.

## Design (gate-internal, deterministic)
- En `validate_pr_event`, tras la query inicial: si la issue de la rama está AUSENTE en `closingIssuesReferences`, `chain:partial` NO está en labels y el body declara keyword de cierre verbatim para esa issue (`Closes|Fixes|Resolves #N` — regex nueva `_CLOSING_KEYWORD_RE`, captura el número completo, `#1421` no dispara para #42), se re-consulta con backoff: delays por defecto 30/60/90s (total añadido ≤90s, solo cuando la ref está ausente).
- Delays configurables vía env `ISSUE_SPEC_CLOSING_RETRY_SECONDS` (lista separada por comas; malformed/negativo falla loud). Inyectables en tests vía `retry_delays` + `sleep` (tests corren con delays 0).
- Sin keyword en el body → fallo inmediato, cero reintentos (fallo genuino igual que hoy).
- `chain:partial` intacto: con ref ausente pasa con 1 query (sin reintento — el reintento podría convertir un pase en fallo si la ref aparece tarde); con ref presente falla igual que hoy. Exit codes intactos.
- Issue #956 intacta: el body solo se lee como disparador del reintento; el veredicto siempre deriva del campo estructurado de GitHub. El reintento solo re-consulta, nunca fabrica resultados.
- Cualquier `GitHubApiError` en la ruta lookup+reintento conserva el mensaje legible "cannot read the pull request links" (mismo failure mode que hoy).

## Scope / surfaces
scripts/check_issue_specs.py, tests/test_check_issue_specs.py, odd/tasks/. Out: ci.yml (el default aplica sin configuración), semántica chain:partial, otros gates.

## Tasks
- [x] T1 Issue #1195 con status:approved + type:chore (aprobada por mandato de épica).
- [x] T2 RED: 7 tests nuevos (keyword parser, late-registration en dos fases, never-registers con backoff completo, sin keyword sin reintentos, chain:partial sin reintento, env default/override, env malformed fail-loud).
- [x] T3 GREEN: reintento con backoff en validate_pr_event + `body_declares_closing_keyword` + `closing_retry_delays`.
- [x] T4 Suite completa test_check_issue_specs.py en verde; ruff check; forms gate; check_rules.
- [x] T5 Sondeo real read-only contra PRs reales (#1192 pasa; #1158/#1150 fallan solo por issue de rama cerrada post-merge, estado idéntico en main).

## Acceptance criteria (from #1195)
- Keyword en body + ref tardía → pasa tras reintento (mock GraphQL dos fases).
- Keyword + ref que nunca se registra → falla tras backoff completo (delays comprimidos inyectados).
- Sin keyword → fallo inmediato sin reintentos.
- chain:partial sin reintento (ref ausente pasa con 1 query; ref presente falla igual que hoy).
- Delays inyectables y configurables vía `ISSUE_SPEC_CLOSING_RETRY_SECONDS`.

## Progress / evidence
- RED: 7 failed (API ausente), 28 passed preexistentes.
- GREEN: 35 passed en 0.70s (delays inyectados a 0 — suite rápida).
- ruff check: All checks passed (ambos ficheros). mypy: 0 errores en check_issue_specs.py (1 error preexistente en scripts/check_branch_name.py no tocado, typeshed local py3.14). forms gate: contract satisfied. check_rules: exit 0.
- Diff: +191/-4 ≈ 195 líneas — dentro del presupuesto de 400.
- Honestidad del sondeo real: la carrera B11 (ref ausente los primeros segundos) no es reproducible on demand sin crear un PR desechable; el evidence de la carrera es el test mockeado de dos fases (ausente→presente), no un sondeo live. El sondeo live verifica solo que el gate sigue leyendo GitHub real correctamente.

## Next step
Commit, push, PR con `Closes #1195`, auto-merge.
