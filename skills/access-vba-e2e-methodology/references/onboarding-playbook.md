# Onboarding + pre-flight in a new Access/VBA project

Skipping this onboarding costs a session. The forms-thin-refactor session lost its first 4 messages re-deriving what would have been obvious from `AGENTS.md` + a 5-minute audit.

## 5 minutes before writing any code

1. **Read the project `AGENTS.md`.** Every project has one. It carries the project-specific rules (gemelos invariant, `getdb()` discipline, `projectId`, target branch, form-to-form prohibitions). The skill's hard rules are necessary but not sufficient.
2. **Read its Dysflow section.** Note `projectId`, `capabilities.allowWrites`, target branch. Without these you cannot make a single `dysflow.*` call correctly.
3. **Run pre-flight C (inter-form census)** below. 2 seconds; tells you whether the project has the form-to-form anti-pattern.
4. **List the 5 largest `.bas`** and read their headers to learn project conventions (error handling, naming, doc-comment style). Match them in new code.
   ```powershell
   Get-ChildItem src\modules -Filter *.bas | Sort-Object Length -Descending | Select-Object -First 5
   ```
5. **Read the test manifest** (`tests/tests.vba.json` if present). It tells you the testing convention: per-feature JSON, contract keys (`ok`/`fail`), tags. Match them in new tests.
6. **If there is a stash with `WIP` commits**, do NOT touch them. Ask before unstashing.
7. **If a previous failed epic is in recent history**, read its proposal/spec/tasks to learn what the user values. Do not propose something already rejected.

## Pre-flight before any epic — A, B, C (each is one PowerShell pipeline)

**A. Binario health check.** Import a trivial known-good helper (or run `dysflow.verify_code` on a module last imported in a known-good commit). If the user reports "no compila" and you skipped this, you do not know whether the breakage is yours or pre-existing.

**B. Project smoke test.** Run `dysflow.test_vba` on 1-2 atoms that existed before your session and are unrelated to your change. Pass → the project is healthy. Fail → pre-existing bug to fix (or document) before you start. Skipping this cost the forms-thin-refactor session 2 round-trips where the agent blamed its own work for pre-existing failures.

**C. Inter-form callsite census.**
```powershell
Get-ChildItem -Path src\forms -Filter 'Form_Form*.cls' | ForEach-Object {
    $f = $_.Name; $c = (Select-String -Path $_.FullName -Pattern 'Form_Form\w+\.').Count
    if ($c -gt 0) { "$f -> $c llamadas inter-form" }
} | Sort-Object { [int]($_ -split ' -> ')[1] } -Descending
```
Use it to size the epic honestly (don't guess), sequence the blocks (forms with most callsites first), and detect when an epic is bigger than the proposal said.
