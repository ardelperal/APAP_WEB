# #909 — Épica: e2e autenticado a producción como release gate (opción B endurecida)

## Goal

Cadena de 5 issues de la épica #909 para que una sesión de IA pueda
validar UI contra producción como release gate: ON → baterías e2e →
OFF, leyendo solo el runbook. **ESTADO: COMPLETA 5/5 (2026-09-26).**

## Nota del primer release

El gate `release-e2e-gate` es fail-closed: el primer release tras el
merge de #1013 fallará hasta que el operador registre la evidencia
(`gh variable set APAP_E2E_GATE_EVIDENCE --body "<run-url>"`) o un
bypass auditable (`skipped:<reason>`). El flag de producción queda en
reposo (OFF, `/e2e/login` → 404).

## Scope

| # | Issue | Rama | Estado |
|---|---|---|---|
| 1 | #904 (auth) — endurecer `/e2e/login`: auditoría `log_safe` + rate-limit 5/min/IP + flag-off 404 | `feat/904-e2e-login-hardening` | ✅ **Mergeado** — PR #1006, merge `52bb0ee`, tras fix round 1 del dual review (8 items) + audit doc HR-14. size:exception justificada. Follow-up: #1007 (XFF rightmost-hop). |
| 2 | #906 (e2e) — CLI `scripts/e2e_login.py` + fixture `authenticated_state` + migrar stepper suite | `feat/906-e2e-login-cli` | ✅ **Mergeado** — PR #1000, merge `e022390`, tras fix round 1 del dual review (fefa6c2: skip-policy, secure por scheme, AuthStateCache TTL 240s, Max-Age precedence, catch transporte). size:exception justificada. |
| 3 | #905 (infra) — secretos e2e Coolify + GitHub, ciclo ON/OFF | (operador + API) | ✅ **Ejecutado y cerrado** — PR #1014 (`460c56f`): secreto 64-char en GitHub Actions + Coolify, ciclo ON verificado (401 sin header / 200+Set-Cookie con header) y vuelta a reposo (404, flag OFF). Endpoints Coolify verificados en vivo y volcados al runbook. |
| 4 | #907 (docs) — runbook `docs/runbooks/e2e-production.md` | `docs/907-e2e-production-runbook` | ✅ **Mergeado** — PR #1011 (`1c916bb`), TODO-VERIFY resueltos por el dry run de #905 |
| 5 | #908 (release) — gate fail-closed anclado al proceso de release | `chore/908-release-e2e-gate` | ✅ **Mergeado** — PR #1013 (`6f22064`): job `release-e2e-gate` signal-only en deploy.yml, `deploy` needs: [evidence, release-e2e-gate], bypass auditable `skipped:<reason>` |

Fuera de la ola: #903 (Gitleaks/security-deep) — su PR hermano #910
(público: referencia #903) pertenece a la otra IA; confirmar con el
usuario antes de tomarlo.

## Constraints

- **High-stakes**: auth + secretos de producción → `judgment-day`
  obligatorio en revisión; skills `apap-security`, `apap-architecture`,
  `apap-testing` cargadas por cada writer.
- TDD estricto; `make verify` verde antes de cada commit.
- El flag `APAP_E2E_AUTH_ENABLED` queda **OFF** en producción al cerrar
  cada PR (estado reposo del épico).
- Ningún valor de secreto en repo, logs, argv ni storageState.
- Coordinación: la otra IA tiene la ola de auditoría de código
  (épica #911) y los PRs #900/#910/#962/#991 — no tocar sus áreas.
- Un PR por issue con `Closes #NNN`; merge solo con CI verde contra
  base actual (re-sync de main antes de cada merge).

## Progress log

- 2026-09-26 — Ola creada tras barrido de issues sin reclamo; el
  usuario eligió la Zona A (#909). Writers de #904 y #906 lanzados
  en paralelo (worktrees separados, scopes disjuntos).

- 2026-09-26 — **#906 mergeado (PR #1000, merge e022390)**. Dual
  review (judges A+B) dio 5 hallazgos → fix round 1 (fefa6c2):
  skip-policy del fixture (solo missing-env/404 skipean), secure
  derivado del scheme (Chromium dropea cookies Secure en http),
  AuthStateCache TTL-aware (re-mint a 240s bajo la caché server de
  300s), precedencia Max-Age (RFC 6265 §5.2.2), catch de errores de
  transporte. make verify 4755 passed. size:exception con
  justificación (unidad CLI+fixture+tests atómica, tests dominan el
  diff). Colisión con el merge de la otra IA (PR #1001) resuelta
  con update-branch REST + CI re-corrido sobre la head nueva.

- 2026-09-26 — **#904 mergeado (PR #1006, merge 52bb0ee)**. Dual
  review (judges A+B) dio 8 items → fix round 1 (5 commits): guard
  ASCII en compare_digest (probe no-ASCII daba 500 sin auditoría),
  bucket solo con flag on (404 pelado, sin fingerprinting),
  auditoría de branches 400/503, evento forense con IP en el 429,
  cap de email auditado (120 chars), pin multi-hop XFF,
  determinismo de .env en composición, audit doc HR-14 alineado
  (docs/audits/e2e-login-hardening-2026-Q3.md). make verify verde;
  size:exception justificada. Follow-up creado: #1007 (rediseño
  rightmost-hop de identidad bajo trust_xff).
