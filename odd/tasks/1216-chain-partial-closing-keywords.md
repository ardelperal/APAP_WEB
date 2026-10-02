# #1216 — Repo half of team-skills#155 item 3: closing keywords in chain:partial PRs

## Goal

Prevent closing keywords (`Closes`/`Fixes`/`close #N`) in the **body or title** of a
`chain:partial` PR from creating real `closingIssuesReferences`. Two incidents: the #1120
chain:partial PR wrote «close #1120» in prose (issue-spec red, premature close); #1138's
TITLE contained «closes #1073 with the chain tip» and #1073 was closed by the intermediate
leg. The gate detects a posteriori (`check_issue_specs.py` reads structured
`closingIssuesReferences`); nothing prevents it at authoring time.

## Scope

1. CONTRIBUTING.md authoring rule: a `chain:partial` PR must not contain closing keywords
   in body or title (use `Refs #N` in prose only).
2. Improve the premature-close failure message of `scripts/check_issue_specs.py` to name
   body AND title as locations to clean.

Out of scope: prose parsing by the gate (design decision #956; #1127 aligned docs with what
the gate evaluates), chain:partial semantics changes.

## Cross-references

- Skill half: DysTelefonica/team-skills#155 (checklist item 3) — dual-issue directive 2026-10-02.
- Adjacent: #1127 (`Refs #N` docs↔gate alignment; explicitly excludes prose parsing).
- Evidence: #1120 PR prose, #1138 merged title, `scripts/check_issue_specs.py:53,428-442`,
  `CONTRIBUTING.md:157`.

## Status

Issue created 2026-10-02: https://github.com/ardelperal/APAP_WEB/issues/1216
(labels `status:approved` + `type:chore`; passes `issue_contract_errors` with 0 errors).
Not started: CONTRIBUTING rule + message test (RED/GREEN) + preflight.
