# Failure modes

Each entry: the symptom as it presents, the cause, and the command that
distinguishes it from its look-alikes. All four were observed on this VPS.

## FM-1 — Runner never returns after a restart

**Symptom.** Runner shows `offline` after any restart. Before that it worked
fine for hours. Jobs sit `queued` with no runner assigned.

**Cause.** The container receives a GitHub **registration** token in
`RUNNER_TOKEN`. Those expire **one hour** after issue. The entrypoint re-runs
`config.sh` with it on every start, so any restart later than that hour cannot
register. The runner is not crashing — it has no way back.

**Distinguish.**

```sh
docker inspect <container> --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -E 'RUNNER_TOKEN|ACCESS_TOKEN'
```

`RUNNER_TOKEN` present = latent. It will look healthy until something restarts it.

**Consequence for automation.** A watchdog that restarts a runner on
`RUNNER_TOKEN` **destroys** it. Never add auto-restart, auto-heal, or a
scheduled bounce to a runner still on a static token. Migrate first.

**Fix.** `ACCESS_TOKEN` (PAT, `repo` scope) plus mint-at-start; see
`assets/runner-compose.yml`.

## FM-2 — `online, busy=false` with jobs queued

**Symptom.** `gh api .../actions/runners` reports the runner online and idle
while jobs stay `queued` for many minutes.

**Cause, in order of likelihood.**
1. FM-1 already happened and a *stale* registration is still listed.
2. No runner in the pool carries every label the job requests.
3. The pool has one runner and several jobs became eligible at once — a runner
   executes exactly **one job at a time**, so this is normal serialisation, not
   a fault.

**Distinguish.** Compare requested labels against every runner's labels, and
count eligible jobs:

```sh
gh api repos/<OWNER>/<REPO>/actions/runs/<RUN_ID>/jobs \
  -q '.jobs[] | "\(.name)\t\(.status)\trunner=\(.runner_name // "-")"'
```

If exactly one job is `in_progress` and the rest `queued`, it is case 3 and
nothing is broken.

## FM-3 — Mute hang on a Docker step

**Symptom.** A job that runs `docker run` produces no output and only ends at
the job timeout — or at 360 minutes when the job has no timeout.

**Cause.** The daemon is wedged. `docker run` blocks instead of failing.

**Fix.** `timeout 30 docker info` preflight before the first `docker run`, and a
`timeout-minutes` on every job. See `assets/repo-ci-hardening.yml` blocks 1 and 3.

## FM-4 — Two runners corrupt each other

**Symptom.** Intermittent test failures, wrong branch content, or a port bind
error, only when two runs overlap.

**Cause.** Either a shared `_work` bind mount (two branches, one checkout
directory), or a service container published on a fixed host port such as
`5432:5432` — two concurrent jobs then collide on the port or, worse, share one
database silently across branches.

**Note.** Putting each runner in its own pod does **not** fix the port case
while the runners share `/var/run/docker.sock`: the service containers are
created by the runner against the host daemon, so pod isolation applies to the
wrong process. Either give each pod its own container runtime — which costs each
runner a private image cache — or publish the container port alone and read the
assigned host port back.

**Fix before scaling the pool.** `assets/repo-ci-hardening.yml` block 4, and one
`_work` path per runner.

## FM-5 — Reusage makes FM-1 permanent

**Symptom.** A runner with a valid `ACCESS_TOKEN` *still* restart-loops on
`Failed to create a session. The runner registration has been deleted from the
server`. Fixing the token changes nothing.

**Cause.** The container persists its configuration. On `myoung34/github-runner`
that is `CONFIGURED_ACTIONS_RUNNER_FILES_DIR` plus a state volume holding
`.runner` and `.credentials`. The entrypoint sees them, reports
`The runner has already been configured`, and **skips registration entirely** —
including when the server-side registration is gone. Reusage turns a recoverable
outage into a permanent one, so it is FM-1's multiplier rather than a separate
bug.

**Distinguish.** The log says it plainly, two lines before the failure:

```
Runner reusage is enabled
Copying previous data
The runner has already been configured
```

**Fix.** Remove the reusage state so the container configures fresh on every
start. Fresh configuration costs seconds and cannot wedge.

**Recovery is not a restart.** The credentials live in the container's writable
layer as well as the volume, and both survive `docker restart` and `docker start`.
The sequence that works:

1. Stop the service so the container is **removed**, not just stopped.
2. `docker volume rm <uuid>_runner-state`.
3. Start. Watch for `Obtaining the token of the runner` → `Settings Saved.` →
   `Listening for Jobs`.

Clearing the volume alone, or restarting after clearing it, both fail — verified
the slow way.

## FM-6 — A registration with nothing behind it

**Symptom.** `gh api .../actions/runners` lists more runners than exist, some
`online` and idle. The pool looks bigger than it is, and a report of "N runners"
is wrong in the direction that hides a single point of failure.

**Cause.** A registration whose container was renamed, replaced or removed. It
lingers until GitHub reaps it.

**Distinguish.** Never size a pool from the GitHub list. Cross-check every
registration against a live container:

```sh
for c in $(docker ps -a --format '{{.Names}}'); do
  n=$(docker inspect "$c" --format '{{range .Config.Env}}{{println .}}{{end}}'         | grep -E '^RUNNER_NAME=' | cut -d= -f2)
  [ -n "$n" ] && echo "$c -> $n"
done
```

A name in the API with no line here is a ghost. Delete it:
`gh api -X DELETE repos/<O>/<R>/actions/runners/<ID>`.
