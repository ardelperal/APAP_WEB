# Anti-patterns (Access/VBA E2E)

Referenced from the main SKILL.md.

| Anti-pattern | Why wrong | What to do instead |
|---|---|---|
| Test in form's `.cls` event handler | COM can't run it; failure pops UI; blocks automation | Extract logic to helper; test the helper |
| Atom asserts only "no exception" | Humo (no behavior verified) | Assert concrete state: row count, value returned, side effect on fixture |
| UAT card cites internal commit hash in user-facing text | Quality team can't act on it | Put `ref` in the downloaded record, not in the card |
| Helper shared across gemelos changed without auditing all 4 | Breaks PC/CDCA/CDCASUB/PCSUB invariant | Audit gemelos first; align in same slice or split into separate SDD |
| Skip helper extraction because "only one line" | One inline line blocks testing → blocks confidence → blocks UAT | Extract anyway; one-liner cost is trivial vs. testing block |
| Generate UAT HTML without TDD verde first | Quality team tests blind; defeats purpose | 100% TDD verde is a hard gate before UAT |
| `MsgBox "ok?"` inside event handler | Blocks COM; cannot test | Helper returns `ByRef p_PromptResult As Long`; form passes to MsgBox; atom asserts the long |
| TDD atom uses `Debug.Print` | COM doesn't see it; not verifiable | Use `logs` array in JSON contract (`{ok, value, payload, error, logs}`) |
| UAT scenario includes technical terms (`Verified-runtime`, `BR-001`) | Non-technical validator can't act on jargon | Translate to user-visible outcome; jargon goes in the `ref` only |
| Schema-first gate skipped (INSERT without ERD check) | Test fails for setup, not logic; debug lost | Read ERD before any INSERT; document required/not-null fields |
| `SELECT TOP 1` without test filter in test fixture | Not a fixture; environmental luck | Seed explicit rows with deterministic IDs in `900000+` range |
| Two suites use different sandbox setup patterns | Harness inconsistency = debt | One canonical harness (ForceLocalBackend / BeginTestSession) project-wide |
| UAT card with no `pasos` | Not reproducible; not validatable | Reject; rewrite with click-by-click steps |
| Audit fails (form has untested logic) but feature is shipped | Technical debt ships | Block feature sign-off; document in cap-doc §7 confidence ledger (`Verified-static`); schedule extraction |