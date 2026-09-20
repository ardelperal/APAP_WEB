---
name: collab-with-alan
description: Trigger: contributor workflow on Gentleman-Programming/gentle-ai or Gentleman-Programming/engram. Two outputs and one action, repo-aware. Output 1: 'my work' table — open and recent PRs/branches by @ardelperal, with Alan-TheGentleman's merge + comment status and any pending action. Output 2: 'approved list' — issues with `status:approved`, open, no PR cross-reference, no duplicates-of-already-resolved (3-layer detection: linkedPullRequests, cross-repo search, textual duplicate markers), sorted by priority (high → medium → low → none) then oldest first. Skipped items shown in a dedicated section. Picking rule for mutually-duplicate candidates documented. Action: when the contributor names an issue number, delegate implementation to the SDD chain and the contribution rules skills. Triggers on phrases like 'cómo va mi PR en <repo>', 'lista de <repo>', 'atacar otra issue nueva', 'voy con #N', 'ya terminó'.
license: Apache-2.0
metadata:
  author: ardelperal
  version: 1.3.0
  depends_on: 
  last_verified: 2026-09-05
  scope: ['universal']
  auto_invoke: ['loading the collab-with-alan skill']
  tiers: ['universal']
---



## What this skill is

Two outputs and one action. They are independent — invoke either on its own.

- **Output 1 — My work in `<repo>`** (tabla). Triggered by phrases like "cómo va mi colaboración en `<repo>`", "status de mis PRs", "qué dijo Alan", "ya terminé". Lists the contributor's own PRs and active branches, with merge + comment state and the next action the contributor can run.
- **Output 2 — Approved list for `<repo>`** (tabla). Triggered by phrases like "qué issues aprobadas hay", "dame la lista de `<repo>`", "atacar otra issue nueva". Lists issues the contributor is **not in flight on**, sorted by priority then oldest first.
- **Action — Implement `#N`**. Triggered by "voy con `#N`" / "ataco `#N`" / "elijo `#N`". Delegates the implementation to the SDD chain and the contribution rules skill. The orchestrator does not write code inline.

If the contributor says just "tira la skill" / "muéstrame las dos" / "status general", show BOTH outputs for the repo they are on.

---

## How to detect which repo (cwd-default)

**The default rule: only the repo whose `cwd` is `git rev-parse --show-toplevel` matches `Gentleman-Programming/<repo>`.** That is, when the contributor runs the skill from inside `C:\Proyectos\gentle-ai`, the skill operates on `gentle-ai` and produces **only** gentle-ai output. When run from inside `C:\Proyectos\engram`, only engram. They never see the other repo in the same output unless they explicitly say "ambos" / "los dos repos".

Bundled scripts in `scripts/` already implement this:

```text
scripts/
├── run.ps1                      # both outputs for the cwd-detected repo
├── output1_my_work.ps1          # Output 1 only
└── output2_approved_list.ps1    # Output 2 only
```

Each script supports `-Repo auto|gentle-ai|engram`. Default `auto` resolves the repo from the git checkout of the current working directory: it probes **every** configured remote (in order `upstream`, `origin`, then the rest) and matches on the repo **name** under any owner, so a fork-only remote like `ardelperal/gentle-ai` resolves just as well as the canonical one. **The scripts do not query the other repo** — even though GitHub has both repositories, the skill by design surfaces one at a time.

> **Gotcha (fixed 2026-08-08):** detection used to read `remote.origin.url` alone and `exit 0` when it found nothing. That combination is a silent-failure trap — a checkout with no `origin` (fork-only, or a vestigial remote that was deleted) produced an empty result that looked exactly like "you have no pending work". Detection now scans all remotes and **exits `2` on failure with the probed remote list on stderr**. If you see exit 2, pass `-Repo` explicitly; never interpret an empty run as "nothing pending" without checking the exit code.

Invocation examples (from `C:\Proyectos\gentle-ai`):

```bash
pwsh -NoProfile -File "C:\Users\adm1\.opencode\skills\collab-with-alan\scripts\run.ps1"
pwsh -NoProfile -File "C:\Users\adm1\.opencode\skills\collab-with-alan\scripts\output2_approved_list.ps1"
```

When invoking from `bash` tool, set `workdir` to the target repo so the script's `git rev-parse` resolves correctly:

```text
workdir: "C:\Proyectos\gentle-ai"   →  repo=gentle-ai
workdir: "C:\Proyectos\engram"     →  repo=engram
```

Override:
- `-Repo gentle-ai` or `-Repo engram` forces a specific repo regardless of cwd. The contributor can name the repo explicitly ("en engram") and the AI passes `-Repo engram`.
- If cwd resolves to neither (`$remote -notmatch 'Gentleman-Programming/(gentle-ai|engram)'`), the script exits with a one-liner naming the problem and the contributor can either cd into a repo or pass `-Repo` explicitly.

**Do NOT recreate the scripts from the recipes below.** The recipes document the logic; the scripts are the implementation. Always invoke the bundled scripts.

When the contributor names a repo explicitly in the trigger ("en engram", "del repo engram"), pass `-Repo <name>` to the script.

If the contributor asks for "ambos" / "los dos repos" / explicitly span, run the bundled script twice with `-Repo gentle-ai` and `-Repo engram`, with their result concatenated by the AI.

---

## Output 1 — My work in `<repo>`

### Filters (strict — only the contributor's work)

- `gh pr list --author "@me"` for every state (run `open`, `merged`, `closed` separately — `--state all` fails on this `gh`).
- `gh pr view <N>` for each open PR to fetch comments filtered by `author.login == "Alan-TheGentleman"` and `mergedAt` / `closedAt`.
- Local branches by the contributor only. Author detection:

  ```bash
  # Last 30 commits on a branch; if any is by ardelperal, the branch is "mine"
  git -C "C:\Proyectos\<repo>" log -30 --pretty=format:'%H %an %ae' <branch> -- |
    Select-String 'ardelperal|aroman|aroman@'
  ```

  This avoids claiming abandoned branches like `pr-613` or `fix/cloud-image-version-stamp` that have a different author.

- `gh search issues --author "@me"` for engagement I'm holding on issue comments (separate column).

### Recipe (engram-friendly, single pass)

```bash
REPO=Gentleman-Programming/<repo>
ME=$(gh api user --jq .login)   # resolves to 'ardelperal'

# a) Open PRs (live state, full)
gh pr list --repo "$REPO" --author "@me" --state open   --limit 30 \
  --json number,title,headRefName,baseRefName,labels,isDraft,url,createdAt,updatedAt,additions,deletions,changedFiles,reviewDecision,statusCheckRollup,mergeable

# b) Merged PRs in the last 90 days (conclude interest window)
gh pr list --repo "$REPO" --author "@me" --state merged --limit 30 \
  --json number,title,headRefName,url,mergedAt,mergedBy,additions,deletions,changedFiles,updatedAt

# c) Closed-not-merged PRs in the last 90 days (follow-up triage)
gh pr list --repo "$REPO" --author "@me" --state closed --limit 30 \
  --json number,title,headRefName,url,closedAt,updatedAt

# d) For each OPEN PR, append Alan's comments + CI rollup
for N in <open PRs>; do
    gh pr view "$N" --repo "$REPO" --json comments \
      --jq "[.comments[] | select(.author.login == \"Alan-TheGentleman\") | {author: .author.login, createdAt: .createdAt, body: .body}]"
    gh pr checks "$N" --repo "$REPO" --json name,state,bucket,link
done

# e) Maintainer universe (one fetch per Output 1 run) — used for race detection
#    below. Filter to author != $me downstream.
gh pr list --repo "$REPO" --state all --limit 200 \
  --json number,title,headRefName,author,createdAt,mergedAt,state,mergedBy,closingIssuesReferences
```

### Maintainer-race detection (open contributor PRs only)

For every **open** contributor PR, check whether the maintainer has shipped a competing fix **after** the contributor PR was opened. This is a separate signal from CI, labels, and Alan's comments — it can shift the recommended action from `keep` to `close as duplicate` without any new review comment.

**Universe**: every PR where `author.login != @me` (typically Alan + the small dnlrsls/decode2 group), `--state all --limit 200`. Fetch **once per Output 1 run**, not per contributor PR. Required fields: `number, title, headRefName, author.login, createdAt, mergedAt, state, mergedBy.login, closingIssuesReferences[].number`. `closingIssuesReferences` is the cheap reliable signal and is inlined by `gh pr list` — do not pay for `gh pr view N` per row.

**Per contributor PR**, filter the maintainer universe to entries with `createdAt > contributor.createdAt` for the obsolescence buckets below. **EXCEPTION — the same-issue signal is scanned in BOTH directions**: a rival that links the same issue but was created BEFORE the contributor PR is a `priority-risk` (open-time-priority threat, not obsolescence) and must never be skipped. Report exact ISO creation dates in the row, never just a PR number.

**Classify each rival into exactly one bucket:**

| Bucket | Trigger | Action |
|---|---|---|
| `superseded/full` | LATER rival, `closingIssuesReferences` shares ≥ 1 issue with the contributor PR **and** the rival covers the full linked issue scope, MERGED | `close as duplicate of #N` |
| `superseded/partial` | LATER rival, MERGED: same linked issue but partial coverage (rival shipped one slice, contributor covers the rest), **or** no shared issue but ≥ 2 shared meaningful title tokens (root-cause overlap) | `adapt` — your PR may add incremental value above the shipped slice |
| `priority-risk` | Same linked issue (both `closingIssuesReferences`), rival created BEFORE the contributor PR, any state | **HARD-GATE close + post adjudication comment** — open-time priority favors the rival (precedent: #2198/#2184, #2596/#2601, **#2924/#2878 2026-08-10**). The action is no longer advisory. If the rival covers the full linked-issue scope OR shares ≥ 2 meaningful title tokens, **close the contributor PR immediately** with the race verdict and post a comment on the linked issue asking Alan to adjudicate. If the contributor scope is genuinely complementary (additive beyond the rival), keep but **do not push further commits until Alan confirms**. The "inspect and hold further slices" guidance was advisory and got ignored in practice — three concrete losses (the #2268 chain, the #1889 chain, the #744 #2596 vs #2601 stale-open) trace directly to it. |
| `overlap/area` | Same files touched, but titles + linked issues differ | `keep` — shared area is NOT obsolescence |
| `inflight` | LATER rival is `OPEN` or `CLOSED-not-merged` | `inspect` — NOT shipped; do NOT close your PR on this signal alone |
| `err/unknown` | API fetch failed (`gh pr list` returned no JSON) | `inspect` — re-fetch manually before recommending keep/close |

**Hard constraints on classification:**

- Closed-unmerged maintainer PR is **never** a shipped fix. It goes to `inflight`, not `superseded`.
- Same-issue rivals created BEFORE the contributor PR are **never** skipped by the later-only filter. They are a priority threat, not obsolescence: classify as `priority-risk`, never as `superseded` (the rival has open-time priority; adjudication decides, not the merge button).
- File count or file overlap **alone** is **never** evidence of obsolescence. Two PRs in the same package may address unrelated symptoms; downgrade to `overlap/area` and let the contributor decide.
- API failure must surface as `err/unknown`. Never silently report `none`.
- One race entry per row, **ranked by severity**: `full` → `partial` → `overlap/area` → `inflight`. If multiple later maintainer PRs match, list the top severity first and append `also <bucket>: …` lines.
- "Same linked issue" requires the actual issue number to appear in **both** PRs' `closingIssuesReferences`. `Refs #N` does not count — it is not in `closingIssuesReferences`.

**Operational examples (encoded as patterns, not history):**

- `#1791` contributor opened 2026-07-29. Maintainer opens `#2511` on 2026-07-31, MERGED, shares the same linked issue → row reads `superseded/full #2511 (2026-07-31) → close`.
- `#1857` contributor opened 2026-07-30. Maintainer opens `#2493` on 2026-08-04 and `#2513` on 2026-08-05, MERGED, no shared issue, ≥ 2 shared meaningful title tokens → row reads `superseded/partial #2493 (2026-08-04), #2513 (2026-08-05) → adapt`.
- `#2158` contributor opened 2026-08-01. Maintainer opens `#2481` on 2026-08-03, MERGED, no shared issue, no title-token overlap, but shares files under `internal/sync/` → row reads `overlap/area #2481 (2026-08-03) → keep`.

> **Note (script vs contract)**: the bundled `scripts/output1_my_work.ps1` implements the `full / partial / inflight / priority-risk` buckets and surfaces a per-PR race line, but currently collapses `superseded/full` and `superseded/partial (same issue)` into one bucket and does not populate `overlap/area` (the file-fetch cost is paid only when the user requests it). This SKILL.md section is the canonical contract; if the bundled script is unavailable or partial, the agent operationalizes the full taxonomy directly.

### Closed-PR closing harvest (closed-not-merged only)

When a contributor PR is closed without merge — especially by someone other than the contributor — the closing comment is a free design review. Harvest it in the same Output 1 run; the script's `closed sin merge (revisar closing comment)` action cell is the trigger, not the answer:

1. Fetch `gh pr view <N> --json closedBy,comments,closingIssuesReferences`; take the LAST non-bot comment (skip `coderabbitai`, `github-actions`, `dependabot`) as the closing critique.
2. Record the technical reason VERBATIM in `state.md` (Closed section). Paraphrase loses the design lesson.
3. Search the maintainer universe for a PR by the SAME author, created within ~72h of the close, whose `closingIssuesReferences` shares the closed PR's issue. If found, record it as `superseded-by #N` — the closer's own fix confirms the line of work is taken and shows the approach that won.
4. Default action: do NOT reopen, do NOT retry the same approach. A retry needs a different design than the one the closing critique rejected.

Worked example (2026-08-08): #2647 closed by dnlrsls — critique: the branch "still accepts the first reported case… correcting that requires replacing the write-admission rule"; ~2.5h later dnlrsls opened #2831 closing the same #2231 → harvested as `superseded-by #2831`, do-not-reopen.

### Pre-apply race recheck (local WIP without a PR)

Race detection over open contributor PRs does NOT protect work that has no PR yet (planning artifacts, local branches, SDD explore→tasks chains). Between "issue picked" and "apply started", someone can open a PR on the same issue — the planning investment does not justify starting apply against a live rival.

Before starting ANY implementation on issue #N (`sdd-apply`, direct fix, next slice), re-run the same-issue scan: filter the maintainer universe for PRs whose `closingIssuesReferences` contains N, plus the issue timeline for `cross-referenced` events with a PR source. If an OPEN rival exists → `inspect` before writing code: compare scope, check open-time priority, and only proceed if the rival is stale, closed-unmerged, or clearly disjoint.

Worked example (2026-08-09): full SDD planning for #2268 finished locally (explore→tasks, zero code commits); dnlrsls had opened #2878 on #2268 the same day → apply withheld, monitor instead.

### Inter-phase race recheck (SDD planning window)

The "pre-apply race recheck" only catches rivals that appear between pick and apply. Maintainers can open and merge a PR **during** the SDD planning window (propose → spec → design → tasks), so the work written by `sdd-propose`, `sdd-spec`, and `sdd-design` can be obsolete before `sdd-apply` ever runs.

**Rule**: re-run the same-issue scan between EVERY SDD phase transition — not only at the apply gate. Treat the same-issue universe as a moving target: fetch `--state all` (not just `--state open`), filter for `closingIssuesReferences` containing the issue number, and cross-check each match's actual `state` field with `gh pr view N --json state,mergedAt`. A maintainer race that lands during the planning window flips the entire plan to `superseded/foreign-fix`.

**Sub-agent state claims about external PRs MUST be cross-checked.** When a sub-agent reports a PR's state ("open", "merged", "draft"), the orchestrator re-verifies with `gh pr view N --json state` before acting on the claim. Sub-agents have no persistent memory and may hallucinate state at the phase-result gate; the orchestrator's gatekeeper is the authoritative reader of GitHub state, not the sub-agent's prose.

**Classify a maintainer PR that ships during the planning window as `superseded/foreign-fix`**, not as a planning failure. The plan, spec, and design are RETAINED for reference; the change is archived with the upstream PR number, the merge commit, and a comparison table (planned scope vs shipped scope). The contributor fast-forwards their fork to the upstream merge commit if the change is acceptable, or files a NEW issue for any follow-up the maintainer did not include. No contributor code is authored.

Worked example (2026-08-10): issue #2871 (sdd-attempt settle `invalid_continuation`) picked at race check `none`. SDD plan written (proposal engram 24529, spec 24530, design 24531, forecast 125-180 lines, no chained PR). At the design-result gate, the design sub-agent reported "existing PR #2921" but misreported its state as `open`; `gh pr view 2921 --json state` showed `MERGED` (Alan-TheGentleman, 2026-08-10 09:41:48 UTC, 149 authored lines, fix commit `475f2e57`). Plan archived as `superseded/foreign-fix`; local fork fast-forwarded from `f0828da5` to `dd333de1`; fix verified at `runtime_compact.go:286`. No contributor code authored. Lesson also saved to engram `sdd/race-check-protocol` (id 24533).

### Sibling-shipped re-verification

When a PR row tracks a sibling issue ("watch #N") and that sibling ships (a merged PR closes it), the contributor's own issue may or may not survive the fix. Before nudging or pushing further slices: reproduce the contributor's linked issue against current main (test or minimal repro) and record the verdict in `state.md`. If it no longer reproduces → close the PR as fixed-by-sibling with a comment citing the sibling PR; do not keep it open on momentum.

Worked example (2026-08-08): Alan merged #2801 closing #2358, the tracked sibling of #2357 (which closes #2206) → #2206 needs a fresh repro on current main before any nudge.

### Output format — TABLE, one row per PR

Group rows: open / merged (90d) / closed-not-merged (90d).

| PR# | Title | Branch | Status | CI | Alan merged / closed | Alan last action | Later maintainer PR / decision | Last update | Action for me |
|---|---|---|---|---|---|---|---|---|---|
| #1171 | feat(skills): collab-perfect skill | `skill/gentle-ai-collab-perfect` | open | ✓ green | — | comment 3d ago | none | 2026-07-13 | rebase + force-push |

`Status` cell values: `open`, `open:draft`, `merged`, `closed:not-merged`. `Alan merged/closed` shows the merge commit / closing user if any. `Alan last action` is the most recent comment by Alan-TheGentleman (or "—"). `Later maintainer PR / decision` follows the maintainer-race taxonomy (`superseded/full`, `superseded/partial`, `overlap/area`, `inflight`, `err/unknown`, or `none`) and embeds the action verb (`close` / `adapt` / `keep` / `inspect`). When multiple later maintainer PRs match, the row shows the top severity first and the rest as `also <bucket>: …` lines. `Action for me` is one verb and should never contradict the `Later maintainer PR / decision` cell.

When the row's status is `open` AND `labels: []` AND the linked issue is `status:approved`, the action cell must read "ping Alan en issue `#N` para labels" — never "add `type:*`" (contributor gets `403 AddLabelsToLabelable`).

For merged / closed-not-merged rows, include a closing-comment 1-liner if one exists, so the contributor sees whether to follow up, retry, or move on.

After the table, append 1–2 sentences only if there is a non-obvious blocker worth surfacing (e.g. "branch `slice/tui-cli` has 13 commits ahead and no upstream — push to `ardelperal/<repo>` before any review can happen").

---

## Output 2 — Approved list (issues I am not in flight on)

Only this repo. Only issues:

- `status:approved` label set.
- `state = open`.
- **No duplicate of an already-resolved or in-flight issue** (see "Duplicate detection" below).
- **No** `cross-referenced` event in the timeline whose `source.issue.pull_request` is truthy (cross-fork refs hide here, see gotcha).
- (Optional tightening the contributor may want: also exclude issues where the contributor has open activity — author `@me` filter on timeline comments. Default off; the contributor can opt in.)

### Duplicate detection — three layers

A "duplicate" here means: an issue is effectively already addressed by work that lives elsewhere, even if the issue itself is still open. Three signals to check, in order:

1. **Same-repo fix already shipped** (catches #1006, #1380):
   - Use `gh issue view <N> --json linkedPullRequests` to get the array of PRs that explicitly link this issue. The GitHub UI surface includes all PRs whose body uses `Closes #N` / `Fixes #N` / `Resolves #N` / `Refs #N`, even after back-sync.
   - For each linked PR: if any is `merged=true` (or `state=CLOSED` with merge_commit), the issue is **resolved** → skip.
   - Also walk the timeline for `cross-referenced` events with `source.issue.pull_request` truthy (this layer catches the case where the PR body did not use a keyword but the issue was referenced).
2. **Cross-repo fix shipped** (catches #1019 — fix landed in `engram`, issue lives in `gentle-ai`):
   - When the candidate repo is the **upstream orchestrator** (gentle-ai), also search the **other** repo of the org for the same root cause. Pragmatic check: `gh search issues "owner:Gentleman-Programming <same keywords>" --state all --json number,title,state` and look for closed/merged entries in either repo that match the symptom.
   - This is a heuristic; if matched, the orchestrator must say explicitly in the hand-back: *"this issue's fix landed in <other-repo> via PR #X; please close as duplicate"*. The contributor cannot close cross-repo.
3. **Textual duplicate marker in body or comments** (catches when a maintainer leaves a `dupe of #N` comment but never closes it):
   - Read first 500 chars of body + all comments.
   - Regex match (case-insensitive): `(?:duplicate|dupe|see\s+#\d+|already\s+(fixed|resolved|merged)\s+in\s+#\d+)`.
   - If matched, skip and report `"skip: text says dupe of #N"` in the hand-back summary.

If any layer matches, the issue goes into a **"Skipped (duplicates or already resolved)"** section at the end of Output 2 — visible to the user with the reason. This section is informational; the user can override and say "actually do this one", and the orchestrator proceeds.

### Picking between two mutually-duplicate candidates

If multiple candidates are mutually-duplicates (e.g. one says "dupe of #256" and #256 says "dupe of #1380" and #1380 is the only real one), pick using this order:

1. **Source / canonical issue** wins. The issue that others mark as `duplicate of <this>` is the one to attack. Detect by: appears as the target of the textual duplicate marker in another issue.
2. **More recent maintainer activity**. Tied at #1: pick the one with more recent maintainer comment, or a `status:approved` label that the other lacks.
3. **Higher priority label** (`priority:high` > `medium` > `low` > none).
4. **Older createdAt**. Tied at all of the above: pick the earliest (chronological = the original report).
5. **Smaller scope** as a tiebreaker (smaller diff = lower risk, easier review).

Document the picking reasoning in the hand-back so the user can override.

### Recipe

```bash
REPO=Gentleman-Programming/<repo>

# Step 1: candidates with the basic status filter.
$list = gh issue list --repo "$REPO" --state open --label "status:approved" --limit 200 \
        --json number,labels,createdAt,body

$candidates = @()
$skipped = @()
foreach ($i in $list) {
    $view = gh issue view $i.number --repo "$REPO" --json linkedPullRequests,comments 2>$null | ConvertFrom-Json
    $events = gh api "repos/$REPO/issues/$($i.number)/timeline?per_page=100" --paginate | ConvertFrom-Json

    # Layer 1: linked PRs (explicit Closes/Fixes/Resolves/Refs).
    $mergedLinked = $view.linkedPullRequests | Where-Object { $_.merged_at -or $_.state -eq 'closed' }
    if ($mergedLinked) {
        $skipped += [PSCustomObject]@{ Number = $i.number; Reason = "fix-merged"; PR = ($mergedLinked | Select-Object -First 1).number }
        continue
    }

    # Layer 1b: timeline cross-ref to a closed/merged PR.
    $crossRefPR = $events | Where-Object { $_.event -eq 'cross-referenced' -and $_.source -and $_.source.type -eq 'issue' -and $_.source.issue.pull_request -and ($_.source.issue.state -eq 'closed' -or $_.source.issue.pull_request.merged_at) }
    if ($crossRefPR) {
        $skipped += [PSCustomObject]@{ Number = $i.number; Reason = "cross-ref-closed"; PR = ($crossRefPR | Select-Object -First 1).source.issue.number }
        continue
    }

    # Layer 2: cross-repo search if upstream orchestrator.
    if ($REPO -eq 'Gentleman-Programming/gentle-ai') {
        $crossRepo = gh search issues "owner:Gentleman-Programming $($i.title.Substring(0, [Math]::Min(60, $i.title.Length)))" --state closed --json number,title,state,repository 2>$null | ConvertFrom-Json
        $crossRepoFix = $crossRepo | Where-Object { $_.repository.nameWithOwner -ne $REPO -and $_.title -match $i.title.Substring(0, [Math]::Min(30, $i.title.Length)) }
        if ($crossRepoFix) {
            $skipped += [PSCustomObject]@{ Number = $i.number; Reason = "cross-repo-fix"; PR = $crossRepoFix[0].number }
            continue
        }
    }

    # Layer 3: textual duplicate marker.
    $commentText = ($view.comments | ForEach-Object { $_.body }) -join "\n"
    $text = ($i.body + "\n" + $commentText).Substring(0, [Math]::Min(2000, $i.body.Length + $commentText.Length))
    if ($text -match '(?i)(?:duplicate|dupe|already\s+(fixed|resolved|merged)\s+in|see\s+#\d+)') {
        $skipped += [PSCustomObject]@{ Number = $i.number; Reason = "text-dupe-marker" }
        continue
    }

    # Layer 4: RDD wave-disposition check (Hard Rule #13).
    # Resolve the highest-numbered wave-planning branch on upstream; grep
    # `docs/architecture/rdd-backlog-disposition.md` from that branch for #N.
    # The label returned decides whether to skip, candidate-with-note, or
    # candidate-as-orthogonal. See Hard Rule #13 for the full taxonomy.
    $disposition = (Get-RddWaveDisposition -IssueNumber $i.number)
    switch ($disposition.Class) {
        { $_ -match '^absorbed-into-wave-(\d+)$' } {
            $skipped += [PSCustomObject]@{
                Number = $i.number; Reason = "wave-disposition-$($Matches[1])"
                Notes  = "absorbed into RDD wave $($Matches[1]); will close when wave ships exit evidence per `Closure audit protocol`"
            }
            continue
        }
        'superseded-by-design' {
            $skipped += [PSCustomObject]@{
                Number = $i.number; Reason = "wave-disposition-superseded"
                Notes  = "superseded-by-design (Wave 7 REMOVE); the reported site is deleted, not fixed by a wave"
            }
            continue
        }
        default {
            # orthogonal | still-valid-fix-now | unclassified | n/a → keep
            # as candidate; surface the disposition label in the output column.
            $i | Add-Member -NotePropertyName Disposition -NotePropertyValue $disposition.Label -Force
            $candidates += $i
        }
    }
}
```

`Get-RddWaveDisposition` is a one-call helper that the bundled scripts expose so the recipe stays small. Pseudocode:

```powershell
function Get-RddWaveDisposition($IssueNumber) {
    # 1. Discover the canonical snapshot: list upstream branches matching
    #    `docs/rdd-wave\d+-(freeze|amended-design|disposition)`, take the
    #    highest-numbered waveN. As of 2026-08-11 the canonical snapshot
    #    is `docs/rdd-wave0-freeze-and-disposition`.
    $branches = git ls-remote upstream 'refs/heads/docs/rdd-wave*-freeze-and-disposition' |
        ForEach-Object { ($_ -split '\s+')[1] } |
        Sort-Object { [regex]::Match($_, 'wave(\d+)').Groups[1].Value -as [int] } -Descending
    $canonical = $branches | Select-Object -First 1
    if (-not $canonical) {
        return [PSCustomObject]@{ Class = 'n/a'; Label = 'n/a (no wave-disposition branch)' }
    }
    # 2. Grep the document from the canonical branch for `#<issue>`.
    $line = git show "$($canonical -replace 'refs/heads/',''):docs/architecture/rdd-backlog-disposition.md" 2>$null |
        Select-String -Pattern "gentle-ai#$IssueNumber\b" | Select-Object -First 1
    if (-not $line) {
        return [PSCustomObject]@{ Class = 'n/a'; Label = 'n/a (post-snapshot or non-RDD)' }
    }
    # 3. Map the matched line to a class+label.
    if ($line -match 'absorbed-into-wave-(\d+)') { return [PSCustomObject]@{ Class = "absorbed-into-wave-$($Matches[1])"; Label = "WAVE $($Matches[1]) (absorbed)" } }
    if ($line -match 'superseded-by-design')    { return [PSCustomObject]@{ Class = 'superseded-by-design'; Label = 'superseded-by-design (Wave 7)' } }
    if ($line -match 'still-valid-fix-now')     { return [PSCustomObject]@{ Class = 'still-valid-fix-now'; Label = 'still-valid (security-defect override)' } }
    if ($line -match '\borthogonal\b')          { return [PSCustomObject]@{ Class = 'orthogonal'; Label = 'orthogonal (safe)' } }
    if ($line -match 'unclassified')            { return [PSCustomObject]@{ Class = 'unclassified'; Label = 'unclear (C8 deferred or audit gap)' } }
    return [PSCustomObject]@{ Class = 'n/a'; Label = 'n/a (unknown label)' }
}
```

> **Snapshot drift note.** The disposition is a snapshot — its `ece470da` pin is the durable classification; the row-level `State @ read` column drifts. When the orchestrator fetches the document, the file itself lives on a wave-planning branch (`docs/rdd-waveN-freeze-and-disposition` or `docs/rdd-waveN-amended-design`); the *highest-numbered* waveN branch is the canonical snapshot. If the orchestrator finds a higher-numbered wave branch on a subsequent run, it MUST re-fetch and re-grep; older wave branches are kept for archaeology, not for classification.

> **Critical gotcha:** event name is `cross-referenced` (hyphen), NOT `cross_reference` (underscore). Verified against #1209 in gentle-ai (closed PR #1365 cross-referenced).

### Sort order

`priority:high` → `priority:medium` → `priority:low` → `(none)`. Within band, oldest `createdAt` first. If multiple `priority:*` labels are present (shouldn't be, but possible), the first one wins.

### Output format — TABLE grouped by priority band, plus a "Skipped" section

For each band, present its own table. **The `Disposition` column is mandatory** for every row — it tells the contributor at a glance whether the issue is safe to attack, already absorbed into a wave, or carries a special carve-out.

`priority:high` band (typically 2–10 rows): full detail.

| # | Type | Title | Author | Created | Disposition | URL |
|---|---|---|---|---|---|---|
| #1462 | bug | retire invalid legacy-v1 authority through audited lifecycle | Alan-TheGentleman | 2026-07-19 | WAVE 7 (superseded-by-design) | link |

`(none)` band (typically 40+ rows): condensed. Keep the Disposition column even when condensed — it is the highest-signal column for the pick decision.

| # | Title | Author | Created | Disposition |
|---|---|---|---|---|
| #273 | Suport for Copilot CLI | henri318 | 2026-04-10 | n/a (post-snapshot or non-RDD) |
| #1471 | fix(review): support lifecycle-safe zero-diff tracker branch bootstrap | ardelperal | 2026-08-04 | unclear (C8 deferred — safe to attack, but wave may reclassify) |

`Disposition` column values: `WAVE 1..5 (absorbed)` = skip, listed in Skipped section. `superseded-by-design (Wave 7)` = skip, listed in Skipped section. `orthogonal (safe)` = attack freely. `still-valid (security-defect override)` = attackable only after reproduction on current main. `unclear (C8 deferred — safe to attack, but wave may reclassify)` = attackable, but flag in the PR description that Alan may reclassify. `n/a (post-snapshot or non-RDD)` = attackable, no wave-absorbsion risk from this document.

Cap each band at 25 rows; if more, append `... and N more (oldest first, full list available)`.

After the tables, append a **`Skipped (duplicates, already resolved, or wave-disposition)`** section. The wave-disposition rows are the new Layer 4 contribution:

| # | Reason | Linked PR / Cross-ref | Notes |
|---|---|---|---|
| #1006 | fix-merged in PR #1001 | PR #1001 (closed/merged) | Skill-registry symlink scan already shipped in v1.43.3 |
| #1019 | cross-repo-fix in PR #627 | engram repo | MCP serverInstructions fix landed in engram |
| #1379 | wave-disposition-superseded | — | RDD Wave 7 RETIRE; legacy mutation lifecycle deleted, not fixed |
| #1222 | wave-disposition-2 | — | absorbed-into-wave-2 (Classified authority disposition); will close when wave 2 ships exit evidence |

If the user says "actually do this one", the orchestrator proceeds anyway, but must surface the wave-absorbsion risk explicitly in the hand-back: *"this issue is `absorbed-into-wave-N` per `rdd-backlog-disposition.md`; if Alan's wave ships before your PR, your work closes as outdated."*

After the skipped section, append a 3–5-item "cosas para mirar antes de elegir" only when context matters: owner-authored, Windows-only test path, touches release pipeline, recent cluster by same author, etc.

---

## Action — Implement `#N`

Triggered when the contributor says "voy con `#N`" / "ataco `#N`" / "elijo `#N`". Delegate; do not write code inline.

### Steps

1. **Read the issue whole.**

   ```bash
   gh issue view <N> --repo "$REPO" --json body,labels,comments,closingIssuesReferences,timelineItems,assignees
   ```

   Look for sub-issues, prior PRs referenced, and any comment that already narrows scope. If the issue is ambiguous, stop and ask the contributor one targeted question — never invent scope.

2. **Branch from `origin/main`, not local main.**

   ```bash
   git -C "C:\Proyectos\<repo>" fetch origin main
   git -C "C:\Proyectos\<repo>" checkout -b <type>/<slug> origin/main
   ```

   Branch regex (gentle-ai CI-enforced): `^(feat|fix|chore|docs|style|refactor|perf|test|build|ci|revert)/[a-z0-9._-]+$`. One scope, no comma, lowercase.

3. **Load companion skills** based on size:
   - Small (≤400 lines forecast): `gentle-ai-branch-pr` + `gentle-ai-collab-perfect`.
   - Large: also `gentle-ai-chained-pr`. Pick Stacked vs Feature Branch Chain **with** the contributor. Cross-fork base refs are NOT supported on GitHub; without maintainer cooperation on pushing slice branches upstream, Stacked to main is the only path.

4. **Delegate the code work** to the SDD chain. For small fixes, `sdd-apply` directly with a re-stated task; for non-trivial changes, `sdd-onboard` first. **Never write code inline in the orchestrator.**

5. **Tests + verification.** Honest PR body means actually running `go test` (or the project's test command) and naming pre-existing failures with the `git stash` baseline. "All tests pass" without that context is dishonest.

6. **PR body** per `.github/PULL_REQUEST_TEMPLATE.md`: `## 🔗 Linked Issue` with `Closes/Fixes/Resolves #N`, `## 🏷️ PR Type`, `## 📝 Summary`, `## 📂 Changes` (line counts from API), `## 🧪 Test Plan`, `## ✅ Contributor Checklist`, `## 💬 Notes for Reviewers`.

7. **`gh pr create`** targeting `Gentleman-Programming/<repo>:main`. The contributor cannot apply `type:*` or `size:exception` labels — `gh pr edit --add-label` returns 403. Move maintainer-only items to `## Pending maintainer actions` in the body.

8. **Watch CI to completion.** After opening the PR, **do not consider the work done until every required check is green**. Use `gh pr checks <N> --repo <repo>` to see status. The two categories of red checks to distinguish:

   - **Red that's the contributor's fault** (test breaks introduced by the diff, build failed, vet issue): **fix it before handing back**. Add a follow-up commit, force-push (`git push -f`), wait for CI again. **Never** hand back a PR with this kind of red.
   - **Red that's a maintainer-only action** (e.g., `Check PR Has type:* Label` failing because the label is not yet applied; `Check PR Cognitive Load` failing while waiting for `size:exception`): acceptable IF AND ONLY IF it is explicitly documented in the PR body's `## Pending maintainer actions` section AND the orchestrator surfaces it on Output 1 next time it's asked.

   **Recipe** to watch:
   ```bash
   gh pr checks <N> --repo <repo>        # status of each check
   gh pr view <N> --repo <repo> --json statusCheckRollup,mergeable
   ```
   If any check is FAILURE and not in the documented exceptions list, fetch logs (`gh run view --log-failed`), identify the cause, fix it, and force-push.

9. **Hand back** the PR URL, the diff size from API, the `Pending maintainer actions` section, AND the final CI status (all green or only documented exceptions). Do not solicit feedback — the contributor will tell you when to re-review.

### What this skill does NOT cover

- The PR body itself — load `gentle-ai-collab-perfect`.
- The branch create + PR commands — load `gentle-ai-branch-pr`.
- The code — delegate. Never write inline.
- **The CI green-gate** — that's this skill's Hard Rule #8. Do not skip.

---

## Hard rules

1. **Two outputs and one action, not a state machine.** Each output is independent; each is invoked by its own trigger phrase. Do not "step through" them.
2. **The contributor filter is strict.** For Output 1: `--author @me` everywhere. For git branches: include only branches where the contributor is the most recent author of any commit (the `Select-String 'ardelperal|aroman|aroman@'` recipe). Do not collapse "the repo is dirty" with "I have work pending".
3. **Repo first, always.** If the contributor did not name a repo in the trigger, infer from `cwd` and remotes. If still ambiguous, ask with the `question` tool — present the two repos as options, not as plain text.
4. **Verified data only.** Every status cell comes from a real `gh`, `git`, or filesystem query. If a query fails, mark the row's cell as `err`; never infer. **A tool that returns empty is not the same as a tool that returns "none"** — check exit codes before reporting an absence. A failed `git fetch`, a missing remote, or a stale cached ref can all produce confident-looking empty output. This applies to `git rev-list` in particular: measure drift against a ref you have just verified exists (`upstream/main` in the gentle-ai checkout), never against a ref that may be a fossil.
5. **Output 2 lists issues the contributor is NOT in flight on.** That means filter by `no cross-referenced PR in timeline`, NOT by "no PR mention in `closedByPullRequestsReferences`" (the latter misses cross-fork).
6. **No state mutation without consent.** Output 1 and Output 2 are read-only. The action mutates only after the contributor has named the issue, the branch, and said go.
7. **Tables, not bullets.** Both outputs are markdown tables with one row per item. Bullet lists make scanning impossible above 20 rows.
8. **Source-of-truth files are read at the start of every implementation, not cached.** Re-read `CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`, and `.github/ISSUE_TEMPLATE/*.yml` from the active repo before opening any PR. Rules evolve.
9. **"mergeable" by API ≠ ready to merge.** GitHub's `gh pr view --json mergeable` returns `MERGEABLE` whenever the PR has no merge conflict and is not in draft — it does **not** reflect required-check state. In a branch-protection-required repo (gentle-ai, engram), any required check failing (including `Check PR Has type:* Label`, `Check PR Cognitive Load`, etc.) **disables the merge button** even when API reports `mergeable: MERGEABLE`. Treat `mergeable: MERGEABLE` as necessary-but-not-sufficient. The user-facing truth is "**all required checks are green**, or the only reds are documented maintainer-only actions that Alan must apply (and the contributor says so explicitly in the hand-back)". Failures introduced by the diff (test/lint/vet/build regression, bad scope, missing label) MUST be fixed in a follow-up commit BEFORE handing back. The CI green-state is the hard exit gate; do not hand back a PR whose only path to merge is "Alan needs to do something" without saying so explicitly.
10. **Maintainer-race is a first-class signal, not a footnote.** For every open contributor PR, scan the maintainer universe for later MERGED PRs (same linked issue / shared root-cause / shared area) and surface the classification + exact creation date in the `Later maintainer PR / decision` column. Closed-unmerged and OPEN maintainer PRs are `inflight`, NOT `superseded`. File overlap alone never implies obsolescence. API failure surfaces as `err/unknown`; never silently report `none`.
11. **Race checks are point-in-time snapshots; re-run them between every SDD phase transition, not only at the apply gate.** The initial race check at issue-pick time can pass while a maintainer opens, reviews, and merges a competing fix during the SDD planning window (propose → spec → design → tasks). Between every phase transition the orchestrator fetches `--state all` for the same-issue universe and cross-checks any reported PR state with `gh pr view N --json state,mergedAt`. A maintainer PR that ships during the window reclassifies the change as `superseded/foreign-fix`; the plan, spec, and design are archived for reference, the fork fast-forwards, and no contributor code is authored. Sub-agent state claims about external PRs (open/merged/closed) are always cross-checked by the orchestrator before being acted upon — sub-agents have no persistent memory and may hallucinate state at the phase-result gate.
12. **Pre-push race gate is a hard block, not advisory.** Before any `git push` of a contributor branch, run `scripts/pre-push-race-check.ps1` from the worktree. If a `priority-risk` rival exists (same linked issue, earlier `createdAt`, OPEN state in the upstream repo) the script exits `1` and blocks the push. Bypass requires `-Force` and writes a `pre-push-race-bypass.log` line to stderr explaining why. The script auto-detects linked issues from (in priority order) (a) the existing PR's `closingIssuesReferences`, (b) `Closes #N` / `Fixes #N` / `Resolves #N` keywords in the current branch's HEAD~5 commit messages, (c) the issue number embedded in the branch name (regex `(?:fix|feat|chore|docs|refactor|perf|test|build|ci|revert)/(\d+)-`). The contributor wires this as a git `pre-push` hook (one-time per worktree, see `scripts/install-pre-push-hook.ps1`). Worked losses that would have been blocked: **#2825** vs #2800 (overlay JSONs, +4h), **#2862** vs #2800 (profiles.go, +4h), **#2924** vs #2878 (sdd_verify_validate + verification, +16h).
13. **RDD wave-disposition is a first-class filter, not a footnote.** Alan maintains `docs/architecture/rdd-backlog-disposition.md` (lives in branch `docs/rdd-wave0-freeze-and-disposition` on upstream, snapshot at `ece470da`) that classifies every RDD-related issue into one of five labels: `absorbed-into-wave-1..5`, `superseded-by-design` (wave-7), `still-valid-fix-now` (security-defect override), `orthogonal` (portability/diagnostics), or `unclassified — needs triage`. **Output 2 must grep every `status:approved` candidate against this file BEFORE recommending it**. Behavior:
    - **`absorbed-into-wave-N` or `superseded-by-design`** → skip with reason `wave-disposition-N` (or `superseded-by-design`); the issue will close when wave N ships exit evidence per the document's own `Closure audit protocol`. Do NOT attack it.
    - **`orthogonal`** → candidate with disposition column `orthogonal`; safe to attack (RDD wave scope won't subsume it).
    - **`still-valid-fix-now`** → candidate with disposition column `still-valid (security)`; requires reproduction on current main before applying per the disposition's security-defect criteria.
    - **`unclassified — needs triage`** → candidate with disposition column `unclear (C8 deferred)` or similar; safe to attack but expect Alan may classify it into a future wave.
    - **Not in the disposition** → candidate with disposition column `n/a (post-2026-08-02 or non-RDD)`; safe to attack, but verify the snapshot date hasn't drifted into a new wave-planning branch. Wave-planning branches follow the pattern `docs/rdd-wave{N}-{topic}`; the **highest-numbered** wave branch on upstream is the canonical snapshot.
    The same filter applies to Output 1 maintainer-race: when a rival PR closes an issue classified `absorbed-into-wave-N`, the bucket becomes `superseded/wave-N` instead of `superseded/full`. The filter also applies to the Pre-apply and Inter-phase race rechecks — between every SDD phase transition, grep the linked issue against the highest-numbered wave-disposition branch; a newly-classified wave-absorbsion flips the plan to `superseded/wave-N`. Companion planning docs live in `docs/architecture/rdd-ownership-inventory.md`, `rdd-freeze-expansion-policy.md`, `rdd-root-simplification-design.md`, and `rdd-shadow-evaluation.md`.

---

## State persistence — do not re-paste the same answer

The contributor has explicitly asked the orchestrator to **maintain a persistent state mirror** of Alan's PR activity, so that re-asking the same question ("how's Alan?", "qué mergeó", "ha adelantado algo", "mira si me ha mergeado algo") does not produce a duplicated full table. The state file lives at:

```text
C:\Users\adm1\.opencode\skills\collab-with-alan\state.md
```

### Trigger phrases for state recall

Any of these phrases means "fetch current state and diff vs `state.md`":

- "cómo va mi colaboración", "status de mis PRs", "qué dijo Alan", "ya terminó"
- "ha adelantado algo", "me ha mergeado algo", "mira si Alan hizo algo"
- "qué mergeó hoy/ayer", "qué cambió"
- "estado de las PRs", "status Alan"

### Workflow — read first, fetch second, report only the diff

1. **Read** `state.md` and parse the `_Last fetched:` timestamp at the top.
2. **Fetch** current GitHub state via `gh pr list --author ardelperal --state merged --limit 10` and `gh pr list --author ardelperal --state open --limit 30`. Plus per-PR comments and review decisions if needed.
3. **Diff**:
   - **Merged**: any PR in the new merged list not in `state.md`'s merged table → that's a new merge since last fetch.
   - **Open**: any change in `headRefOid`, `reviewDecision`, or comment author (Alan) → that's a new state.
   - **No changes**: state hasn't moved.
4. **Report**:
   - If no changes: respond with a single line like "Sin cambios desde {_Last fetched_}. Resumen en `state.md`." — do not paste the table.
   - If changes: report only the diff (new merges, new reviews, status flips), then update `state.md` with the new state and bump `_Last fetched:`.
   - **Always** update `state.md` to mirror live state, even if nothing changed (refresh `_Last fetched:`). This is the only way the next ask can be a no-op.
5. **Never** paste the full table again after the first fetch in a session — the contributor has already seen it; they want the delta.

### What "no changes" looks like

The user-facing reply should be terse and reference the file:

```text
Sin cambios desde {timestamp}. {N} PRs abiertas esperando label, {M} mergeadas en los últimos 30 días. Ver `state.md` para el detalle.
```

If the user explicitly asks for the full table despite no changes, then paste it — but mark it as "from `state.md`, no live fetch needed".

### Updates that MUST be reflected in `state.md`

- New merge (added to merged table with timestamp + merger).
- New PR opened by ardelperal (added to appropriate open bucket).
- New `CHANGES_REQUESTED` or other review decision from Alan (added to "waiting on re-review" bucket).
- New comment from Alan (timestamp updated in "Alan's activity" section).
- PRs closed-not-merged (added to a new "closed-not-merged" section in `state.md`).
- New pre-existing CI flake observed (appended to "Cross-cutting notes" with the ratchet pattern reference).

### What goes in `state.md`

The schema (current canonical version, see the file for the live example):

```markdown
# Collab State with Alan — Gentle-AI

_Last fetched: <ISO timestamp>_
_Last user ask: <ISO timestamp>_

## Merged PRs (last 30 days)
[table: #, Title, Merged at, Merged by]

## Open PRs (waiting on maintainer labels — only blocker is `type:*`)
[table: #, Branch, Title, Needs]

## Open PRs (waiting on `size:exception` + label)
[table: #, Branch, Title, Needs]

## Open PRs (waiting on Alan re-review — contributor work done)
[table: #, Branch, Title, Why waiting]

## Open PRs (older, no recent activity)
[table: #, Branch, Title, Last activity]

## Alan's activity (last seen, last action)
- Last merge: <ISO>
- Last review/comment: <ISO>
- No activity from Alan since <ISO> on PRs

## Pending maintainer actions (Alan-only)
[bullets of all pending labels and size exceptions]

## Cross-cutting notes
- pre-existing CI flakes, ritmo, slice strategy, skill collaborator references
```

### Anti-patterns

| Don't | Why |
|---|---|
| Paste the full table every time the user asks | The contributor has the state file; they want deltas |
| Skip reading `state.md` and re-fetch from scratch | Wastes tokens AND may produce stale data (live GitHub can lag `state.md` if a fetch was interrupted) |
| Update `_Last fetched:` without diffing first | The file becomes a snapshot rather than a record of changes; the "no changes" reply becomes ambiguous |
| Mutate `state.md` from anything but the orchestrator | The contributor's edits are a separate signal; if they edit, ask before overwriting |
| Forget to update `state.md` after reporting changes | Next ask will re-report the same diff and look like a bug |

---

## Pre-flight checklist before opening a PR (lessons learned 2026-07)

Five patterns from the last batch of contributor PRs (#1433, #1481, #1608, #1132-#1134). Run this checklist **before** opening a PR — every item corresponds to a real review red that cost round-trips. Full detail, including the worked counter-example for pattern 1, lives in `C:\Proyectos\gentle-ai\docs\contributing\lessons-learned.md` (load it on demand when planning a state-machine, routing, or refactor PR).

| # | Pattern (PR) | One-line action |
|---|---|---|
| 1 | State machines with unverified exits (#1433) | Before wiring routing, grep the path the CLI actually runs and confirm every exit has a next-state in `legalStateTransition` plus a receipt path. Tests that mock the path do NOT prove the path. |
| 2 | Reimplementing stdlib / existing helpers (#1481, #1433) | Before writing a hex / encoding / hashing / identity helper, `grep -r` the repo for an equivalent. There are already three different sha256-identity checks in this tree; do not be the fourth. |
| 3 | Docstring coverage < 80% on new exports (#1608, #1134) | Treat docstrings on new exports as a linter rule, not a nice-to-have — CodeRabbit pre-merge check is the gate. |
| 4 | Slice body claims more than the slice delivers (#1481) | In every slice PR body, declare: "this slice does X; slice B in PR #N wires Y; both required for #M". If Alan cannot see slice B in his radar, he will ask for it in review. |
| 5 | Stacked-to-main chains hide slice boundaries (#1132-#1134) | In the PR body, label which commits belong to this slice vs. prior slices. Cross-fork `base=main` limitation means every stacked PR diff contains the prior slices' commits. |

> **State machines and routing are the highest-risk surface.** A missed exit can deadlock an entire lineage silently — no failure surfaces in tests that do not exercise the real CLI path. If your PR touches state transitions, routing, or anything that mutates the state machine or audit journal, treat it as the deepest review item in the PR. Re-run the verification with the real binary, not just unit tests, and re-state in the PR body exactly which exit lands in which state and which state emits the receipt.

---

## Repo supplements

### `Gentleman-Programming/gentle-ai`

- Issue-first: no PR opens without `status:approved` from a maintainer. Contributor cannot apply the label (GraphQL 403 `AddLabelsToLabelable`).
- Linked issue syntax in PR body: `Closes / Fixes / Resolves #N`. `Refs #N` does NOT count.
- Exactly one `type:*` label per PR (`bug`, `feature`, `docs`, `refactor`, `chore`, `breaking-change`). Zero or two fails `Check PR Has type:* Label`.
- 400-line budget per PR. Overflow → `size:exception` from a maintainer.
- Branch regex: `^(feat|fix|chore|docs|style|refactor|perf|test|build|ci|revert)/[a-z0-9._-]+$`.
- No `Co-Authored-By` trailers in commits.
- Issue templates: `bug_report.yml`, `feature_request.yml`. Questions go to Discussions, not issues.

### `Gentleman-Programming/engram`

The companion rules skill for engram is not yet authored (in roadmap). Until it lands, treat engram with the gentle-ai rules above **plus**:

- Third template: `docs_improvement.yml`.
- Auto-labels on creation: `type:bug`, `type:feature`, `type:docs` are applied by templates — contributors do not need to fight for them.
- Extra labels: `effort:small|medium|large`; gentle-ai doesn't have these.
- Stale bot auto-closes after 30 days of inactivity. Exempt: `status:approved`, `status:in-progress`, `priority:high`, `priority:critical`.
- CODEOWNERS at the org level (`@Gentleman-Programming`). Sensitive paths: `internal/store/`, `internal/server/`, `cmd/`, `.github/`, `skills/`, `.goreleaser.yaml`, `go.mod`, `go.sum`.
- **No 400-line gate** in CI on engram — larger PRs land without `size:exception`.
- CONTRIBUTING.md does not enforce a branch-name regex — use gentle-ai's regex as a soft guideline.
- npm hygiene (`npq`, `.npmrc` with `ignore-scripts=true`, Snyk Advisor link) required only for `plugin/pi` and `plugin/obsidian`.

---

## Anti-patterns

| Don't | Why | Instead |
|---|---|---|
| Treat the outputs as steps in a state machine | The contributor wants per-trigger output, not a flow | Each trigger phrase calls its own output independently |
| Filter "pending" by "the repo is dirty" or "main is behind upstream" | Those are upstream concerns, not the contributor's pending work | Filter by `--author @me` for `gh`, by author `ardelperal` for git |
| Run `gh issue list` once and infer "no PR" | Closed-by-PR is not surfaced by `gh issue list`; cross-fork refs hide in the timeline | Always do the timeline cross-ref check (see Output 2 recipe) |
| Auto-open an issue from Output 2 | The contributor picks | Wait for explicit "voy con `#N`" |
| Treat `status:approved` + open issue as "ready to PR" | A PR could already be in flight elsewhere | Verify via timeline cross-ref before recommending |
| Concatenate engram and gentle-ai into one list | Different rules | One table per repo |
| Use `--author @me --state all` | gh CLI rejects this argument | Run `open`, `merged`, `closed` separately |
| Use `@{u}` in PowerShell `git` calls | Parser error: `Missing '=' operator after key` | Use `'origin/main...HEAD'` (three-dot) |
| Write PR body inline here | That's `gentle-ai-collab-perfect`'s scope | Hand off to that skill |
| Write code inline in the orchestrator | Bypasses the SDD chain | Delegate to `sdd-apply` |
| Hand back a PR with a red CI check you caused | The contributor can't tell the difference between your fault and a maintainer-action wait; "all done" lies | Watch CI to green. If it's a maintainer-only fail (label/cognitive-load waiting for size:exception), document in `## Pending maintainer actions`. If it's your fault (test/lint/vet regression), commit the fix and force-push before considering the work done. |
| Skip CI verification because "I'll do it later" | You will forget, and the contributor picks it up as a broken state | Run `gh pr checks <N> --repo <repo>` after `gh pr create`; do not hand back until green or only documented exceptions remain |
| Skip the maintainer-race check on open contributor PRs | A maintainer-shipped competitor can flip the recommended action from `keep` to `close` without any new review comment | Always fetch the maintainer universe once per Output 1 run and classify every later maintainer PR before recommending an action |
| Infer obsolescence from shared files or file count alone | Same area does NOT imply same root cause; two PRs can touch the same files for unrelated symptoms | Always classify as `overlap/area → keep`; require shared linked issue (in both `closingIssuesReferences`) OR ≥ 2 shared meaningful title tokens for any supersession claim |
| Treat a closed-not-merged maintainer PR as a shipped fix | Closed-not-merged is NOT shipped — Alan may have abandoned that approach or replaced it with a narrower redesign | Classify as `inflight → inspect`; never close contributor PR on this signal alone |
| Skip maintainer PRs created BEFORE yours in the race scan | Same-issue rivals older than your PR win adjudication by open-time priority (precedent: #2198/#2184, #2596/#2601) | Scan same-issue signal in BOTH directions; classify earlier same-issue rivals as `priority-risk`, never silently skip |
| Report `closed sin merge (revisar closing comment)` without harvesting the reason | The closing critique is a free design review and often names the rival fix PR | Run the closing harvest: extract the closer + critique + same-issue follow-up PR into `state.md` |
| Start apply on a planned issue without re-checking the same-issue universe | Planning windows are blind spots: rivals can open PRs between pick and apply | Run the pre-apply race recheck before any implementation step |
| Nudge a sibling-watched PR after the sibling shipped without re-verifying | The shipped sibling fix may have absorbed your issue | Re-verify your issue on current main first; close as fixed-by-sibling if it no longer reproduces |
| Treat CI check-count drift as a state change | Release waves add/remove checks; totals drift without meaning | Track pass/fail semantics (the failing checks), not absolute count of checks |
| Re-run the race check only before `sdd-apply` | Maintainers can ship during the planning window; the work written by `sdd-propose`/`sdd-spec`/`sdd-design` can be obsolete before apply ever runs | Re-run the same-issue scan between EVERY SDD phase transition (propose→spec, spec→design, design→tasks, tasks→apply); classify a maintainer PR that ships mid-planning as `superseded/foreign-fix` |
| Trust sub-agent state claims about external PRs (open/merged/closed) without cross-check | Sub-agents have no persistent memory and may hallucinate state at the phase-result gate | Cross-check every reported PR state with `gh pr view N --json state,mergedAt` before acting on it; the orchestrator's gatekeeper is the authoritative reader of GitHub state |
| Treat a closed-merged maintainer PR as "still in flight" and continue planning | The work is already shipped; the contributor's plan is now obsolete; duplicate code wastes reviewer attention and risks conflict | Reclassify the change as `superseded/foreign-fix`; archive the plan, spec, and design for reference; fast-forward the fork to the upstream merge commit; do not author duplicate code |
| Pick a `status:approved` issue without grepping `rdd-backlog-disposition.md` | The issue may be `absorbed-into-wave-N` (will close when wave N ships) or `superseded-by-design` (will be deleted, not fixed). Investing in either is wasted work the moment Alan's wave merges | Always run the Layer 4 wave-disposition check (Hard Rule #13) before recommending a candidate. The Disposition column in the Output 2 table is the gate, not a footnote |
| Skip the `Disposition` column in the Output 2 table to save width | The contributor cannot tell `WAVE 2 (absorbed)` from `orthogonal (safe)` without that column; they pick the wrong issue and lose hours | Disposition column is mandatory in every candidate row per Hard Rule #13. Cap rows, not columns |
| Trust a stale `rdd-backlog-disposition.md` snapshot | The disposition is a snapshot. A new wave-planning branch (`docs/rdd-waveN+1-...`) on upstream supersedes the previous one. Fetching the wrong branch returns stale classifications | Always resolve the **highest-numbered** `docs/rdd-waveN-freeze-and-disposition` branch on upstream. If the orchestrator fetched `wave0` yesterday and `wave1` exists today, the new fetch wins |
| Attack an issue classified `still-valid-fix-now` without reproducing on current main | The disposition's security-defect override requires reproduction proof before the fix is exempted; skipping it ships a fix for a defect that may no longer exist | Before applying, write a minimal repro on `upstream/main`; if the defect no longer reproduces, surface it on the issue and close as outdated instead of pushing code |
| Skip the wave-disposition check because "this is a small fix" | Wave-absorbsion does not scale with diff size. A 30-line fix on a wave-3 issue still closes as outdated when wave 3 ships exit evidence | The check runs once per candidate regardless of size; it is cheaper than any size of wasted work |

---

## References

- `gentle-ai-collab-perfect/SKILL.md` — companion skill for PR body rules (gentle-ai).
- `gentle-ai-branch-pr/SKILL.md` — branch and PR mechanics.
- `gentle-ai-issue-creation/SKILL.md` — issue creation mechanics.
- `gentle-ai-chained-pr/SKILL.md` — chained/stacked PR strategy.
- `sdd-onboard/SKILL.md` — canonical SDD life cycle.
- `sdd-apply/SKILL.md` — code-work delegation.
- `CONTRIBUTING.md` and `.github/PULL_REQUEST_TEMPLATE.md` in the active repo — read at the start of every contribution.
- `openspec/changes/` in the active repo — SDD change source of truth.
