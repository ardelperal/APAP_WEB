---
name: workflow-carriles-refresh
description: Trigger: refresh carriles, migrate Sol models, sync Codex to OpenCode, upgrade gentle-ai binary. Maintains gentle-ai defaults and Codex-to-OpenCode carriles.
license: Apache-2.0
metadata:
  author: Gentleman-Programming
  version: 1.1
  last_verified: 2026-09-01
  scope: ['universal']
  auto_invoke: ['refreshing model profiles']
  tiers: ['universal']
---



## Activation

Use only for gentle-ai binary/default refresh, Codex carril migrations, and
Codex-to-OpenCode maintenance. Use `ai-model-profile-manager` for everyday
profile selection, preview, apply, backup, validation, and rollback.

## Hard Rules

- **HR-1** — Run `gentle-ai doctor` before and after maintenance; require final `healthy` status.
- **HR-2** — Move stale binaries to `~/.gentle-ai/backups/`; never delete them.
- **HR-3** — Fetch current carril defaults from gentle-ai source; never hardcode evolving defaults.
- **HR-4** — Keep this skill out of normal provider/profile switching.
- **HR-5** — Route the generated OpenAI profile through `ai-model-profile-manager`; never mutate agent models directly.
- **HR-6** — Stop after one failed repair cycle and report the degraded doctor output.

## Decision Gates

| Condition | Action |
|---|---|
| User requests a normal profile switch | Route to `ai-model-profile-manager`. |
| gentle-ai is stale or duplicated | Back up stale copies, upgrade on the requested channel, and run doctor. |
| Codex defaults changed | Refresh state and Codex tier configs, then run the sync adapter. |
| Codex must update OpenCode | Run `sync-codex-to-opencode.ps1`, which delegates profile application. |
| Final doctor remains degraded | Stop and report; do not retry indefinitely. |

## Execution Steps

1. Capture `gentle-ai version` and `gentle-ai doctor`.
2. Back up stale binaries and upgrade gentle-ai when required.
3. Read current defaults from `internal/agents/codex/profiles.go` on gentle-ai `main`.
4. Update `~/.gentle-ai/state.json` and the three Codex tier configs atomically.
5. Run `gentle-ai sync --agent opencode`.
6. Run `sync-codex-to-opencode.ps1`; preview unless apply is explicit.
7. Run doctor and report before/after evidence.

## Output Contract

| Key | Type | Description |
|---|---|---|
| `status` | `"success" \| "blocked" \| "failed"` | Maintenance outcome. |
| `before_version` | string | Initial gentle-ai version. |
| `after_version` | string | Final gentle-ai version. |
| `files_changed` | string[] | Updated maintenance files. |
| `doctor_status` | string | Final doctor status. |
| `profile_dispatch` | object \| null | Result from `ai-model-profile-manager`. |
| `skill_resolution` | `"paths-injected"` | Skill resolution evidence. |

## Anti-patterns

| Symptom | Fix |
|---|---|
| Quota exhaustion triggers a full carriles refresh | Select another profile with `ai-model-profile-manager`. |
| Agent model fields are edited by hand | Delegate the generated profile to the profile manager. |
| Stale binaries are deleted | Move them to the backup directory. |

## References

- `sync-codex-to-opencode.ps1` — Codex maintenance bridge.
- `../ai-model-profile-manager/SKILL.md` — everyday profile operations.
