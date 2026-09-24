---
name: gentle-stack-a-main
description: Trigger: actualiza todo gentle a main, gentle stack a main, todo gentle al main, actualiza gentle stack, refresh todo gentle. Sube el binario gentle-ai, el binario engram y el paquete gentle-pi (el plugin de gentle-ai para Pi) al HEAD de main y corre gentle-ai sync al final.
license: MIT
metadata:
  author: ardelperal
  version: 1.2
  last_verified: 2026-09-21
  scope: ['universal', 'ops']
  auto_invoke: ['raising the gentle stack to main', 'updating gentle-ai engram and gentle-pi to main', 'fixing an agent binary missing from PATH']
  tiers: ['universal', 'ops']
---

# gentle-stack-a-main

Raise the whole **Gentle-AI** stack (CLI binary, Engram memory, Pi plugin) to each repo's `main` HEAD in one pass, with verification at the end.

## §1 Activation

Load this skill when the user asks for any of:
- "actualiza todo gentle a main"
- "actualiza el stack gentle a main"
- "actualiza gentle stack al HEAD"
- "refresh todo gentle"
- "todo gentle al main / a main / al head"
- "actualizá todo el gentle al último"

Do NOT load this skill when:
- The user asks for **stable / `@latest`** (that is the stable channel, not main).
- The user asks for a single component without the others (use `gentle-ai-binario-a-main` or the component's native flow).
- The user wants to work on a PR against one of the repos (that is `engineering-workflow`).
- The user wants only `gentle-ai sync` with no prior upgrade.
- The user only wants a broken agent binary back on PATH. That is a §7 recovery, and §7 is self-contained — do not run the full stack upgrade for it.

## §2 Hard Rules

1. **HR-1** — ALWAYS set `$env:GENTLE_AI_CHANNEL='beta'` in the PowerShell session BEFORE running `gentle-ai upgrade`. Without it, upgrade defaults to stable and reports "No upgrades available" even when `main` has newer commits.
2. **HR-2** — ALWAYS run `gentle-ai sync` at least twice: once after the `gentle-ai upgrade`, once after installing `gentle-pi`. Sync propagates persona, managed skills, themes and `opencode.json` to the active runtime.
3. **HR-3** — ALWAYS capture versions BEFORE and AFTER every replacement, plus the short SHA (last 12 chars of the pseudo-version) for every component that reports one.
4. **HR-4** — NEVER delete a stale binary. Move it to `~/.gentle-ai/backups/<name>-<version>-<timestamp>.exe` first. This applies to the native `gentle-ai upgrade` (which backs itself up) AND to every `go install` that overwrites `~/go/bin/<tool>.exe` — `go install` does NOT back anything up, so you must.
5. **HR-5** — If `gentle-ai upgrade` stalls more than 3 minutes in any step (Checking / Creating pre-upgrade backup / Downloading / Installing), STOP and fall back to `$env:GOPROXY='direct'` + `go install github.com/gentleman-programming/gentle-ai/v3/cmd/gentle-ai@main`. Surface the stall as an anomaly. The `/v3/` segment is current; `/v2/` now fails with `invalid version: go.mod has non-.../v2 module path`.
6. **HR-6** — ALWAYS run `gentle-ai doctor` at the end and surface the result. Some unhealthy checks are KNOWN NON-BLOCKERS — report them, do not fail the cycle, do not retry: `kiro not found in PATH`; `gga` manual-update-required on Windows; `engram doctor` `[error] sync_target_closed_space` when its own remedy text says no action is required; `engram doctor` `[warn] ambiguous_active_runtime_sessions`. Every other unhealthy check MUST stop and surface to the user. A missing **agent** binary (`tool:pi`, `tool:opencode`, ...) is NOT a non-blocker: route it through §7.
7. **HR-7** — ALWAYS end the report with an explicit "restart OpenCode / Pi" prompt. Sync writes to runtime files; until the runtime reloads, the old binary and assets remain active.
8. **HR-8** — NEVER modify the global git config, force-push, or push to any remote during this routine. `git pull origin main` on the local `gentle-pi` clone is the only git mutation allowed, and it MUST be fast-forward.
9. **HR-9** — NEVER enable npm remote fetching (`EALLOWREMOTE`) as a workaround for installing `gentle-pi` from main. Use `npm install -g <absolute-path-to-local-clone>` — the supported path for this setup.
10. **HR-10** — NEVER use `npm install -g gentle-pi@main`. npm does not resolve git refs as `@main`; the only published artifact is the semver release. HEAD of main is reachable only through a local clone + `npm install -g <path>`.
11. **HR-11** — The local `gentle-pi` clone MUST be on `main` before the routine starts. If it is on a feature branch, STOP and ask whether to switch to main or skip the `gentle-pi` step.
12. **HR-12** — Module-path CASING is per-module and MUST be derived from the module's own `go.mod`, never assumed from the other repo. Guessing wrong fails with `version constraints conflict` (or `invalid version: go.mod has non-.../vN module path`). Verified table:

    | Module | Path to use | Casing | Major |
    |---|---|---|---|
    | gentle-ai | `github.com/gentleman-programming/gentle-ai/v3` | all lowercase | `/v3` |
    | engram | `github.com/Gentleman-Programming/engram/v2` | **capital `G`** | `/v2` |

    They disagree on purpose: gentle-ai declares lowercase, engram declares `Gentleman-Programming`. If a new major lands, re-derive with `go list -m <path>@main` instead of trusting this table.

13. **HR-13** — NEVER overwrite the package-local Pi binary while Pi holds it open (`Device or resource busy`). Use `mv old .bak && cp new in place`; if `mv` also fails, set `restart_pi_required: true` and skip the copy. FIRST verify the path exists (see step 1) — in the current setup `~/.pi/agent/npm/node_modules/gentle-pi` has no `.gentle-ai/` directory at all, so this branch is a no-op and `restart_pi_required` stays `false`.
14. **HR-14** — ALWAYS run `gentle-ai skill-registry refresh` after the second sync. It re-scans the local skills and rebuilds `.atl/skill-registry.md` so Pi and OpenCode can route. It may return a cache-hit and print no `N skills` count; in that case derive the count by counting table rows in `.atl/skill-registry.md`.
15. **HR-15** — If the package-local binary was actually touched, ALWAYS report `restart_pi_required: true` and tell the user to restart Pi before invoking `gentle_review` or any other native operation. Pi caches the binary in memory; until restart, the on-disk copy and the in-memory copy can disagree.
16. **HR-16** — NEVER conclude that `engram` is current from the native `gentle-ai update` check. Observed: with `GENTLE_AI_CHANNEL=beta`, it reported `engram installed: 2.0.0 latest: 2.0.0` while `main` was already at `2.0.1-0.20260920084808-70870987f56a`. It is channel-aware for `gentle-ai` (`latest: main@<sha>`) but resolves engram against the latest stable tag. Always resolve main yourself with `go list -m`, and if installed already equals main, skip the install AND the backup.
17. **HR-17** — A missing agent binary is fixed by repairing its owning package manager, NEVER by loosening the doctor check, hand-copying a shim into PATH, or editing `state.json` to drop the agent. Follow §7.
18. **HR-18** — NEVER dump full package-manager config (`pnpm config list`, `npm config list`) into the transcript or a report: it prints auth tokens in plaintext. Use targeted `config get <key>` only.

## §3 Decision Gates

| Condition | Action |
|---|---|
| `where.exe gentle-ai` first match is not `~/go/bin/gentle-ai.exe` | Move stale copy to `~/.gentle-ai/backups/` with a timestamp, then upgrade |
| `gentle-ai upgrade` reports "No upgrades available" with `GENTLE_AI_CHANNEL=beta` set | Already on latest main; skip upgrade, still sync twice, still report |
| `gentle-ai upgrade` stalls > 3 min in any step | Stop, fall back to `go install .../gentle-ai/v3/cmd/gentle-ai@main`, log the stall as an anomaly |
| `gentle-ai upgrade` output is dominated by `gga` and reports `0 succeeded, 0 failed, 1 skipped` | Expected on Windows. `gga` cannot self-update there. Re-read `gentle-ai --version` to confirm whether gentle-ai itself moved, and record the `gga` skip as an anomaly (HR-6 non-blocker) |
| `go install` fails with `version constraints conflict` or `go.mod has non-.../vN module path` | Wrong casing or wrong major. Re-derive from the module's own `go.mod` per HR-12; do not guess |
| `go list -m <path>@main` reports the same version already installed | Skip the install and the backup for that component; report it as already-current |
| `go install github.com/Gentleman-Programming/engram/cmd/engram@main` (no major segment) succeeds but `engram --version` does not change | Silent trap: the v1-suffixed path resolves to a stale pseudo-version instead of erroring. `main` is on `/v2`, so use `/v2/cmd/engram@main`. Any `go install` that reports success while `--version` is unchanged is this class of defect — re-derive the path, do not retry |
| Native `gentle-ai update` shows engram as up to date | Ignore for engram. Confirm against `go list -m ...@main` per HR-16 |
| `gentle-pi` local clone is not on `main` | STOP, ask the user, do not switch branches silently |
| `git pull origin main` produces a non-fast-forward | STOP, surface the conflict, do not force-pull |
| `npm install -g <path>` reports `EALLOWREMOTE` | STOP; the path-based install should not trigger remote fetching. Investigate |
| `~/.pi/agent/npm/node_modules/gentle-pi/.gentle-ai/<ver>/gentle-ai.exe` does not exist | Skip the whole package-binary branch. Report `package_local_binary_present: false` and `restart_pi_required: false` |
| `cp` to the package-local binary fails with `Device or resource busy` | Use `mv old .bak && cp new in place` per HR-13. If `mv` also fails, set `restart_pi_required: true` and skip the copy |
| `skill-registry refresh` returns a cache-hit with no count | Count table rows in `.atl/skill-registry.md` and use that as `skill_registry_count` |
| `gentle-ai doctor` reports `tool:<agent>` not found in PATH | NOT a dead STOP. Route through §7 before deciding `doctor_status` |
| `gentle-ai doctor` reports a duplicate binary in PATH | Report as a warning. Do NOT remove either copy without asking — `~/.gentle-ai/bin/opencode.cmd` is the gentle-ai managed launcher |
| `engram doctor` reports `[error] sync_target_closed_space` | Non-blocker when the remedy text itself says no action is required (inert legacy rows after a major-version jump). Report it, continue |
| `engram doctor` reports `[blocked] sync_mutation_required_fields` | Actionable but not a stack failure: pending cloud mutations for non-enrolled projects. Surface `engram cloud enroll <project>` and continue |
| `engram doctor` reports `[warn] ambiguous_active_runtime_sessions` | Continue. Report in the Output Contract. Non-blocking |
| `engram doctor` reports any other `[error]` / `[fail]` | STOP per HR-6. Surface the errors. Do not continue |

## §4 Execution Steps

1. **Pre-check binaries, clone, and the package-local path.**
   - `where.exe gentle-ai` (expect first match = `~/go/bin/gentle-ai.exe`).
   - `where.exe engram` (expect first match = `~/go/bin/engram.exe`).
   - `git -C <path-to-gentle-pi-clone> rev-parse --abbrev-ref HEAD` (expect `main`).
   - Test whether the package-local Pi binary path exists; record `package_local_binary_present`.
   - If any check fails, route through the matching Decision Gate and STOP if there is no fix.
2. **Capture baseline and resolve `main` for each component.**
   - `gentle-ai --version` → `gentle_ai_before`.
   - `engram --version` → `engram_before`.
   - `git -C <path-to-gentle-pi-clone> rev-parse --short HEAD` → `gentle_pi_repo_commit_before`.
   - `npm list -g gentle-pi --depth=0` → `gentle_pi_npm_before`.
   - `$env:GOPROXY='direct'`; `go list -m github.com/Gentleman-Programming/engram/v2@main` → `engram_main_resolved`. Do NOT skip this: the native check lies about engram (HR-16).
3. **Upgrade `gentle-ai` to main.**
   - `$env:GENTLE_AI_CHANNEL = 'beta'`.
   - `gentle-ai upgrade` with a 3-minute timeout.
   - If it stalls, fall back per HR-5.
   - `gentle-ai --version` → `gentle_ai_after` + `gentle_ai_short_sha`.
4. **First sync.**
   - `gentle-ai sync`. Capture the file-count summary line → `sync_files_changed_first`.
5. **Upgrade `engram` to main (conditional).**
   - If `engram_main_resolved` equals the installed version, skip to step 6.
   - Otherwise, FIRST back up `~/go/bin/engram.exe` to `~/.gentle-ai/backups/engram-<version>-<timestamp>.exe` (HR-4).
   - `go install github.com/Gentleman-Programming/engram/v2/cmd/engram@main` (capital `G`, per HR-12).
   - `engram --version` → `engram_after` + `engram_short_sha`.
6. **Pull the `gentle-pi` clone to main.**
   - `git -C <clone> pull --ff-only origin main`. Expect fast-forward.
   - `git -C <clone> rev-parse --short HEAD` → `gentle_pi_repo_commit_after`.
   - Read the clone's `package.json` version and capture it.
7. **Install `gentle-pi` globally from the local clone.**
   - `npm install -g <absolute-path-to-gentle-pi-clone>`.
   - `npm list -g gentle-pi --depth=0` → `gentle_pi_npm_after`. A `-> <path>` arrow is expected: a path-based install creates a symlink, and the version is read from the linked `package.json`.
8. **Second sync and registry refresh.**
   - `gentle-ai sync` again → `sync_files_changed`.
   - `gentle-ai skill-registry refresh` → `skill_registry_count` (fall back to counting rows in `.atl/skill-registry.md`).
9. **Verify.**
   - `gentle-ai doctor`. Capture the report. On `tool:<agent>` failure, run §7 before deciding `doctor_status`.
   - `gentle-ai --version`, `engram --version`, `npm list -g gentle-pi` for the final readout.
10. **Report.**
    - Output the §5 Output Contract keys in order.
    - End with the explicit restart prompt per HR-7.

## §5 Output Contract

| Key | Type | Description |
|---|---|---|
| `status` | `"success" \| "partial" \| "failed" \| "blocked"` | Overall outcome. `partial` = at least one component moved, at least one did not. `failed` = nothing moved because of a pre-check failure. `blocked` = a real STOP condition (non-FF pull, wrong branch, non-recoverable doctor failure). |
| `gentle_ai_before` / `gentle_ai_after` | string | `gentle-ai --version` before and after. |
| `gentle_ai_short_sha` | string | Last 12 chars of the new pseudo-version (e.g. `134409f6a9d5`). |
| `gentle_ai_upgrade_path` | `"native" \| "go_install_fallback" \| "already_current"` | How gentle-ai was brought to main. |
| `engram_before` / `engram_after` | string | `engram --version` before and after. |
| `engram_main_resolved` | string | Version `main` actually resolves to, from `go list -m`. The authority when the native check disagrees (HR-16). |
| `engram_short_sha` | string | Last 12 chars of the new engram pseudo-version. `null` if skipped. |
| `gentle_pi_repo_commit_before` / `_after` | string | Short SHA of the clone before and after the pull. |
| `gentle_pi_repo_fast_forward` | `"yes" \| "no"` | Whether the pull was fast-forward. |
| `gentle_pi_npm_before` / `gentle_pi_npm_after` | string | `npm list -g gentle-pi` versions. |
| `sync_files_changed_first` | number | File count from the first sync. |
| `sync_files_changed` | number | File count from the second sync. |
| `doctor_status` | `"pass" \| "degraded" \| "failed"` | Roll known non-blockers (HR-6) into `pass`/`degraded`. `failed` only if something is genuinely broken and unresolved. |
| `agent_binary_recovery` | string \| null | What §7 did for a missing agent binary, or `null`. |
| `package_local_binary_present` | boolean | Whether the package-local Pi binary path existed at all. |
| `package_binary_locked` | boolean | `true` if the copy to the package-local binary failed with `busy`. Drives `restart_pi_required`. |
| `restart_pi_required` | boolean | `true` only if the package-local binary was actually replaced while Pi held it open. |
| `skill_registry_count` | number | Skills reported by the refresh, or counted from `.atl/skill-registry.md`. `null` if the refresh was skipped. |
| `anomalies` | string[] | Stalls, fallbacks used, `gga` manual update required, module-path casing corrections, etc. |
| `next_recommended` | `"restart_opencode" \| "fix_violations" \| "none"` | `restart_opencode` on success AND on `degraded`; `fix_violations` if `doctor_status` is `failed`. |
| `risks` | string[] | Open risks (clone not on main, `EALLOWREMOTE`, duplicate binaries left in PATH, etc.). |

## §6 Anti-patterns

| Symptom | Fix |
|---|---|
| Running `gentle-ai upgrade` without `$env:GENTLE_AI_CHANNEL='beta'` | It goes to stable; set the env var first, always |
| Running `go install @main` as the first option, without trying the beta channel | Try `gentle-ai upgrade` with `GENTLE_AI_CHANNEL=beta` first; `go install` is the documented fallback (HR-5) |
| Copying the casing from one repo's `go install` line into the other | They disagree: gentle-ai is lowercase, engram is capital `G` (HR-12). Derive it, never assume |
| Using `go install .../gentle-ai/v2/...` | gentle-ai's module is now `/v3`; `/v2` fails with `invalid version` (HR-5) |
| Trusting the native update check for engram | It resolves engram against the latest stable tag, not main. Use `go list -m ...@main` (HR-16) |
| Running `go install` over `~/go/bin/engram.exe` with no backup | `go install` backs up nothing; copy to `~/.gentle-ai/backups/` first (HR-4) |
| Running `npm install -g gentle-pi@main` | npm does not resolve `@main`; use `npm install -g <path-to-local-clone>` |
| Enabling `EALLOWREMOTE` to fetch the tarball | Breaks this setup; use the local path (HR-9) |
| Deleting the old binary before installing the new one | Move it to `~/.gentle-ai/backups/` with a timestamp; never delete (HR-4) |
| Forgetting the second `gentle-ai sync` after installing `gentle-pi` | Without it the new assets never reach the active runtime (HR-2) |
| Assuming `engram` has its own `upgrade` subcommand | It does not; always `go install ...@main` |
| `git pull origin main` with uncommitted changes in the clone | STOP, ask the user to commit or stash; never force-pull |
| Chasing `~/.pi/agent/.../gentle-ai.exe` when the path does not exist | Check existence in step 1 and skip the branch — do not create the directory to satisfy the skill |
| Ending the report with no explicit restart prompt | Mandatory (HR-7); always close with that line |
| Continuing when `gentle-ai doctor` is unhealthy for anything outside the HR-6 non-blocker list | STOP per HR-6; surface the failing checks, no blind retry |
| Treating `tool:pi` (or any agent binary) not found as a dead STOP | Route it through §7 — it is a repair, not a blocker (HR-6 / HR-17) |
| Hand-copying a shim into PATH to satisfy the doctor check | Fix the owning package manager instead (HR-17). A hand-made shim is untracked and will rot |
| Running `pnpm config list` / `npm config list` for diagnosis | It prints auth tokens in plaintext; use targeted `config get` (HR-18) |
| Editing `state.json` to drop an agent so doctor stops complaining | That hides the defect instead of fixing it (HR-17) |
| Forgetting `gentle-ai skill-registry refresh` after the second sync | Per HR-14; without it, new/changed skills are not routable |
| Assuming an unchanged `engram --version` after a "successful" `go install` means you are already current | It usually means the module path is wrong (missing or stale major segment). Re-derive the path; do not retry the same command |
| Counting `skill_registry_count` as `0` because the refresh was a cache-hit | Count the rows in `.atl/skill-registry.md` instead |

## §7 Installed-agent binary recovery

Symptom: `gentle-ai doctor` reports `tool:<agent> not found in PATH` for an agent listed in `state.json`. The doctor resolves agent binaries via `exec.LookPath` using the `agentToolBinaries` map in `internal/cli/doctor.go` (`pi` → `pi`, `opencode` → `opencode`, ...).

Diagnose in this order — do not skip to installing a second copy:

1. **Confirm it is genuinely absent.** `where.exe <binary>`. If it resolves, the doctor's PATH differs from yours; re-run doctor from the same shell.
2. **Find the owner.** Locate the package that ships the binary. For `pi` it is `@earendil-works/pi-coding-agent` (`bin: {"pi": "dist/bundle/cli.js"}`). Search the package-manager manifests rather than the disk:

   ```powershell
   Get-Content "$env:LOCALAPPDATA\pnpm\global\5\package.json" -Raw   # pnpm global manifest
   Get-ChildItem "$env:APPDATA\npm\node_modules" -Force              # npm global
   ```

3. **Check whether the shim dir is on PATH.** `pnpm bin -g` and `$env:PNPM_HOME` should agree, and that directory must be on PATH.
4. **Distrust `list -g` when it contradicts the disk.** Observed: the pnpm global manifest contained a bogus dependency `"5": "link:"` (empty link target), and pnpm had materialized it as a **self-referential junction** `<global>\node_modules\5` → `<global>\`. Also observed: `pnpm list -g` reported `@earendil-works/pi-coding-agent 0.85.1` as installed even though nothing was on disk (no `@earendil-works` dir, no `.pnpm` entry, no shim). The likely mechanism — not separately proven — is that `list -g` walked the junction loop back into another linked package's nested `node_modules`, where that version does exist. Treat the disk as authoritative over `list -g`; the fix sequence below worked regardless of which reading is right. Detect the junction with:

   ```powershell
   Get-Item "$env:LOCALAPPDATA\pnpm\global\5\node_modules\5" | Select-Object Name, LinkType, Target
   ```

5. **Repair the owner, then materialize the shim.** The two steps are NOT the same command:

   ```powershell
   $g       = "$env:LOCALAPPDATA\pnpm\global\5"
   $backups = "$env:USERPROFILE\.gentle-ai\backups"
   $ts      = Get-Date -Format 'yyyyMMddTHHmmssZ'
   New-Item -ItemType Directory -Path $backups -Force | Out-Null

   # 0. back up the manifest and lock first (HR-4)
   Copy-Item "$g\package.json"   "$backups\pnpm-global-5-package.json-$ts.bak" -Force
   Copy-Item "$g\pnpm-lock.yaml" "$backups\pnpm-global-5-pnpm-lock.yaml-$ts.bak" -Force

   # 1. remove the bogus junction (rmdir does NOT follow reparse points; Remove-Item can)
   cmd /c rmdir "$g\node_modules\5"

   # 2. delete the '"5": "link:"' line from the pnpm global package.json

   # 3. materialize the declared dependency
   $env:PNPM_HOME = "$env:LOCALAPPDATA\pnpm"
   pnpm install -g

   # 4. THIS is the step that creates the shim in $PNPM_HOME
   pnpm add -g "@earendil-works/pi-coding-agent@<declared-version>"
   ```

   **Why step 4 exists:** `pnpm install -g` only writes `global\5\node_modules\.bin\pi`. It does NOT populate `$PNPM_HOME`. Only `pnpm add -g` links the bin into the global bin directory that PATH actually sees. Skip step 4 and `where pi` stays empty even though the install reported success.
6. **Verify with the same instrument the doctor uses.** `where.exe pi` then `pi --version`, then re-run `gentle-ai doctor` and confirm `tool:pi` is `[ok]`.

Related warnings observed in the same pnpm global, neither of which breaks `codegraph` (it resolves from `%LOCALAPPDATA%\codegraph\current\bin\codegraph.cmd`): `@colbymchenry/codegraph` fails bin creation with an `ENOENT` on `dist/bin/codegraph.js.EXE`, and the `codegraph-vba` link target `C:\00repos\codigo\00_codegraph_main` does not exist. Report these; do not silently repair them.

## §8 Self-compliance

This skill MUST pass these checks before it ships:

```bash
head -10 SKILL.md                                   # frontmatter, six fields
wc -l SKILL.md                                      # body budget ≤ 700 (target 180-450)
head -3 SKILL.md | grep -q "Trigger:"               # description starts with Trigger:
grep -E '^## §' SKILL.md                            # canonical sections, in order
grep -cE '^[0-9]+\. \*\*HR-[0-9]+\*\* —' SKILL.md    # hard rules numbered HR-N (not mere references)
grep -E '\| (Condition|Symptom|Key) \|' SKILL.md     # contract tables present
grep -n "Gentleman-Programming/engram/v2" SKILL.md   # engram casing is capital G
grep -n "gentleman-programming/gentle-ai/v3" SKILL.md # gentle-ai path is v3 lowercase
```

Reference counter (v1.2): 9 numbered sections, 18 HR-N rules, Decision Gates / Anti-patterns / Output Contract as tables, body budget target ≤ 450 lines.

## §9 References

- `~/.opencode/skills/gentle-ai-binario-a-main/SKILL.md` — single-component upstream. Use it when the user only wants the gentle-ai binary + sync.
- `https://github.com/Gentleman-Programming/gentle-ai/blob/main/README.md` — `GENTLE_AI_CHANNEL=beta` channel contract, `gentle-ai sync` post-install requirement.
- `https://github.com/Gentleman-Programming/engram/blob/main/docs/INSTALLATION.md` — `go install .../v2/cmd/engram@main` (no native `upgrade` subcommand).
- `https://github.com/Gentleman-Programming/gentle-pi/blob/main/README.md` — official install is `pi install npm:gentle-pi@<stable>`; HEAD of main only via local clone + `npm install -g <path>`.
