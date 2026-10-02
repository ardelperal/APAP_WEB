# docs-964-contributing-ci-alignment

Issue: #964 — align CONTRIBUTING.md with the real CI (P3: code wins).
Refs #935 (epic CI), precedents #941/#956/#962.

## Tasks

1. [x] Worktree `apap-app-worktrees/964-contributing-ci` + branch
       `docs/964-contributing-ci-alignment` off origin/main @ c1cfdcc.
2. [ ] Worker (background): update "Validación local" (1 command per blocking
       job), checks table vs real branch protection, chained-PR section,
       size:exception flow, CI-on-chained-PRs note. Sync quality-gates.md and
       PR template only where contradicting.
3. [ ] Verification: check_alantyle green; table cross-checked against
       `gh api .../branches/main/protection` and ci.yml jobs; inventory test
       extended if it fits budget.
4. [ ] Work-unit commit(s), push, PR with `Closes #964` (no merge).

## Constraints

- Docs in Castellano peninsular formal; no gate/workflow changes.
- Budget ~80-200 doc lines. No "CVE" acronym in docs/.
- Follow-ups discovered → report as issue suggestions for #935, never inline.

## Evidence log

- Background worker task: muk9psm2-3-pj88 (gentle-ai-worker) — COMPLETED (+51/-10).
- Independent verify: muk9zvif-5-sgt1 — FIX-NEEDED with 4 exact fixes; all applied inline (venv activation, APAP_TEST_PG_DSN row, retarget+push phrasing, workflow_dispatch is NOT a revalidation).
- Final: +52/-10, check_alantyle OK, make verify 4941 passed / cov 88.64%, make typecheck OK, make test-ci OK.
- PR: https://github.com/ardelperal/APAP_WEB/pull/1051 (Closes #964) — open, NOT merged. Commits on docs/964-contributing-ci-alignment.
- Follow-ups suggested: refresh sections when #956/#962/#941 land; pin test for checks table.

## Follow-up: travesía del contribuidor (2026-09-27)

- Issue #1056 (aprobada por instrucción directa del usuario) + PR #1057 encadenada sobre docs/964-contributing-ci-alignment (base ≠ main; retarget tras merge de #1051).
- Nueva sección «Travesía del contribuidor (vista completa)» en CONTRIBUTING.md: contrato issue-spec (5 secciones en la issue enlazada), firma documental alantyle (prohibidas las versalitas — cazó 2 en la propia redacción), batería local, size:exception + re-run, ciclos BEHIND, judgment-day + deploy-order, cierre.
- check_alantyle verde; CI no corre en base ≠ main (#962) — barra local hasta retarget.

## Follow-up: barrido de alineación documental (issue #1061)

- Usuario pidió agente background alineando toda la doc al estilo alan + estado del repo.
- Baseline: check_alantyle CI-scope ya verde (146 archivos) — el sweep es de exactitud P3, no de firma.
- Issue #1061 aprobada (instrucción directa), worktree 1061-docs-alignment off c6ac0ce, worker mul5l50p-i-k8i6.
- Exclusiones: archivos de PRs abiertas (#1050/#1051/#1052/#1057) + AGENTS.md (report-only) + registros históricos congelados.

## Sweep #1061 cerrado — 2026-09-28

- Worker mul5l50p-i-k8i6: 23 líneas, 5 claims corregidos (ui-e2e-gate en hardening-roadmap, contrato release-e2e-gate en el runbook, olas 0/3 de auditoría cerradas, APAP_S3_SECURE default true, PLAN-E2E-COVERAGE como foto histórica). 8 clusters verificados sin drift.
- Commits bc4195f + c96c97e; PR #1062 (Closes #1061) — abierta, sin merge.
- Report-only: AGENTS.md drift (enlace roto test-audit.md, skills inexistentes apap-orchestrator-discipline/apap-migration, épica #909 aún OPEN estando completa), docstring drift s3.py (localhost:9000 vs minio:9000), DOCS.md tabla no exhaustiva, PLAN-E2E-COVERAGE con 50 ALAN003 preexistentes fuera de scope CI.
