---
name: fleet-registry-curator
description: Trigger: change consumer active_branch, add a consumer repo to the fleet, disable a consumer, rename a consumer's owner/name, dry-run distribution for a consumer. Curate the central fleet registry (fleet/registry.json) of consumer repositories for the skill-fleet propagation system. Add, remove, or update consumer entries; toggle enabled; change active_branch or bot_branch; produce a per-consumer dry-run showing which artifacts from the catalog would apply given current metadata.distribution. Changes are direct commits to team-skills/main after strict validation.
license: Apache-2.0
metadata:
  author: ardelperal
  version: 0.1
  last_verified: 2026-09-16
  scope: ['universal', 'ops']
  auto_invoke: ['updating the fleet registry', 'changing a consumer branch', 'adding a consumer to the fleet', 'running a fleet distribution dry-run']
  tiers: ['universal', 'ops']
---

# Fleet Registry Curator

Curates `fleet/registry.json`, the central registry of consumer repositories for the skill-fleet propagation system. Each consumer entry declares identity, primary type, enabled state, and the active integration branch that receives skill-fleet PRs.

## Activation Contract

Load when the user asks any of:
- "agregá el repo X al fleet"
- "cambiá la rama base del repo X a staging / rc.x"
- "deshabilita el repo X" / "habilita el repo X"
- "renombrá el repo X a Y"
- "sacá el repo X del fleet"
- "qué aplicaría al repo X con el catálogo actual" (dry-run)
- "mostrame los consumers habilitados" (lightweight read)

**Do NOT load** for: skill catalog changes (use `skill-improver`); AGENTS.md overlay changes (use the runtime overlays directly); `refresh-personal-symlinks.sh` operations (legacy system, intentionally out of scope).

## Hard Rules

1. **`active_branch` MUST be `staging` or `rc.<n>`.** `active_branch: main` is forbidden as a routine destination. If the user asks for main, surface the rule and ask them to choose staging or an `rc.<n>` branch.
2. **`id` format: `"<owner>/<name>"`.** Matches the GitHub path. Lowercase owner; name preserves original case. Uniqueness across the registry: no two entries may share the same id OR the same owner/name combination.
3. **`bot_branch` format: `"skill-fleet/<name>"`.** Stable per repo, never a human branch. If the repo already has a PR open from the previous bot_branch, the publisher reuses or supersedes it (do not introduce a new bot_branch to dodge an old PR).
4. **`enabled: true` requires a real `active_branch` and `bot_branch`.** An entry with `enabled: true` and empty branch fields is invalid; refuse the write.
5. **Direct commit to `team-skills/main` after validation.** No PR for registry changes. The validation gate (HR-7 below) is the safety net. Never force-push, never amend someone else's commit.
6. **Atomic JSON write.** Read → validate → show diff to user → write to a temp file (`fleet/registry.json.tmp`) → `jq`-validate the temp → atomic rename over the real file. Never write half-valid JSON.
7. **Validation gate (run before every commit):**
   - Schema: `schema_version: 1`, every entry has `id`, `host`, `owner`, `name`, `enabled`, `primary_type`, `active_branch`, `bot_branch`, `labels`.
   - `active_branch` not `main`.
   - `id` unique, `owner/name` unique.
   - `bot_branch` does not collide with any other entry's `bot_branch`.
   - `primary_type` is one of the canonical fleet types (extend the list here when adding new types).
8. **Mutability:** `id` is immutable once written; renaming a repo = remove old + add new (with explicit user confirmation that this is a repo move, not a typo). Mutable fields: `host`, `enabled`, `primary_type`, `active_branch`, `bot_branch`, `labels`.
9. **No `$HOME`, no absolute paths, no symlinks in any field.** All values are GitHub-hosted identities or branch names.
10. **Dry-run does NOT modify the file.** Dry-run reads catalog + registry and reports per consumer.
11. **`local_layout` is a top-level field of the registry.** Holds `local_root` (the absolute path on the executor where consumer clones and worktrees live, e.g., `"C:\\00repos\\codigo"`). Validated as a non-empty absolute path with no trailing slash. Mutability: same as the rest of the registry (direct commit, atomic write). One `local_layout` per registry, applies to all consumers.
12. **`canonical_name` is a per-consumer field.** The directory name under `local_root` where the consumer's `main` branch lives. Default convention: `"00_" + UPPER(repo_name)` (e.g., cadete → `"00_CADETE"`). The publisher derives paths from `canonical_name`:
    - `main_wt = <local_root>/<canonical_name>`
    - `worktrees_container = <local_root>/<canonical_name>-worktrees`
    - `wt_for_active_branch = <local_root>/<canonical_name>-worktrees/<active_branch>`
    - If `wt_for_active_branch` does not exist locally, the publisher clones fresh from GitHub against `active_branch` before materializing.
    The curator writes `canonical_name` explicitly when the convention doesn't apply (escape hatch for non-default naming). If omitted, the publisher assumes the default convention.

## Decision Gates

| Situation | Action |
|---|---|
| User wants to add a consumer | Validate new entry against HR-7; show proposed diff; commit on confirm. |
| User wants to remove a consumer | Prefer `enabled: false` first (preserves the audit trail). Only delete the entry if the user explicitly says "delete the entry" or "remove from registry". |
| User wants to change `active_branch` | Reject `main`; show current branch and new branch; commit on confirm. If the repo already has an open PR from the old branch, surface that and note the publisher will supersede it. |
| User wants to rename a repo (owner/name change) | Treat as remove + add (HR-8). Confirm with the user that this is intentional, not a typo. |
| User wants to toggle `enabled` | Show current state and new state; commit on confirm. No other validation needed beyond HR-7. |
| User wants to know what a consumer would receive | Dry-run: read `skills/**/SKILL.md` frontmatter, filter by `metadata.distribution.applies_to` (all / types / repositories) and `runtime_owned`, list artifacts per consumer. Do NOT modify the file. |
| User asks for `main` as `active_branch` | Refuse. Explain: `main` is not a routine destination; choose `staging` or `rc.<n>`. |
| Validation fails | Refuse the write. Show the exact failing rule and the offending field. |

## Execution Steps

1. **Parse intent.** Map the user's request to one of: add, remove, update, dry-run, list. If ambiguous, ask one focused question.
2. **Read current state.** Load `fleet/registry.json` (atomic read; if missing or malformed, surface the error and stop).
3. **For writes (add/remove/update):**
   - Compute the proposed next state in memory.
   - Run the validation gate (HR-7).
   - Show the proposed diff to the user (JSON diff or table view) and ask for explicit confirmation.
   - On confirm: write to `fleet/registry.json.tmp`, validate the temp with `jq`, atomic rename to `fleet/registry.json`.
   - Stage and commit with a conventional message: `chore(fleet): <action> <owner/name> [<field>: <new-value>]` (e.g. `chore(fleet): update DysTelefonica/dysflow active_branch: rc.3`).
4. **For dry-run:**
   - Read catalog: `skills/**/SKILL.md`, extract `name`, `version`, `metadata.distribution`.
   - For each consumer in the registry, compute applicable artifacts:
     - If `metadata.distribution.applies_to.all: true` → applies.
     - If `metadata.distribution.applies_to.types` includes `consumer.primary_type` → applies.
     - If `metadata.distribution.applies_to.repositories` includes `consumer.id` → applies.
     - Exclude if `metadata.distribution.runtime_owned: true`.
   - Render a Markdown table: consumer | applicable skills | applicable overlays | runtime-owned exclusions.
   - Do NOT modify the registry.
5. **Report.** Inline summary: action taken (or dry-run result), commit hash if a write happened, next-step suggestion (e.g. "run the publisher to push to consumers", or "no further action needed for dry-run").

## Output Contract

For writes:

```json
{
  "status": "applied|blocked|skipped",
  "action": "add|remove|update",
  "consumer_id": "<owner>/<name>",
  "field_changes": [
    {"field": "active_branch", "from": "staging", "to": "rc.3"}
  ],
  "validation_passed": true,
  "commit_sha": "<sha after commit>",
  "registry_path": "fleet/registry.json",
  "next_recommended": "run_publisher|none"
}
```

For dry-run:

```json
{
  "status": "ok",
  "consumers": [
    {
      "id": "DysTelefonica/dysflow",
      "applicable_skills": ["skill-name-1", "skill-name-2", "..."],
      "applicable_overlays": ["agents/opencode/overlays/...", "..."],
      "runtime_owned_excluded": ["dysflow-usage", "..."]
    }
  ],
  "catalog_size": 60,
  "registry_size": 12,
  "next_recommended": "none"
}
```

## Anti-patterns

- Deleting an entry instead of `enabled: false` when the user only asked to "stop propagation to X".
- Setting `active_branch: main` "just this once".
- Adding `bot_branch` that collides with a human branch.
- Writing half-valid JSON (missing field, trailing comma, wrong type).
- Committing the registry without showing the diff to the user.
- Treating `metadata.distribution.applies_to.repositories` as optional when it should be the precise list.
- Using `refresh-personal-symlinks.sh` or any other HOME-level path in any registry field.
- Forgetting to update the publisher's mental model: registry changes take effect on the next push to `team-skills/main`, not retroactively.
- Storing paths under the registry (the registry is identity + branch metadata only).

## References

- `openspec/changes/repository-scoped-skill-fleet/design.md` — canonical design of the fleet system.
- `openspec/changes/repository-scoped-skill-fleet/specs/...` — behavioral spec.
- `skills/skill-style-guide/SKILL.md` — frontmatter and body conventions.
- `docs/architecture/fleet-propagation.md` (when written) — top-level overview of the propagation system.
