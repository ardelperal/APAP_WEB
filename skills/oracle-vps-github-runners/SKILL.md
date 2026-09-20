---
name: oracle-vps-github-runners
description: Trigger: runner self-hosted, runner en Coolify, VPS Oracle, jobs encolados, runner offline, segundo runner, migrar repo a runners propios. Provision, harden and diagnose self-hosted GitHub Actions runners, and migrate repos onto them.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 2.0
  scope: ['universal', 'infra']
  last_verified: 2026-08-12
  auto_invoke: ['provisioning an Oracle VPS GitHub runner']
  tiers: ['universal', 'infra']
---



## Activation Contract

Load when provisioning, repairing, scaling or diagnosing a self-hosted runner
on the Oracle VPS, or migrating a repository onto that pool.

## Hard Rules

Rationale lives in the references; these are the constraints.

1. **Never let a failure become an answer.** Exit 127, a missing input, an empty
   context — behind `|| echo 0`, a default or a `skip()`, each becomes a
   plausible verdict. Fail the step. A long silent step is the same defect with a
   human reading it, and their failure mode is to cancel: heartbeat it.
2. **Never `RUNNER_TOKEN`** — it expires in an hour. `ACCESS_TOKEN`, minted at start.
3. **Never restart or watchdog a runner still on `RUNNER_TOKEN`.** Migrate first.
4. **One `_work` per runner**, identical path inside and outside the container.
5. **No second runner** while any job publishes a fixed host port.
6. **Identical labels, distinct `RUNNER_NAME`.** Labels route, not identify.
7. **Every job carries `timeout-minutes`**, sized on THIS runner. Default 360.
8. **No `gh`, no `python` on this image.** Add `setup-python`; use curl + jq.
9. **Read a service port in a step, never `jobs.<id>.env`** — empty, silently.
10. **Ship every requirement with a gate**, prove it fails on the real tree, and
    make it ignore comments.
11. **Neither `status=online` nor the API's runner count is proof.**
    Deregister and restart; cross-check every name to a container.
12. **Green PR checks are not a merge.** Read the post-merge runs.
13. **Pool size = the job graph's widest tier**, computed, not guessed.

## Decision Gates

| Symptom | Read | Action |
|---|---|---|
| Offline after restart, or restart loop | FM-1 | Migrate to `ACCESS_TOKEN` |
| Still looping with a valid PAT | FM-5 | Drop reusage; recreate, not restart |
| More registrations than containers | FM-6 | Ghost — delete it |
| `online, busy=false` + queued | FM-2 | Labels first, then job count |
| Jobs queue instead of overlapping | FM-2 | `pool-sizing.md` |
| Mute hang on `docker run` | FM-3 | `timeout 30 docker info` |
| Overlap-only flakiness | FM-4 | Dynamic ports, per-runner `_work` |
| Exit 127, or a gate that never fails | R1 | `repo-migration.md` |

## Execution Steps

1. Read `references/vps-topology.md` and re-verify host facts before citing them.
2. Diagnose against `references/failure-modes.md` before changing anything.
3. **Provisioning or repairing**: use `assets/runner-compose.yml`, replacing
   every placeholder. Set `ACCESS_TOKEN` as a Coolify env var, never inline.
   Delete any leftover `RUNNER_TOKEN`. Verify per Rule 11.
4. **Migrating a repository**: follow `references/repo-migration.md` in order,
   applying the blocks it names from `assets/repo-ci-hardening.yml`. Blocks 1
   and 4 gate any future second runner.
5. Confirm one real run goes green, then the post-merge runs too (Rule 12).

## Output Contract

Report: runner name, labels, `_work`, auth, deregister-restart result,
hardening blocks still missing, and post-merge run conclusions.

## References

- `references/vps-topology.md` — host, runners, labels, billing caveat.
- `references/failure-modes.md` — FM-1..FM-6 and how to tell them apart.
- `references/repo-migration.md` — ordered migration; writing gates that
  cannot quietly stop working.
- `references/pool-sizing.md` — how many runners, measured not guessed.
- `assets/runner-compose.yml` — verified Coolify template.
- `assets/repo-ci-hardening.yml` — the seven consumer requirements.
