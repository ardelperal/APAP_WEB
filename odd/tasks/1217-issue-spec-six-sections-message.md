# #1217 — Repo half of team-skills#155 item 9: issue-spec message must name the six canonical sections

## Goal

When `issue-spec` fails for missing sections, the message must name all six canonical
sections (`Problema y contexto`, `Evidencia verificable`, `Alcance y no objetivos`,
`Criterios de aceptación`, `Plan de validación`, `Dependencias y riesgos` —
`scripts/check_issue_specs.py:29-36`). Today the error is per-section
(«missing or empty section: X») and never states the full contract, so an author who
created the issue via `gh issue create --body`/API (bypassing the form templates, which DO
expose the six fields) discovers the contract red, section by section, after doing the
work. Lived on the 2026-10-02 session: a checklist-style approved issue failed until the
body was hand-augmented.

## Scope

1. Gate failure message enumerates the six sections when any is missing (deterministic,
   tested).
2. Optional CONTRIBUTING note for the non-form authoring path.

Out of scope: repairing the 20 non-compliant issues (#1184 owns that), contract changes,
new form templates.

## Cross-references

- Skill half: DysTelefonica/team-skills#155 (checklist item 9).
- Adjacent: #1184 (repairs the 20 existing violations, different scope), #1187 (cites
  B4/B11 but has no checklist item for this message), #1127.

## Status

Issue created 2026-10-02: https://github.com/ardelperal/APAP_WEB/issues/1217
(labels `status:approved` + `type:chore`; passes `issue_contract_errors` with 0 errors).
Implemented 2026-10-03: `issue_contract_errors` appends a contract-naming error
(`the issue contract requires all six canonical sections: ...`) whenever any canonical
section is missing; per-section errors keep their actionable detail. RED observed
(test asserted every `REQUIRED_SECTIONS` entry appears in the failure output), GREEN
after the change; the existing exact-list expectation was extended in the same round.
The optional CONTRIBUTING note was skipped to avoid overlapping #1216's CONTRIBUTING
edits (chained PRs would conflict); the failure message itself now carries the
authoring guidance.
