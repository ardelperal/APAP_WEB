# Collab State with Alan — Gentle-AI

_Last fetched: 2026-08-31T13:00:00Z_
_Last user ask: 2026-08-31T13:00:00Z (activity since yesterday)_

## Open PRs (8) — wave-disposition + race detection

| PR# | Title | Branch | Linked | Wave-disp | Status | Merged rival | Other rival | Action |
|---|---|---|---|---|---|---|---|---|
| #3906 | feat(state): record last_synced_at after successful sync | `feat/1273-last-synced-at` | #1273 | n/a (post-snapshot) | open · MERGEABLE | none | none | push + wait for label; replacement for #1978 (closed 2026-08-30 with smaller scope: timestamp-only) |
| #3731 | fix(opencode): probe PATH gentle-ai before relay, refuse on skew | `fix/3049-reviewer-plugin-path-skew` | #3049 | n/a (post-snapshot) | open · MERGEABLE | none | none | push + wait for label; no rival |
| #3629 | fix(install): replace the Unix binary atomically | `fix/1728-atomic-unix-binary` | #1728 (Refs #1748) | n/a (post-snapshot) | open · MERGEABLE | none | none | push + wait for label; no rival |
| #3624 | feat(doctor): detect mixed binary and managed-asset versions | `feat/1884-doctor-mixed-versions` | #1884 | n/a (post-snapshot) | open · MERGEABLE | none | none | push + wait for label; no rival |
| #3048 | fix(opencode): classify ENOENT in skill-registry plugin | `fix/2971-skill-registry-enoent` | #2971 | n/a (post-snapshot) | open · MERGEABLE (was CONFLICTING) | none | none | push + wait for label; conflict resolved vs simplification PR #2462 |
| #3023 | fix(opencode): keep SDD phase commands in primary | `fix/2939-keep-sdd-commands-primary` | #2939 | n/a (post-snapshot) | open · MERGEABLE · CHANGES_REQUESTED | none | **PR #3864 (danielgap/decode2, OPEN)** carries same work forward with installation ratchet; branch on fork already deleted | respond to danielgap: consolidate on #3864 (preferred) or keep #3023; no merge conflict yet but #3864 is the live line |
| #2342 | fix(sdd): emit PowerShell-safe UserPromptSubmit hook on Windows | `fix/2124-userpromptsubmit-hook-windows-ps51` | #2124 | n/a (post-snapshot) | open · MERGEABLE · CHANGES_REQUESTED | none | **PR #2807 (jjeg1979, OPEN)** closes #2124 directly | decide scope split with jjeg1979 or close mine as duplicate |
| #2021 | fix(backup): preserve directory and symlink-directory snapshot types | `fix/backup-preserve-dir-symlink-types` | #1723 | n/a (post-snapshot) | open · MERGEABLE · CHANGES_REQUESTED | none | none | push + wait for label |

## Closed-not-merged PRs since 2026-08-15 (added in this fetch)

| PR# | Title | Closed at | Reason | Linked |
|---|---|---|---|---|
| #3449 | docs(agents): add OpenCode headless delegation recipe on Windows | 2026-08-22 07:05 | self-closed — out of release scope, batch later | #1017 |
| #3448 | docs(engram): add Cloud Sync (Optional) section | 2026-08-22 07:05 | self-closed — out of release scope, batch later | #1021 |
| #3447 | docs: add Hermes knowledge-layer section in CONTRIBUTING.md | 2026-08-22 07:05 | self-closed — out of release scope, batch later | #966 |
| #3446 | docs(readme): trust the Homebrew tap instead of a single formula | 2026-08-22 07:05 | self-closed — type:docs label is maintainer gate | #832 |
| #2994 | feat(cli): add review-verb resolver and by-design envelope types | 2026-08-23 17:55 | self-closed superseded/foreign-fix (rc.1 / main changes the surface) | #2415 |
| #2761 | fix(tui): preserve Codex capabilities and OpenCode fast variants | 2026-08-23 17:55 | self-closed superseded/foreign-fix (rc.1 / main changes the surface) | #2218 |
| #2928 | feat(review): expose managed/advisory RDD enforcement | 2026-08-22 07:05 | self-closed — RDD strategy shifted to fail-closed + stop offering | #1842 |
| #2932 | fix(review): fail closed when explicit --lineage recovers foreign | 2026-08-22 13:15 | **closed by Alan** with Rule A obsolescence verdict; #1987 already fixed at b43e0928a2bf | #1987 |
| #2715 | fix(update): swap Windows binary when destination is held | 2026-08-26 19:12 | self-closed superseded/foreign-fix — v2.5.0-rc.1 ships manual-fallback strategy instead of atomic swap | #2319 |
| #1978 | feat(state): record last_synced_version and last_synced_at | 2026-08-30 12:22 | self-closed in favor of smaller re-scope → #3906 (LastSyncedVersion was redundant with InstalledBinaryVersion in main) | #1273 |

## Merged PRs (last 90d, top 17 by date) — context

| PR# | Title | Merged at | Closer | Linked issue |
|---|---|---|---|---|
| #3113 | fix(orchestrator): amend closed single-select contract clauses | 2026-08-14 | Alan | #3070 |
| #2277 | fix(review): skip provably-unrelated leaves from pre-push gate assessment | 2026-08-13 | Alan | #1886 |
| #2170 | fix(manifest): disable static prompt injection for AgentPi (Slice A1) | 2026-08-13 | Alan | #1194 |
| #2149 | fix(claude-code): add Engram read tools to sdd-explore frontmatter | 2026-08-13 | Alan | #1976 |
| #2121 | fix(review): classify unsupported Windows authority filesystems | 2026-08-13 | Alan | #1918 |
| #2089 | fix(install): roll back applied assets when state persistence fails | 2026-08-13 | Alan | #1725 |
| #2083 | feat(upgrade): show doctor advisory after successful upgrade | 2026-08-13 | Alan | #1901 |
| #2081 | feat(judgment-day): bind judge/fix-actor roles to explicit subagent_type in SKILL.md | 2026-08-13 | Alan | #1923 |
| #2079 | fix(opencode): prefer worktree over directory in skill-registry refresh | 2026-08-13 | Alan | #1731 |
| #1981 | fix(skills): add mandatory privacy review to issue-creation skill | 2026-07-30 | Alan | #1906 |
| #1607 | feat(review): enumerate all invalid compact recovery edges in one pass | 2026-07-21 | Alan | #1582 |
| #1481 | fix(upgrade): scaffold minisign signature verification (slice A) | 2026-07-22 | Alan | #359 |
| #1467 | fix(doctor): derive required agents from state.json and tighten duplicate detection | 2026-07-19 | Alan | #709 |
| #1444 | fix(sdd): profile agent assignments fall back to global when per-profile is empty | 2026-07-19 | Alan | #557 |
| #1435 | fix(installer): pin GGA installs to tagged release | 2026-07-19 | Alan | #360 |
| #1171 | feat(skills): add gentle-ai-collab-perfect workflow skill for external contributors | 2026-07-19 | Alan | #1170 |

## Closed-not-merged PRs (last 90d, none for ardelperal)

See "Closed-not-merged PRs since 2026-08-15" section above for the current 10 closed entries.

## Alan's activity (last seen, last action)

- Last merge (gentle-ai): 2026-08-31 12:47:13Z (#3962) — ongoing merge marathon on `fix(sdd)/fix(review)` today (20+ merges since 2026-08-30 16:18Z)
- Last comment on contributor PRs from Alan: 2026-08-22 13:15Z on #2932 (Rule A obsolescence verdict)
- Last comment on contributor PRs from danielgap (decode2): 2026-08-31 00:00:29Z on #3023 (consolidation offer onto #3864)
- Wave-disposition snapshot: pinned at `e0742a39` (`docs/rdd-wave0-freeze-and-disposition`); HIGHEST wave-branch is wave0 (waves 1-7 do not have a `freeze-and-disposition` suffix — they live on `feat/rdd-waveN-*` branches and are merged individually)

## Recent Alan commits on `upstream/main` that signal RDD simplification (last 30)

| Commit | Title |
|---|---|
| 60388183 | Merge `feature/rdd-root-simplification` (PR #2462, 208 files, +8623/-9649) — RDD root simplification, waves 0–7 |
| 6b18f1fa | Merge PR #2956: fix(sdd): let review act after implementation, not during it |
| 21cd9b89 | fix(review): stop offering review.start when RDD is disabled |
| 8acf83ab | refactor(review): simplify selector-free recovery guard |
| cff02464 | fix(review): finish scoping authority walks past outdated records |
| b0c62a50 | fix(review): skip provably-unrelated pre-push leaves from per-leaf gate assessment |
| cf8b8304 | fix(review): quarantine retired compact snapshot identities |
| 2bf1c036 | fix(review): name authority written by a newer release |
| 7b3b0cb2 | Merge PR #3236: test(review): guard retired advisory command |
| 7cbda861 | test(review): guard retired advisory command |
| 8f28a8b3 | refactor(opencode): retire the delegators the background rebase orphaned |

## Pending maintainer actions (Alan-only)

| PR# | Need | Why |
|---|---|---|
| #3906 | `type:feature` label | contributor 403 AddLabelsToLabelable |
| #3731 | `type:bug` label | same |
| #3629 | `type:bug` label | same |
| #3624 | `type:feature` label | same |
| #2342 | `type:bug` label | same |
| #2021 | `type:bug` label | same |

(`#3048` already has `type:bug`; needs `priority:*` + `status:approved` from Alan. `#3023` also has `type:bug`; needs re-review decision + danielgap consolidation to #3864.)

## Cross-cutting notes

- **Alan merged a marathon today** — `fix(sdd)/fix(review)` flood (20+ PRs between 2026-08-30 16:18Z and 2026-08-31 12:47Z: #3918, #3914, #3911, #3910, #3907, #3905, #3899, #3891, #3883, #3811, #3943, #3945, #3947, #3949, #3950, #3951, #3952, #3953, #3954, #3955, #3956, #3957, #3958, #3959, #3960, #3962, #3965, #3966). None close issues we target (#1273, #3049, #1728, #1884, #2971, #2939, #2124, #1723) — file overlaps are incidental, no semantic obsolescence.
- **#3966 "fix(claude): rename the SDD commands to gentle-sdd prefix"** touches `internal/cli/sync.go` (overlaps #3906 / #3624 / #2342) and `internal/components/sdd/inject.go` (overlaps #2342 / #3958). Different semantic scope per file — no obsolescence.
- **danielgap opened #3864** as a "carry" of #3023 with installation ratchet + rebased on main. danielgap explicitly offered to drop #3864 if you finish #3023 yourself; branch on your fork was already deleted per their 2026-08-30 23:58Z comment. Decision needed.
- **Self-closure pattern after rc.1 / simplification merge (#2462)**: 4 PRs closed as `superseded/foreign-fix` (#2994, #2761, #2928, #2715) and 1 by Alan as Rule A obsolescence (#2932). All self-driven; no judgment calls to revise.
- **#1978 → #3906 re-scope**: LastSyncedVersion field was redundant (main already stamps InstalledBinaryVersion); only the timestamp is now in #3906.
- **#3048 conflict resolved**: was CONFLICTING, now MERGEABLE per rebase against current main.

## Things to look at before picking another issue

1. **#3023** — respond to danielgap on PR thread: consolidate on #3864 (preferred per their offer) or finish #3023 yourself; branch on your fork is already gone
2. **#2124** — ping jjeg1979 on PR #2807 about scope split (unchanged from previous fetch)
3. **#3906, #3731, #3629, #3624, #3048, #2342, #2021** — push and wait for Alan to apply labels; nothing to do

## Anti-patterns reminder (last batch of round-trip cost PRs)

- Don't ship state machines without grepping for every exit (pattern #1433)
- Don't reimplement sha256/hex/encoding helpers (pattern #1481)
- Don't skip docstring coverage on new exports (pattern #1608)
- Don't claim slice body does more than the slice delivers (pattern #1481)
- Don't stack-to-main chains without labeling slice boundaries (pattern #1132-#1134)
