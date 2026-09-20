<#
.SYNOPSIS
  Engram sync repair — apply fixes from the doctor findings.

.DESCRIPTION
  Walks each category of BLOCKED finding and asks before applying the fix.
  Always backs up engram.db before any mutation. After repair, runs diagnose.ps1
  again to confirm no new BLOCKED findings appear.

  Categories repaired (each opt-in):
    1. Title repair       — observations.title = first line of content
    2. Session ID repair  — observations.session_id = 'manual-save-<project>'
    3. Orphan prune       — DELETE sync_mutations whose entity_key is empty or
                            whose entity is 'relation' (cloud schema rejects)
    4. Allowlist prune    — DELETE sync_mutations whose project NOT in
                            ENGRAM_CLOUD_ALLOWED_PROJECTS
    5. Sync state reset   — clear last_error, consecutive_failures, etc.
                            on non-allowed targets in sync_state

.PARAMETER AssumeYes
  Apply every category without per-category prompts. Use only after running
  diagnose.ps1 and confirming the categories are safe to apply.

.PARAMETER SkipCategory
  Comma-separated list of category numbers to skip (1..5). Default: none.

.PARAMETER Confirm
  Required when -AssumeYes is set, as a safety interlock.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File repair.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File repair.ps1 -AssumeYes -Confirm

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File repair.ps1 -SkipCategory 5
#>

[CmdletBinding()]
param(
  [switch]$AssumeYes,
  [string]$SkipCategory = '',
  [switch]$Confirm
)

$ErrorActionPreference = 'Stop'
$script:WslDistro = 'Ubuntu-22.04'
$script:EngramDbPath = '/mnt/c/Users/adm1/.engram/engram.db'
$script:EngramDbWindows = Join-Path $env:USERPROFILE '.engram\engram.db'
$script:EngramExePath = "$env:LOCALAPPDATA\engram\bin\engram.exe"
$script:PostgresPort = 5433

if ($AssumeYes -and -not $Confirm) {
  Write-Host "ERROR: -AssumeYes requires -Confirm. Refusing to run unattended without explicit confirmation." -ForegroundColor Red
  exit 2
}

function Read-WslInput {
  param([string]$WslPath, [string]$WslCmd)
  wsl -d $script:WslDistro -u root -- bash -c "$WslCmd" 2>&1
}

function Backup-Db {
  $ts = Get-Date -Format 'yyyyMMdd-HHmmss'
  $backupPath = Join-Path $env:USERPROFILE ".engram\engram.db.repair-$ts.bak"
  Copy-Item $script:EngramDbWindows $backupPath -Force
  Write-Host "[backup] engram.db copied to $backupPath" -ForegroundColor Cyan
  return $backupPath
}

function Stop-Daemon {
  $procs = Get-Process -Name 'engram' -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $script:EngramExePath -and $_.CommandLine -like '*serve*' }
  if ($procs) {
    $procs | Stop-Process -Force
    Start-Sleep -Seconds 2
    Write-Host "[daemon] stopped $($procs.Count) serve process(es)" -ForegroundColor Cyan
  }
}

function Start-Daemon {
  Start-Process -FilePath $script:EngramExePath -ArgumentList 'serve' -NoNewWindow `
    -RedirectStandardOutput "$env:USERPROFILE\.engram\serve.out.log" `
    -RedirectStandardError "$env:USERPROFILE\.engram\serve.err.log"
  Start-Sleep -Seconds 5
  $check = Test-NetConnection -ComputerName 127.0.0.1 -Port 7437 -InformationLevel Quiet -WarningAction SilentlyContinue
  if ($check) {
    Write-Host "[daemon] started successfully" -ForegroundColor Green
  } else {
    Write-Host "[daemon] FAILED to start within 5s. Check $env:USERPROFILE\.engram\serve.err.log" -ForegroundColor Red
    exit 3
  }
}

function Invoke-WslSqlite {
  param([string]$Sql, [switch]$ReadOnly)
  $escaped = $Sql -replace '"', '\"'
  $out = Read-WslInput -WslCmd "sqlite3 $script:EngramDbPath \"$escaped\"" 2>&1
  if ($LASTEXITCODE -ne 0) { throw "sqlite3 failed: $out" }
  return ($out -split "`n" | Where-Object { $_ -match '\S' })
}

function Copy-Db-WslToWindows {
  # This is the step that historically corrupted the DB. Order matters:
  # 1) PRAGMA wal_checkpoint(TRUNCATE) to flush WAL
  # 2) Copy from WSL to Windows
  # 3) Delete WAL/SHM on Windows so the daemon opens cleanly
  Read-WslInput -WslCmd 'sqlite3 /root/work/repair.db "PRAGMA wal_checkpoint(TRUNCATE);"' | Out-Null
  Read-WslInput -WslCmd "cp /root/work/repair.db $script:EngramDbPath" | Out-Null
  Remove-Item "$($script:EngramDbWindows)-wal" -ErrorAction SilentlyContinue
  Remove-Item "$($script:EngramDbWindows)-shm" -ErrorAction SilentlyContinue
  Write-Host "[copy] repaired DB propagated to Windows" -ForegroundColor Cyan
}

function Run-Sql {
  param([string]$Sql, [string]$Description)
  Write-Host "[sql] $Description" -ForegroundColor DarkCyan
  Read-WslInput -WslCmd "sqlite3 /root/work/repair.db \"$($Sql -replace '"','\"')\"" 2>&1 | Out-Null
}

function Confirm-Action {
  param([string]$Prompt)
  if ($AssumeYes) { return $true }
  $resp = Read-Host "$Prompt [y/N]"
  return ($resp -match '^[yY]')
}

# --- Pre-flight -------------------------------------------------------------
Write-Host "`n=== Engram Sync Repair ===" -ForegroundColor Cyan
Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-ddTHH:mm:ssZ')"
Write-Host "Skip categories: $($SkipCategory -replace '^$','none')`n"

$skipSet = @{}
if ($SkipCategory) { $SkipCategory -split ',' | ForEach-Object { $skipSet[$_.Trim()] = $true } }

# --- Stop daemon & backup ---------------------------------------------------
Write-Host "Stopping daemon..." -ForegroundColor Yellow
Stop-Daemon
$backup = Backup-Db

# Copy current DB to WSL work area
Read-WslInput -WslCmd 'mkdir -p /root/work' | Out-Null
Read-WslInput -WslCmd "cp $script:EngramDbPath /root/work/repair.db && chmod 644 /root/work/repair.db" | Out-Null
Read-WslInput -WslCmd 'sqlite3 /root/work/repair.db "PRAGMA wal_checkpoint(TRUNCATE);"' | Out-Null

# --- Category 1: Title repair ----------------------------------------------
if (-not $skipSet['1']) {
  $emptyTitles = Invoke-WslSqlite "SELECT count(*) FROM observations WHERE (title IS NULL OR title='') AND content IS NOT NULL AND content != '' AND deleted_at IS NULL" 2>$null
  $cnt = if ($emptyTitles) { $emptyTitles -join ',' } else { '0' }
  Write-Host ""
  Write-Host "[cat 1] Title repair: $cnt observations have empty title but valid content"
  if (Confirm-Action "Apply title repair to $cnt observations?") {
    Run-Sql @"
UPDATE observations
SET title = CASE
  WHEN instr(content, char(10)) > 0 THEN substr(content, 1, MIN(instr(content, char(10)) - 1, 200))
  ELSE substr(content, 1, 200)
END
WHERE (title IS NULL OR title='')
  AND content IS NOT NULL AND content != ''
  AND deleted_at IS NULL;
"@ "title from first line of content"

    Run-Sql @"
UPDATE sync_mutations
SET payload = json_set(payload, '\$.title',
  (SELECT title FROM observations WHERE observations.sync_id = sync_mutations.entity_key LIMIT 1))
WHERE entity='observation' AND op='upsert'
  AND (json_extract(payload, '\$.title') IS NULL OR json_extract(payload, '\$.title')='')
  AND EXISTS (SELECT 1 FROM observations WHERE observations.sync_id = sync_mutations.entity_key);
"@ "propagate titles into sync_mutations"
  } else { Write-Host "[cat 1] skipped" -ForegroundColor DarkGray }
}

# --- Category 2: Session ID repair -----------------------------------------
if (-not $skipSet['2']) {
  $emptySid = Invoke-WslSqlite "SELECT count(*) FROM observations WHERE (session_id IS NULL OR session_id='') AND content IS NOT NULL AND content != '' AND deleted_at IS NULL" 2>$null
  $cnt = if ($emptySid) { $emptySid -join ',' } else { '0' }
  Write-Host ""
  Write-Host "[cat 2] Session ID repair: $cnt observations have empty session_id"
  if (Confirm-Action "Apply session_id=manual-save-<project> to $cnt observations?") {
    Run-Sql @"
UPDATE observations
SET session_id = COALESCE(NULLIF(session_id,''), 'manual-save-' || project)
WHERE (session_id IS NULL OR session_id='')
  AND content IS NOT NULL AND content != ''
  AND deleted_at IS NULL;
"@ "fallback session_id"

    Run-Sql @"
UPDATE sync_mutations
SET payload = json_set(payload, '\$.session_id',
  (SELECT session_id FROM observations WHERE observations.sync_id = sync_mutations.entity_key LIMIT 1))
WHERE entity='observation' AND op='upsert'
  AND (json_extract(payload, '\$.session_id') IS NULL OR json_extract(payload, '\$.session_id')='')
  AND EXISTS (SELECT 1 FROM observations WHERE observations.sync_id = sync_mutations.entity_key);
"@ "propagate session_ids into sync_mutations"
  } else { Write-Host "[cat 2] skipped" -ForegroundColor DarkGray }
}

# --- Category 3: Orphan prune ----------------------------------------------
if (-not $skipSet['3']) {
  $relCnt = Invoke-WslSqlite "SELECT count(*) FROM sync_mutations WHERE entity='relation'" 2>$null
  $noKeyCnt = Invoke-WslSqlite "SELECT count(*) FROM sync_mutations WHERE entity_key IS NULL OR entity_key=''" 2>$null
  $orphanObs = Invoke-WslSqlite "SELECT count(*) FROM sync_mutations sm WHERE entity='observation' AND op='upsert' AND (json_extract(payload,'\$.title') IS NULL OR json_extract(payload,'\$.title')='' OR json_extract(payload,'\$.content') IS NULL OR json_extract(payload,'\$.content')='') AND EXISTS (SELECT 1 FROM observations o WHERE o.sync_id = sm.entity_key AND (o.title IS NULL OR o.title='' OR o.content IS NULL OR o.content=''))" 2>$null
  $orphanSess = Invoke-WslSqlite "SELECT count(*) FROM sync_mutations WHERE entity='session' AND op='upsert' AND (json_extract(payload,'\$.id') IS NULL OR json_extract(payload,'\$.id')='') AND NOT EXISTS (SELECT 1 FROM sessions WHERE sessions.id = sync_mutations.entity_key)" 2>$null
  $orphanPrompt = Invoke-WslSqlite "SELECT count(*) FROM sync_mutations WHERE entity='prompt' AND op='upsert' AND (json_extract(payload,'\$.content') IS NULL OR json_extract(payload,'\$.content')='') AND EXISTS (SELECT 1 FROM user_prompts up WHERE up.sync_id = sync_mutations.entity_key AND (up.content IS NULL OR up.content=''))" 2>$null

  $rel = if ($relCnt) { [int]($relCnt -join ',') } else { 0 }
  $noKey = if ($noKeyCnt) { [int]($noKeyCnt -join ',') } else { 0 }
  $oObs = if ($orphanObs) { [int]($orphanObs -join ',') } else { 0 }
  $oSess = if ($orphanSess) { [int]($orphanSess -join ',') } else { 0 }
  $oPrompt = if ($orphanPrompt) { [int]($orphanPrompt -join ',') } else { 0 }
  $totalOrphan = $rel + $noKey + $oObs + $oSess + $oPrompt

  Write-Host ""
  Write-Host "[cat 3] Orphan prune:"
  Write-Host "         - relation entities:        $rel"
  Write-Host "         - missing entity_key:       $noKey"
  Write-Host "         - orphan observation upserts (source title/content empty): $oObs"
  Write-Host "         - orphan session upserts (no source row): $oSess"
  Write-Host "         - orphan prompt upserts (source content empty): $oPrompt"
  Write-Host "         Total: $totalOrphan"
  if (Confirm-Action "DELETE all $totalOrphan orphan rows from sync_mutations?") {
    Run-Sql "DELETE FROM sync_mutations WHERE entity='relation';" "delete relations"
    Run-Sql "DELETE FROM sync_mutations WHERE entity_key IS NULL OR entity_key='';" "delete missing entity_key"
    Run-Sql @"
DELETE FROM sync_mutations
WHERE entity='observation' AND op='upsert'
  AND (json_extract(payload,'\$.title') IS NULL OR json_extract(payload,'\$.title')=''
       OR json_extract(payload,'\$.content') IS NULL OR json_extract(payload,'\$.content')='')
  AND EXISTS (SELECT 1 FROM observations o WHERE o.sync_id = sync_mutations.entity_key
              AND (o.title IS NULL OR o.title='' OR o.content IS NULL OR o.content=''));
"@ "delete orphan obs upserts"
    Run-Sql @"
DELETE FROM sync_mutations
WHERE entity='session' AND op='upsert'
  AND (json_extract(payload,'\$.id') IS NULL OR json_extract(payload,'\$.id')='')
  AND NOT EXISTS (SELECT 1 FROM sessions WHERE sessions.id = sync_mutations.entity_key);
"@ "delete orphan session upserts"
    Run-Sql @"
DELETE FROM sync_mutations
WHERE entity='prompt' AND op='upsert'
  AND (json_extract(payload,'\$.content') IS NULL OR json_extract(payload,'\$.content')='')
  AND EXISTS (SELECT 1 FROM user_prompts up WHERE up.sync_id = sync_mutations.entity_key
              AND (up.content IS NULL OR up.content=''));
"@ "delete orphan prompt upserts"
  } else { Write-Host "[cat 3] skipped" -ForegroundColor DarkGray }
}

# --- Category 4: Allowlist prune -------------------------------------------
if (-not $skipSet['4']) {
  $allowlist = [Environment]::GetEnvironmentVariable('ENGRAM_CLOUD_ALLOWED_PROJECTS', 'User')
  if (-not $allowlist) {
    Write-Host "[cat 4] ENGRAM_CLOUD_ALLOWED_PROJECTS not set, skipping" -ForegroundColor Yellow
  } else {
    $allowedSet = $allowlist -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $allowedSql = ($allowedSet | ForEach-Object { "'$_'" }) -join ','
    $cnt = Invoke-WslSqlite "SELECT count(*) FROM sync_mutations WHERE project NOT IN ($allowedSql)" 2>$null
    $count = if ($cnt) { [int]($cnt -join ',') } else { 0 }
    Write-Host ""
    Write-Host "[cat 4] Allowlist prune: $count mutations belong to projects NOT in allowlist"
    if ($count -gt 0) {
      if (Confirm-Action "DELETE $count non-allowlisted mutations?") {
        Run-Sql "DELETE FROM sync_mutations WHERE project NOT IN ($allowedSql);" "delete non-allowlisted mutations"
      } else { Write-Host "[cat 4] skipped" -ForegroundColor DarkGray }
    }
  }
}

# --- Category 5: Sync state reset ------------------------------------------
if (-not $skipSet['5']) {
  $allowlist = [Environment]::GetEnvironmentVariable('ENGRAM_CLOUD_ALLOWED_PROJECTS', 'User')
  if (-not $allowlist) {
    Write-Host "[cat 5] ENGRAM_CLOUD_ALLOWED_PROJECTS not set, skipping" -ForegroundColor Yellow
  } else {
    $allowedSet = $allowlist -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $allowedTargets = ($allowedSet | ForEach-Object { "'cloud:$_'" }) -join ','
    $cnt = Invoke-WslSqlite "SELECT count(*) FROM sync_state WHERE target_key NOT IN ($allowedTargets)" 2>$null
    $count = if ($cnt) { [int]($cnt -join ',') } else { 0 }
    Write-Host ""
    Write-Host "[cat 5] Sync state reset: $count targets are not in allowlist"
    if ($count -gt 0) {
      if (Confirm-Action "Clear last_error/consecutive_failures/backoff on $count non-allowed targets?") {
        Run-Sql "UPDATE sync_state SET last_error=NULL, consecutive_failures=0, backoff_until=NULL, reason_code=NULL, reason_message=NULL WHERE target_key NOT IN ($allowedTargets);" "reset non-allowed sync_state"
      } else { Write-Host "[cat 5] skipped" -ForegroundColor DarkGray }
    }
  }
}

# --- Final: REINDEX + integrity + propagate --------------------------------
Write-Host ""
Write-Host "Final steps: REINDEX, integrity_check, propagate, restart daemon..." -ForegroundColor Yellow
Read-WslInput -WslCmd 'sqlite3 /root/work/repair.db "REINDEX;"' | Out-Null
$integrity = Invoke-WslSqlite "PRAGMA integrity_check"
if ($integrity -notcontains 'ok') {
  Write-Host "[FATAL] integrity_check failed after repair: $($integrity -join '; ')" -ForegroundColor Red
  Write-Host "Restore from backup: $backup"
  exit 4
}
Write-Host "[integrity] ok" -ForegroundColor Green

Copy-Db-WslToWindows
Start-Daemon

# --- Post-check: run diagnose again ----------------------------------------
Write-Host ""
Write-Host "Running diagnose.ps1 for post-repair verification..." -ForegroundColor Cyan
$diagScript = Join-Path $PSScriptRoot 'diagnose.ps1'
& powershell -ExecutionPolicy Bypass -File $diagScript

Write-Host "`nRepair complete. Backup at: $backup" -ForegroundColor Cyan
