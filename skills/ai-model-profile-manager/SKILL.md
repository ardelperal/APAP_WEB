---
name: ai-model-profile-manager
description: Trigger: switch model profile, apply model profile, select model profile, set models across agents. Manages safe everyday model-profile selection across supported agents.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 1.0
  last_verified: 2026-09-01
  scope: ['universal']
  auto_invoke: ['loading the ai-model-profile-manager skill']
  tiers: ['universal']
---



## Activation

Use this skill as the everyday entry point for selecting, previewing, applying,
validating, backing up, or rolling back model profiles across OpenCode, Pi, and Codex.
Do not activate it for refresh, upgrade, maintenance sync, or Codex-to-OpenCode
synchronization terms; `workflow-carriles-refresh` owns those requests exclusively.

## Hard Rules

- **HR-1** — Default every operation to preview; require `-Apply` for writes.
- **HR-2** — Validate the complete profile and every target before writing any target.
- **HR-3** — Back up each changed file before replacement and return every backup path.
- **HR-4** — Never read, copy, print, or overwrite authentication files or credentials.
- **HR-5** — Fail closed on malformed JSON, unsupported schema versions, unknown targets, missing target files, or incomplete Codex entries.
- **HR-6** — Use `assets/Invoke-AIModelProfile.ps1` as the only public dispatcher; adapters may build candidates but must not own apply, backup, rollback, or result contracts.
- **HR-7** — Report restart requirements for every applied target and expose rollback as an explicit operation.

## Decision Gates

| Condition | Action |
|---|---|
| Named profile set is requested | Run `Invoke-AIModelProfile.ps1 -Profile <path>` and review the JSON preview. |
| Preview is approved | Repeat with `-Apply`. |
| Provider and tier mapping is requested | Use dispatcher `-Provider` and `-Tier`; it routes to the OpenCode tier adapter. |
| Existing apply must be reverted | Run dispatcher with `-RollbackManifest <path> -Apply`. |
| Any validation fails | Stop without writes and return the failing target. |

## Execution Steps

1. Resolve the profile and requested targets.
2. Validate against `assets/profile.schema.json` semantics.
3. Build all candidates in memory and report changed files and agent assignments.
4. On explicit `-Apply`, create a pending typed manifest, back up exact bytes, and replace candidates atomically.
5. Return the rollback manifest path and restart requirements.
6. For Codex-to-OpenCode maintenance only, route to `workflow-carriles-refresh`.
7. Invoke list, scope, and provider/tier operations through the dispatcher; never call adapters directly.

The dispatcher is the transaction boundary. It derives authorized target paths from explicit
parameters and validated identities; rollback manifests describe entries but never authorize paths.
An operating-system or power hard kill can interrupt between atomic replacements. Pending manifests
and exact-byte backups make recovery explicit, not automatically guaranteed after forced termination.

## Output Contract

| Key | Type | Description |
|---|---|---|
| `status` | `"success"` | Returned results are successful; operational failures throw and do not emit a result object. |
| `operation` | `"preview" \| "apply" \| "validate" \| "rollback" \| "bulk-model-apply" \| "list-models" \| "what-if-scope"` | Completed dispatcher operation. |
| `profile` | string \| null | Profile name, provider/tier pair, or null for list/scope operations. |
| `targets` | string[] | Evaluated target names. |
| `changes` | object[] | Candidate changes by target and path. |
| `backups` | object[] | Backup paths created during apply. |
| `rollbackManifest` | string \| null | Manifest used to restore the apply transaction. |
| `restartRequired` | string[] | Applications that must restart. |
| `credentialsPreserved` | boolean | Always true; credential files are out of scope. |
| `skill_resolution` | `"paths-injected"` | Skill resolution evidence. |

For `changes` returned by list, scope, or tier operations, the single adapter payload may include
operation-specific fields: `mappings`, `unavailable`, `catalogCheck`, `canonicalPath`, `scope`,
`missingAgents`, `fallbacksIncluded`, `generalExcluded`, `agentCount`, `provider`, `tier`,
`changedAgents`, `dryRun`, `validation`, `beforeHash`, `candidateHash`, and `idempotent`. Fields that
do not apply to the selected operation are absent only inside that typed adapter payload; every
top-level key above is always returned. `candidateBase64` is internal adapter transport and is
removed from dispatcher output.

## Anti-patterns

| Symptom | Fix |
|---|---|
| A normal provider switch invokes carriles refresh | Use this skill's dispatcher. |
| A script writes before every target validates | Build all candidates first, then apply. |
| A profile embeds API keys | Remove secrets; profiles contain routing only. |

## References

- `assets/Invoke-AIModelProfile.ps1` — deterministic public dispatcher.
- `assets/profile.schema.json` — neutral profile manifest schema.
- `assets/adapters/Set-OpenCodeTierMapping.ps1` — provider/tier adapter.
