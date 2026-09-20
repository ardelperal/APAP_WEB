<#
.SYNOPSIS
  Engram sync diagnostic — read-only health check.

.DESCRIPTION
  Inspects the local Engram installation and reports its sync health to Cloud.
  Never mutates state. Safe to run at any time, including with daemon running.

  Reports findings in four categories:
    [OK]       — working as expected
    [WARN]     — degraded but not blocking
    [BLOCKED]  — sync cannot drain until user acts

  Exit codes:
    0  — all OK or only WARN
    1  — at least one BLOCKED finding
    2  — diagnostic itself failed (e.g., engram CLI missing)

.PARAMETER Json
  Emit a machine-readable JSON report instead of formatted text.

.PARAMETER Project
  Limit the report to one project (optional). Default: all enrolled.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File diagnose.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File diagnose.ps1 -Json | ConvertFrom-Json
#>

[CmdletBinding()]
param(
  [switch]$Json,
  [string]$Project
)

$ErrorActionPreference = 'Continue'
$script:Findings = [System.Collections.ArrayList]::new()
$script:WslDistro = 'Ubuntu-22.04'
$script:EngramDataDir = Join-Path $env:USERPROFILE '.engram'
$script:EngramDbPath = Join-Path $script:EngramDataDir 'engram.db'
$script:EngramExePath = "$env:LOCALAPPDATA\engram\bin\engram.exe"
$script:DaemonPort = 7437
$script:PostgresPort = 5433
$script:CloudUrl = 'https://engram.romancaba.com'

function Add-Finding {
  param([string]$Severity, [string]$Category, [string]$Message)
  $null = $script:Findings.Add([PSCustomObject]@{
    Severity = $Severity
    Category = $Category
    Message  = $Message
  })
}

function Invoke-WslSqlite {
  param([string]$Sql, [string]$DbPath = "/mnt/c/Users/adm1/.engram/engram.db")
  $escaped = $Sql -replace '"', '\"'
  $out = wsl -d $script:WslDistro -u root -- bash -c "sqlite3 '$DbPath' \"$escaped\"" 2>&1
  if ($LASTEXITCODE -ne 0) { return $null }
  return ($out -split "`n" | Where-Object { $_ -match '\S' })
}

function Invoke-WslPsql {
  param([string]$Sql)
  $escaped = $Sql -replace '"', '\"'
  $out = wsl -d $script:WslDistro -u root -- bash -c "PGPASSWORD=engram psql -h 127.0.0.1 -p $script:PostgresPort -U engram -d engram_cloud -t -A -c \"$escaped\"" 2>&1
  return ($out -split "`n" | Where-Object { $_ -match '\S' })
}

# --- Pre-flight: is engram installed? ----------------------------------------
if (-not (Test-Path $script:EngramExePath)) {
  Add-Finding 'BLOCKED' 'preflight' "engram CLI not found at $script:EngramExePath"
  if ($Json) { $script:Findings | ConvertTo-Json -Depth 3 } else { Format-Findings }
  exit 2
}

# --- 1. Daemon process -------------------------------------------------------
# Strategy: trust the port check (section 2) as the source of truth for "is
# the daemon up?". Use netstat to find the PID listening on the daemon port,
# then optionally enrich with CommandLine via CIM (best-effort).
$daemonProcs = @()
try {
  $netstatOut = netstat -ano | Select-String ":$($script:DaemonPort)\s+.*LISTENING\s+(\d+)" | ForEach-Object { $_.Matches[0].Groups[1].Value }
  foreach ($p in ($netstatOut | Sort-Object -Unique)) {
    $proc = Get-Process -Id ([int]$p) -ErrorAction SilentlyContinue
    if ($proc -and $proc.ProcessName -eq 'engram') { $daemonProcs += $proc }
  }
} catch {}

if ($daemonProcs.Count -gt 0) {
  $daemonPid = ($daemonProcs | Select-Object -First 1).Id
  Add-Finding 'OK' 'daemon' "engram serve running on port $($script:DaemonPort) (PID $daemonPid)"
} else {
  Add-Finding 'BLOCKED' 'daemon' 'engram serve not running on port 7437. Start with: Start-Process -FilePath engram -ArgumentList serve'
}

# --- 2. Port 7437 listening --------------------------------------------------
$portCheck = Test-NetConnection -ComputerName 127.0.0.1 -Port $script:DaemonPort -InformationLevel Quiet -WarningAction SilentlyContinue
if ($portCheck) {
  Add-Finding 'OK' 'daemon.port' "$($script:DaemonPort) is listening"
} else {
  Add-Finding 'BLOCKED' 'daemon.port' "Port $($script:DaemonPort) is NOT listening"
}

# --- 3. HTTP /sync/status ----------------------------------------------------
$syncStatus = $null
if ($portCheck) {
  try {
    $syncStatus = Invoke-WebRequest -Uri "http://127.0.0.1:$($script:DaemonPort)/sync/status" -UseBasicParsing -TimeoutSec 5 | ConvertFrom-Json
    Add-Finding 'OK' 'daemon.http' '/sync/status responded'
  } catch {
    Add-Finding 'WARN' 'daemon.http' "/sync/status failed: $($_.Exception.Message)"
  }
}

# --- 4. Autosync state -------------------------------------------------------
if ($syncStatus) {
  if ($syncStatus.enabled) {
    Add-Finding 'OK' 'autosync' 'autosync enabled'
  } else {
    Add-Finding 'BLOCKED' 'autosync' 'autosync DISABLED. Set ENGRAM_CLOUD_AUTOSYNC=1 and restart daemon'
  }
  if ($syncStatus.phase -eq 'healthy') {
    Add-Finding 'OK' 'autosync.phase' 'phase=healthy'
  } elseif ($syncStatus.phase -eq 'degraded') {
    Add-Finding 'WARN' 'autosync.phase' "phase=degraded, consecutive_failures=$($syncStatus.consecutive_failures), last_error=$($syncStatus.last_error)"
  } else {
    Add-Finding 'BLOCKED' 'autosync.phase' "phase=$($syncStatus.phase), last_error=$($syncStatus.last_error)"
  }
  if ($syncStatus.last_sync_at) {
    Add-Finding 'OK' 'autosync.last' "last_sync_at=$($syncStatus.last_sync_at)"
  } else {
    Add-Finding 'WARN' 'autosync.last' 'last_sync_at is empty (autosync has never successfully synced)'
  }
}

# --- 5. Env vars -------------------------------------------------------------
$server = [Environment]::GetEnvironmentVariable('ENGRAM_CLOUD_SERVER', 'User')
$token  = [Environment]::GetEnvironmentVariable('ENGRAM_CLOUD_TOKEN', 'User')
$autosync = [Environment]::GetEnvironmentVariable('ENGRAM_CLOUD_AUTOSYNC', 'User')
$allowlist = [Environment]::GetEnvironmentVariable('ENGRAM_CLOUD_ALLOWED_PROJECTS', 'User')
if ($server) { Add-Finding 'OK' 'env.server' "ENGRAM_CLOUD_SERVER=$server" } else { Add-Finding 'BLOCKED' 'env.server' 'ENGRAM_CLOUD_SERVER not set' }
if ($token)  { Add-Finding 'OK' 'env.token'  "ENGRAM_CLOUD_TOKEN present (length=$($token.Length))" } else { Add-Finding 'BLOCKED' 'env.token' 'ENGRAM_CLOUD_TOKEN not set' }
if ($autosync -eq '1') { Add-Finding 'OK' 'env.autosync' 'ENGRAM_CLOUD_AUTOSYNC=1' } else { Add-Finding 'BLOCKED' 'env.autosync' "ENGRAM_CLOUD_AUTOSYNC=$autosync (expected 1)" }
if ($allowlist) {
  $allowlistProjects = $allowlist -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
  Add-Finding 'OK' 'env.allowlist' "$($allowlistProjects.Count) projects in allowlist"
} else { Add-Finding 'BLOCKED' 'env.allowlist' 'ENGRAM_CLOUD_ALLOWED_PROJECTS not set' }

# --- 6. Postgres materializer ------------------------------------------------
$pgCheck = Test-NetConnection -ComputerName 127.0.0.1 -Port $script:PostgresPort -InformationLevel Quiet -WarningAction SilentlyContinue
if ($pgCheck) {
  Add-Finding 'OK' 'postgres' "$($script:PostgresPort) reachable (WSL Postgres materializer)"
  $chunks = Invoke-WslPsql "SELECT count(*) FROM cloud_chunks"
  $mutations = Invoke-WslPsql "SELECT count(*) FROM cloud_mutations"
  if ($chunks) { Add-Finding 'OK' 'postgres.chunks' "cloud_chunks=$($chunks -join ',')" }
  if ($mutations) { Add-Finding 'OK' 'postgres.mutations' "cloud_mutations=$($mutations -join ',')" }
} else {
  Add-Finding 'WARN' 'postgres' "Postgres on $script:PostgresPort not reachable. materialize-mutations will fail but sync --cloud may still work"
}

# --- 7. SQLite integrity -----------------------------------------------------
$integrity = Invoke-WslSqlite "PRAGMA integrity_check"
if (-not $integrity) {
  # WSL sqlite3 hung or returned nothing — DB might be locked by another process.
  Add-Finding 'WARN' 'sqlite' 'PRAGMA integrity_check returned no output. Live DB may be locked or copy is stale.'
} elseif ($integrity -contains 'ok') {
  Add-Finding 'OK' 'sqlite' 'integrity_check=ok'
} else {
  Add-Finding 'BLOCKED' 'sqlite' "integrity_check failed: $($integrity -join '; ')"
}

# --- 8. Mutation queue -------------------------------------------------------
$totalMutations = Invoke-WslSqlite "SELECT count(*) FROM sync_mutations"
if ($totalMutations) { Add-Finding 'OK' 'queue.total' "total mutations=$($totalMutations -join ',')" }

# Invalid categories
$invalidObs = Invoke-WslSqlite "SELECT count(*) FROM sync_mutations WHERE entity='observation' AND op='upsert' AND (json_extract(payload,'$.title') IS NULL OR json_extract(payload,'$.title')='' OR json_extract(payload,'$.session_id') IS NULL OR json_extract(payload,'$.session_id')='' OR json_extract(payload,'$.type') IS NULL OR json_extract(payload,'$.type')='' OR json_extract(payload,'$.content') IS NULL OR json_extract(payload,'$.content')='')"
if ($invalidObs -and $invalidObs -ne '0') {
  Add-Finding 'BLOCKED' 'queue.invalid' "invalid observation upserts=$($invalidObs -join ','). Run repair.ps1"
} else {
  Add-Finding 'OK' 'queue.invalid' 'no invalid observation upserts'
}

$invalidSess = Invoke-WslSqlite "SELECT count(*) FROM sync_mutations WHERE entity='session' AND op='upsert' AND (json_extract(payload,'$.id') IS NULL OR json_extract(payload,'$.id')='')"
if ($invalidSess -and $invalidSess -ne '0') {
  Add-Finding 'BLOCKED' 'queue.invalid' "invalid session upserts=$($invalidSess -join ','). Run repair.ps1"
} else {
  Add-Finding 'OK' 'queue.invalid' 'no invalid session upserts'
}

$invalidPrompt = Invoke-WslSqlite "SELECT count(*) FROM sync_mutations WHERE entity='prompt' AND op='upsert' AND (json_extract(payload,'$.content') IS NULL OR json_extract(payload,'$.content')='')"
if ($invalidPrompt -and $invalidPrompt -ne '0') {
  Add-Finding 'BLOCKED' 'queue.invalid' "invalid prompt upserts=$($invalidPrompt -join ','). Run repair.ps1"
} else {
  Add-Finding 'OK' 'queue.invalid' 'no invalid prompt upserts'
}

# Missing entity_key
$missingKey = Invoke-WslSqlite "SELECT count(*) FROM sync_mutations WHERE entity_key IS NULL OR entity_key=''"
if ($missingKey -and $missingKey -ne '0') {
  Add-Finding 'BLOCKED' 'queue.invalid' "mutations with missing entity_key=$($missingKey -join ','). Run repair.ps1"
}

# Relations (cloud schema doesn't accept)
$relations = Invoke-WslSqlite "SELECT count(*) FROM sync_mutations WHERE entity='relation'"
if ($relations -and $relations -ne '0') {
  Add-Finding 'WARN' 'queue.relations' "$($relations -join ',') relation entities queued. Cloud schema doesn't accept these; repair will prune."
}

# --- 9. Allowlist collision --------------------------------------------------
if ($allowlist) {
  $allowedSet = $allowlist -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
  $allowedSql = $allowedSet -join "','"
  $allowedSql = "'$allowedSql'"
  $nonAllowed = Invoke-WslSqlite "SELECT count(*) FROM sync_mutations WHERE project NOT IN ($allowedSql)"
  if ($nonAllowed -and $nonAllowed -ne '0') {
    Add-Finding 'BLOCKED' 'allowlist.collision' "$($nonAllowed -join ',') mutations queued for projects NOT in allowlist. Cloud will 403 them. Run repair.ps1."
  } else {
    Add-Finding 'OK' 'allowlist.collision' 'all queued mutations belong to allowlisted projects'
  }
}

# --- 10. Repairable observations ---------------------------------------------
$repairableTitle = Invoke-WslSqlite "SELECT count(*) FROM observations WHERE (title IS NULL OR title='') AND content IS NOT NULL AND content != '' AND deleted_at IS NULL"
if ($repairableTitle -and $repairableTitle -ne '0') {
  Add-Finding 'WARN' 'observations.repairable' "$($repairableTitle -join ',') observations have empty title but valid content. repair.ps1 will extract first line."
}

$repairableSid = Invoke-WslSqlite "SELECT count(*) FROM observations WHERE (session_id IS NULL OR session_id='') AND content IS NOT NULL AND content != '' AND deleted_at IS NULL"
if ($repairableSid -and $repairableSid -ne '0') {
  Add-Finding 'WARN' 'observations.repairable' "$($repairableSid -join ',') observations have empty session_id. repair.ps1 will set to manual-save-<project>."
}

# --- Output ------------------------------------------------------------------
function Format-Findings {
  $ok = $script:Findings | Where-Object { $_.Severity -eq 'OK' }
  $warn = $script:Findings | Where-Object { $_.Severity -eq 'WARN' }
  $blocked = $script:Findings | Where-Object { $_.Severity -eq 'BLOCKED' }

  Write-Host "`n=== Engram Sync Doctor ===" -ForegroundColor Cyan
  Write-Host "Project root: $($PWD)"
  Write-Host "Timestamp:    $(Get-Date -Format 'yyyy-MM-ddTHH:mm:ssZ')"
  Write-Host "Daemon:       $(if ($daemonProcs) { "running (PID $daemonPid)" } else { 'NOT RUNNING' })"
  Write-Host "Cloud:        $($script:CloudUrl)`n"

  foreach ($f in ($ok + $warn + $blocked | Group-Object Severity | ForEach-Object { $_.Group })) {
    $color = switch ($f.Severity) {
      'OK'      { 'Green' }
      'WARN'    { 'Yellow' }
      'BLOCKED' { 'Red' }
      default   { 'White' }
    }
    Write-Host ("[{0,-7}] {1,-30} {2}" -f $f.Severity, $f.Category, $f.Message) -ForegroundColor $color
  }

  Write-Host ''
  if ($blocked) {
    Write-Host "Verdict: BLOCKED. Run repair.ps1 to clear blocking categories." -ForegroundColor Red
  } elseif ($warn) {
    Write-Host "Verdict: DEGRADED. Review warnings; consider running repair.ps1." -ForegroundColor Yellow
  } else {
    Write-Host "Verdict: HEALTHY. No action required." -ForegroundColor Green
  }
}

if ($Json) {
  $script:Findings | ConvertTo-Json -Depth 3
} else {
  Format-Findings
}

if ($script:Findings | Where-Object { $_.Severity -eq 'BLOCKED' }) { exit 1 } else { exit 0 }
