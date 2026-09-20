# install-pre-push-hook.ps1
# Wires pre-push-race-check.ps1 as the git pre-push hook for the current worktree.
# Per collab-with-alan SKILL.md Hard Rule #12.
#
# Usage (from the worktree root):
#   pwsh -NoProfile -File <skill>/scripts/install-pre-push-hook.ps1
# Or with explicit path:
#   pwsh -NoProfile -File <skill>/scripts/install-pre-push-hook.ps1 -Cwd <worktree-path>

[CmdletBinding()]
param(
    [string]$Cwd = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path $PSScriptRoot 'pre-push-race-check.ps1'
if (-not (Test-Path -LiteralPath $scriptPath)) {
    Write-Host "[ERR] pre-push-race-check.ps1 not found at $scriptPath" -ForegroundColor Red
    exit 1
}

# Resolve the git directory (handles worktrees where .git is a file)
$gitDirRaw = (& git -C $Cwd rev-parse --git-dir 2>$null)
$LASTEXITCODE_SAVED = $LASTEXITCODE
# PowerShell native command output capture returns the full stream as a string array.
# Normalize to a single trimmed string.
if ($null -eq $gitDirRaw) {
    $gitDirRaw = ''
} elseif ($gitDirRaw -is [array]) {
    $gitDirRaw = ($gitDirRaw | Where-Object { $_ } | Select-Object -First 1)
}
$gitDirRaw = ([string]$gitDirRaw).Trim()
if ($LASTEXITCODE_SAVED -ne 0 -or [string]::IsNullOrWhiteSpace($gitDirRaw)) {
    Write-Host "[ERR] not a git worktree: $Cwd (git rev-parse --git-dir returned '$gitDirRaw', exit=$LASTEXITCODE_SAVED)" -ForegroundColor Red
    exit 1
}
# If relative, resolve against Cwd
if (-not [System.IO.Path]::IsPathRooted($gitDirRaw)) {
    $gitDir = Join-Path $Cwd $gitDirRaw
} else {
    $gitDir = $gitDirRaw
}
$hooksDir = Join-Path $gitDir 'hooks'
if (-not (Test-Path -LiteralPath $hooksDir)) {
    New-Item -ItemType Directory -Path $hooksDir -Force | Out-Null
}

$hookPath = Join-Path $hooksDir 'pre-push'

# Back up any existing hook
if (Test-Path -LiteralPath $hookPath) {
    $backup = "$hookPath.bak-$(Get-Date -Format yyyyMMddHHmmss)"
    Copy-Item -LiteralPath $hookPath -Destination $backup -Force
    Write-Host "[INFO] existing hook backed up to $backup" -ForegroundColor Yellow
}

# Write the hook: PowerShell wrapper that calls the script with the worktree cwd.
# git hooks receive hook args on stdin/argv. pre-push passes local ref info on stdin;
# we ignore it because the script reads the current branch itself.
$hookContent = @"
#!/usr/bin/env pwsh
# Installed by collab-with-alan/scripts/install-pre-push-hook.ps1
# Hard-gate before push: blocks priority-risk pushes per SKILL.md Hard Rule #12.
$scriptPath -Cwd "$Cwd" @args
exit `$LASTEXITCODE
"@

Set-Content -LiteralPath $hookPath -Value $hookContent -Encoding utf8 -NoNewline

# Make executable (no-op on Windows; needed for WSL/git bash portability)
try {
    & git -C $Cwd config core.hooksPath $null 2>$null
} catch { }

Write-Host "[OK] pre-push hook installed at $hookPath" -ForegroundColor Green
Write-Host "       Bypass with: git push --no-verify   OR   pwsh -File $scriptPath -Force" -ForegroundColor Cyan
