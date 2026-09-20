# Sub-agent failure modes

Added because `sdd-apply` hung twice in the forms-thin-refactor session. When delegating to a sub-agent (`sdd-apply`, `sdd-archive`, etc.), watch for these.

| Failure mode | Detection | Action |
|---|---|---|
| **Hangs / no response** | Supposed to produce files in `changes/<epic>/` + Engram observations; nothing written after N=5 min | Cancel the task, do the work inline. Do NOT re-launch the same prompt — it will hang again. |
| **Partial work** | `git status --short` shows a mix of `M` and `??` that doesn't match the SDD task list | Do NOT `git checkout` to revert; audit what's done, finish the rest inline, commit only verified parts. |
| **Over-deletes** | `git status --short` shows files you did not ask to delete (e.g. an HTML the user just signed off) | `git restore` those files IMMEDIATELY before anything else. |
| **Wrong branch** | `git log --oneline -5` and `git branch --show-current` show a feature branch or `main` instead of the staging branch | Revert and re-apply on the correct branch. |
| **Scope creep** | `git diff --stat` shows changes to files NOT in the SDD task list | `git checkout` those files; back to the user's approved state. |

## Two-message protocol for non-trivial sub-agent tasks

When the sub-agent task is non-trivial (> 30 min of work, > 5 files), use a two-message protocol:

1. Sub-agent proposes a plan and waits for OK.
2. Sub-agent executes.

Do NOT give a single "do everything" prompt — the failure modes above are the predictable consequence of that.
