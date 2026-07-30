#Requires -Version 5.1
<#
.SYNOPSIS
    Verifies GitHub self-hosted runner connectivity and label correctness.

.DESCRIPTION
    Calls the GitHub Actions Runners API to confirm:
    1. At least one runner with the expected label set is registered.
    2. The runner's status is Idle or Online (not Offline).
    3. The runner is not已被移除 (removed).

    Exits 0 on success, 1 on any failure.

.PARAMETER RunnerUrl
    The full repository URL passed to the runner config, e.g.
    "https://github.com/ardelperal/APAP_WEB".

.PARAMETER Labels
    Comma-separated label list to verify. Must include all expected labels.
    Default: "self-hosted,Linux,ARM64,apap,oracle".

.PARAMETER Token
    GitHub personal access token with "repo" scope (or "admin:org" for org runners).
    If not provided, the script reads $env:GH_TOKEN.

.EXAMPLE
    .\check-runner.ps1 -RunnerUrl "https://github.com/ardelperal/APAP_WEB" -Labels "self-hosted,Linux,ARM64,apap,oracle"

.EXAMPLE
    $env:GH_TOKEN = "ghp_..."; .\check-runner.ps1 -RunnerUrl "https://github.com/ardelperal/APAP_WEB"
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$RunnerUrl,

    [Parameter(Mandatory = $false)]
    [string]$Labels = "self-hosted,Linux,ARM64,apap,oracle",

    [Parameter(Mandatory = $false)]
    [string]$Token = $env:GH_TOKEN
)

$ErrorActionPreference = "Stop"

# ── Resolve repository from RunnerUrl ────────────────────────────────────────
if ($RunnerUrl -match 'github\.com/([^/]+/[^/]+)/?') {
    $repo = $Matches[1].TrimEnd('/')
} else {
    Write-Error "RunnerUrl must be a GitHub repository URL, e.g. https://github.com/owner/repo"
    exit 1
}

# ── Auth ─────────────────────────────────────────────────────────────────────
if ([string]::IsNullOrWhiteSpace($Token)) {
    Write-Error "GitHub token not provided. Set -Token or $env:GH_TOKEN"
    exit 1
}

$headers = @{
    Authorization  = "Bearer $Token"
    Accept         = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

# ── Fetch runner list ─────────────────────────────────────────────────────────
$apiUrl = "https://api.github.com/repos/$repo/actions/runners"

try {
    $response = Invoke-RestMethod -Uri $apiUrl -Headers $headers -Method Get
} catch {
    Write-Error "Failed to fetch runners from $apiUrl : $_"
    exit 1
}

$expectedLabels = $Labels.Split(',').ForEach({ $_.Trim() })

Write-Host "Checking runners for '$repo'..."
Write-Host "Expected labels: $($expectedLabels -join ', ')"

$matchedRunners = $response.runners | Where-Object {
    $runnerLabels = $_.labels | ForEach-Object { $_.name }
    # All expected labels must be present on the runner
    ($expectedLabels | ForEach-Object { $_ -in $runnerLabels }) -notcontains $false
}

if ($matchedRunners.Count -eq 0) {
    Write-Error "No runner found with all expected labels [$Labels]."
    Write-Host "Available runners:"
    $response.runners | ForEach-Object {
        $rLabels = $_.labels | ForEach-Object { $_.name } -join ', '
        Write-Host "  - $($_.name) [$($_.status)] labels: $rLabels"
    }
    exit 1
}

# ── Check status ──────────────────────────────────────────────────────────────
$onlineRunners = $matchedRunners | Where-Object { $_.status -in @('idle', 'online') }
$offlineRunners = $matchedRunners | Where-Object { $_.status -eq 'offline' }

if ($onlineRunners.Count -gt 0) {
    Write-Host "SUCCESS: $($onlineRunners.Count) runner(s) are $($onlineRunners[0].status):"
    $onlineRunners | ForEach-Object {
        $rLabels = $_.labels | ForEach-Object { $_.name } -join ', '
        Write-Host "  - $($_.name) [$($_.status)] labels: $rLabels"
    }
}

if ($offlineRunners.Count -gt 0) {
    Write-Error "WARNING: $($offlineRunners.Count) matched runner(s) are OFFLINE and cannot accept jobs:"
    $offlineRunners | ForEach-Object {
        $rLabels = $_.labels | ForEach-Object { $_.name } -join ', '
        Write-Host "  - $($_.name) [offline] labels: $rLabels"
    }
    Write-Host "Run the deregistration / re-registration steps in docs/runbooks/github-runner-registration.md"
    exit 1
}

if ($matchedRunners.Count -gt 0 -and $onlineRunners.Count -eq 0) {
    # Some runners exist but none are online
    Write-Error "Runner(s) found but none are idle or online. Statuses:"
    $matchedRunners | ForEach-Object {
        Write-Host "  - $($_.name) [$($_.status)]"
    }
    exit 1
}

Write-Host ""
Write-Host "All checks passed. Runner is ready to accept e2e jobs."
exit 0
