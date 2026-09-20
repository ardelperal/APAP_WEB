---
name: engram-sync-doctor
description: Trigger: engram cloud sync, sync status, autosync roto, mutaciones inválidas, sync queue atascado, doctor engram, desatascar engram, repair sync_mutations, repair engram cloud, materializer postgres caído, daemon engram no levanta. Diagnostica y repara el autosync local↔cloud de Engram: valida daemon, Postgres materializer, env vars, integridad SQLite, mutaciones inválidas (title/session_id/content/id), huérfanos contra allowlist, y descongestiona la cola de sync_mutations siguiendo los patrones validados en sesiones reales.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 1.0
  tested_on: Windows 11 + WSL2 Ubuntu 22.04 + engram 1.19.0 + PostgreSQL 16
  last_verified: 2026-09-05
  scope: ['engram', 'runtime']
  auto_invoke: ['diagnosing engram sync failures']
  tiers: ['engram', 'runtime']
---



## Activation Contract

Use this skill when the user reports or suspects:

- Autosync no está empujando memorias a `https://engram.romancaba.com`
- `engram sync --cloud --project X` falla con `upgrade_blocked_legacy_mutation_manual`
- `engram doctor` devuelve `blocked` con `sync_mutation_required_fields`
- El daemon engram arrancó pero el status dice "Local daemon: not running on port 7437" (falso negativo conocido)
- `consecutive_failures` lleva horas subiendo sin drenar
- El Postgres materializer (puerto 5433) está caído y `materialize-mutations` devuelve `cloudstore: ping postgres failed`
- Hay observaciones locales con `title=""` o `session_id=""` que impiden el push
- Hay mutaciones para proyectos que NO están en `ENGRAM_CLOUD_ALLOWED_PROJECTS`
- La DB SQLite (`%USERPROFILE%\.engram\engram.db`) reporta "database disk image is malformed"

The skill is **read-first, write-with-consent**: diagnose never mutates; repair requires explicit per-category user confirmation before any DELETE or UPDATE.

## Hard Rules

1. **Read-only by default.** `assets/diagnose.ps1` never mutates state. Run it first, always.
2. **Never kill engram MCP clients (`codex` parents) silently.** They belong to other agents. The daemon (`engram serve`) is the only thing the skill is allowed to stop/restart.
3. **Always backup `engram.db` before any repair.** Format: `engram.db.before-{phase}-{yyyyMMdd-HHmmss}.bak`. The backup is the rollback path.
4. **Never write to Postgres without verification.** The materializer Postgres at `127.0.0.1:5433` is shared with WSL Ubuntu. The skill only connects read-only except for the `materialize-mutations --apply` step, which is the engram-blessed write path.
5. **Never delete user-authored observations, sessions, prompts, or `mem_save` results.** The skill only touches `sync_mutations` (the push queue), `sync_state` (per-target counters), and the `observations.title` / `observations.session_id` *fields* (with first-line-of-content repair). It never deletes a row from `observations`, `sessions`, or `user_prompts` unless that source row is provably orphaned (no entity_key match anywhere).
6. **Never fabricate titles.** Repairs of `observations.title` extract from the first line of `observations.content` (`**What**: ...` pattern preferred). If the content is empty or has no newline, the observation stays orphaned and is reported, not auto-repaired.
7. **Never modify `observations.session_id` without a fallback strategy.** Repairs use the project's canonical manual-save session (`manual-save-<project>`) only when the source observation's `session_id` is empty AND the observation has real content. Anything else is reported as orphan.
8. **Always REINDEX + `PRAGMA integrity_check` after any SQL mutation.** WAL corruption has been observed on this machine when copying between WSL and Windows paths; the only reliable recovery is REINDEX.
9. **Never overwrite the live `engram.db` while the daemon is alive.** Stop daemon → WAL checkpoint → copy → REINDEX → integrity_check → copy back → restart. Skip none.
10. **Always ask before deleting.** The repair script lists every category of invalid/orphan mutation with counts and asks per-category before applying.

## Decision Gates

| User intent / symptom | Action |
| --- | --- |
| "cómo está mi sync" / "sync status" / "está al día?" | `assets/diagnose.ps1` only (read-only) |
| "arregla sync" / "desatascar engram" / "repair" | `assets/diagnose.ps1` first, then `assets/repair.ps1` interactively |
| "hazlo todo de una" / "reparación sin parar" | `assets/repair.ps1 -AssumeYes` (uses cached decisions, all YES) |
| "solo dame el reporte" / "modo lectura" | `assets/diagnose.ps1 -Json` for machine-readable output |
| User asks to add/remove projects from allowlist | **Out of scope.** Skill reports current allowlist; user edits Windows env var manually. |
| User asks to set the scheduled task for daemon persistence | **Out of scope.** Skill prints the snippet from `## Reference snippets`; user pastes in elevated PowerShell. |
| `engram` CLI missing | Skill stops with error. User must install engram first. |
| Postgres not running on 5433 | Skill stops with hint. User must start WSL Postgres (or accept degraded mode without materializer). |

## Execution Steps

### Phase 1 — Diagnose (always run first)

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Proyectos\skills\engram-sync-doctor\assets\diagnose.ps1"
```

The diagnose script runs all checks and prints a categorized report:

```
[OK]      daemon listening on 127.0.0.1:7437
[OK]      autosync enabled=true, phase=healthy
[OK]      Postgres materializer reachable on 127.0.0.1:5433
[OK]      engram.db integrity_check = ok
[OK]      14 projects in allowlist match user's live list
[OK]      0 invalid observation upserts
[WARN]    23 orphan observation upserts with empty session_id (expedientes)
[BLOCKED] 4,354 mutations queued for projects NOT in allowlist (skills, etc.)
```

### Phase 2 — Decide

- All `[OK]` → nothing to do.
- Only `[WARN]` → ask user if they want to auto-repair the warned category.
- Any `[BLOCKED]` → user must approve repair. Skill never auto-runs repair.

### Phase 3 — Repair (interactive)

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Proyectos\skills\engram-sync-doctor\assets\repair.ps1"
```

The repair script walks each category:

1. **Title repair**: For observations with `title=""` but content not empty, extract title from first line of content (up to 200 chars).
2. **Session ID repair**: For observations with empty `session_id` and valid content, set to `manual-save-<project>`.
3. **Orphan prune (sync_mutations)**: DELETE sync_mutations with missing entity_key, or whose entity is `relation`, or where the source row is irrecoverable (orphan title + orphan session_id, or no matching source row).
4. **Allowlist prune (sync_mutations)**: DELETE sync_mutations whose `project` is NOT in the user's allowlist (read from `ENGRAM_CLOUD_ALLOWED_PROJECTS`).
5. **Sync state reset**: For non-allowed project targets in `sync_state`, clear `last_error`, `consecutive_failures`, `backoff_until`, `reason_code`, `reason_message`.

Each category asks: "Apply X to N rows? [y/N]". User can skip or apply per category.

### Phase 4 — Post-check

The repair script automatically runs `diagnose.ps1` again at the end. If new `[BLOCKED]` findings appear, the skill reports them. If `phase=healthy` and `consecutive_failures=0`, the skill reports success.

## Output Contract

Both scripts return a structured result:

```
=== Engram Sync Doctor ===
Project root: C:\00repos\codigo\00_CADETE_staging
Timestamp: 2026-07-16T20:15:00Z
Daemon: running (PID 12345)
Cloud: https://engram.romancaba.com

Health Summary:
  phase:                   healthy
  consecutive_failures:    0
  last_sync_at:            2026-07-16T20:04:52

Queue Inventory:
  total mutations:         53,105
  valid observation upserts: 18,800
  valid observation deletes: 3,230
  valid sessions:          14,000
  valid prompts:           17,075
  invalid observations:    0
  invalid sessions:        0
  invalid prompts:         0
  non-allowlist projects:   0

Postgres Materializer:
  reachable: yes (127.0.0.1:5433)
  database: engram_cloud
  cloud_chunks: 0 (post-repair, will populate on next materialize)
  cloud_mutations: 0

Verdict: HEALTHY — autosync draining. No action required.
```

Failures output:

```
Verdict: BLOCKED — 4,354 mutations queued for non-allowed projects.

Repairs available (run assets/repair.ps1):
  [1] Allowlist prune (sync_mutations)         — 4,354 rows
  [2] Orphan prune (sync_mutations)            — 0 rows
  [3] Title repair (observations)              — 0 rows
  [4] Session ID repair (observations)         — 23 rows
  [5] Sync state reset                         — 7 rows
```

## Reference snippets (printed on demand, never auto-applied)

### Set daemon persistence (Task Scheduler, requires elevated PowerShell)

```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -Command `"Start-Process -FilePath 'C:\Users\adm1\AppData\Local\engram\bin\engram.exe' -ArgumentList 'serve' -NoNewWindow -RedirectStandardOutput '$env:USERPROFILE\.engram\serve.out.log' -RedirectStandardError '$env:USERPROFILE\.engram\serve.err.log'`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
Register-ScheduledTask -TaskName "EngramMemoryServer" -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Description "Engram persistent memory server (engram serve)"
```

### Live allowlist (as of 2026-07-16, 15 projects)

```
brass, condor, documentacion, expedientes, gestion_riesgos, hps, hps_solicitudes, no_conformidades, workflow, lanzadera, agedys, dysflow, cadete, labmanager, apap
```

### Dead projects (user removed from cloud allowlist)

```
automatizaciones, mi-cerebro, multi-project, openspec, sdd, segundo-cerebro, vba-sync, vba-sync-cli
```

(`hps_solicitudes` was previously listed as dead but the user re-enrolled it on 2026-07-16.)

## Diagnostic Categories Reference

The diagnose script checks these specific conditions, in order:

1. **Process**: `engram serve` process exists with parent not being `codex.exe`, `claude.exe`, or other agent CLI.
2. **Port**: `127.0.0.1:7437` is listening. (`engram cloud status` reports this incorrectly; we use direct TCP check.)
3. **HTTP**: `GET http://127.0.0.1:7437/sync/status` returns 200 with parseable JSON.
4. **Autosync state**: From the `/sync/status` response: `enabled` must be true, `phase` must be `healthy` or `degraded` (not `blocked`), `consecutive_failures` must be 0.
5. **Cloud config**: `ENGRAM_CLOUD_SERVER`, `ENGRAM_CLOUD_TOKEN`, `ENGRAM_CLOUD_AUTOSYNC` env vars must be set at User level (the daemon inherits them on Windows).
6. **Postgres**: `Test-NetConnection 127.0.0.1:5433` must succeed. The skill connects via `psql` (Linux) through WSL because the user's environment does not have `psql.exe` on Windows.
7. **SQLite integrity**: `PRAGMA integrity_check` on the live `engram.db` (read-only via WSL SQLite 3.45+) must return `ok`.
8. **Allowlist consistency**: `ENGRAM_CLOUD_ALLOWED_PROJECTS` (User level) must not contain empty entries or duplicates. The skill does NOT validate the contents against the user's intent — that's a human decision.
9. **Mutation queue validity**: For each mutation in `sync_mutations` where `acked_at IS NULL`, the required fields per `entity` must be present and non-empty.
10. **Orphan detection**: Mutations whose entity_key does not exist in the corresponding source table (`observations` for entity=observation, `sessions` for entity=session, `user_prompts` for entity=prompt).
11. **Allowlist collision**: Mutations whose `project` is NOT in `ENGRAM_CLOUD_ALLOWED_PROJECTS`.
12. **Repairable observations**: Count of observations where `title=""` AND content is not empty (repairable via first-line extraction) AND where `session_id=""` AND content is not empty (repairable via fallback).

## Why these checks matter (field notes from sessions)

- The "Local daemon: not running" message in `engram cloud status` is a false negative when the daemon IS up. The actual check is `Test-NetConnection 127.0.0.1:7437` and `GET /sync/status`.
- 403 errors on `skills` project were the historical #1 reason autosync couldn't drain — the queue included pending mutations for projects not in the user's allowlist. The cloud server rejects them, the queue stalls, exponential backoff kicks in.
- Observation rows with empty `title` block sync because the cloud requires `title` for upsert. The first-line-of-content repair recovers observations that follow the `**What**: ...` format used by `mem_save`.
- Observation rows with empty `session_id` block sync the same way. The fallback `manual-save-<project>` is a valid session_id that already exists in `sessions` for every project.
- Mutation rows whose `entity_key` is empty cannot be pushed (no primary key on cloud side). Same for `entity=relation` rows: the cloud schema does not accept them.
- WAL corruption has been observed on this machine when copying `engram.db` between WSL and Windows paths. The repair flow must: stop daemon → `PRAGMA wal_checkpoint(TRUNCATE)` → copy → `REINDEX` → `PRAGMA integrity_check` → copy back → start daemon. Skipping the WAL checkpoint causes the live daemon to fail with "database disk image is malformed (11)".

## Tests

Run the smoke test:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Proyectos\skills\engram-sync-doctor\tests\diagnose.Tests.ps1"
```

The test mocks the `Invoke-WebRequest` / `Test-NetConnection` paths and verifies:
- Diagnose returns the expected status fields even when daemon is down
- The WSL SQLite path resolution works for the user's home directory
- Repair script refuses to run without `-Confirm` in non-interactive mode

## Upstream Documentation & Version Awareness

This skill targets **Engram 1.19.0** (the version installed at session 2026-07-16). The Engram project evolves quickly and the diagnostic scripts depend on:

- **`sync_mutations` schema** (columns: `seq`, `target_key`, `entity`, `entity_key`, `op`, `payload`, `source`, `occurred_at`, `acked_at`, `project`)
- **`sync_state` schema** (columns: `target_key`, `lifecycle`, `last_enqueued_seq`, `last_acked_seq`, `last_pulled_seq`, `consecutive_failures`, `backoff_until`, `lease_owner`, `lease_until`, `last_error`, `updated_at`, `reason_code`, `reason_message`)
- **`sync_enrolled_projects` schema** (columns: `project`, `enrolled_at`)
- **CLI commands**: `engram cloud status|enroll|config|serve|upgrade|repair|bootstrap`, `engram sync --cloud --project X`, `engram doctor`
- **HTTP API**: `GET http://127.0.0.1:7437/sync/status`, `GET /health`
- **Cloud config env vars**: `ENGRAM_CLOUD_AUTOSYNC`, `ENGRAM_CLOUD_TOKEN`, `ENGRAM_CLOUD_SERVER`, `ENGRAM_CLOUD_ALLOWED_PROJECTS`, `ENGRAM_DATABASE_URL`, `ENGRAM_JWT_SECRET`

If the user upgrades Engram or if any of these change, **the diagnose and repair scripts may silently misbehave**. Before applying this skill to a new environment, verify against the upstream docs:

| Resource | URL | When to consult |
| --- | --- | --- |
| Repository (canonical) | https://github.com/Gentleman-Programming/engram | Source of truth for all code, schema, and CLI |
| README.md | https://raw.githubusercontent.com/Gentleman-Programming/engram/main/README.md | CLI reference table, env vars, setup FAQ |
| DOCS.md | https://raw.githubusercontent.com/Gentleman-Programming/engram/main/DOCS.md | Running as a service (Task Scheduler template at lines 1310–1347), repair paths, "Working as a Service" section (lines 1227–1347) |
| INSTALLATION.md | https://raw.githubusercontent.com/Gentleman-Programming/engram/main/docs/INSTALLATION.md | Windows install paths, PATH configuration, AV false-positive notes |
| CHANGELOG.md | https://raw.githubusercontent.com/Gentleman-Programming/engram/main/CHANGELOG.md | Breaking changes, new env vars, schema migrations |
| Agent Setup | https://raw.githubusercontent.com/Gentleman-Programming/engram/main/docs/AGENT-SETUP.md | MCP plugin wiring, plugin autostart semantics |
| Issues (search) | https://github.com/Gentleman-Programming/engram/issues?q=is%3Aissue | Known bugs in `materialize-mutations`, false-negative "Local daemon: not running" status, etc. |

**Recommended pre-flight when upgrading Engram:**

1. Pull `CHANGELOG.md` and diff against the version this skill was authored against.
2. Confirm `engram version` matches the tested version (currently 1.19.0).
3. Run `assets/diagnose.ps1` against the upgraded install and verify all `[OK]`/expected `[WARN]`/`[BLOCKED]` rows match what this skill was trained on.
4. If any new fields appear in `sync_state` or `sync_mutations`, update the schema comments at the top of `assets/diagnose.ps1` and the field references in `assets/repair.ps1`.
5. If the cloud server URL or auth mechanism changes, update the `Cloud config env vars` block above and the `ENGRAM_CLOUD_*` references in `assets/diagnose.ps1`.

**Last validated against:** `Gentleman-Programming/engram` commit hash from the 2026-07-16 session (the session that authored this skill). The repo evolves — re-validate before relying on this skill after upgrading.

## Known Limitations

- **Single-instance only.** The skill assumes one Engram daemon per Windows user. Multi-instance deployments (multiple daemons on different ports) are not handled.
- **Windows + WSL2 only.** PowerShell Core + WSL Ubuntu with bash + sqlite3 in WSL. Pure Linux or pure macOS deployments would need porting (the SQLite WAL corruption pattern is specific to WSL↔Windows file paths).
- **No remote cloud chunk deletion.** The skill can prune the local push queue but cannot delete chunks already in `https://engram.romancaba.com`. That requires either an undocumented remote API or direct cloud-server access.
- **No automatic allowlist sync.** The allowlist lives in Windows env vars (User-level); the skill reads it but does not write it. To change the allowlist, edit env vars manually and restart the daemon.
- **No multi-cloud.** This skill assumes the single cloud at `engram.romancaba.com`. Multi-cloud replication (e.g., local + remote + another tenant) would need extension.
