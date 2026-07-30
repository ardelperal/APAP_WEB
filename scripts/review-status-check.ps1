# review-status-check.ps1
# Verifies that the gentle-ai review authority inventory is clean.
# Exits 0 only when authoritative=true, complete=true, AND status=complete.
# For use in pre-commit hooks, CI aids, or manual verification.
#
# Usage:
#   ./review-status-check.ps1 [-Cwd <path>]
#
# Examples:
#   ./review-status-check.ps1
#   ./review-status-check.ps1 -Cwd "C:\00repos\codigo\APAP_WEB_worktrees\wt-198-review-authority"
#
# Exit codes:
#   0  — inventory is authoritative, complete, and status is "complete"
#   1  — inventory check failed (authoritative=false, complete=false, or status!=complete)
#   2  — gentle-ai CLI not found or command failed

param(
    [string]$Cwd = (Get-Location).Path
)

$ErrorActionPreference = "Stop"

# Check gentle-ai is available
try {
    $null = Get-Command gentle-ai -ErrorAction Stop
} catch {
    Write-Error "gentle-ai CLI not found in PATH. Install from https://github.com/Gentleman-Programming/gentle-ai"
    exit 2
}

# Run review status
try {
    $statusJson = gentle-ai review status --cwd $Cwd 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "gentle-ai review status failed with exit code $LASTEXITCODE`: $statusJson"
        exit 2
    }
} catch {
    Write-Error "Failed to run gentle-ai review status: $_"
    exit 2
}

try {
    $status = $statusJson | ConvertFrom-Json
} catch {
    Write-Error "Failed to parse gentle-ai review status JSON: $_"
    Write-Error "Output was: $statusJson"
    exit 2
}

$authoritative = $status.authoritative -eq $true
$complete     = $status.complete -eq $true
$statusVal    = $status.status

if ($authoritative -and $complete -and $statusVal -eq "complete") {
    Write-Host "[OK] Review authority inventory is clean: authoritative=$($status.authoritative), complete=$($status.complete), status=$statusVal"
    exit 0
} else {
    Write-Host "[WARN] Review authority inventory is NOT complete."
    Write-Host "       authoritative: $($status.authoritative) (expected: true)"
    Write-Host "       complete:      $($status.complete) (expected: true)"
    Write-Host "       status:       $statusVal (expected: complete)"
    Write-Host ""
    Write-Host "In pre-MVP mode (RDD off, CI gate), 'status=active' with authoritative=true"
    Write-Host "and complete=true is an acceptable clean state. 'status=complete' requires all"
    Write-Host "entries to be in terminal states (approved/invalidated/superseded/quarantined)."
    Write-Host ""
    Write-Host "Known limitation: entries in 'active/correction_required' or 'active/validating'"
    Write-Host "state with corrupted reviewer artifacts cannot be resolved without a gentle-ai CLI"
    Write-Host "update or a reviewer re-running the full review cycle."
    exit 1
}
