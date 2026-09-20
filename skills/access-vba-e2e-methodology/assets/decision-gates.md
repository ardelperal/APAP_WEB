# Decision Gates (Access/VBA E2E)

Referenced from the main SKILL.md.

| Situation | Action |
|---|---|
| Form has business logic in event handler | Extract to `<Feature>Helper.bas` FIRST; then write atoms against the helper |
| Workflow step uncovered by any atom | Add TDD atom; do NOT add it only to UAT (defeats the bridge) |
| UAT scenario has no backing atom | Add atom first; reference from UAT `ref` |
| Quality team asks "how do I test X?" | Map X → UAT scenario → atom → provide `ref` (commit hash + atom name) |
| Defect found in UAT | Fix helper, add regression atom, update UAT card with new `ref` |
| Gemelo shared helper change proposed | Audit all 4 gemelos (PC/CDCA/CDCASUB/PCSUB) before merging; align in same slice or split into separate SDD |
| Form has MsgBox/InputBox in event handler | Refactor: helper returns `ByRef p_PromptResult As Long`; form passes it to MsgBox; atom asserts the long value, no real modal |
| Coverage report shows untestable logic | Document as debt in capability doc §7 confidence ledger (`Verified-static`), schedule extraction; do NOT accept the feature as done |
| UAT case is too narrow (tests a single character) | Re-scope: aggregate into a user-actionable rule (e.g., "campos obligatorios" covers many sub-cases) |
| UAT case is too broad (tests whole workflow) | Split: each rule gets its own card; the workflow coverage is TDD's job |