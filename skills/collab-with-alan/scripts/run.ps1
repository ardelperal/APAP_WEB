#!/usr/bin/env pwsh
# collab-with-alan / run: tira la skill completa para el repo detectado en cwd.

param(
    [ValidateSet('auto', 'gentle-ai', 'engram')]
    [string]$Repo = 'auto'
)

$ErrorActionPreference = 'SilentlyContinue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($s in @('output1_my_work.ps1', 'output2_approved_list.ps1')) {
    $scriptPath = Join-Path $here $s
    if (Test-Path -LiteralPath $scriptPath) {
        & pwsh -NoProfile -File $scriptPath -Repo $Repo
    } else {
        Write-Host "[run] falta $s en $here"
    }
}
