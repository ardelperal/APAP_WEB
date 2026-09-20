# Sizing the pool

The goal is that a repository's CI behaves as it would on GitHub-hosted runners.
Nobody should be able to tell from the timings that a VPS is underneath.

## The number is the graph's widest tier, not the branch count

A workflow's YAML expresses a **dependency graph**, not concurrency. `needs:`
states what must come first; the absence of `needs:` between two jobs states they
*may* run together — if there is capacity. "Parallel in the graph" is not
"parallel in execution", because **one runner executes exactly one job at a
time**.

So the pool size that reproduces hosted behaviour for one pull request is the
widest topological tier of the job graph. Compute it, do not estimate it:

```python
import yaml
from pathlib import Path

w = yaml.safe_load(Path(".github/workflows/ci.yml").read_text(encoding="utf-8"))
# Exclude jobs gated to schedule/dispatch — they are not part of a PR.
jobs = {n: j for n, j in w["jobs"].items() if n not in ("mutation", "security-deep")}

def needs(n):
    v = jobs[n].get("needs") or []
    return [v] if isinstance(v, str) else v

remaining, done, tiers = dict(jobs), set(), []
while remaining:
    tier = [n for n in remaining if all(d in done for d in needs(n))]
    tiers.append(tier)
    done |= set(tier)
    for n in tier:
        remaining.pop(n)

for i, t in enumerate(tiers, 1):
    print(f"tier {i}: {len(t)} -> {sorted(t)}")
print("runners for full parallelism of ONE PR:", max(len(t) for t in tiers))
```

Measured on APAP_WEB: tiers of 2, 3, 1, 1 → **3 runners**.

Concurrent pull requests multiply that demand. Three runners give one PR hosted-
like timings; two overlapping PRs still queue. Match the tier width first, and
only go wider if overlapping PRs are the actual complaint.

## Do not size from job durations — measure the gaps

Summing job durations understates the cost of serialisation, sometimes by a
factor of three. The gaps between jobs are paid **once** when jobs run in
parallel and **every time** when they queue.

Real gaps on this VPS, single runner: 52 s and 90 s between consecutive jobs —
runner pickup, checkout, dependency setup. Compare wall clock, not sums:

```sh
gh api repos/<O>/<R>/actions/runs/<RUN_ID>/jobs \
  -q '.jobs[] | select(.conclusion=="success") |
      "\(.name)\t\(.started_at)\t\(.completed_at)\t\(.runner_name)"'
```

On APAP_WEB, the same `lint`→`test`/`security`/`integration` window took **233 s**
on hosted runners and **592 s** on one self-hosted runner. Summing durations had
predicted a ~130 s difference; the truth was ~360 s.

## Verifying the pool actually parallelises

Read `runner_name` alongside the timestamps. Success looks like sibling jobs
sharing a start second across different runners:

```
lint         09:13:44 -> 09:15:11   noble-2   ┐ same second
typecheck    09:13:44 -> 09:14:19   noble     ┘
test         09:15:13 -> 09:18:08   noble-2   ┐ same second
integration  09:15:13 -> 09:16:00   noble     ┘
```

A job that waits is not automatically a fault. Check whether every runner was
genuinely occupied at that instant before concluding one is idle — on the run
above, a third job waited because the third runner was busy with a scheduled
`mutation` job, which is correct behaviour under real contention.

## Do not test parallelism with `workflow_dispatch`

Heavy jobs are commonly gated to `schedule || workflow_dispatch`. A manual
dispatch therefore starts them: on APAP_WEB it launched a 45-minute cosmic-ray
mutation run that occupied a third of the pool and read, to the human watching,
as CI hanging. Check each job's `if:` before dispatching, or trigger a real pull
request instead.

## Host ceiling

4 vCPU and 23 GiB, shared with every other container on the box. Three
simultaneous jobs measured ~1 core each, so three runners fit. Beyond the tier
width the gain goes sublinear and then negative: more runners cannot create more
cores, they only divide the same ones into slower slices.
