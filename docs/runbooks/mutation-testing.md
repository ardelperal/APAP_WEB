# Runbook — mutation testing gate

Issue #431 (PR #2 of `quality-gates-expansion`). Companion to
`scripts/check_mutation.py` and `docs/quality/cosmic-ray.toml`.

## When to trigger

- A nightly/weekly scheduled CI run (once TASK-2.6 wires the job).
- Manually, before strengthening the tests of a module in the target set.
- After adding a module to the target set, to acquire its baseline entry.

Never on a pull request. A cosmic-ray session over the pilot module is ~233
mutants; the gate is a trend instrument, not a per-PR check.

## Pre-flight checklist

1. **You are on Linux.** This is not a preference. cosmic-ray 8.4.6 returns
   `INCOMPETENT` for 100% of mutants on native Windows — measured 27/27 on a
   12-line control module and 233/233 on `migration/derivation.py` — while
   `cr-rate` reports a passing `0.00` for exactly those sessions. `mutmut`
   3.7.0 refuses to start on Windows outright (upstream issue boxed/mutmut#397).
   On a Windows workstation, use WSL:

   ```bash
   wsl -d Ubuntu-22.04
   ```

2. **The test command resolves without a shell.** cosmic-ray spawns its worker
   with no shell, so a bare `python` may not resolve. If
   `cosmic-ray baseline docs/quality/cosmic-ray.toml` prints an error block,
   substitute an absolute interpreter path in `test-command` before going
   further.

3. **The unmutated suite is green.** `cosmic-ray baseline` must print nothing.
   A failing baseline makes every subsequent result meaningless.

## Acquiring or refreshing the baseline

```bash
export PYTHONHASHSEED=0                     # determinism (TASK-2.1, W-5)
cosmic-ray init docs/quality/cosmic-ray.toml mutation.sqlite
cr-filter-operators mutation.sqlite docs/quality/cosmic-ray.toml
cosmic-ray exec docs/quality/cosmic-ray.toml mutation.sqlite
python scripts/check_mutation.py mutation.sqlite --emit-baseline
```

**Never skip `cr-filter-operators`.** It excludes mutations of the `|` in PEP
604 type annotations, which no test can kill because `from __future__ import
annotations` stops annotations from ever evaluating. On the first pilot run
those accounted for 66 of 104 reported survivors — 63% of the score was noise
that would have been frozen into the baseline as if it were real debt.

`--worker-count=1` from TASK-2.1 does **not** exist: `cosmic-ray exec` 8.4.6
takes no such option and its `local` distributor is already sequential.

Write the emitted JSON into `docs/quality/mutation-baseline.json` under a
`modules` key, and record in the PR body **which platform and runner** produced
it. A baseline acquired anywhere other than the CI Linux runner is not
admissible.

## Verification

```bash
python scripts/check_mutation.py mutation.sqlite
```

Exit code 0 with `check_mutation: OK` is the pass condition.

## How to read a failure

| Message | Meaning | Action |
|---|---|---|
| `came back INCOMPETENT, above the 20% ceiling` | The runner is broken, not the code. Almost always: the session was produced on Windows. | Re-run on Linux. Do **not** adjust the ceiling. |
| `0/N mutants were killed` | The suite never ran against mutated code. | Check `cosmic-ray baseline` and the `test-command`. |
| `session is incomplete` | `cosmic-ray exec` was interrupted. | Re-run `exec`; the session resumes. |
| `grew beyond its baseline` | Real regression: a change added surviving mutants. | Strengthen the tests, or justify and re-baseline explicitly in the PR. |
| `no baseline entry` | A module entered the target set without being pinned. | Add its entry via `--emit-baseline` in the same PR. |
| `stale baseline entry` | A pinned module left the target set or was renamed. | Remove or update the entry. |

The first two rows are the reason this wrapper exists. `cr-rate --fail-over N`
cannot distinguish them from a perfect score — it reports `0.00` and exits 0 in
both cases. Verified end to end on 2026-08-06: on the broken Windows session,
`cr-rate --fail-over 20` exits 0 while `scripts/check_mutation.py` exits 1.

## Rollback

The gate is read-only over a session database and touches no application code.
To disable it, remove the CI step; there is no state to unwind. Deleting
`docs/quality/mutation-baseline.json` makes the gate fail closed
(`baseline not found`) rather than silently pass — that is intentional.
