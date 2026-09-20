---
name: wiki-digest
description: Trigger: wiki digest, knowledge graph curation. Curates the DysTelefonica/wiki knowledge graph from TIER 1 material (Engram, per-project docs, OpenSpec dumps, git history) and TIER 2 cache (wiki/raw/). This is the SINGLE routine that processes incoming info into the wiki. Use when the user says 'digerí', 'digest', 'meté esto en la wiki', 'update the wiki', 'process the wiki', or any reference to curating DysTelefonica/wiki. Triggered explicitly by the user — NOT on every event. The wiki is a DERIVED artifact, batch-curated on a schedule or by request.
license: Apache-2.0
metadata:
  author: ardelperal
  version: 1.0
  last_verified: 2026-09-05
  scope: ['universal', 'ops']
  auto_invoke: ['digesting wiki source into curated pages']
  tiers: ['universal', 'ops']
---



# wiki-digest

The `wiki-digest` skill is the **single routine that curates `C:\00repos\wiki\`**. Every piece of incoming TIER 1 information flows through this skill to reach TIER 3.

**Critical: this skill is invoked EXPLICITLY by the user, not on every event.** The wiki is a derived artifact curated on a schedule (typically weekly) or on-demand.

---

## Scope — explicit triggers and what each does

The user picks a **scope** when invoking. The skill follows the same procedure but reads from different sources and writes to different TIER 3 paths.

### Scope: `all` (default weekly digest)

**Sources**:
- Engram `mem_search` for the last 14 days, all projects
- `git -C <repo> log --since="14 days ago" --oneline` for every repo in `C:\00repos\codigo\`
- `git -C <repo> tag --sort=-creatordate | head -5` for releases
- `<repo>/CHANGELOG.md` (if exists) for new version sections
- `wiki/raw/incoming/` for manually dropped material
- `wiki/raw/openspec/<repo>/<change>/` for unprocessed SDD artifacts
- `wiki/raw/releases/` for unprocessed release evidence

**Writes**: any TIER 3 page that needs updating.

### Scope: `project:<repo>`

**Sources**: only that repo's TIER 1 + TIER 2.

**Writes**: `wiki/projects/<repo>.md`, related `wiki/openspec/<change>.md`, `wiki/releases/<repo>-v*.md`.

### Scope: `pr:<number>`

**Sources**:
- `gh pr view <number> --repo DysTelefonica/<repo> --json title,body,files,commits,mergedAt`
- The merge commit + diff: `git -C C:\00repos\codigo\<repo>\00_main show <merge-commit>`
- Linked issue(s): `gh issue view <N>`

**Writes**:
- Update `wiki/projects/<repo>.md` capabilities: add new feature with `since: <merge-date>` and `source: "PR #<number>"`
- If the PR introduced an ADR: create `wiki/decisions/ADR-NNN-<slug>.md`
- If the PR closed an issue: optionally update OpenSpec page if one exists for the issue

### Scope: `release:<tag>` (e.g., `release:gentle-ai-v2.14.0`)

**Sources**:
- `git -C C:\00repos\codigo\<repo>\00_main show <tag>` — tag metadata
- `git -C ... log <previous-tag>..<tag>` — all commits in the release
- `wiki/raw/releases/<repo>-<version>/` — release artifacts (if pre-staged)
- `<repo>/CHANGELOG.md` — if a version section exists

**Writes**:
- Create `wiki/releases/<repo>-v<X>.<Y>.<Z>.md` using `templates/release.md`
- Update `wiki/projects/<repo>.md` capabilities: mark features in the release range as `shipped: <release-date>`

### Scope: `openspec:<change>`

**Sources**: `wiki/raw/openspec/<repo>/<change>/{proposal,spec,design,tasks,verify}.md` if exists; or `<repo>/openspec/<change>/` if the user has per-project openspec.

**Writes**: `wiki/openspec/<change>.md` (curated summary of the SDD change).

### Scope: `incoming`

**Sources**: `wiki/raw/incoming/` (manual drop zone). Files in here MUST be triaged before deletion.

**Writes**: route each file to its TIER 3 destination:
- OpenSpec proposal/spec → `wiki/openspec/<change>.md`
- PR description → update `wiki/projects/<repo>.md` capabilities
- ADR/decision → `wiki/decisions/ADR-NNN-<slug>.md`
- Random notes that don't fit anywhere → flag with the user, do NOT silently discard

After triage, the file should be moved to `wiki/raw/processed/` (auto-created) or kept in `incoming/` if processing is incomplete.

### Scope: `lint` (health check, mostly read-only)

**Sources**: read all `wiki/wiki/**/*.md`, check `wiki/index.md` and `wiki/log.md`.

**Writes**:
- Only updates `wiki/log.md` with `## [YYYY-MM-DD] lint | <scope>` entry listing findings
- Does NOT modify TIER 3 pages — just reports issues

**Findings to look for**:
- Orphan TIER 3 pages (no inbound wikilinks)
- TIER 3 pages NOT in `index.md`
- Missing frontmatter on any TIER 3 page
- Stale `since:` or `source:` dates (older than 6 months with no recent updates)
- Capability entries with `status: shipped` but no `since:` date
- Broken wikilinks (`[[NonExistent]]` references)
- Contradictions between capabilities of related projects

---

## Universal procedure (every scope)

### Step 1: Confirm scope

If the user said "digerí" without specifying, ask: "¿Qué scope? `all`, `project:<repo>`, `pr:<NNN>`, `release:<tag>`, `openspec:<change>`, `incoming`, `lint`?"

Default if user says "todo" or "all": `all` with last 14 days.

### Step 2: Read sources per scope

(See "Sources" in each scope section above.)

### Step 3: Classify each item

For each piece of incoming information, decide:

| Item type | Trigger | TIER 3 destination |
|---|---|---|
| New project (first time) | New repo encountered | Create `wiki/projects/<repo>.md` |
| Project description / capability update | New feature in commits | Update `wiki/projects/<repo>.md` capabilities |
| New release (git tag) | New tag since last digest | Create `wiki/releases/<repo>-v<X>.<Y>.<Z>.md` |
| Architectural decision (with rationale) | ADR proposed/accepted | Create `wiki/decisions/ADR-NNN-<slug>.md` |
| SDD change summary | OpenSpec proposal/spec/tasks/verify | Create/update `wiki/openspec/<change>.md` |
| Cross-cutting pattern (applies to multiple repos) | Recurring across projects | Create `wiki/patterns/<name>.md` |
| Free-form topic | Concept needs its own page | Create `wiki/topics/<name>.md` |
| Noise / not worth curating | — | Skip (or move to `wiki/raw/incoming/_archive/` if from manual drop) |

### Step 4: Write or update TIER 3 pages

For each item:

1. Use the **frontmatter schema** from `AGENTS.md` (in `C:\00repos\wiki\AGENTS.md`). Always include `type`, `created`, `updated`, `tags`.
2. Use **wikilinks** (`[[target]]`) for ALL cross-references, by title not path.
3. Cite sources explicitly:
   - `Engram observation #21298`
   - `PR #190`
   - `commit 35ddc3d6a2e5438d59eddb5ba307371bca27de38`
   - `wiki/raw/openspec/<repo>/<change>/proposal.md` line 23
4. Match conventions in templates (`templates/project-page.md`, `templates/release.md`, etc.).
5. Spanish where the user's domain uses Spanish (Cadete, Telefónica); English otherwise.
6. For capabilities updates on existing project pages:
   - ADD new entries, don't rewrite old ones
   - Use `since:` only when verifiable from git log / tags / CHANGELOG
   - Use `source:` as concrete reference (PR #, commit SHA, ADR)
   - Bump `updated:` to today's date
7. For new ADRs:
   - Check existing ADRs in `wiki/decisions/`
   - Assign `ADR-NNN` with next zero-padded sequence
   - Use `templates/decision-adr.md`
8. For releases:
   - Use `templates/release.md`
   - Include all PRs between previous tag and this tag
   - Include verification status from evidence files

### Step 5: Update `wiki/index.md`

- Add new entries to the appropriate section
- Remove stale entries (don't delete files unless user asks)
- Keep one line per page: `[[Title]] — <one-line summary>`

### Step 6: Append to `wiki/log.md`

```
## [YYYY-MM-DD] digest | <scope>
- Updated [[<page-1>]] (capabilities: +X, -Y)
- Created [[<new-page>]] (sources: ...)
- Linked [[<page-1>]] ← [[<page-2>]]
- Lint findings: <list if scope=lint>
```

**Never edit past log entries. Always append.**

### Step 7: Verify

Before saying "done", verify:

```bash
# All new/modified pages have frontmatter
for f in $(git diff --name-only HEAD wiki/wiki/); do
  head -1 "$f" | grep -q "^---" || echo "MISSING FRONTMATTER: $f"
done

# All new pages are listed in index.md
for f in $(git diff --name-only HEAD wiki/wiki/); do
  page=$(basename "$f" .md)
  grep -q "\[\[$page\]\]" wiki/index.md || echo "NOT IN INDEX: $page"
done

# Log entry added
grep "^## \[$(date +%Y-%m-%d)\] digest" wiki/log.md
```

If any check fails, fix before reporting.

### Step 8: Suggest commit

Report: "Updated N pages, created M new. Want me to commit and push?"

The user controls commit/push. Do NOT auto-commit.

---

## Idempotency guarantees

The skill MUST be safe to run multiple times:

- ✅ Re-running produces the same TIER 3 state (modulo `updated:` timestamp)
- ✅ A page that's already up-to-date doesn't get rewritten (only `updated:` bumps)
- ✅ A capability entry with the same PR source isn't duplicated
- ✅ A release page that already exists isn't overwritten (unless new info emerged)
- ✅ Manual `wiki/raw/incoming/` files aren't re-processed unless they moved

**Test**: if you run `all` twice in a row, the second run should produce zero new pages and zero log entries (or just `updated:` bumps).

---

## What the skill does NOT do

- ❌ Modify TIER 1 files (Engram, per-project docs, per-project openspec)
- ❌ Modify TIER 2 files in `wiki/raw/` (except moving from `incoming/` to `processed/` after triage)
- ❌ Auto-commit to git
- ❌ Trigger itself on every event (this is the user's call)
- ❌ Promote items from TIER 1 to TIER 2 (that's the user's responsibility)
- ❌ Discard items without flagging — if unsure, ask the user

---

## Cadence recommendations

- **Weekly `all`** is the sweet spot. Less = wiki goes stale; more = wasted tokens.
- **After major milestones**: a release, a big PR merge, a sprint end.
- **Before onboarding**: process everything related to a topic for a new collaborator.
- **`pr:<NNN>`** when you want a specific PR captured immediately (rare).
- **`lint`** every 2-4 weeks.

---

## Example triggers and expected behavior

**User:** "digerí todo lo de esta semana"
**Skill:** Reads Engram + git logs + raw/incoming/ + recent raw/openspec/. Updates TIER 3 pages. Reports N pages updated.

**User:** "meté el PR #190 en la wiki"
**Skill:** Fetches PR #190 from GitHub, gets merge commit, finds files touched. Adds capability entry to `wiki/projects/00_CADETE.md`. Maybe creates decision record if PR introduced an ADR.

**User:** "digerí release gentle-ai v2.14.0"
**Skill:** Reads the v2.14.0 tag, gets commits since v2.13.x, finds release evidence in `wiki/raw/releases/`. Creates `wiki/releases/gentle-ai-v2.14.0.md`. Updates `wiki/projects/gentle-ai.md` capabilities (mark features as shipped on 2026-07-22).

**User:** "lint the wiki"
**Skill:** Reads all TIER 3 pages, finds 3 orphans, 1 missing frontmatter, 2 stale capabilities. Appends to `log.md` with findings. Does NOT modify TIER 3.

---

## Cross-references

- `C:\00repos\wiki\AGENTS.md` — the schema file (read it before any digest).
- `C:\00repos\wiki\templates\` — templates for each TIER 3 page type.
- `C:\00repos\wiki\index.md` — the catalog.
- `C:\00repos\wiki\log.md` — the chronological ledger.
- Engram via MCP — `mem_search`, `mem_get_observation`, `mem_save`.