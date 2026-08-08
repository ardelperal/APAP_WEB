# Hardening — sesión cerrada 2026-08-07

**Sesión:** 2026-08-06 (continuación) hasta 2026-08-07. El usuario estuvo fuera (playa + errands) y solo intervino para decir "sigue sin parar me voy a la playa", "lleva un subagente más de 4 horas" (cancela subagente de #390) y "cerramos sesión".

**Estado final de `main`:** `88f5c7c` (post-misc docs commit). PRs merged esta sesión: #455, #456, #457, #459, #461, #462. PR cerrado manualmente: #463 (parcial, ver "Pendiente").

## Mergeado en esta sesión

| # | PR | Commit | What |
|---|---|---|---|
| A1 | #439 | `e94c34c` | Integration job fix. |
| A2 | #429 | `fde7c42` | Foundations (CRAP, jscpd, mutation-sites, AGENTS.md §23). |
| A3 | #432 | `ba489c6` | Cosmic-ray mutation gate + AGENTS.md §34. Tag trigger añadido al job `mutation` durante rebase. |
| B1 | #444 | `91e6f79` | Hexagonal layer gate + lint refactor. |
| B2 | #447 | `61e1ad1` | Resolve #437 cross-cutting core. |
| C1 | #446 | `4e2863a` | test_animals_queries.py — 36 casos. |
| C2 | #448 | `c5ad0bc` | Kill 38 mutation survivors in derivation.py. |
| CI | #452 | `b53109b` | Basic gates self-hosted → ubuntu-latest. + lock.py CRAP fix. |
| B3 | #449 | `e430140` | Slice-completeness gate. |
| A4 | #450 | `1822222` | adopciones/service.py mutation target con PENDING Linux. |
| B4 | #451 | `cce67b3` | Migration boundary gate (jscpd refactor). |
| Doc | #445 | `c8fc9f7` | Roadmap final session log. |
| Doc | #453 | `0b8cadc` | AGENTS.md §15.2 retention rewrite. |
| CI | #455 | `a6bbc1c` | Branch-name gate (#441). |
| CI | #456 | `42f3e5b` | PR size gate (#442). |
| Infra | #459 | `5ea49d8` | Import-cycle detector (#443). |
| Refactor | #461 | `7c851fb` | Split auth_dependencies_di (#430). |
| Mutation | #462 | `c2296a0` | diff_engine mutation target (#434 segundo item). |

Cero baseline bumps (excepto C2 con marker PENDING explícito). Cero force-pushes. Todos los merges citaron run URL verde.

## Pendiente — al retomar

### PR #463 (refactor #390) — CERRADO PARCIALMENTE

Worktree en `C:/00repos/codigo/APAP_WEB_worktrees/wt-issue-390-cleanups` con commit `0cab510` en `refactor/390-plr0911-cleanups`. PR cerrado en GitHub.

**Lo que está hecho en el worktree:**
- 10 funciones PLR0911 reducidas a ≤6 returns (subagente anterior).
- `_dispatch_write` (rate_limit_middleware): CC 7 → 2.
- `_apply_tables` (cli_apply_reverse): CC 11 → 7 (todavía > 6).
- Lazy import en `_apply_one_table` para romper el ciclo `cli.py ↔ cli_apply_reverse.py`.

**Lo que falta:**
- `_build_probe_result` en `migration/storage_spike.py` (CC 7 → ≤5).
- `_apply_tables` sigue en CC 7 (necesita otro helper para reducir a ≤5).
- El PR anterior tuvo 969 LOC — apply `size:exception` label antes de re-abrir.

**Para retomar:**
1. Continuar refactor desde `0cab510` en el worktree.
2. Refactorizar `_build_probe_result` y `_apply_tables`.
3. Apply `size:exception` label.
4. Re-abrir PR (estaba cerrado).
5. CI verde → merge.

### Issues abiertos en rango #341-#443

- **#390** (refactor ARG/C901/ERA): parcial, ver arriba.
- **#430** ✓ cerrado (PR #461).
- **#434** ✓ abierto — A4 (adopciones) y B3 (diff_engine) hechos. Faltan más módulos.
- **#420** ✓ epic abierto — Steps 4, 5, 6 pendientes (architecture reviewer agent, más mutation targets).
- **#395** ✓ epic abierto — cierra con cada ratchet nuevo.
- **#341** ✓ epic abierto — code-quality audit.

### Decisiones D1-D7 (resumidas)

D1-D5 ver `docs/quality/pendientes-2026-08-06.md` (versión expandida).
D6: Migración a ubuntu-latest (PR #452) por runner zombie del Oracle VPS.
D7: Self-hosted runner queda registrado pero no se usa por defecto. Decidir si quitarlo.

## Worktrees遗留antes a limpiar

15+ worktrees locales. El usuario puede `git worktree remove --force` cada uno:

- `wt-fix-pr429-integration` (A1, merged)
- `wt-rebase-pr432` (A3, merged)
- `wt-fix-pr438-lint-and-437` (B1, merged)
- `wt-roadmap-update` (Doc, merged)
- `wt-fix-437` (B2, merged)
- `wt-test-animals-queries` (C1, merged)
- `wt-fix-derivation-survivors` (C2, merged)
- `wt-ci-move-to-github` (CI, merged)
- `wt-slice-completeness-gate` (B3, merged)
- `wt-migration-boundaries-gate` (B4, merged)
- `wt-mutation-target-adopciones` (A4, merged)
- `wt-fix-build` (rebasado)
- `wt-policy-no-remote-delete` (PR #454, merged)
- `wt-issue-441-branch-gate` (PR #455, merged)
- `wt-issue-442-pr-size-gate` (PR #456, merged)
- `wt-issue-443-import-cycle` (PR #459, merged)
- `wt-issue-390-cleanups` (PR #463 cerrado, commit parcial guardado)
- `wt-issue-430-split-auth-deps` (PR #461, merged)
- `wt-issue-434-diff-engine` (PR #462, merged)

Comando de cleanup:

```bash
git worktree remove --force C:/00repos/codigo/APAP_WEB_worktrees/wt-fix-pr429-integration \
                                 C:/00repos/codigo/APAP_WEB_worktrees/wt-rebase-pr432 \
                                 C:/00repos/codigo/APAP_WEB_worktrees/wt-fix-pr438-lint-and-437 \
                                 ... (lista completa arriba)
```

## Política actualizada (per request del usuario)

- ✅ **NUNCA** `git push origin --delete <branch>` después de merge. Solo `git worktree remove --force <path>` para worktrees locales. Las ramas remotas se retienen para que un fork herede el historial.
- ✅ PRs con tamaño > 400 LOC pueden usar el label `size:exception` (creado en PR #442, documentado en AGENTS.md §15.1/§15.6).
- ✅ Branch names deben ser `<type>/<issue>-<slug>` donde type ∈ `feat|fix|refactor|docs|ci|test`. NO `chore` (el regex del branch-name gate no lo permite).

## Cuando vuelvas

1. Lee este archivo.
2. Continúa con PR #463 (refactor #390): `_build_probe_result` y `_apply_tables` quedan.
3. Considera otros issues (#430 cerrado, #434 quedan más módulos, #420/#395/#341 son epics).
4. Limpia los worktrees listados arriba.
5. Decide sobre el runner Oracle (D7).

— el agente, antes de irse
