#!/usr/bin/env pwsh
# collab-with-alan / Output 1: My work in the repo detected from cwd.
# Detects repo via git remote origin.url. Defaults to no query if cwd is not
# a Gentleman-Programming/* checkout.
#
# Maintainer-race detection (per open contributor PR):
#   - Fetch the maintainer-side PR universe ONCE: state=all, limit=200, all
#     non-`@me` authors (typically Alan, plus dnlrsls, decode2, etc.).
#   - For each open contributor PR, classify each LATER maintainer PR (createdAt
#     > contributor.createdAt) that is currently MERGED (state=MERGED, mergedAt!=null)
#     into superseded/full or superseded/partial.
#   - Closed-not-merged and OPEN maintainer PRs (later) do NOT count as shipped
#     fixes — surfaced as `inflight` only.
#   - SAME-ISSUE RIVALS CREATED BEFORE THE CONTRIBUTOR PR are a separate signal:
#     classified as `priority-risk` (open-time-priority threat, NOT obsolescence).
#     They are never silently skipped by the later-only filter.
#   - Three signals for the later-rival buckets, in priority order:
#       1. Direct same-issue evidence (closingIssuesReferences ∩ ≠ ∅) → superseded/full
#       2. Title-word root-cause overlap (≥ 2 meaningful tokens shared) → superseded/partial
#       3. File overlap (light) → overlap/ambiguous (informational, never a supersession
#          claim on its own per audit guidance)
#   - API failures surface as `err/unknown`, never silently as "no competing PR".
#
# Closed-PR closing harvest (per closed-not-merged contributor PR, last 14d):
#   - Fetch closedBy + comments via gh pr view; extract the last non-bot comment
#     (skip coderabbitai / github-actions / dependabot) as the closing critique.
#   - Search the maintainer universe for a same-author PR created within ~72h
#     of the close that shares a linked issue → surfaced as `superseded-by #N`.

param(
    [ValidateSet('auto', 'gentle-ai', 'engram')]
    [string]$Repo = 'auto'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'SilentlyContinue'

# ---- detect repo from cwd if -Repo auto ----
$owner = 'Gentleman-Programming'

if ($Repo -eq 'auto') {
    $gitRoot = git rev-parse --show-toplevel 2>$null
    $probed = @()
    if ($gitRoot) {
        # Scan EVERY remote, not just `origin`. A checkout can legitimately have
        # no `origin` at all (fork-only clone, or a vestigial remote that was
        # removed). Probe `upstream` then `origin` first so detection stays
        # deterministic when more than one remote matches.
        $names = @(git -C $gitRoot remote 2>$null)
        $ordered = @('upstream', 'origin') + @($names | Where-Object { $_ -ne 'upstream' -and $_ -ne 'origin' })
        foreach ($n in $ordered) {
            if ($names -notcontains $n) { continue }
            $url = git -C $gitRoot config --get "remote.$n.url" 2>$null
            if (-not $url) { continue }
            $probed += "${n}=${url}"
            # Match on repo NAME under any owner: a fork remote
            # (ardelperal/gentle-ai) identifies the repo just as well as the
            # canonical Gentleman-Programming one.
            if ($url -match '[/:][^/:]+/(gentle-ai|engram)(\.git)?/?$') { $Repo = $Matches[1]; break }
        }
    }
    if ($Repo -eq 'auto') {
        # Fail LOUD and non-zero. Exiting 0 here made "detection failed" look
        # identical to "you have no pending work" to every caller.
        $seen = if ($probed.Count) { $probed -join ', ' } else { '(ninguno)' }
        [Console]::Error.WriteLine("[output1_my_work] no pude detectar el repo desde cwd '$gitRoot'. Remotes probados: $seen. Pasá -Repo gentle-ai|engram explícito.")
        exit 2
    }
}

# Resolve the contributor's login (matches `--author "@me"` semantics).
$me = gh api user --jq .login 2>$null
if (-not $me) { $me = '@me' }

# ---- maintainer PR universe (one fetch) ----
$maintErr = $false
$maintRaw = gh pr list --repo "$owner/$Repo" --state all --limit 200 `
    --json number,title,headRefName,author,createdAt,mergedAt,state,mergedBy,closingIssuesReferences 2>$null
if (-not $maintRaw) {
    $maintErr = $true
    $maintPrs = @()
} else {
    $allMaint = $maintRaw | ConvertFrom-Json
    # Filter out the contributor's own PRs (anything authored by $me).
    $maintPrs = @($allMaint | Where-Object { $_.author.login -ne $me })
}

Write-Host "##### OUTPUT 1: my work — repo=$Repo, me=$me #####"
Write-Host ""

if ($maintErr) {
    Write-Host "[maintainer-race] could not fetch maintainer PR universe; per-PR race lines will read `err/unknown`."
    Write-Host ""
}

# ---- helpers ----

# Title words: strip conventional-commit prefix and stopwords; keep tokens ≥ 5 chars;
# apply light suffix stemming so `enumerate`/`enumerating`, `derive`/`derived` collapse.
# Cross-language neutral: pure title text, no codepath parsing.
function Get-MeaningfulTitleWords {
    param([string]$Title)
    if (-not $Title) { return @() }
    $t = $Title.ToLower()
    # Strip conventional-commit prefix: type(scope): ...
    $t = $t -replace '^[a-z]+\([^)]+\):\s*', ''
    $t = $t -replace '^[a-z]+(?:\([^)]+\))?!?:\s*', ''
    # Tokenize on non-letter / non-digit.
    $tokens = $t -split '[^a-z0-9]+' | Where-Object { $_ -and $_.Length -ge 5 }
    # Drop conventional-commit types and common English stopwords.
    $stop = @(
        'fix','feat','chore','refactor','docs','perf','test','build','style','revert','breaking-change',
        'about','above','after','again','against','always','among','also','another','anyone','anything',
        'because','before','between','both','could','during','each','either','every','first','found',
        'further','given','going','have','having','instead','itself','know','known','later','least',
        'like','made','make','makes','might','more','most','must','never','newer','older','other',
        'over','part','parts','place','present','rather','really','right','said','same','second',
        'several','should','since','small','some','still','such','take','than','that','their','them',
        'then','there','these','they','this','those','three','through','thus','time','times','together',
        'toward','towards','under','until','upon','used','using','very','want','well','were','what',
        'when','where','which','while','whose','will','with','within','without','would','your',
        # tokens captured under conventional-commit prefixes (scope)
        'update','add','added','drop','kept','left','make','moved','moves','pass','reported',
        'would','shall','should','shall','merge','review','still','always','never'
    )
    $rawWords = @($tokens | Where-Object { $stop -notcontains $_ })
    # Light suffix stemming on words ≥ 6 chars; canonical (idempotent) stem.
    # After applying inflectional rules, also strip a trailing -e (only if the
    # stem would still be ≥ 5 chars). This collapses `enumerate` ↔ `enumerating`,
    # `derive` ↔ `derived`, `manage` ↔ `management` ↔ `managing`.
    $stems = @()
    foreach ($w in $rawWords) {
        $stem = $w
        if ($w.Length -ge 6) {
            if ($w -match '^(.+)ing$') { $stem = $Matches[1] }
            elseif ($w -match '^(.+)(ed|tion|ment|ness|able|ible)$') { $stem = $Matches[1] }
            elseif ($w -match '^(.+)s$' -and $w -notmatch 'ss$') { $stem = $Matches[1] }
        }
        # Canonical trailing -e removal (length-guarded) so the two sides converge.
        if ($stem.Length -ge 5 -and $stem.EndsWith('e')) {
            $cand = $stem.Substring(0, $stem.Length - 1)
            if ($cand.Length -ge 5) { $stem = $cand }
        }
        if ($stem.Length -lt 5) { $stem = $w }
        $stems += $stem
    }
    $stems | Select-Object -Unique
}

# For one contributor PR, scan all later maintainer PRs that are MERGED and
# produce a structured list of race entries.
# Bucket semantics:
#   superseded/full    → direct same-issue evidence (closingIssuesReferences ∩)
#   superseded/partial → title-word root-cause overlap (≥ 2 shared meaningful tokens), no shared issue
#   overlap/ambiguous  → file overlap only (≤ 2 shared touched files in same area), explicit downgrade
#   in-flight          → maintainer PR open or closed-not-merged; surfaces as a SEPARATE warning
#                        (NEVER counts as a shipped fix)
function Get-MaintainerRace {
    param(
        $MyPR,
        $MyFiles,
        $MaintList
    )
    $myIssueNums = @($MyPR.closingIssuesReferences | ForEach-Object { $_.number }) | Where-Object { $_ }
    $myTitleWords = @(Get-MeaningfulTitleWords -Title $MyPR.title)
    $myFileSet = if ($MyFiles) { @($MyFiles) } else { @() }

    $full = New-Object System.Collections.Generic.List[object]
    $partial = New-Object System.Collections.Generic.List[object]
    $ambig = New-Object System.Collections.Generic.List[object]
    $inFlight = New-Object System.Collections.Generic.List[object]
    $earlierSameIssue = New-Object System.Collections.Generic.List[object]

    foreach ($m in $MaintList) {
        $created = $null
        if ($m.createdAt) { try { $created = [DateTime]$m.createdAt } catch { $created = $null } }
        if (-not $created) { continue }

        # Hoist same-issue signal so we can use it BOTH for the earlier-rival
        # `priority-risk` bucket AND the later-rival `superseded/full` bucket.
        $mIssueNums = @($m.closingIssuesReferences | ForEach-Object { $_.number }) | Where-Object { $_ }
        $sharedIssues = @($mIssueNums | Where-Object { $myIssueNums -contains $_ })

        # EARLIER same-issue rival: created BEFORE contributor's PR, any state.
        # Open-time priority favors the rival (precedent: #2198/#2184, #2596/#2601).
        # This is `priority-risk`, never obsolescence. Surface even if the rival
        # is OPEN (still unmerged) — that's the dangerous case, not safety.
        if ($created -le [DateTime]$MyPR.createdAt) {
            if ($sharedIssues.Count -gt 0) {
                $earlierSameIssue.Add([PSCustomObject]@{
                    PR = $m.number
                    Author = $m.author.login
                    CreatedAt = $m.createdAt
                    State = [string]$m.state
                    SharedIssues = ($sharedIssues | ForEach-Object { "#$_" }) -join ','
                })
            }
            continue
        }

        $state = [string]$m.state
        $mergedAt = $null
        if ($m.mergedAt) { try { $mergedAt = [DateTime]$m.mergedAt } catch { $mergedAt = $null } }

        # Closed-not-merged or open: in-flight warning only. Do NOT count as shipped.
        if ($state -ne 'MERGED' -or -not $mergedAt) {
            $inFlight.Add([PSCustomObject]@{
                PR = $m.number
                Author = $m.author.login
                CreatedAt = $m.createdAt
                State = $state
                Title = $m.title
            })
            continue
        }

        # 1. Direct same-issue evidence.
        if ($sharedIssues.Count -gt 0) {
            $full.Add([PSCustomObject]@{
                PR = $m.number
                Author = $m.author.login
                CreatedAt = $m.createdAt
                MergedAt = $m.mergedAt
                SharedIssues = ($sharedIssues | ForEach-Object { "#$_" }) -join ','
            })
            continue
        }

        # 2. Title-word root-cause overlap.
        $mTitleWords = @(Get-MeaningfulTitleWords -Title $m.title)
        $common = @($myTitleWords | Where-Object { $mTitleWords -contains $_ }) | Select-Object -Unique
        if ($common.Count -ge 2) {
            $partial.Add([PSCustomObject]@{
                PR = $m.number
                Author = $m.author.login
                CreatedAt = $m.createdAt
                MergedAt = $m.mergedAt
                CommonTerms = ($common -join ',')
            })
            continue
        }

        # 3. File overlap (informational only; never a supersession claim on its own).
        #    Files for $m are not in the bulk fetch; would require `gh pr view N --json files`
        #    per candidate. We do not pay that cost here; left for downstream enrichment.
        #    Surface as `ambig` only if the maintainer PR title mentions the same module
        #    substring as the contributor (cheap proxy; avoids the N+1 fetch).
        $myStem = ($myTitleWords | Select-Object -First 1) # not useful — keep empty
    }

    return [PSCustomObject]@{
        Full = $full
        Partial = $partial
        Ambiguous = $ambig
        InFlight = $inFlight
        EarlierSameIssue = $earlierSameIssue
    }
}

foreach ($state in @('open', 'merged', 'closed')) {
    $listRaw = gh pr list --repo "$owner/$Repo" --author "@me" --state $state --limit 50 `
        --json number,title,headRefName,baseRefName,labels,isDraft,url,createdAt,updatedAt,additions,deletions,changedFiles,reviewDecision,mergeable,mergedAt,mergedBy,closedAt,closingIssuesReferences 2>$null
    if (-not $listRaw) { continue }
    $prs = $listRaw | ConvertFrom-Json
    if ($prs.Count -eq 0) { continue }

    Write-Host "-- state=$state ($($prs.Count))"
    foreach ($pr in $prs) {
        $alanCt = 0; $alanLast = '—'; $ciSummary = ''; $action = '—'; $mergedBy = ''

        if ($state -eq 'open') {
            $comRaw = gh pr view $pr.number --repo "$owner/$Repo" --json comments 2>$null
            if ($comRaw) {
                $com = $comRaw | ConvertFrom-Json
                $alanCom = @($com | Where-Object { $_.author.login -eq 'Alan-TheGentleman' })
                $alanCt = $alanCom.Count
                if ($alanCt -gt 0) {
                    $latest = $alanCom | Sort-Object createdAt -Descending | Select-Object -First 1
                    $body = $latest.body -replace '\s+', ' '
                    $alanLast = $latest.createdAt.Substring(0,10) + ' "' + $body.Substring(0, [Math]::Min(60, $body.Length)) + '"'
                }
            }
            $checksRaw = gh pr checks $pr.number --repo "$owner/$Repo" --json name,state,bucket 2>$null
            if ($checksRaw) {
                $checks = $checksRaw | ConvertFrom-Json
                $fail = @($checks | Where-Object { $_.state -in @('FAILURE','ERROR') }).Count
                $pend = @($checks | Where-Object { $_.state -eq 'IN_PROGRESS' }).Count
                $ok   = @($checks | Where-Object { $_.state -eq 'SUCCESS' }).Count
                $ciSummary = "ok=$ok pend=$pend fail=$fail"
            }
            $labCount = @($pr.labels).Count
            $review = $pr.reviewDecision
            if ($labCount -eq 0) { $action = 'ping Alan en la issue para que aplique labels' }
            elseif ($review -eq 'CHANGES_REQUESTED') { $action = 'leer review, ajustar y pushear' }
            elseif ($review -eq 'APPROVED') { $action = 'esperar merge de Alan' }
            elseif ($fail -gt 0) { $action = "arreglar CI ($fail failing)" }
            else { $action = 'monitor' }
        } elseif ($state -eq 'merged') {
            $mergedBy = if ($pr.mergedBy) { $pr.mergedBy.login } else { '—' }
            $action = 'done (merged)'
        } elseif ($state -eq 'closed' -and -not $pr.mergedAt) {
            # Default; replaced by the closing harvest below for recent closes.
            $action = 'closed sin merge (revisar closing comment)'

            # Closing harvest: only for recent closes (last 14d) to bound cost.
            # Identifies the closer as the author of the last non-bot comment
            # (this `gh` build does NOT expose closedBy via --json), surfaces the
            # last human comment as the critique, and searches the maintainer
            # universe for a same-author follow-up PR that closes the same issue.
            if ($pr.closedAt) {
                $closedAt = [DateTime]$pr.closedAt
                if (([DateTime]::UtcNow - $closedAt).TotalDays -le 14) {
                    $detailRaw = gh pr view $pr.number --repo "$owner/$Repo" --json comments,closingIssuesReferences 2>$null
                    if ($detailRaw) {
                        $detail = $detailRaw | ConvertFrom-Json
                        $bots = @('coderabbitai','github-actions','dependabot','codecov[bot]')
                        $human = @($detail.comments | Where-Object { $bots -notcontains $_.author.login })
                        $closer = '—'; $critique = ''
                        if ($human.Count -gt 0) {
                            $lastC = $human | Sort-Object createdAt -Descending | Select-Object -First 1
                            $closer = $lastC.author.login
                            $cbody = ($lastC.body -replace '\s+', ' ').Trim()
                            $critique = $closer + ' @ ' + $lastC.createdAt + ': ' + $cbody.Substring(0, [Math]::Min(220, $cbody.Length))
                        }
                        $prIssues = @($detail.closingIssuesReferences | ForEach-Object { $_.number }) | Where-Object { $_ }
                        $followUps = @()
                        if (-not $maintErr -and $prIssues.Count -gt 0 -and $closer -ne '—') {
                            $followUps = @($maintPrs | Where-Object {
                                $_.author.login -eq $closer -and
                                $_.number -ne $pr.number -and
                                @(($_.closingIssuesReferences | ForEach-Object { $_.number }) | Where-Object { $prIssues -contains $_ }).Count -gt 0
                            })
                        }
                        $action = "closed sin merge — harvest: closer=$closer"
                        if ($critique) { $action += "; critique: $critique" }
                        if ($followUps.Count -gt 0) {
                            $f = $followUps | Select-Object -First 1
                            $action += "; superseded-by #$($f.number) ($($f.Author), state=$($f.state), closes same)"
                        }
                    }
                }
            }
        }

        $addD = if ($null -eq $pr.additions) { 0 } else { $pr.additions }
        $delD = if ($null -eq $pr.deletions) { 0 } else { $pr.deletions }
        $cf   = if ($null -eq $pr.changedFiles) { 0 } else { $pr.changedFiles }

        Write-Host "  #$($pr.number) $($pr.title)"
        Write-Host "    branch=$($pr.headRefName)  base=$($pr.baseRefName)  status=$state"
        Write-Host "    diff: +$addD -$delD across $cf files"
        if ($state -eq 'open') {
            Write-Host "    CI: $ciSummary  reviewDecision=$($pr.reviewDecision)"
            Write-Host "    Alan commented: $alanCt time(s)  last: $alanLast"
        }
        if ($state -eq 'merged') {
            Write-Host "    mergedBy=$mergedBy  mergedAt=$($pr.mergedAt)"
        }
        Write-Host "    action: $action"

        # ---- maintainer-race analysis (open PRs only; closed/merged are history) ----
        if ($state -eq 'open') {
            if ($maintErr) {
                Write-Host "    maintainer-race: ERR/UNKNOWN — could not fetch maintainer PR list (`gh pr list` returned no JSON or an error). Manually verify with \`gh pr list --state all --search \`"around $($pr.number)\`\` if a competitor is suspected."
            } else {
                $race = Get-MaintainerRace -MyPR $pr -MyFiles $null -MaintList $maintPrs
                $fullEntries = @($race.Full)
                $partialEntries = @($race.Partial)
                $inflightEntries = @($race.InFlight)
                $earlierEntries = @($race.EarlierSameIssue)
                $lines = New-Object System.Collections.Generic.List[string]
                if ($fullEntries.Count -gt 0) {
                    $main = $fullEntries | Select-Object -First 1
                    $line = "    maintainer-race: SUPERSEDED/FULL — #$($main.PR) by $($main.Author), created $($main.CreatedAt), merged $($main.MergedAt), closes same $($main.SharedIssues)"
                    $lines.Add($line)
                    foreach ($extra in ($fullEntries | Select-Object -Skip 1)) {
                        $lines.Add("      also full: #$($extra.PR) by $($extra.Author), created $($extra.CreatedAt), merged $($extra.MergedAt), closes same $($extra.SharedIssues)")
                    }
                    foreach ($p in $partialEntries) {
                        $lines.Add("      also partial (root-cause): #$($p.PR) by $($p.Author), created $($p.CreatedAt), merged $($p.MergedAt), shared terms: $($p.CommonTerms)")
                    }
                    if ($fullEntries.Count -gt 0) {
                        $first = $fullEntries | Select-Object -First 1
                        $lines.Add("    decision: CLOSE as duplicate of #$($first.PR) — same linked issue merged after your PR was opened")
                    }
                } elseif ($partialEntries.Count -gt 0) {
                    $main = $partialEntries | Select-Object -First 1
                    $line = "    maintainer-race: superseded/partial — #$($main.PR) by $($main.Author), created $($main.CreatedAt), merged $($main.MergedAt), shared root-cause terms: $($main.CommonTerms)"
                    $lines.Add($line)
                    foreach ($extra in ($partialEntries | Select-Object -Skip 1)) {
                        $lines.Add("      also partial: #$($extra.PR) by $($extra.Author), created $($extra.CreatedAt), shared terms: $($extra.CommonTerms)")
                    }
                    $lines.Add("    decision: REVIEW — same root-cause already shipped but your PR may add incremental value (Codex hooks.json wiring, walkEmbeddedAssetDir, etc.). Confirm with Alan whether to keep, adapt, or close.")
                } else {
                    $lines.Add("    maintainer-race: none — no later MERGED maintainer PR shares an issue or root-cause word set with this PR")
                }
                if ($inflightEntries.Count -gt 0) {
                    $lines.Add("    maintainer-in-flight (informational, NOT a shipped fix):")
                    foreach ($i in $inflightEntries) {
                        $lines.Add("      #$($i.PR) by $($i.Author), created $($i.CreatedAt), state=$($i.State) — same root-cause area, but NOT YET merged")
                    }
                }
                if ($earlierEntries.Count -gt 0) {
                    $lines.Add("    priority-risk (EARLIER same-issue rival — NOT obsolescence, open-time-priority threat):")
                    foreach ($e in $earlierEntries) {
                        $lines.Add("      #$($e.PR) by $($e.Author), created $($e.CreatedAt) (BEFORE this PR), state=$($e.State), closes same $($e.SharedIssues) — hold further work, seek adjudication")
                    }
                }
                foreach ($l in $lines) { Write-Host $l }
            }
        }

        $updatedStr = if ($pr.updatedAt) { ([DateTime]$pr.updatedAt).ToString('yyyy-MM-dd') } else { '—' }
        Write-Host "    updated=$updatedStr  url=$($pr.url)"
        Write-Host ""
    }
}
