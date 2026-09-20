# pre-push-race-check.ps1
# Hard-gate before `git push`. Detects priority-risk rivals on the same linked
# issue and blocks the push. Per collab-with-alan SKILL.md Hard Rule #12.
#
# Detection sources for the linked issue(s) of the current branch (priority order):
#   1. Existing PR's closingIssuesReferences (`gh pr view --json closingIssuesReferences`)
#   2. Commit messages in HEAD~5 with Closes / Fixes / Resolves / Refs keywords
#   3. Issue number embedded in branch name regex `(?:fix|feat|chore|docs|refactor|perf|test|build|ci|revert)/(\d+)-`
# Manual override: `-Issue <N>` (repeatable)
#
# Verdict:
#   For each linked issue, query upstream PRs whose closingIssuesReferences
#   contains it, filter to: not @me, not CLOSED, and createdAt strictly
#   earlier than the contributor's own PR/branch first commit. Any match =>
#   priority-risk => exit 1 BLOCKED.
#
# Exit codes:
#   0 = OK to push (no priority-risk detected, or only safe rivals)
#   1 = BLOCKED (priority-risk rival detected; do not push)
#   2 = SKIPPED (no linked issues found and no -Issue given; cannot gate)
#   3 = ERROR (gh API failure, repo unreachable, etc.)
#
# Usage:
#   .\pre-push-race-check.ps1                 # auto-detect from current branch
#   .\pre-push-race-check.ps1 -Issue 2268     # explicit override (repeatable)
#   .\pre-push-race-check.ps1 -Force          # bypass (logged to stderr)
#   .\pre-push-race-check.ps1 -Repo <owner/repo> -Cwd <path>
#
# Install as a git pre-push hook (one-time per worktree):
#   New-Item -ItemType HardLink -Path <worktree>/.git/hooks/pre-push `
#     -Target $PSScriptRoot\pre-push-race-check.ps1
# Or run scripts/install-pre-push-hook.ps1 (provided).

[CmdletBinding()]
param(
    [int[]]$Issue,
    [switch]$Force,
    [string]$Repo = 'Gentleman-Programming/gentle-ai',
    [string]$Cwd = (Get-Location).Path,
    [int]$MaxCommits = 5
)

$ErrorActionPreference = 'Stop'

function Write-Banner {
    param([string]$Text, [string]$Color = 'Cyan')
    Write-Host ""
    Write-Host "===== $Text =====" -ForegroundColor $Color
    Write-Host ""
}

function Get-CurrentBranch {
    try {
        $b = (& git -C $Cwd rev-parse --abbrev-ref HEAD 2>$null).Trim()
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($b)) { return $null }
        return $b
    } catch { return $null }
}

function Get-BranchFirstCommit {
    param([string]$Branch)
    try {
        # First commit unique to this branch (compared to upstream/main)
        $sha = (& git -C $Cwd rev-list --reverse upstream/main..$Branch -- 2>$null | Select-Object -First 1).Trim()
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($sha)) { return $null }
        return $sha
    } catch { return $null }
}

function Get-BranchFirstCommitISO {
    param([string]$Branch)
    $sha = Get-BranchFirstCommit -Branch $Branch
    if (-not $sha) { return $null }
    try {
        $iso = (& git -C $Cwd show -s --format=%cI $sha 2>$null).Trim()
        if ($LASTEXITCODE -ne 0) { return $null }
        return $iso
    } catch { return $null }
}

function Get-LinkedIssuesFromPR {
    # Returns array of issue numbers from existing PR's closingIssuesReferences.
    # Uses `gh pr list --head <branch> --state all` because cross-fork branches
    # cannot be queried via `gh pr view <branch>`.
    $branch = Get-CurrentBranch
    if (-not $branch) { return @() }
    try {
        $listJson = gh pr list --repo $Repo --head $branch --state all --limit 5 `
            --json number,title,state,author,createdAt,closingIssuesReferences 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($listJson)) { return @() }
        $list = $listJson | ConvertFrom-Json
        if (-not $list -or $list.Count -eq 0) { return @() }
        # Filter to our own PR (the one being pushed)
        $mine = @($list | Where-Object { $_.author.login -eq $me })
        if ($mine.Count -eq 0) { return @() }
        $pr = $mine[0]
        if (-not $pr.closingIssuesReferences) { return @() }
        return @($pr.closingIssuesReferences | ForEach-Object { $_.number })
    } catch { return @() }
}

function Get-LinkedIssuesFromCommits {
    param([int]$Max = 5)
    try {
        $branch = Get-CurrentBranch
        if (-not $branch) { return @() }
        $log = (& git -C $Cwd log upstream/main..$Branch --pretty=format:'%s' -n $Max 2>$null)
        if ($LASTEXITCODE -ne 0) { return @() }
        $pattern = '(?i)(?:closes|fixes|resolves|refs)\s+#(\d+)'
        $issues = @()
        foreach ($line in $log) {
            if ($line -match $pattern) {
                $issues += [int]$Matches[1]
            }
        }
        return @($issues | Sort-Object -Unique)
    } catch { return @() }
}

function Get-LinkedIssuesFromBranchName {
    $branch = Get-CurrentBranch
    if (-not $branch) { return @() }
    # Accept both `type/N-slug` and `type-N-slug` (worktree convention drift).
    if ($branch -match '(?i)(?:fix|feat|chore|docs|refactor|perf|test|build|ci|revert)[/-](\d+)[/-]') {
        return @([int]$Matches[1])
    }
    return @()
}

function Get-PriorityRiskRivals {
    param(
        [int[]]$Issues,
        [string]$ContributorCreatedISO
    )
    if (-not $Issues -or $Issues.Count -eq 0) { return @() }
    $rivals = @()
    foreach ($n in $Issues) {
        try {
            # Query all open + closed (not merged) PRs in upstream with this issue in closingIssuesReferences
            $list = gh pr list --repo $Repo --state all --limit 100 `
                --json number,title,state,author,createdAt,closingIssuesReferences 2>$null |
                ConvertFrom-Json
            if ($LASTEXITCODE -ne 0 -or -not $list) { continue }
            foreach ($pr in $list) {
                if ($pr.author.login -eq $me) { continue }   # @me filter
                if ($pr.state -ne 'OPEN') { continue }       # only OPEN rivals are priority-risk
                $closesN = @($pr.closingIssuesReferences | ForEach-Object { $_.number })
                if ($closesN -notcontains $n) { continue }
                # Rival must be createdAt STRICTLY earlier than contributor's first commit
                if ($ContributorCreatedISO -and $pr.createdAt -ge $ContributorCreatedISO) { continue }
                $rivals += [PSCustomObject]@{
                    Issue      = $n
                    PRNumber   = $pr.number
                    Title      = $pr.title
                    Author     = $pr.author.login
                    CreatedAt  = $pr.createdAt
                    State      = $pr.state
                }
            }
        } catch { }
    }
    return $rivals
}

function Get-MyLogin {
    try {
        $u = (gh api user --jq .login 2>$null).Trim()
        if ($LASTEXITCODE -eq 0 -and $u) { return $u }
    } catch { }
    return $null
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

$me = Get-MyLogin
if (-not $me) {
    Write-Host "[ERR] cannot resolve @me via gh api user; aborting." -ForegroundColor Red
    exit 3
}

# Verify upstream remote exists
$remote = (& git -C $Cwd remote get-url upstream 2>$null).Trim()
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERR] no upstream remote configured; aborting." -ForegroundColor Red
    exit 3
}

# Verify upstream/main exists (avoid fossil refs)
$upstreamMain = (& git -C $Cwd rev-parse --verify upstream/main 2>$null).Trim()
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERR] upstream/main not resolvable; aborting." -ForegroundColor Red
    exit 3
}

$branch = Get-CurrentBranch
Write-Banner -Text "pre-push-race-check :: repo=$Repo branch=$branch @me=$me"

if ($Force) {
    Write-Host "[BYPASS] -Force supplied; gate skipped. Logged to stderr." -ForegroundColor Yellow
    [Console]::Error.WriteLine("[pre-push-race-bypass] $(Get-Date -Format o) repo=$Repo branch=$branch @me=$me reason=manual-force")
    exit 0
}

# Collect linked issues
$linked = @()
if ($Issue) {
    $linked += $Issue
}
$linked += Get-LinkedIssuesFromPR
$linked += Get-LinkedIssuesFromCommits -Max $MaxCommits
$linked += Get-LinkedIssuesFromBranchName
$linked = @($linked | Where-Object { $_ -gt 0 } | Sort-Object -Unique)

if (-not $linked -or $linked.Count -eq 0) {
    Write-Host "[SKIP] no linked issue detected (no PR, no Closes/Fixes keyword, no branch-name issue)." -ForegroundColor Yellow
    Write-Host "        If this push references an issue, pass -Issue <N> or include 'Closes #N' in your commit message." -ForegroundColor Yellow
    exit 2
}

Write-Host ("Linked issues detected: " + ($linked -join ', ')) -ForegroundColor Cyan

# Contributor timeline anchor: PR createdAt if exists, else first commit on branch
$contributorCreated = $null
try {
    $listJson = gh pr list --repo $Repo --head $branch --state all --limit 5 --json createdAt,author 2>$null
    if ($LASTEXITCODE -eq 0 -and $listJson) {
        $list = $listJson | ConvertFrom-Json
        $mine = @($list | Where-Object { $_.author.login -eq $me })
        if ($mine.Count -gt 0) {
            $contributorCreated = $mine[0].createdAt
        }
    }
} catch { }
if (-not $contributorCreated) {
    $contributorCreated = Get-BranchFirstCommitISO -Branch $branch
}

Write-Host "Contributor timeline anchor: $contributorCreated"
Write-Host ""

# Query rivals
$rivals = Get-PriorityRiskRivals -Issues $linked -ContributorCreatedISO $contributorCreated

if (-not $rivals -or $rivals.Count -eq 0) {
    Write-Host "[OK] no priority-risk rival detected for issues: $($linked -join ', ')" -ForegroundColor Green
    exit 0
}

Write-Banner -Text "BLOCKED :: priority-risk rival(s) detected" -Color Red
foreach ($r in $rivals) {
    Write-Host ("  - issue #{0,-6}  rival PR #{1,-6}  by {2,-20}  opened {3}" -f $r.Issue, $r.PRNumber, $r.Author, $r.CreatedAt) -ForegroundColor Red
    Write-Host ("    title: {0}" -f $r.Title) -ForegroundColor DarkRed
}
Write-Host ""
Write-Host "Per collab-with-alan Hard Rule #12, priority-risk (same linked issue, earlier createdAt, OPEN) BLOCKS the push." -ForegroundColor Red
Write-Host ""
Write-Host "Recommended actions:" -ForegroundColor Yellow
Write-Host "  1. Read the rival PR and compare scope against your branch."
Write-Host "  2. If your scope is fully covered by the rival -> close your PR with a race-verdict comment."
Write-Host "  3. If your scope is complementary -> post a comment on the linked issue asking Alan to adjudicate."
Write-Host "  4. Only bypass with -Force if Alan has explicitly approved the work continuing."
Write-Host ""
exit 1
