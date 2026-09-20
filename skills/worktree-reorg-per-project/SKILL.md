---
name: worktree-reorg-per-project
description: Trigger: worktree reorg per project, clean main. Reorganize git worktrees so each project has main at the project root and all linked worktrees live in a sibling `<project>-worktrees\\` container outside the repo. Trigger: scattered worktree dirs INSIDE a project folder (e.g. `<project>/bugfix_125\\`), request to 'mover worktrees fuera del repo', 'organizar worktrees', 'sacar worktrees de dentro del proyecto', or pre-PR cleanup of a project in c:\\00repos\\codigo\\.
license: Apache-2.0
metadata:
  author: ardelpeal
  version: 2.0
  last_verified: 2026-09-05
  scope: ['universal']
  auto_invoke: ['reorganizing worktrees per project']
  tiers: ['universal']
---



## When to Use

Load this skill when:

- A repo's worktrees are scattered **inside** the project folder (e.g. `c:\00repos\codigo\00_CADETE\bugfix_125\`) instead of in the sibling `<project>-worktrees\` container.
- The user asks to organize, consolidate, or restructure worktree folders, asking specifically that **main stay at the project root** and worktrees move **out of the repo**.
- Before creating a new project folder structure from scratch.

Do **not** use it when:

- The repo already has the layout below applied (main at `<project>/` root and linked worktrees at `<project>-worktrees/<wt-name>\`).
- The user only wants one-off `git worktree add` / `git worktree move` (use git directly).
- The user wants the opposite (main inside `00_main/` and worktrees nested under the project); that is the legacy v1 layout and is no longer recommended.

## Target Layout

```
c:\00repos\codigo\
├── <project>\                  ← main worktree, lives at the project root
│   └── .git\                   ← .git is a DIRECTORY (classic format, not a file)
└── <project>-worktrees\        ← sibling container OUTSIDE the repo
    ├── <wt-name>\              ← linked worktree 1 (no project prefix)
    └── <wt-name>\              ← linked worktree 2 (no project prefix)
```

The `.git\` at the project root is a **directory** (the canonical git layout). The `<project>-worktrees\` container holds every linked worktree as its own directory, named after the branch slug or issue shortname — never with the project prefix.

This is the **classic git layout** plus a sibling container for linked worktrees. Git walks up from `$PWD`, finds the `.git\` directory, and uses it directly. The user `cd`s into `<project>\` for main work and into `<project>-worktrees\<wt-name>\` for a linked worktree.

## Naming Convention

- Worktree dir name = branch slug or issue shortname, **without the project prefix**.
  - `bugfix_125` (not `00_CADETE_bugfix_125`)
  - `develop` (not `00_BRASS-develop`)
  - `refactor_PLAN-003-clean-start` (not `00_HPS_refactor_PLAN-003-clean-start`)
- Main is the **project root itself** — no `00_main` prefix, no separate directory. The project root **is** the main worktree.
- The sibling container is `<project>-worktrees\` (literal dash + `worktrees`, lowercase). It is a **sibling of the project root**, not a child.
- If the container does not exist, create it before moving worktrees into it.

## Execution Order (strict)

The order matters because of git's expectations. **Always in this sequence:**

### Phase 1 — Ensure the sibling container exists (FIRST)

```powershell
$proj = '00_CADETE'
$p = "C:\00repos\codigo\$proj"

# 1. Inventory current state
git -C $p worktree list --porcelain
git -C $p status --short --branch

# 2. Create the sibling container if missing
$container = "C:\00repos\codigo\$proj-worktrees"
if (-not (Test-Path -LiteralPath $container)) {
    New-Item -ItemType Directory -Path $container -Force | Out-Null
}
```

Verify: `Get-ChildItem -LiteralPath $container` should be empty or contain only existing worktree dirs.

### Phase 1.5 — Patch dysflow config (ONLY if the new worktree will host a dysflow project)

If the project carries `.dysflow/project.json` (Access/VBA projects typically do), the freshly created worktree inherits a copy of that file. The copied config still points at the original repo root. Patch it **before the first dysflow write** so the worktree's frontend/source/backend resolve correctly:

```powershell
$wtRoot = "C:\00repos\codigo\$proj-worktrees\$wtName"
$cfg = Join-Path $wtRoot ".dysflow\project.json"
if (Test-Path -LiteralPath $cfg) {
    $j = Get-Content -LiteralPath $cfg -Raw | ConvertFrom-Json
    $j.projectRoot = $wtRoot
    if ($j.destinationRoot -and $j.destinationRoot -like '*..*') {
        # keep it relative-local; do not rewrite unless it points outside the worktree
    }
    $j | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $cfg -Encoding UTF8
    Write-Host "patched $cfg (projectRoot -> $wtRoot)"
}
```

Then commit the patch on the worktree branch (do NOT land it on the base):

```powershell
git -C $wtRoot add .dysflow/project.json
git -C $wtRoot commit -m "chore(dysflow): align .dysflow/project.json to this worktree"
```

Also update the allowlist if the branch will add new `Test_*` procedures: append each new procedure name to `capabilities.procedures.allow` in the same commit.

Why: the runtime resolves `frontendFile` under the worktree that physically owns `.dysflow/project.json`, but explicit `projectRoot` and `destinationRoot` stay cached and must point at the worktree, otherwise writes land in the wrong tree. See DysTelefonica/dysflow#1662 (config drift) and DysTelefonica/dysflow#1663 (allowlist drift).

### Phase 2 — Move each scattered worktree out of the project (SECOND)

For each linked worktree currently **inside** the project folder:

```powershell
$linkedNames = @('bugfix_125', 'pr129', ...) # short names (no project prefix)

foreach ($oldName in $linkedNames) {
    $oldDir = "C:\00repos\codigo\$proj\$oldName"
    $newDir = "C:\00repos\codigo\$proj-worktrees\$oldName"

    if (-not (Test-Path -LiteralPath $oldDir)) {
        Write-Warning "skip $oldName — not found at $oldDir"
        continue
    }

    # 1. Inspect .git file content (it points to metadata in <project>/.git/worktrees/<name>)
    $gf = "$oldDir\.git"
    if (Test-Path -LiteralPath $gf) {
        $content = Get-Content -LiteralPath $gf -Raw
        Write-Verbose "$oldName .git content: $content"
        # No rewrite needed for this layout — .git file still references
        # <project>/.git/worktrees/<name>, which is still valid.
    }

    # 2. Move with ABSOLUTE PATHS (git worktree move path is relative to CWD)
    git -C $p worktree move $oldDir $newDir
}
```

**Important**: with this layout the `.git` file inside each worktree points to `<project>/.git/worktrees/<name>\`, and that path does **not** change when the worktree dir moves out of the project. No `.git` file rewrite is needed for the basic case.

If you also need to **rename** the worktree directory to strip a legacy project prefix (e.g. `00_CADETE_bugfix_125` → `bugfix_125`), combine the move with the rename in one step:

```powershell
$legacyName = '00_CADETE_bugfix_125'   # full legacy name as it sits in the project
$newName = $legacyName -replace '^[^_]+_?', ''   # strip project prefix
$oldDir = "C:\00repos\codigo\$proj\$legacyName"
$newDir = "C:\00repos\codigo\$proj-worktrees\$newName"
git -C $p worktree move $oldDir $newDir
```

The branch name itself does not change — `git worktree move` only relocates the working tree; the metadata records the new path and the branch stays put.

### Phase 3 — Cleanup

```powershell
# If you had a legacy <project>-worktrees\ container that was a CHILD of the project
# (e.g. <project>/worktrees/), it is now empty; delete it.
$legacyChildContainer = "$p\worktrees"
if (Test-Path -LiteralPath $legacyChildContainer) {
    Remove-Item -LiteralPath $legacyChildContainer -Recurse -Force
}

# Prune stale metadata (if any worktree was half-deleted during the run)
git -C $p worktree prune

# If a project-internal orphan dir fails to delete with "Access is denied", that's
# a Windows file lock (AV/Indexer). Retry later or accept as residual — the
# worktree list no longer references it.
```

## Bulk Update Helper

For many worktrees, loop the move:

```powershell
$wtDirs = @('C:\path\to\project\wt1', 'C:\path\to\project\wt2')
$container = 'C:\path\to\project-worktrees'
foreach ($dir in $wtDirs) {
    $name = Split-Path $dir -Leaf
    $dest = Join-Path $container $name
    git -C (Split-Path $dir -Parent) worktree move $dir $dest
}
```

## Verification

```powershell
# All worktrees registered, all inside the sibling container
git -C "C:\00repos\codigo\$proj" worktree list
# Expected output: every linked worktree path begins with "C:/00repos/codigo/<proj>-worktrees/"

# No more project-internal orphan worktree dirs
Get-ChildItem -LiteralPath "C:\00repos\codigo\$proj" -Directory -Force |
    Where-Object { Test-Path "$($_.FullName)\.git" -PathType Leaf }
# Expected: empty (no scattered .git-files inside the project)

# Main is still at the project root
git -C "C:\00repos\codigo\$proj" rev-parse --show-toplevel
# Expected: C:/00repos/codigo/<proj>

# Working tree sanity
git -C "C:\00repos\codigo\$proj" status --short --branch
# Should show: `## main...origin/main` plus any preserved dirty files.

# If main was the active worktree during reorganization, dirty state survives.
# The reorganization only moves files; it does NOT modify the working tree content.
```

## Critical Gotchas

| # | Trap | Symptom | Fix |
|---|------|---------|-----|
| 1 | `git worktree add <path>` with a **relative** `<path>` | Path interpreted relative to CWD, not repo. Creates `PROJ/PROJ/worktree` nesting. | Always use **absolute paths** or `./`-prefix. |
| 2 | `git worktree add --force` on an existing dir | "already exists" error. | Either move the existing dir out first, or use a different fresh dir. |
| 3 | File locks on `.accdb` / `.atl` / `.codegraph` / `.dysflow` | "Access is denied" on Remove-Item or Move-Item. | Wait 5-10s and retry. AV/Windows Indexer usually releases within ~30s. If persistent, accept as residual. |
| 4 | `PowerShell Rename-Item` on a dir containing `.git\` | Fails first try with "Access is denied". | **Wait 5-10s and retry.** It's a transient lock. Backup plan: rename source to a temp backup name → `git worktree add --force` with absolute path → robocopy overlay from backup excluding `.git` file. |
| 5 | `git worktree move <src> <dst>` with invalid `.git` file | "is not a working tree" / "is not a .git file" error. | Read the `.git` file inside the worktree first. It should point to `<project>/.git/worktrees/<name>\`. If the project root itself moved, see gotcha #10. |
| 5a | **Migrating v1→v2 with scattered WTs**: after Phase A moves the real `.git\` directory from `<project>/00_main/.git\` to `<project>/.git\`, the `.git` FILE inside each scattered worktree still points to the OLD path `<project>/00_main/.git/worktrees/<name>\`, which no longer exists. Subsequent `git worktree move` fails with "fatal: is not a working tree". | Before Phase B, rewrite each scattered WT's `.git` file to point to the NEW location of its metadata inside the project's real `.git\` dir. The metadata subdir name (inside `.git/worktrees/<name>`) is internal to git and may include a project prefix even when the worktree dir does not — preserve that prefix exactly. Fix per WT: `Set-Content -LiteralPath "$p\$<wt-name>\.git" -Value "gitdir: <new path>"`. Without this fix, Phase B leaves the scattered WTs broken and Phase 3's `git worktree prune` would silently delete their metadata. |
| 6 | `git push --no-verify` in APAP_ACTUAL | Server-side **pre-receive hook** blocks pushes to main with message: "BLOCKED: push to 'refs/heads/main' — this repo is staging-only." | Use `git push --no-verify origin main` (bypass is documented by the hook itself). Applies to `ardelperal/APAP_ACTUAL`. |
| 7 | `git worktree prune` semantics | Removes metadata for worktrees whose dir no longer exists. Cleans up after partial deletions. | Use after manual deletes, before final check. |
| 8 | `Move-Item` with `.git\` and other dirs in same call | Sometimes leaves a leftover empty dir at the source. | Cleanup with `Remove-Item -Recurse -Force` (may need wait if locked). |
| 9 | After moving the **whole project folder** to a new parent path (cross-directory migration) | The metadata file `<project>/.git/worktrees/<name>/gitdir` still contains the OLD absolute path. `git worktree list` reports the worktree as `prunable` at the old path. | Edit the `gitdir` file inside the metadata dir and replace the old path prefix with the new one. Both the `.git` FILE in the worktree and the `gitdir` FILE in the metadata need updating — they are independent. |
| 10 | `Move-Item -LiteralPath X Y` from a different PowerShell cell can return `NotFound: FileSystem.access` even after the move completed | The tool wrapper reports an error mid-flight. | Always verify with `Test-Path` before retrying. The move usually succeeded; do NOT retry if source no longer exists. |
| 11 | `.codegraph/codegraph.db` lock from MCP codegraph server (not AV / Indexer) | `Process cannot access the file because it is being used by another process` on Move-Item. The lock is held by 4 `codegraph.exe` + N node processes of the MCP codegraph-vba server. | Waiting 5-10s does NOT release it. Either kill the MCP processes (`Stop-Process` on `codegraph.exe` + node processes whose path contains `codegraph-vba`), or accept the directory as residual and move on. The user prefers to close other active sessions first before killing the MCP. |
| 12 | `Move-Item -LiteralPath src dst` fails when destination is a child path that already contains a directory of the same name nested inside | `Cannot create 'X' because a file or directory with the same name already exists`. Happens when a previous partial move created the dest with subdirs. | Copy the loose files (`codegraph.db`, `daemon.log`, etc.) individually with `Copy-Item -Force`, then `Remove-Item -Recurse -Force` on the source. Don't try to merge whole dirs. |
| 13 | Container already exists but is empty / stale | `git worktree move` fails because the dest dir exists with a `.git` file from a previous run. | `Remove-Item -LiteralPath $dest\.git -Force` (and prune), then retry the move. |

## Special Cases

### A. Repo is broken — `.git` directory is corrupt or replaced by a stale file

Symptom: `git status` shows every file as deleted, or `fatal: not a git repository`.

The repo was once a worktree but its main repo reorganized and the old metadata path is gone.

Fix:
1. Inspect the broken `.git` (file or directory).
2. If it is a **file** that you wrote previously under the legacy v1 layout, delete it (the project is no longer a worktree — it is the main). The real `.git\` lives elsewhere; restore from a backup or fresh clone.
3. If it is a **directory** with corrupt metadata, prefer `git fsck` and `git reflog` to recover. Worst case, `rm -rf .git && git init && git remote add origin <url>` and accept the loss of stash/notes.

### B. Legacy `<project>/worktrees\` child container (older pre-v2 pattern)

Example: `00_CADETE/worktrees/refactor-issue-204\`.

The worktree `.git` file points to `00_CADETE/.git/worktrees/refactor-issue-204\` (still under the project root). Phase 2's `git worktree move` to `00_CADETE-worktrees/refactor-issue-204\` works without rewriting the `.git` file — the metadata path is still valid. After the move, the old `00_CADETE/worktrees\` child is empty and gets deleted in Phase 3.

### C. Branch-less orphan directories inside the project

Sometimes there are directories that **look like worktrees** but have no `.git` file and no branch tracking. They're stale code clones (likely from aborted chained-PR experiments).

Fix: check for any branch matching the directory name via `git ls-remote origin <branch>` and `git branch -a | grep <branch>`. If neither matches, delete the directory as historical debris.

### D. `--force` move failures leaving half-state

`git worktree move` may leave a partial state (source partially emptied, target partial). Diagnosis:
- `git worktree list` shows the worktree at the wrong path
- The directory structure is split between source and target
- Metadata may be inconsistent

Recovery:
1. `git worktree prune` clears stale metadata
2. `git worktree add <path> <branch>` re-creates the worktree from the branch
3. Manually `robocopy` over the broken state if files were lost

## Edge Cases by Project Type

These don't change the workflow but worth noting:

| Project type | Sticky files | Notes |
|---|---|---|
| **Access VBA** (00_EXPEDIENTES, 00_GESTION_RIESGOS, 00_HPS, 00_CONDOR, 00_LANZADERA, 00_NO_CONFORMIDADES) | `.accdb` | Often locked by AV scanning. `Start-Sleep -Seconds 30` if "Access is denied". |
| **Python** (LabManager, APAP_WEB-B, bench-clone-fresh) | `.mypy_cache`, `.pytest_cache` | No issues, fast moves. |
| **.NET / Node / TypeScript** (00_CADETE, codegraph-vba) | `node_modules`, `bin/`, `obj/` | Don't move these — `.gitignore` excludes them. The move only touches tracked files. |
| **Tool cache dirs** (`.atl`, `.codegraph`, `.dysflow`, `NVIDIA Corporation`) | Persistent sometimes | Move them — they're auto-regenerated by tools. |

## Cleanup Decision Tree

```
After main reorganization, are there project-internal dirs with a .git file?
├── Yes — and they're listed in `git worktree list` → move them out (Phase 2)
├── Yes — and NOT in `git worktree list` → likely orphan; check git data; delete
└── No  → main reorganization done
```

For orphan dirs without git tracking:
1. Try `Remove-Item -Recurse -Force` — usually works
2. If "Access is denied": wait 10s, retry
3. If persistent: leave as residual, document in the session summary

## After the Reorganization

- Run `git worktree list` from the project root — every linked worktree should be at `<project>-worktrees/<wt-name>\`.
- Run `git -C <project> status --short --branch` — should be clean or reflect preserved dirty state.
- If you find a project-internal orphan (e.g. due to file lock), note it for the user — they may need to retry on next session or after reboot.
- Save the lesson: this skill exists because file-system reorganization has surprising nuances (locks, scattered vs sibling container, dotfile fragility).

## Cross-References

- See memory `cadete-expedientes-reorg-lessons-learned` (Engram, observation #21298) for the original set of gotchas discovered.
- See memory `pattern/cadete-reorganization-2026-07-23-per-project-folder-structure` (Engram, #21298) for the pattern as a workflow.
- The user's shared AGENTS.md (`~/.config/opencode/AGENTS.md`, `~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`) references this skill — the AI auto-loads it when needed via the `available_skills` mechanism.

## Changelog

- **v2.0** (2026-08-13): inverted convention. Main stays at the project root (classic git layout); linked worktrees live in a sibling `<project>-worktrees\` container **outside** the repo. `.git\` remains a directory. Supersedes the v1 "main inside `00_main/` + nested worktrees + `.git` FILE" layout.
- **v1.0** (2026-07-23): initial convention. Main in `<project>/00_main/`, linked worktrees in `<project>/<wt-name>/`, `.git` as a FILE pointing to `00_main/.git`.
