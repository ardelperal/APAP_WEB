#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Copies Codex carril model assignments into OpenCode's opencode.json.
    Deterministic, single-command bridge: Codex tiers → OpenAI.json → opencode.json.

.DESCRIPTION
    Flow:
      1. (Optional) Run `gentle-ai sync --agent opencode` to regenerate OpenAI.json
         from the latest Codex carril defaults in state.json
      2. Read the resulting ~/.config/opencode/profiles/OpenAI.json
      3. Delegate preview or apply to ai-model-profile-manager

    This ensures OpenCode always matches the Codex carril configuration without
    manual editing. Unlike resolving from state.json directly, this preserves the
    full agent roster (review-*, sdd-init, etc.) that Codex's built-in template knows.

.PARAMETER SyncFirst
    If set, runs `gentle-ai sync --agent opencode` BEFORE applying.
    Use this after upgrading gentle-ai or changing state.json.

.PARAMETER Apply
    If set, applies the generated profile. The default is preview-only.

.PARAMETER SkipDoctor
    If set, skip the gentle-ai doctor pre-check.

.EXAMPLE
    # Preview what would change (assumes OpenAI.json is current)
    ./sync-codex-to-opencode.ps1

    # Apply current Codex carrils to OpenCode
    ./sync-codex-to-opencode.ps1 -Apply

    # Sync Codex, then preview
    ./sync-codex-to-opencode.ps1 -SyncFirst

    # Sync Codex, then apply
    ./sync-codex-to-opencode.ps1 -SyncFirst -Apply

    # Full chain: upgrade + sync + apply
    gentle-ai upgrade --channel beta && ./sync-codex-to-opencode.ps1 -SyncFirst
#>

param(
    [switch]$SyncFirst,
    [switch]$Apply,
    [switch]$SkipDoctor
)

$ErrorActionPreference = 'Stop'
$OpenAIProfile = "$env:USERPROFILE\.config\opencode\profiles\OpenAI.json"
$ProfileDispatcher = Join-Path (Split-Path -Parent $PSScriptRoot) 'ai-model-profile-manager\assets\Invoke-AIModelProfile.ps1'

# ── Pre-flight checks ─────────────────────────────────────────────────────────
if (-not (Test-Path -LiteralPath $OpenAIProfile)) {
    Write-Error "OpenAI.json not found at $OpenAIProfile. Run 'gentle-ai sync --agent opencode' first."
    exit 1
}

if (-not $SkipDoctor) {
    Write-Host "Checking gentle-ai doctor..." -ForegroundColor Cyan
    $doctor = & gentle-ai doctor 2>&1
    $healthy = ($doctor -match "Status:\s*healthy")
    if (-not $healthy) {
        Write-Host "gentle-ai doctor is NOT healthy:" -ForegroundColor Yellow
        $doctor | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
        Write-Host "Run gentle-ai upgrade + sync first, or use -SkipDoctor." -ForegroundColor Red
        exit 1
    }
    Write-Host "  ✓ healthy" -ForegroundColor Green
}

# ── Optional: sync first ──────────────────────────────────────────────────────
if ($SyncFirst) {
    Write-Host "Running gentle-ai sync --agent opencode..." -ForegroundColor Cyan
    $syncOut = & gentle-ai sync --agent opencode 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "gentle-ai sync failed: $syncOut"
        exit 1
    }
    Write-Host "  ✓ sync complete — OpenAI.json regenerated from Codex carrils" -ForegroundColor Green
}

# ── Read the current OpenAI.json to report carrils ─────────────────────────────
$profileData = Get-Content -Raw -LiteralPath $OpenAIProfile | ConvertFrom-Json -AsHashtable
$models = $profileData['models']
$count = $models.Count

Write-Host "`nOpenAI.json profile: $count agents" -ForegroundColor Cyan

# Show unique models
$models.Values | Group-Object | Sort-Object Count -Descending | ForEach-Object {
    Write-Host "  $($_.Count)x → $($_.Name)" -ForegroundColor Gray
}

# ── Apply to opencode.json ────────────────────────────────────────────────────
Write-Host "`nDispatching OpenCode profile operation..." -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $ProfileDispatcher -PathType Leaf)) {
    Write-Error "Profile dispatcher not found: $ProfileDispatcher"
    exit 1
}
& $ProfileDispatcher -Profile $OpenAIProfile -Targets OpenCode -Apply:$Apply

Write-Host "`n✓ Done." -ForegroundColor Green
