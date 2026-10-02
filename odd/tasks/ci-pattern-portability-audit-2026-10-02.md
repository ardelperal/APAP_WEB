# ci-pattern quality audit — dispatcher + coverage map (2026-10-02)

- Repository: DysTelefonica/team-skills (canonical: `personal/ardelperal/ci-pattern/`, authorship stage)
- Trigger: operator audit — "would a DIFFERENT repo using these skills reproduce the CI failures this session hit in APAP_WEB?"
- Issues created: #164 (dispatcher), #165 (fleet tooling + host state), #166 (evidence-binding integrity), #167 (runbook state premises). Comments on #155 (items 4 and 13).
- Canonical sources read in full: ci-pattern SKILL.md (HR-1..HR-31) + all references/assets; oracle-vps-github-runners SKILL.md + 4 references; slices/partials/web.md; personal-skills AGENTS.md + README.md; in-flight issues #155, #144, #156, #159, #160, #141.

## Coverage map (failure → verdict)

| # | Failure | Verdict |
|---|---|---|
| 1 | Deploy job tooling per runner (envsubst) | NEW → #165 |
| 2 | Previous-revision resolved from run-list heuristic | NEW → #166 |
| 3 | Asymmetric bootstrap exemption | NEW → #166 |
| 4 | allow_update_branch enables, does not auto-update | #155 item 4 + comment (HR-23 text contradicts reality) |
| 5 | Closing keywords in body/title of chain:partial | COVERED: HR-7, §3, §6 + #155 item 3 + APAP #1216 |
| 6 | closingIssuesReferences retry built into gate | #155 item 2 (APAP #1197 merged) |
| 7 | rerun --failed broken → empty commit re-trigger | #155 item 6 |
| 8 | Releases selected by array index | #155 item 5 |
| 9 | issue-spec contract on the ISSUE body side | #155 item 9 (APAP #1217) |
| 10 | Silent no-op on paywalled settings | COVERED: HR-27 already in canonical + #155 item 11 |
| 11 | .env poisoning | COVERED: HR-28 already in canonical + #155 item 12 (APAP #1218) |
| 12 | Ratchet baselines invisible to plain ruff | #155 item 8; HR-4 exists (#156 challenges its implementability) |
| 13 | Docs-only fast lane as pattern | #155 item 7 (APAP #1196/#1202 merged) |
| 14 | Runbook assuming DB state (e2e user lost) | NEW → #167 (APAP #1223) |
| 15 | Binary/version provenance (MCP v3 vs daemon v2) | #155 item 13 + comment generalizing to process fleets |
| 16 | Out-of-band manual host state vs declaration | NEW → #165 |
| 17 | Branch prescriptions violating the branch-name gate | NEW → #164 (dispatcher HR 1-2) |
| 18 | Probe issued a real PATCH where GET intended | NEW → #164 (dispatcher HR 9) |

## Dispatcher diagnosis (the highest-leverage finding)

The failures happened with the rules already written — nothing loaded them. The APAP root AGENTS.md has trigger columns in its skill tables but no hard-rule orchestration block and no "about to X → load skill Y §Z" table. The propagated slice block (@ v985a74e) is STALE vs canonical `slices/partials/web.md` (missing the §Arranque section) and never routes to ci-pattern/oracle-vps-github-runners. Slice-mirror drift is not covered by #156.3 (skills only). Fix lives in #164: HR block (10 rules) + trigger table, in the consumer AGENTS.md AND the canonical partial, then re-propagate + blob-diff verify.

## Honest residual (still not prevented after all issues land)

1. #155 items are tracked, not landed: until the PRs merge, the canonical text still lacks failures 4,6,7,8,9,12,15 and still carries the misleading HR-23 claim.
2. Several rules are prose-only; the reference implementation (preflight.py, check_release_evidence.py…) is still "pendiente de publicarse como asset portátil" (parameters.md) — a new repo hand-ports and can mis-port.
3. The dispatcher is behavioral: no mechanical gate verifies a session read it.
4. Slice propagation has no CI drift check (only #156.3 for skills).
5. Per-job tooling lists (#165) are declared data that can drift; only the fail-loud gate catches it at run time.
