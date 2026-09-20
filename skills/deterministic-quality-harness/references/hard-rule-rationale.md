# Hard-rule rationale

Use this reference when a rule needs explanation during adoption or review. The runtime contract in
`SKILL.md` remains authoritative; this document explains why each rule exists and what failure it
prevents.

## Gate integrity

1. **Fail loudly.** A red CI result is safer than a false negative. Shell fallbacks, permissive CI
   flags, and narrow output filters can turn a real scanner failure into green output.
2. **Pin governing tools exactly.** A range such as `ruff>=0.6` silently changes the rule set. Exact
   tool versions still need a hash-locked dependency graph, fixed runner image, action SHAs, and
   scanner digests to make the environment reproducible.
3. **Ratchet stable finding identities.** Counts allow one new defect to replace one removed defect
   without failing. Layer identities use `violation-class|source-path|import-subject`; mutation
   survivors use `module-path|operator-name|occurrence`. Baseline migration must be explicit.
4. **Pin wiring at set level.** A per-gate list cannot detect a gate omitted from both the workflow
   and the list. Walking the gate scripts and comparing executable identities across scripts, CI,
   and `make verify` catches that double omission.
5. **Do not ignore antipatterns silently.** Broad ignores such as `B008` preserve fragile code long
   after the original reason disappears. Prefer the safe construct or a narrow documented exception.
6. **Pin images by digest.** Tags are mutable even when they look versioned. Upgrade the tag and
   resolved digest together as a reviewed change.
7. **Keep allowlists shrink-only.** An ignored vulnerability without an open issue becomes permanent
   invisible debt. One ID, one issue, one removal path.
8. **Use pytest's real exit boundary.** `config.exitstatus = 1` does not control the final process
   code. `pytest_sessionfinish` must mutate `session.exitstatus`, and `pytester` must prove it.
9. **Use AST layer checks.** Regex fails across aliases, multiline imports, comments, and refactors.
   `PURE_LAYERS` and `ALLOWED_IMPORTS` need syntax-aware enforcement.
10. **Repair drift immediately.** A documented convention that no longer matches executable behavior
    compounds review errors until one side is corrected.

## Ownership, thresholds, and order

11. **Segregate ownership.** Every gate states who runs it and what that actor does not own. The
    change author cannot be the only judge of the change.
12. **Ceiling before ratchet.** A ratchet is a migration ramp, not the destination. Fixed ceilings
    make verdicts independent of neighboring code; `top-N` does not. Every temporary baseline needs
    a target value and date.
13. **Fix in a fixed order.** Duplication fixes can reintroduce complexity, so order is load-bearing.
    `quality_report.GATES`, CI, and `make verify` must agree.
14. **One testability policy.** Independent exclusion lists change the denominator from gate to gate.
    `quality-policy.json` supplies one ordered, content-hashed manifest and one thin exclusion boundary.
15. **Pin the environment.** `ubuntu-latest`, action tags, and unhashed dependency resolution all
    allow the same commit to execute different machinery later.
16. **Bind evidence to identity.** A number without candidate, policy, scope, subject manifest,
    command, and owner identity can be replayed against the wrong change. Aggregation must reject
    missing, mismatched, or stale bindings.
17. **Expose policy time.** Ratchet expiry is intentionally time-dependent, but gate analysis must not
    read the clock implicitly. One canonical policy date makes replay and expiry behavior auditable.
18. **Prove liveness.** Missing coverage, empty source roots, absent scanners, or all-INCOMPETENT
    mutation runs can otherwise produce perfect-looking numbers. Baseline generation has the same
    health requirements as verdict mode.
19. **One portable local command.** Developers otherwise run a shrinking remembered subset of CI.
    `make verify` covers every checkout-and-tools PR gate in CI order. PR payload, scheduled mutation,
    network, and Docker gates may be excluded only by explicit capability and reason. Preserve LF in
    the Makefile because CRLF breaks recipes on Linux.

## Shipped ceilings

| Gate | Ceiling | Basis |
|---|---|---|
| Layers | 0 violations | The consuming project's architecture decision. |
| Complexity | `CC <= 15` per function | Cheap early global signal. |
| CRAP | `CRAP <= 6` per function | Upstream cleaner policy; requires small functions even at full coverage. |
| DRY | 0 duplicate blocks of 5+ statements | Greenfield default; ratchet legacy debt. |
| Mutation sites | 100 per file | Above this surface, split before handoff. |
| Mutation | 0 unrecorded survivors; INCOMPETENT share `<= 20%` | Fail-closed mutation health. |
| PR size | 400 changed lines | Review-budget decision gate. |

At full coverage CRAP equals cyclomatic complexity, so `CRAP <= 6` dominates `CC <= 15`. Raising
the CRAP ceiling can be a legitimate local decision, but it must be explicit and justified.
