#!/usr/bin/env pwsh
# collab-with-alan / Output 2: Approved-no-PR list with 3-layer duplicate detection.
# v1.3.0 — Layer 4 added: RDD wave-disposition check (Hard Rule #13).
#         Resolves the canonical snapshot branch on upstream
#         (`docs/rdd-waveN-freeze-and-disposition` with highest N), greps
#         `docs/architecture/rdd-backlog-disposition.md` for #N, and either
#         skips (`absorbed-into-wave-N` / `superseded-by-design`) or attaches
#         a Disposition label to the candidate row. Disposition column is
#         mandatory in every candidate row; `wave-disposition-N` and
#         `wave-disposition-superseded` reasons extend the Skipped section.
# v1.2.4 — Layer 1 now uses `closedByPullRequestsReferences` (the correct field;
#         `linkedPullRequests` was a stale name that GitHub CLI silently rejects,
#         causing every in-flight PR detection to fail silently). Per-PR state
#         and merged_at are fetched via `gh pr view` since the issue-level
#         reference does not carry them. Layer 1b (timeline cross-ref) still
#         works as before. Layer 3 regex no longer matches the negative phrase
#         "is not a duplicate" from the bug-report pre-flight checklist.
#         Output 2 also runs the full candidate-vs-skipped split inside the
#         parallel block to avoid a hashtable key-type mismatch (Int32 literals
#         vs Int64 hashtable keys) that previously caused the Skipped section
#         to silently disappear.
# v1.2.3 — duplicate detection (linkedPullRequests + cross-repo + textual)
#         + skipped-section output for transparency.
#         + in-flight PR detection (linkedPullRequests or cross-ref to an
#           OPEN PR counts as "already being attacked" and is skipped).

param(
    [ValidateSet('auto', 'gentle-ai', 'engram')]
    [string]$Repo = 'auto'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'SilentlyContinue'

$owner = 'Gentleman-Programming'
$priorityOrder = @{ 'priority:high' = 0; 'priority:medium' = 1; 'priority:low' = 2; '(none)' = 3 }
$orgRepos = @('gentle-ai', 'engram')

# ---- detect repo from cwd ----
if ($Repo -eq 'auto') {
    $gitRoot = git rev-parse --show-toplevel 2>$null
    $probed = @()
    if ($gitRoot) {
        # Scan EVERY remote, not just `origin` — see output1_my_work.ps1 for the
        # rationale (fork-only clones and removed vestigial remotes both break
        # origin-only detection).
        $names = @(git -C $gitRoot remote 2>$null)
        $ordered = @('upstream', 'origin') + @($names | Where-Object { $_ -ne 'upstream' -and $_ -ne 'origin' })
        foreach ($n in $ordered) {
            if ($names -notcontains $n) { continue }
            $url = git -C $gitRoot config --get "remote.$n.url" 2>$null
            if (-not $url) { continue }
            $probed += "${n}=${url}"
            if ($url -match '[/:][^/:]+/(gentle-ai|engram)(\.git)?/?$') { $Repo = $Matches[1]; break }
        }
    }
    if ($Repo -eq 'auto') {
        # Fail LOUD and non-zero — never let detection failure masquerade as
        # an empty result set.
        $seen = if ($probed.Count) { $probed -join ', ' } else { '(ninguno)' }
        [Console]::Error.WriteLine("[output2_approved_list] no pude detectar el repo desde cwd '$gitRoot'. Remotes probados: $seen. Pasá -Repo gentle-ai|engram explícito.")
        exit 2
    }
}

Write-Host "##### OUTPUT 2: approved list — repo=$Repo #####"
Write-Host ""

# ---- RDD wave-disposition pre-pass (Layer 4 / Hard Rule #13) ----
# This MUST run outside the parallel block, because PowerShell runspaces
# spawned by ForEach-Object -Parallel do not see the parent script's
# variables or functions. We resolve the canonical wave-disposition branch
# here, fetch the document, and build a hashtable `number → disposition`
# that the parallel block consumes via $using:.
$dispositionMap = @{}
$canonicalWaveBranch = $null
$remote = 'upstream'
$branchesRaw = git ls-remote $remote 'refs/heads/docs/rdd-wave*-freeze-and-disposition' 2>$null
if ($branchesRaw) {
    $canonicalWaveBranch = $branchesRaw |
        ForEach-Object { ($_ -split '\s+')[1] } |
        Sort-Object @{ Expression = { [regex]::Match($_, 'wave(\d+)').Groups[1].Value -as [int] } } -Descending |
        Select-Object -First 1
}
$docText = ''
if ($canonicalWaveBranch) {
    $branchName = $canonicalWaveBranch -replace '^refs/heads/', ''
    git fetch $remote $branchName 2>$null | Out-Null
    $docText = git show "$remote/$branchName`:docs/architecture/rdd-backlog-disposition.md" 2>$null
}
if ($docText) {
    foreach ($line in ($docText -split "`n")) {
        if ($line -notmatch 'gentle-ai#(\d+)\b') { continue }
        $n = [int]$Matches[1]
        if ($line -match 'absorbed-into-wave-(\d+)') { $cls = "absorbed-into-wave-$($Matches[1])"; $lbl = "WAVE $($Matches[1]) (absorbed)" }
        elseif ($line -match 'superseded-by-design') { $cls = 'superseded-by-design'; $lbl = 'superseded-by-design (Wave 7)' }
        elseif ($line -match 'still-valid-fix-now')  { $cls = 'still-valid-fix-now';  $lbl = 'still-valid (security-defect override)' }
        elseif ($line -match '\borthogonal\b')       { $cls = 'orthogonal';            $lbl = 'orthogonal (safe)' }
        elseif ($line -match 'unclassified')         { $cls = 'unclassified';          $lbl = 'unclear (C8 deferred or audit gap)' }
        else { continue }
        $dispositionMap[$n] = [PSCustomObject]@{ Class = $cls; Label = $lbl }
    }
}
Write-Host ("(wave-disposition snapshot: {0} entries, source: {1})" -f $dispositionMap.Count, $(if ($canonicalWaveBranch) { $canonicalWaveBranch } else { '(none)' }))
Write-Host ""

# Paso 1: lista plana
$listRaw = gh issue list --repo "$owner/$Repo" --state open --label "status:approved" --limit 200 --json number,title,labels,createdAt,author,url,body 2>$null
if (-not $listRaw) { exit 0 }
$list = $listRaw | ConvertFrom-Json

# Paso 2 + 3: duplicate detection + candidate/skipped split inside one parallel block.
# Each iteration emits a single PSCustomObject with the full classification, so
# the post-loop doesn't need to do a hashtable lookup (which had type-strictness
# problems: Int32 literals vs Int64 keys silently didn't match).
$entries = $list | ForEach-Object -Parallel {
    $n = $_
    $owner = $using:owner
    $repo = $using:Repo
    $orgRepos = $using:orgRepos
    $priorityOrder = $using:priorityOrder
    # $dispositionMap is the pre-pass hashtable from Layer 4 (number → {Class,Label}).
    # Lookup is O(1) inside the runspace; the alternative (per-issue git show) was
    # ~200× slower in the prototype run.
    $dispositionMap = $using:dispositionMap

    $skip = $null

    # Layer 1: closedByPullRequestsReferences (PRs that would close this issue
    # via Closes/Fixes/Resolves in the PR body). The reference carries number/url
    # but NOT state/merged_at, so we fetch each linked PR's status via `gh pr view`.
    $view = gh issue view $n.number --repo "$owner/$repo" --json closedByPullRequestsReferences,comments 2>$null | ConvertFrom-Json
    if ($view -and $view.closedByPullRequestsReferences) {
        foreach ($linked in $view.closedByPullRequestsReferences) {
            $prNum = $linked.number
            if (-not $prNum) { continue }
            $prView = gh pr view $prNum --repo "$owner/$repo" --json state,mergedAt 2>$null | ConvertFrom-Json
            if (-not $prView) { continue }
            if ($prView.mergedAt -or $prView.state -eq 'closed' -or $prView.state -eq 'merged') {
                $skip = [PSCustomObject]@{ Reason = 'fix-merged'; PR = $prNum }
                break
            } elseif ($prView.state -eq 'open') {
                $skip = [PSCustomObject]@{ Reason = 'in-flight-pr'; PR = $prNum }
                break
            }
        }
    }

    # Layer 1b: timeline cross-ref to a closed/merged PR or to an OPEN PR
    if (-not $skip) {
        $events = gh api "repos/$owner/$repo/issues/$($n.number)/timeline?per_page=100" --paginate 2>$null | ConvertFrom-Json
        if ($events) {
            foreach ($e in $events) {
                if ($e.event -eq 'cross-referenced' -and $e.source -and $e.source.type -eq 'issue' -and $e.source.issue.pull_request) {
                    $pr = $e.source.issue.pull_request
                    if ($e.source.issue.state -eq 'closed' -or $pr.merged_at) {
                        $skip = [PSCustomObject]@{ Reason = 'cross-ref-closed'; PR = $e.source.issue.number }
                        break
                    } elseif ($e.source.issue.state -eq 'open') {
                        $skip = [PSCustomObject]@{ Reason = 'cross-ref-in-flight'; PR = $e.source.issue.number }
                        break
                    }
                }
            }
        }
    }

    # Layer 2: cross-repo search (when repo is the upstream orchestrator)
    if (-not $skip -and $repo -eq 'gentle-ai') {
        $otherRepo = $orgRepos | Where-Object { $_ -ne $repo } | Select-Object -First 1
        try {
            $search = gh search issues "owner:$owner $($n.number)" --state all --json number,title,state,repository --limit 30 2>$null | ConvertFrom-Json
            $cross = $search | Where-Object { $_.repository.nameWithOwner -eq "$owner/$otherRepo" -and $_.state -eq 'closed' }
            if ($cross) {
                $first = $cross | Select-Object -First 1
                $skip = [PSCustomObject]@{ Reason = "cross-repo-fix"; PR = $first.number; OtherRepo = $otherRepo }
            }
        } catch { }
    }

    # Layer 3: textual duplicate marker in body or comments
    # NB: the original regex matched the negative phrase "is not a duplicate"
    # in the bug-report pre-flight checklist, marking hundreds of legitimate
    # issues as duplicates. We now anchor with `(?:^|\s)` and require either
    # a "duplicate of #N" pattern or a definitive resolution phrase.
    if (-not $skip -and $view) {
        $commentText = if ($view.comments) { ($view.comments | ForEach-Object { $_.body }) -join "`n" } else { '' }
        $text = ($view.body ?? '') + "`n" + $commentText
        if ($text -match '(?im)(?:^|\s)(?:duplicate\s+of\s+#?\d+|dupe\s+of\s+#?\d+|already\s+(?:fixed|resolved|merged)\s+(?:in\s+)?#?\d+)') {
            $skip = [PSCustomObject]@{ Reason = 'text-dupe-marker' }
        }
    }

    # Layer 4: RDD wave-disposition check (Hard Rule #13).
    # Lookup in the pre-pass map. The map was built outside the parallel
    # block by reading `docs/architecture/rdd-backlog-disposition.md` from
    # the highest-numbered `docs/rdd-waveN-freeze-and-disposition` branch
    # on upstream. A missing entry means the issue is post-snapshot or
    # non-RDD (Label = "n/a ..."), which is NOT a skip reason.
    $dispositionEntry = $dispositionMap[[int]$n.number]
    $dispositionLabel = if ($dispositionEntry) { $dispositionEntry.Label } else { 'n/a (post-snapshot or non-RDD)' }
    if ($dispositionEntry) {
        if ($dispositionEntry.Class -match '^absorbed-into-wave-(\d+)$') {
            $skip = [PSCustomObject]@{ Reason = "wave-disposition-$($Matches[1])"; PR = $null }
        } elseif ($dispositionEntry.Class -eq 'superseded-by-design') {
            $skip = [PSCustomObject]@{ Reason = 'wave-disposition-superseded'; PR = $null }
        }
    }

    # Resolve priority from the issue's labels
    $priority = '(none)'
    foreach ($lab in $n.labels) {
        if ($lab.name -like 'priority:*') { $priority = $lab.name; break }
    }

    # Resolve type from the issue's labels
    $types = ''
    foreach ($lab in $n.labels) {
        if ($lab.name -like 'type:*') { $types = $lab.name }
    }

    $typeMark = if ($types) { " [$($types -replace '^type:','')]" } else { '' }

    if ($skip) {
        # Build the Skipped row directly here so the post-loop doesn't need
        # to do hashtable lookups (Int32 vs Int64 key-type strictness).
        [PSCustomObject]@{
            Kind        = 'skipped'
            Number      = $n.number
            Title       = $n.title
            Reason      = $skip.Reason
            PR          = $skip.PR
            OtherRepo   = $skip.OtherRepo
            Priority    = $priority
            Type        = $typeMark
            Author      = $n.author.login
            Created     = ([DateTime]$n.createdAt).ToString('yyyy-MM-dd')
            Disposition = $dispositionLabel
        }
    } else {
        [PSCustomObject]@{
            Kind        = 'candidate'
            Number      = $n.number
            Title       = $n.title
            Priority    = $priority
            Type        = $typeMark
            Author      = $n.author.login
            Created     = ([DateTime]$n.createdAt).ToString('yyyy-MM-dd')
            URL         = $n.url
            Disposition = $dispositionLabel
        }
    }
} -ThrottleLimit 12

# Paso 4: separar candidates vs skipped
$candidates = @()
$skipped = @()
foreach ($e in $entries) {
    if ($e.Kind -eq 'skipped') {
        $skipped += $e
    } else {
        $candidates += $e
    }
}

# Output principal: candidates. The Disposition column is mandatory per
# Hard Rule #13 — every candidate row tells the contributor at a glance
# whether the issue is safe to attack, already absorbed into a wave, or
# carries a special carve-out.
$sorted = $candidates | Sort-Object @{ Expression = { $priorityOrder[$_.Priority] } }, Created

foreach ($g in ($sorted | Group-Object Priority)) {
    Write-Host "  $($g.Name) ($($g.Count)):"
    $i = 0
    foreach ($r2 in $g.Group) {
        if ($i -ge 25) { Write-Host "    ... and $($g.Count - $i) more"; break }
        $disp = if ($r2.Disposition) { "  [Disp: $($r2.Disposition)]" } else { '' }
        Write-Host "    #$($r2.Number)$($r2.Type) $($r2.Title)  —  $($r2.Author)  $($r2.Created)$disp"
        $i++
    }
}
Write-Host ""

# Output Skipped: duplicates, ya resueltos, y wave-disposition (Hard Rule #13).
if ($skipped.Count -gt 0) {
    Write-Host "##### Skipped (duplicates, already resolved, or wave-disposition) #####"
    foreach ($s in ($skipped | Sort-Object Number)) {
        $extra = if ($s.PR) { " (linked PR #$($s.PR))" } elseif ($s.OtherRepo) { " (cross-repo: $($s.OtherRepo))" } else { '' }
        $disp = if ($s.Disposition) { "  [Disp: $($s.Disposition)]" } else { '' }
        Write-Host "  #$($s.Number) [$($s.Reason)]$extra  —  $($s.Title)$disp"
    }
    Write-Host ""
}
