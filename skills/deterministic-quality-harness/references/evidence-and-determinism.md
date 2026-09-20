# Evidence and determinism contract

Every gate emits a verdict for merge control and indicators for trend control. Evidence is valid
only when it is bound to the candidate, policy, scope, ordered subject manifest, tool command,
owner, and explicit non-owner. The aggregator rejects mismatches and evidence made stale by source
changes.

## Envelope

```json
{
  "gate": "crap",
  "status": "pass",
  "indicators": {
    "max_crap": 4.0,
    "functions_over_ceiling": 0,
    "line_coverage_pct": 91.2
  },
  "ceilings": {"max_crap": 6.0, "functions_over_ceiling": 0},
  "findings": [{"file": "app/x.py", "line": 12, "detail": "..."}]
}
```

The production envelope additionally carries candidate commit/tree, policy and scope hashes,
ordered subject manifest, command identity, checked/skipped/unclassified subjects, ownership, and
the canonical policy date.

## Published indicators

| Indicator | Ceiling | Good direction | Meaning |
|---|---|---|---|
| `layers.violations` | 0 | lower | Architecture boundary crossings. |
| `layers.files_unclassified` | 0 | lower | Files the gate could not place. |
| `layers.files_checked` | — | higher | Files inspected. |
| `complexity.max_complexity` | 15 | lower | Highest function complexity. |
| `complexity.functions_over_ceiling` | 0 | lower | Functions over the ceiling. |
| `complexity.functions_measured` | — | higher | Functions inspected. |
| `crap.max_crap` | 6 | lower | Worst complexity-to-coverage score. |
| `crap.line_coverage_pct` | — | higher | Statements executed by the suite. |
| `mutation_sites.max_mutation_sites` | 100 | lower | Largest file mutation surface. |
| `mutation_sites.files_measured` | — | higher | Files inspected. |
| `dry.duplicate_groups` | 0 | lower | Distinct duplicate blocks. |
| `dry.duplicated_ratio_pct` | — | lower | Duplicated statement share. |
| `dry.statements_measured` | — | higher | Statements inspected. |
| `mutation.mutation_score_pct` | — | higher | Mutants killed. |
| `mutation.survivors_total` | — | lower | Mutants not detected by tests. |
| `mutation.incompetent_ratio_pct` | 20 | lower | Mutants that could not execute. |
| `pr_size.changed_lines` | 400 | lower | Change review surface. |

Mutation runs on a schedule rather than per pull request. Its indicators therefore arrive on a
different cadence; a PR report must not claim mutation evidence it did not run.

## Determinism checklist

| Source of drift | Closure |
|---|---|
| Tool and transitive dependency changes | Exact pins and a hash-checked lockfile. |
| Runner, action, or scanner mutation | Exact runner label, action SHA, and image digest. |
| Hidden wall-clock reads | One orchestrator-supplied `--policy-date`, recorded with the commit. |
| `PYTHONHASHSEED` salting | SHA-256 over canonical serialization, never `hash()`. |
| Locale and encoding | Pin output encoding. |
| Random test order | Disable randomization in the gate run; investigate order separately. |
| Missing or unhealthy execution | Require non-empty subjects and gate-specific liveness evidence. |
| Unclassified inputs | Report them as findings and publish inspected scope. |
| Unstable ratchet keys | Key on the finding's own identity. |
| Filesystem iteration | Sort every walk and report. |
| Fix-order sensitivity | Pin one gate order in report, CI, and local entrypoint. |
| Relative verdicts | Use absolute ceilings, never `top-N`. |
| Coverage denominator drift | Use the shared testability policy. |
| Permanent ratchets | Require target and target date. |
| Local/CI disagreement | Compare executable gate identities mechanically. |
| Unwired scripts | Compare the complete script, CI, and local sets. |
| Makefile line-ending drift | Preserve LF and file mode. |

Two runs over the same commit and policy date must be byte-identical. A new policy date is an
explicit policy evaluation, not hidden analysis drift.
