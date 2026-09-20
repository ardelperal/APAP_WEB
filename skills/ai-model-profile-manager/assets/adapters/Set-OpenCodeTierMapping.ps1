<#
.SYNOPSIS
    Bulk-apply provider + tier model mapping to the gentle-orchestrator agent
    and its managed sub-agents in the canonical opencode.json.
#>

[CmdletBinding(DefaultParameterSetName = 'Apply')]
param(
    [Parameter()][ValidateSet('minimax', 'openai')][string]$Provider,
    [Parameter()][ValidateSet('cheap', 'balanced', 'powerful')][string]$Tier,
    [Parameter(ParameterSetName = 'Apply')][switch]$Apply,
    [Parameter()][string]$ConfigPath,
    [Parameter()][string]$BackupRoot,
    [switch]$CandidateOnly,
    [Parameter(ParameterSetName = 'ListModels', Mandatory = $true)][switch]$ListModels,
    [Parameter(ParameterSetName = 'WhatIfScope', Mandatory = $true)][switch]$WhatIfScope,
    [switch]$SkipRuntimeValidation,
    [Parameter(DontShow)][switch]$InternalNoCatalog
)

$ErrorActionPreference = 'Stop'
if($Apply -and -not$CandidateOnly){throw 'This adapter is candidate-only; apply through Invoke-AIModelProfile.ps1.'}

$strongTierAgents = @(
    'gentle-orchestrator', 'jd-fix-agent', 'jd-fix-agent-fallback',
    'jd-judge-a', 'jd-judge-a-fallback', 'jd-judge-b', 'jd-judge-b-fallback',
    'review-reliability', 'review-resilience', 'review-risk',
    'sdd-design', 'sdd-propose', 'sdd-verify'
)
$mediumTierAgents = @(
    'review-readability', 'sdd-apply', 'sdd-init', 'sdd-onboard'
)
$lightweightTierAgents = @(
    'sdd-explore', 'sdd-spec', 'sdd-tasks'
)
$archiveTierAgents = @('sdd-archive')
$refuterAgent = @('review-refuter')

$script:AgentCategories = @{
    strong = $strongTierAgents
    medium = $mediumTierAgents
    lightweight = $lightweightTierAgents
    archive = $archiveTierAgents
    refuter = $refuterAgent
}
$managedAgents = @($script:AgentCategories.Values | ForEach-Object { $_ } | Sort-Object -Unique)

$script:minimaxByTier = @{
    strong = @{ cheap = 'MiniMax-M2.7'; balanced = 'MiniMax-M3'; powerful = 'MiniMax-M3' }
    medium = @{ cheap = 'MiniMax-M2.7'; balanced = 'MiniMax-M2.7'; powerful = 'MiniMax-M3' }
    lightweight = @{ cheap = 'MiniMax-M2.7-highspeed'; balanced = 'MiniMax-M2.7-highspeed'; powerful = 'MiniMax-M3' }
    archive = @{ cheap = 'MiniMax-M2.5-highspeed'; balanced = 'MiniMax-M2.5-highspeed'; powerful = 'MiniMax-M3' }
    refuter = @{ cheap = 'MiniMax-M2.7'; balanced = 'MiniMax-M2.7'; powerful = 'MiniMax-M3' }
}

# OpenAI strong-tier agents retain the richer balanced terra mapping; other categories use luna until powerful.
$openaiStrongTierAgents = $strongTierAgents
$script:openaiByTier = @{
    strong = @{ cheap = 'openai/gpt-5.6-luna'; balanced = 'openai/gpt-5.6-terra'; powerful = 'openai/gpt-5.6-sol' }
    medium = @{ cheap = 'openai/gpt-5.6-luna'; balanced = 'openai/gpt-5.6-luna'; powerful = 'openai/gpt-5.6-sol' }
    lightweight = @{ cheap = 'openai/gpt-5.6-luna'; balanced = 'openai/gpt-5.6-luna'; powerful = 'openai/gpt-5.6-sol' }
    archive = @{ cheap = 'openai/gpt-5.6-luna'; balanced = 'openai/gpt-5.6-luna'; powerful = 'openai/gpt-5.6-sol' }
    refuter = @{ cheap = 'openai/gpt-5.6-luna'; balanced = 'openai/gpt-5.6-luna'; powerful = 'openai/gpt-5.6-sol' }
}
$script:TierVariant = @{ cheap = 'low'; balanced = 'medium'; powerful = 'high' }
$script:FallbackAgents = @('jd-fix-agent-fallback', 'jd-judge-a-fallback', 'jd-judge-b-fallback')

function Get-FileHashSafe([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
}

function Read-JsonFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Config file not found: $Path" }
    try { Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json -Depth 100 } catch { throw "Failed to parse JSON at $Path. $_" }
}

function Resolve-CanonicalConfigPath {
    if ($env:OPENCODE_CONFIG_CONTENT) { throw 'Canonical config is ambiguous because OPENCODE_CONFIG_CONTENT is set.' }
    if ($ConfigPath) {
        if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw "Explicit config not found: $ConfigPath" }
        return (Resolve-Path -LiteralPath $ConfigPath).Path
    }
    if ($env:OPENCODE_CONFIG) {
        if (-not (Test-Path -LiteralPath $env:OPENCODE_CONFIG -PathType Leaf)) { throw 'OPENCODE_CONFIG does not name an existing file.' }
        return (Resolve-Path -LiteralPath $env:OPENCODE_CONFIG).Path
    }
    $root = Join-Path $HOME '.config\opencode'
    $found = @('opencode.json', 'opencode.jsonc' | ForEach-Object { Join-Path $root $_ } | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
    if ($found.Count -ne 1) { throw "Expected exactly one canonical global opencode.json/jsonc; found $($found.Count)." }
    $found[0]
}

function Get-AgentCategory([string]$AgentName) {
    foreach ($cat in $script:AgentCategories.Keys) {
        if ($AgentName -in $script:AgentCategories[$cat]) { return $cat }
    }
    $null
}

function Get-Mapping([string]$Provider, [string]$Tier, [string]$AgentName) {
    # Returns the (model, variant) for the given (provider, tier, agent).
    # Throws on unknown provider, unknown tier, or agent not in any tier-category.
    $cat = Get-AgentCategory $AgentName
    if (-not $cat) {
        throw "Unknown agent '$AgentName' in scope — cannot map to a tier. Update the agent-category lists."
    }
    if ($Provider -notin @('minimax', 'openai')) { throw "Unknown provider '$Provider'." }
    $byTier = if ($Provider -eq 'minimax') { $script:minimaxByTier[$cat] } else { $script:openaiByTier[$cat] }
    if (-not $byTier) { throw "No tier mapping for provider=$Provider category=$cat" }
    $modelShort = $byTier[$Tier]
    if (-not $modelShort) { throw "Unknown tier '$Tier' for provider=$Provider category=$cat" }
    $model = if ($Provider -eq 'minimax') { "minimax-coding-plan/$modelShort" } else { $modelShort }
    $variant = $script:TierVariant[$Tier]
    [pscustomobject]@{ provider = $Provider; tier = $Tier; model = $model; variant = $variant }
}

function Get-ModelCatalog {
    $output = @(& opencode models 2>&1)
    if ($LASTEXITCODE -ne 0) { return @() }
    @($output | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ -match '^[^\s]+/[^\s]+$' })
}

function Resolve-Scope($Config) {
    if (-not $Config.agent) { throw "Config has no 'agent' section." }
    if (-not $Config.agent.PSObject.Properties['gentle-orchestrator']) { throw "Config has no 'gentle-orchestrator' agent. Nothing to apply to." }
    $orchestrator = $Config.agent.'gentle-orchestrator'
    $delegationList = @()
    if ($orchestrator.permission -and $orchestrator.permission.PSObject.Properties['task']) {
        $task = $orchestrator.permission.task
        if ($task -is [System.Array]) { $delegationList = @($task | ForEach-Object { [string]$_ }) }
        elseif ($task -is [System.Management.Automation.PSCustomObject]) { foreach ($p in $task.PSObject.Properties) { $delegationList += [string]$p.Name } }
    }
    if (-not $delegationList -or $delegationList.Count -eq 0) {
        Write-Warning 'gentle-orchestrator.permission.task is empty; falling back to regex scope (sdd-*, review-*, jd-*, explore).'
        $delegationList = @($Config.agent.PSObject.Properties.Name | Where-Object { $_ -match '^(sdd-|review-|jd-|explore$)' })
    }
    $candidates = @($delegationList | Where-Object { $_ -ne '*' -and $_ -ne 'general' })
    $missing = @(); $present = @()
    foreach ($name in $candidates) {
        if ($Config.agent.PSObject.Properties[$name]) { $present += $name }
        else { $missing += $name; Write-Warning "Scope agent '$name' is not defined in the config; skipping." }
    }
    $scope = @('gentle-orchestrator')
    foreach ($name in $present) { if ($name -ne 'gentle-orchestrator') { $scope += $name } }
    $fallbacksIncluded = @()
    foreach ($fb in $script:FallbackAgents) { if ($Config.agent.PSObject.Properties[$fb]) { $scope += $fb; $fallbacksIncluded += $fb } }
    [pscustomobject]@{ scope = $scope; missingAgents = $missing; fallbacksIncluded = $fallbacksIncluded }
}

function Set-AgentModelVariant($Agent, [string]$Model, [string]$Variant) {
    # AUDIT-FIX: fail closed is enforced before this function for every scoped agent; absent model is intentionally added only from a valid per-agent mapping.
    $hadModel = $Agent.PSObject.Properties.Name -contains 'model'
    $hadVariant = $Agent.PSObject.Properties.Name -contains 'variant'
    $oldModel = if ($hadModel) { $Agent.model } else { $null }
    $oldVariant = if ($hadVariant) { $Agent.variant } else { $null }
    if ($hadModel) { $Agent.model = $Model } else { $Agent | Add-Member -NotePropertyName model -NotePropertyValue $Model }
    if ($null -eq $Variant -or $Variant -eq '') { if ($hadVariant) { $Agent.PSObject.Properties.Remove('variant') } }
    elseif ($hadVariant) { $Agent.variant = $Variant } else { $Agent | Add-Member -NotePropertyName variant -NotePropertyValue $Variant }
    [pscustomobject]@{ oldModel = $oldModel; oldVariant = $oldVariant; newModel = $Agent.model; newVariant = if ($Agent.PSObject.Properties.Name -contains 'variant') { $Agent.variant } else { $null } }
}

function Test-Candidate([string]$CandidatePath) {
    if ($SkipRuntimeValidation) { return 'skipped' }
    $oldConfig = $env:OPENCODE_CONFIG
    $oldDisable = $env:OPENCODE_DISABLE_PROJECT_CONFIG
    try {
        $env:OPENCODE_CONFIG = $CandidatePath
        $env:OPENCODE_DISABLE_PROJECT_CONFIG = '1'
        $output = & opencode debug config 2>&1
        if ($LASTEXITCODE -ne 0) {
            $isMissing = $output -match 'not recognized|not found|cannot find|unknown command'
            if ($isMissing) {
                Write-Warning 'opencode debug config subcommand unavailable; falling back to JSON parse check.'
                try {
                    $null = Get-Content -Raw -LiteralPath $CandidatePath | ConvertFrom-Json -Depth 100
                    return 'fallback-json-parse'
                } catch {
                    throw "Candidate config is not valid JSON: $_"
                }
            }
            throw "opencode debug config rejected the candidate config. Exit=$LASTEXITCODE. Output: $output"
        }
        'passed'
    } finally {
        $env:OPENCODE_CONFIG = $oldConfig
        $env:OPENCODE_DISABLE_PROJECT_CONFIG = $oldDisable
    }
}

function Write-AtomicJson($Candidate, [string]$TargetPath) {
    # Atomic replace: write a sibling temp file, then overwrite the target atomically on the same volume.
    $configRoot = Split-Path -Parent $TargetPath
    $tempPath = Join-Path $configRoot ".ai-model-profile.$([guid]::NewGuid().ToString('N')).tmp.json"
    try {
        [System.IO.File]::WriteAllText($tempPath, ($Candidate | ConvertTo-Json -Depth 100), [System.Text.UTF8Encoding]::new($false))
        [System.IO.File]::Move($tempPath, $TargetPath, $true)
        $tempPath = $null
    } finally { if ($tempPath -and (Test-Path -LiteralPath $tempPath)) { Remove-Item -LiteralPath $tempPath -Force } }
}

function Format-Result($OrderedHashtable) { [pscustomobject]$OrderedHashtable | ConvertTo-Json -Depth 20 }

if ($ListModels) {
    $catalog = if($InternalNoCatalog){@()}else{Get-ModelCatalog}; $rows = @(); $unavailable = @()
    foreach ($provider in @('minimax', 'openai')) { foreach ($agent in $managedAgents) { foreach ($tierName in @('cheap', 'balanced', 'powerful')) { $row = Get-Mapping $provider $tierName $agent; if ($catalog -and $row.model -notin $catalog) { $unavailable += $row.model }; $rows += [pscustomobject]@{ provider = $provider; agent = $agent; tier = $tierName; model = $row.model; variant = $row.variant; available = ($catalog.Count -eq 0) -or ($row.model -in $catalog) } } } }
    Format-Result ([ordered]@{ operation = 'list-models'; mappings = $rows; unavailable = @($unavailable | Sort-Object -Unique); catalogCheck = if ($catalog.Count -gt 0) { 'live' } else { 'skipped' } }); exit 0
}

$canonicalPath = Resolve-CanonicalConfigPath; $configRoot = Split-Path -Parent $canonicalPath; $current = Read-JsonFile $canonicalPath
if ($WhatIfScope) { $scopeInfo = Resolve-Scope $current; Format-Result ([ordered]@{ operation = 'what-if-scope'; canonicalPath = $canonicalPath; scope = $scopeInfo.scope; missingAgents = $scopeInfo.missingAgents; fallbacksIncluded = $scopeInfo.fallbacksIncluded; generalExcluded = $true; agentCount = $scopeInfo.scope.Count }); exit 0 }
if (-not $Provider) { throw 'Provider is required (or use -ListModels / -WhatIfScope).' }
if (-not $Tier) { throw 'Tier is required (or use -ListModels / -WhatIfScope).' }
if ($current.PSObject.Properties['default_agent'] -and $current.default_agent -ne 'gentle-orchestrator') { Write-Warning "WARNING: default_agent is '$($current.default_agent)', expected 'gentle-orchestrator'. Continuing." }
$scopeInfo = Resolve-Scope $current
$catalog = if($InternalNoCatalog){@()}else{Get-ModelCatalog}
$candidate = $current | ConvertTo-Json -Depth 100 | ConvertFrom-Json -Depth 100
$changes = @(); $changedAgents = @()
foreach ($agentName in $scopeInfo.scope) {
    $mapping = Get-Mapping $Provider $Tier $agentName
    if ($catalog -and $mapping.model -notin $catalog) { Write-Warning "Model '$($mapping.model)' is not in the live 'opencode models' catalog. Continuing anyway." }
    $agent = $candidate.agent.PSObject.Properties[$agentName].Value
    $before = [pscustomobject]@{ model = $agent.model; variant = if ($agent.PSObject.Properties.Name -contains 'variant') { $agent.variant } else { $null } }
    $result = Set-AgentModelVariant $agent $mapping.model $mapping.variant
    if ($result.oldModel -ne $result.newModel -or $result.oldVariant -ne $result.newVariant) { $changedAgents += $agentName }
    $changes += [pscustomobject]@{ agent = $agentName; before = $before; after = [pscustomobject]@{ model = $result.newModel; variant = $result.newVariant } }
}
$tempCandidate = Join-Path $configRoot ".ai-model-profile.$([guid]::NewGuid().ToString('N')).tmp.json"; $candidateHash = $null; $validation = 'skipped'
try { [System.IO.File]::WriteAllText($tempCandidate, ($candidate | ConvertTo-Json -Depth 100), [System.Text.UTF8Encoding]::new($false)); $validation = Test-Candidate $tempCandidate; $candidateHash = Get-FileHashSafe $tempCandidate } finally { if (Test-Path -LiteralPath $tempCandidate) { Remove-Item -LiteralPath $tempCandidate -Force } }
$beforeHash = Get-FileHashSafe $canonicalPath
$result = [ordered]@{ operation = 'bulk-model-apply'; provider = $Provider; tier = $Tier; canonicalPath = $canonicalPath; scope = $scopeInfo.scope; missingAgents = $scopeInfo.missingAgents; fallbacksIncluded = $scopeInfo.fallbacksIncluded; generalExcluded = $true; changes = $changes; changedAgents = $changedAgents; dryRun = -not $Apply; validation = $validation; beforeHash = $beforeHash; candidateHash = $candidateHash; idempotent = ($beforeHash -eq $candidateHash) }
$candidateBase64 = [Convert]::ToBase64String([Text.UTF8Encoding]::new($false).GetBytes(($candidate | ConvertTo-Json -Depth 100)))
if($CandidateOnly){$result.candidateBase64=$candidateBase64;Format-Result $result;exit 0}
if (-not $Apply) { Format-Result $result; exit 0 }
if ($candidateHash -eq $beforeHash) { $result.afterHash = $beforeHash; $result.restartRequired = $false; Format-Result $result; exit 0 }
$backupBase = if ($BackupRoot) { if (-not (Test-Path -LiteralPath $BackupRoot)) { New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null }; Join-Path $BackupRoot "tier-$(Get-Date -Format 'yyyyMMdd-HHmmss.fffffff')-$([guid]::NewGuid().ToString('N')).backup" } else { "$canonicalPath.backup.$(Get-Date -Format 'yyyyMMdd-HHmmss.fffffff')-$([guid]::NewGuid().ToString('N'))" }
$backupPath = $backupBase; Copy-Item -LiteralPath $canonicalPath -Destination $backupPath
try { Write-AtomicJson $candidate $canonicalPath } catch { throw "Atomic write failed; backup retained at $backupPath. $_" }
$result.afterHash = Get-FileHashSafe $canonicalPath; $result.backupPath = $backupPath; $result.restartRequired = $true; Format-Result $result; exit 0
