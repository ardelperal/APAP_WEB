[CmdletBinding(DefaultParameterSetName = 'Profile')]
param(
    [Parameter(ParameterSetName='Profile',Mandatory)][string]$Profile,
    [Parameter(ParameterSetName='Tier',Mandatory)][ValidateSet('minimax','openai')][string]$Provider,
    [Parameter(ParameterSetName='Tier',Mandatory)][ValidateSet('cheap','balanced','powerful')][string]$Tier,
    [Parameter(ParameterSetName='List',Mandatory)][switch]$ListModels,
    [Parameter(ParameterSetName='Scope',Mandatory)][switch]$WhatIfScope,
    [Parameter(ParameterSetName='Rollback',Mandatory)][string]$RollbackManifest,
    [ValidateSet('OpenCode','Pi','Codex')][string[]]$Targets=@('OpenCode','Pi','Codex'),
    [string]$OpenCodePath="$HOME\.config\opencode\opencode.json",
    [string]$PiPath="$HOME\.pi\gentle-ai\models.json",
    [string]$PiProfilesRoot="$HOME\.pi\gentle-ai\profiles",
    [string]$PiAgentsRoot="$HOME\.pi\agent\agents",
    [string]$PiSettingsPath="$HOME\.pi\agent\settings.json",
    [string]$CodexRoot="$HOME\.codex",
    [string]$BackupRoot="$HOME\.gentle-ai\backups\model-profiles",
    [switch]$Apply,[switch]$ValidateOnly,[switch]$SkipRuntimeValidation,
    [Parameter(DontShow)][switch]$InternalNoCatalog,
    [Parameter(DontShow)][string]$InternalFailApplyPath,
    [Parameter(DontShow)][string[]]$InternalFailRestorePaths=@()
)
$ErrorActionPreference='Stop'

function Read-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "File not found: $Path" }
    try { Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json -AsHashtable -Depth 100 } catch { throw "Invalid JSON at $Path. $_" }
}
function Write-Atomic([string]$Path,[string]$Content) {
    if($InternalFailApplyPath -and (Full $Path)-eq(Full $InternalFailApplyPath)){throw "Injected apply failure: $Path"}
    $parent=Split-Path -Parent $Path; if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force|Out-Null }
    $temp=Join-Path $parent ".ai-model-profile.$([guid]::NewGuid().ToString('N')).tmp"
    try { [IO.File]::WriteAllText($temp,$Content,[Text.UTF8Encoding]::new($false)); [IO.File]::Move($temp,$Path,$true) }
    finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force } }
}
function Write-AtomicBytes([string]$Path,[byte[]]$Bytes) {
    if(@($InternalFailRestorePaths|ForEach-Object{Full $_}) -contains (Full $Path)){throw "Injected restoration failure: $Path"}
    $parent=Split-Path -Parent $Path; if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force|Out-Null }
    $temp=Join-Path $parent ".ai-model-profile.$([guid]::NewGuid().ToString('N')).tmp"
    try { [IO.File]::WriteAllBytes($temp,$Bytes); [IO.File]::Move($temp,$Path,$true) }
    finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force } }
}
function Write-ApplyBytes([string]$Path,[byte[]]$Bytes) {
    if($InternalFailApplyPath -and (Full $Path)-eq(Full $InternalFailApplyPath)){throw "Injected apply failure: $Path"}
    $parent=Split-Path -Parent $Path;$temp=Join-Path $parent ".ai-model-profile.$([guid]::NewGuid().ToString('N')).tmp"
    try{[IO.File]::WriteAllBytes($temp,$Bytes);[IO.File]::Move($temp,$Path,$true)}finally{if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Force}}
}
function Full([string]$Path) { [IO.Path]::GetFullPath($Path) }
function Is-Within([string]$Path,[string]$Root) { (Full $Path).StartsWith((Full $Root).TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) }
function Assert-SafeName([string]$Name,[string]$Kind) { if($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$' -or $Name -in @('.','..')){throw "Unsafe $Kind '$Name'."} }
function Assert-SafePath([string]$Path,[string]$Root) {
    $full=Full $Path;$rootFull=Full $Root;if($full-ne$rootFull-and-not(Is-Within $full $rootFull)){throw "Path escapes canonical root: $full"}
    $cursor=$full
    while($cursor -and ($cursor-eq$rootFull -or (Is-Within $cursor $rootFull))){if(Test-Path -LiteralPath $cursor){$item=Get-Item -LiteralPath $cursor -Force;if($item.Attributes-band[IO.FileAttributes]::ReparsePoint){throw "Reparse traversal is not allowed: $cursor"}};if($cursor-eq$rootFull){break};$cursor=Split-Path -Parent $cursor}
    $full
}
function Assert-NotCredentialPath([string]$Path) {
    foreach($part in (Full $Path).Split([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar)){if($part -match '(?i)^(auth\.json|.*credential.*|secrets?(\..*)?|local[-_.]?auth(\..*)?)$'){throw "Credential-sensitive path is forbidden: $Path"}}
}
function Assert-AuthorizedTarget([string]$Path,[string]$Root,[string[]]$ExpectedNames,[switch]$RootTarget) {
    Assert-NotCredentialPath $Path;Assert-NotCredentialPath $Root
    $safe=Assert-SafePath $Path $Root
    if($RootTarget){if($safe-ne(Full $Root)){throw "Target must equal trusted root: $Root"}}
    elseif([IO.Path]::GetFileName($safe)-notin$ExpectedNames){throw "Unexpected target filename: $safe"}
    $safe
}
function Get-TrustedHome {if($env:USERPROFILE){Full $env:USERPROFILE}elseif($env:HOME){Full $env:HOME}else{throw 'USERPROFILE or HOME is required.'}}
function Hash([string]$Path) { (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash }
function Size([string]$Path) { (Get-Item -LiteralPath $Path).Length }
function Write-Manifest([string]$Path,$Value) { Write-Atomic $Path ($Value|ConvertTo-Json -Depth 30);Write-Atomic "$Path.sha256" (Hash $Path) }
function Assert-String($Value,[string]$At,[int]$Min=0) { if ($Value -isnot [string] -or $Value.Length -lt $Min) { throw "$At must be a string with minimum length $Min." } }
function Assert-Keys([hashtable]$Object,[string[]]$Allowed,[string]$At) { foreach($key in $Object.Keys){ if($key -notin $Allowed){ throw "$At has unsupported property '$key'." } } }
function Test-ProfileSchema([hashtable]$Data) {
    Assert-Keys $Data @('schemaVersion','name','models','pi','codex') '$'
    foreach($required in @('schemaVersion','name','models')){if(-not $Data.ContainsKey($required)){throw "Profile is missing required property '$required'."}}
    if($Data.schemaVersion -ne 'ai-model-profile/v1'){throw "Unsupported schemaVersion: $($Data.schemaVersion)"}
    Assert-String $Data.name '$.name' 1
    Assert-SafeName $Data.name 'profile name'
    if($Data.models -isnot [hashtable] -or $Data.models.Count -lt 1){throw '$.models must be a non-empty object.'}
    foreach($key in $Data.models.Keys){Assert-String $Data.models[$key] "$.models.$key" 3}
    if($Data.ContainsKey('pi')){if($Data.pi -isnot [hashtable]){throw '$.pi must be an object.'};Assert-Keys $Data.pi @('providerMap') '$.pi';if($Data.pi.ContainsKey('providerMap')){if($Data.pi.providerMap -isnot [hashtable]){throw '$.pi.providerMap must be an object.'};foreach($key in $Data.pi.providerMap.Keys){Assert-String $Data.pi.providerMap[$key] "$.pi.providerMap.$key" 0}}}
    if($Data.ContainsKey('codex')){if($Data.codex -isnot [hashtable]){throw '$.codex must be an object.'};Assert-Keys $Data.codex @('strong','mid','cheap') '$.codex';foreach($tier in $Data.codex.Keys){$v=$Data.codex[$tier];if($v -isnot [hashtable]){throw "$.codex.$tier must be an object."};Assert-Keys $v @('model','reasoningEffort') "$.codex.$tier";foreach($r in @('model','reasoningEffort')){if(-not $v.ContainsKey($r)){throw "$.codex.$tier is missing '$r'."}};Assert-String $v.model "$.codex.$tier.model" 1;if($v.reasoningEffort -notin @('low','medium','high','xhigh')){throw "$.codex.$tier.reasoningEffort is invalid."}}}
}
function Convert-PiModel([string]$Model,[hashtable]$ProviderMap) {
    $parts=$Model -split '/',2;if($parts.Count-ne 2){throw "Model '$Model' must include provider/model."};$p=$parts[0];$m=$parts[1]
    if($ProviderMap.ContainsKey($p)){$p=$ProviderMap[$p]}elseif($p -eq 'minimax-coding-plan'){$p='minimax'}elseif($p -eq 'openai'){$p='openai-codex'}
    if($m -eq 'MiniMax-M2.5-highspeed'){$m='MiniMax-M2.7-highspeed'}elseif($m -eq 'gpt-5.5-pro'){$m='gpt-5.5'}elseif($p -eq 'opencode' -or $m -eq 'mimo-v2.5-free'){return $null}
    "$p/$m"
}
function Set-TomlOwned([string]$Content,[string]$Model,[string]$Effort) {
    foreach($value in @($Model,$Effort)){if($value -notmatch '^[A-Za-z0-9._:/-]+$'){throw "Unsafe TOML scalar '$value'."}}
    $lines=[Collections.Generic.List[string]]::new();foreach($line in ($Content -split "`r?`n",0,'RegexMatch')){$lines.Add($line)}
    $rootEnd=$lines.Count;for($i=0;$i-lt$lines.Count;$i++){if($lines[$i]-match '^\s*\['){$rootEnd=$i;break}}
    foreach($owned in @(@('model',$Model),@('model_reasoning_effort',$Effort))){$found=$false;for($i=0;$i-lt$rootEnd;$i++){if($lines[$i]-match "^\s*$($owned[0])\s*="){$indent=([regex]::Match($lines[$i],'^\s*')).Value;$comment=if($lines[$i]-match '(\s+#.*)$'){$Matches[1]}else{''};$lines[$i]="$indent$($owned[0]) = `"$($owned[1])`"$comment";$found=$true;break}};if(-not$found){$lines.Insert($rootEnd,"$($owned[0]) = `"$($owned[1])`"");$rootEnd++}}
    ($lines -join "`n").TrimEnd()+"`n"
}
function Result([string]$Operation,$ProfileName,$TargetNames,$Changes,$Backups,$Manifest,$Restart){[pscustomobject]@{status='success';operation=$Operation;profile=$ProfileName;targets=@($TargetNames);changes=@($Changes);backups=@($Backups);rollbackManifest=$Manifest;restartRequired=@($Restart);credentialsPreserved=$true;skill_resolution='paths-injected'}|ConvertTo-Json -Depth 30}

$trustedHome=Get-TrustedHome
$trustedOpenCode=Join-Path $trustedHome '.config\opencode';$trustedPiGentle=Join-Path $trustedHome '.pi\gentle-ai';$trustedPiAgent=Join-Path $trustedHome '.pi\agent';$trustedCodex=Join-Path $trustedHome '.codex';$trustedBackup=Join-Path $trustedHome '.gentle-ai\backups\model-profiles'
$OpenCodePath=Assert-AuthorizedTarget $OpenCodePath $trustedOpenCode @('opencode.json','opencode.jsonc')
$PiPath=Assert-AuthorizedTarget $PiPath $trustedPiGentle @('models.json')
$PiProfilesRoot=Assert-AuthorizedTarget $PiProfilesRoot (Join-Path $trustedPiGentle 'profiles') @() -RootTarget
$PiAgentsRoot=Assert-AuthorizedTarget $PiAgentsRoot (Join-Path $trustedPiAgent 'agents') @() -RootTarget
$PiSettingsPath=Assert-AuthorizedTarget $PiSettingsPath $trustedPiAgent @('settings.json')
$CodexRoot=Assert-AuthorizedTarget $CodexRoot $trustedCodex @() -RootTarget
$BackupRoot=Assert-AuthorizedTarget $BackupRoot $trustedBackup @() -RootTarget

if($PSCmdlet.ParameterSetName -in @('Tier','List','Scope')){
    $adapter=Join-Path $PSScriptRoot 'adapters\Set-OpenCodeTierMapping.ps1';$args=@{ConfigPath=$OpenCodePath;SkipRuntimeValidation=$SkipRuntimeValidation;CandidateOnly=$true;InternalNoCatalog=$InternalNoCatalog}
    if($PSCmdlet.ParameterSetName -eq 'Tier'){$args.Provider=$Provider;$args.Tier=$Tier}else{$key = if($PSCmdlet.ParameterSetName -eq 'List'){'ListModels'}else{'WhatIfScope'};$args[$key]=$true}
    $raw=& $adapter @args|ConvertFrom-Json;$candidateBytes=if($raw.PSObject.Properties['candidateBase64']){[Convert]::FromBase64String($raw.candidateBase64)}else{$null};$raw.PSObject.Properties.Remove('candidateBase64')
    if($PSCmdlet.ParameterSetName-ne'Tier'-or-not$Apply){Result $raw.operation $(if($Provider){"$Provider/$Tier"}else{$null}) @('OpenCode') @($raw) @() $null @();exit 0}
    $runRoot=Join-Path $BackupRoot "$(Get-Date -Format 'yyyyMMdd-HHmmss.fffffff')-$([guid]::NewGuid().ToString('N'))";New-Item -ItemType Directory -Path $runRoot -Force|Out-Null;$backup=Join-Path $runRoot '001-opencode.json.backup';Copy-Item -LiteralPath $OpenCodePath -Destination $backup
    $backups=@(@{target='OpenCode';role='OpenCode.config';path=(Full $OpenCodePath);backup=(Full $backup);existed=$true;sha256=(Hash $backup);size=(Size $backup)});$manifestPath=Join-Path $runRoot 'rollback.json';$manifest=@{schemaVersion='ai-model-profile-rollback/v1';transactionId=[guid]::NewGuid().ToString('N');state='pending';profile="$Provider-$Tier";targets=@('OpenCode');files=$backups;applyErrors=@();rollbackErrors=@()};Write-Manifest $manifestPath $manifest
    try{Write-ApplyBytes $OpenCodePath $candidateBytes;$manifest.state='applied'}catch{$original=$_.Exception.Message;$restore=@();foreach($e in $backups){try{if($e.existed){Write-AtomicBytes $e.path ([IO.File]::ReadAllBytes($e.backup))}elseif(Test-Path -LiteralPath $e.path){Remove-Item -LiteralPath $e.path -Force}}catch{$restore+="$($e.path): $($_.Exception.Message)"}};$manifest.state='failed';$manifest.applyErrors=@($original);$manifest.rollbackErrors=$restore;Write-Manifest $manifestPath $manifest;$suffix=if($restore){" Restoration failures: $($restore -join '; ')"}else{''};throw "Apply failed: $original.$suffix"};Write-Manifest $manifestPath $manifest
    Result 'apply' "$Provider/$Tier" @('OpenCode') @($raw) $backups $manifestPath @('OpenCode');exit 0
}
if($PSCmdlet.ParameterSetName-eq'Rollback'){
    if(-not$Apply){throw 'Rollback requires -Apply.'};if(-not$PSBoundParameters.ContainsKey('Targets')){throw 'Rollback requires explicit -Targets.'};$manifestPath=Assert-SafePath $RollbackManifest $BackupRoot;$seal="$manifestPath.sha256";if(-not(Test-Path -LiteralPath $seal -PathType Leaf)-or([IO.File]::ReadAllText($seal).Trim())-ne(Hash $manifestPath)){throw 'Rollback manifest integrity mismatch.'};$m=Read-Json $manifestPath
    if($m.schemaVersion-ne'ai-model-profile-rollback/v1'){throw "Unsupported rollback schemaVersion: $($m.schemaVersion)"};if($m.state-notin@('pending','applied','failed')){throw 'Rollback manifest state is invalid.'};if(-not$m.transactionId-or-not$m.files){throw 'Rollback manifest is incomplete.'}
    if((@($m.targets|Sort-Object)-join'|') -ne (@($Targets|Sort-Object)-join'|')){throw 'Rollback targets do not match explicit dispatcher targets.'}
    $allowed=@{};if($Targets-contains'OpenCode'){$allowed['OpenCode.config']=$OpenCodePath};if($Targets-contains'Codex'){foreach($n in @('strong','mid','cheap')){$allowed["Codex.$n"]=Assert-AuthorizedTarget (Join-Path $CodexRoot "sdd-$n.config.toml") $CodexRoot @("sdd-$n.config.toml")}};if($Targets-contains'Pi'){Assert-SafeName $m.profile 'profile name';$allowed['Pi.active']=$PiPath;$allowed['Pi.profile']=Assert-AuthorizedTarget (Join-Path $PiProfilesRoot "$($m.profile).json") $PiProfilesRoot @("$($m.profile).json");$allowed['Pi.settings']=$PiSettingsPath}
    $trusted=Full (Split-Path -Parent $manifestPath);$seen=@{};$errors=@();foreach($e in $m.files){try{Assert-String $e.role 'rollback role' 1;if($seen.ContainsKey($e.role)){throw 'duplicate role'};$seen[$e.role]=$true;$expected=$allowed[$e.role];if(-not$expected-and$e.role-match'^Pi.agent:(.+)$' -and $Targets-contains'Pi'){$agent=$Matches[1];Assert-SafeName $agent 'Pi agent';$expected=Assert-AuthorizedTarget (Join-Path $PiAgentsRoot "$agent.md") $PiAgentsRoot @("$agent.md")};if(-not$expected){throw 'unknown role'};if((Full $e.path)-ne$expected){throw 'target path mismatch'};Assert-NotCredentialPath $e.backup;Assert-SafePath $e.backup $trusted|Out-Null;if(-not(Test-Path -LiteralPath $e.backup -PathType Leaf)){throw 'backup missing'};if((Size $e.backup)-ne[long]$e.size-or(Hash $e.backup)-ne$e.sha256){throw 'backup integrity mismatch'};if($e.existed){Write-AtomicBytes $expected ([IO.File]::ReadAllBytes($e.backup))}elseif(Test-Path -LiteralPath $expected){Remove-Item -LiteralPath $expected -Force}}catch{$errors+="$($e.role): $($_.Exception.Message)"}}
    $m.state=if($errors){'rollback-failed'}else{'rolled-back'};$m.rollbackErrors=$errors;Write-Manifest $manifestPath $m;if($errors){throw "Rollback failed for $($errors.Count) target(s): $($errors-join'; ')"};Result 'rollback' $m.profile $m.targets @() @() $manifestPath $m.targets;exit 0
}

$data=Read-Json $Profile;Test-ProfileSchema $data
if($Targets -contains 'Codex'){if(-not $data.codex){throw 'Codex target requires codex mappings.'};foreach($n in @('strong','mid','cheap')){if(-not $data.codex.ContainsKey($n)){throw "Codex target requires complete '$n' mapping."}}}
$candidates=@()
if($Targets -contains 'OpenCode'){$config=Read-Json $OpenCodePath;if($config.agent -isnot [hashtable]){throw 'OpenCode config has no agent block.'};$changed=@();foreach($name in $data.models.Keys){Assert-SafeName $name 'agent name';$derivedTargets=@($name,"$name-and","$name-fallback","$name-and-fallback");if($name -eq 'gentle-orchestrator'){$derivedTargets+=@('general','sdd-orchestrator-and','sdd-orchestrator-and-fallback')};$present=@($derivedTargets|Where-Object{$config.agent.ContainsKey($_)});if(-not $present){throw "Profile agent '$name' is missing from OpenCode config: $OpenCodePath"};foreach($agentName in $present){$before=$config.agent[$agentName].model;if($before -ne $data.models[$name]){$config.agent[$agentName].model=$data.models[$name];$changed+=@{agent=$agentName;source=$name;before=$before;after=$data.models[$name]}}}};$candidates+=@{target='OpenCode';role='OpenCode.config';path=$OpenCodePath;content=$config|ConvertTo-Json -Depth 100;changes=$changed}}
if($Targets -contains 'Pi'){$active=Read-Json $PiPath;$map=if($data.pi){$data.pi.providerMap}else{@{}};$routed=@{};$skipped=@();foreach($name in $data.models.Keys){$piName=if($name -eq 'sdd-propose'){'sdd-proposal'}else{$name};$mapped=Convert-PiModel $data.models[$name] $map;if($null -eq $mapped){$skipped+=$name;continue};$routed[$piName]=$mapped}
    if(-not $active.ContainsKey('models')){$active.models=@{}};foreach($name in $routed.Keys){if($name -ne 'gentle-orchestrator'){$active.models[$name]=$routed[$name]}};$active.profile=$data.name
    $candidates+=@{target='Pi';role='Pi.active';path=$PiPath;content=$active|ConvertTo-Json -Depth 100;changes=@{routing=$routed;skipped=$skipped}}
    $library=Assert-AuthorizedTarget (Join-Path $PiProfilesRoot "$($data.name).json") $PiProfilesRoot @("$($data.name).json");$lib=if(Test-Path -LiteralPath $library){Read-Json $library}else{@{}};$lib.schemaVersion='ai-model-profile/v1';$lib.profile=$data.name;if(-not$lib.ContainsKey('models')){$lib.models=@{}};foreach($name in $routed.Keys){if($name -ne 'gentle-orchestrator'){$lib.models[$name]=$routed[$name]}};$candidates+=@{target='Pi';role='Pi.profile';path=$library;content=$lib|ConvertTo-Json -Depth 100;changes=@('profile-library')}
    if($routed.ContainsKey('gentle-orchestrator')){$settings=if(Test-Path -LiteralPath $PiSettingsPath){Read-Json $PiSettingsPath}else{@{}};$parts=$routed['gentle-orchestrator']-split'/',2;$settings.defaultProvider=$parts[0];$settings.defaultModel=$parts[1];$candidates+=@{target='Pi';role='Pi.settings';path=$PiSettingsPath;content=$settings|ConvertTo-Json -Depth 100;changes=@('defaultProvider','defaultModel')}}
    if(Test-Path -LiteralPath $PiAgentsRoot -PathType Container){foreach($name in ($routed.Keys|Where-Object{$_ -ne 'gentle-orchestrator'})){Assert-SafeName $name 'Pi agent';$agentPath=Assert-AuthorizedTarget (Join-Path $PiAgentsRoot "$name.md") $PiAgentsRoot @("$name.md");if(Test-Path -LiteralPath $agentPath){$text=[IO.File]::ReadAllText($agentPath);$new=if($text -match '(?m)^model:\s*.*$'){$text -replace '(?m)^model:\s*.*$',"model: $($routed[$name])"}else{$text};$candidates+=@{target='Pi';role="Pi.agent:$name";path=$agentPath;content=$new;changes=@($name)}}}}
}
if($Targets -contains 'Codex'){foreach($name in @('strong','mid','cheap')){$path=Assert-AuthorizedTarget (Join-Path $CodexRoot "sdd-$name.config.toml") $CodexRoot @("sdd-$name.config.toml");if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Codex target missing: $path"};$mapping=$data.codex[$name];$content=Set-TomlOwned ([IO.File]::ReadAllText($path)) $mapping.model $mapping.reasoningEffort;$candidates+=@{target='Codex';role="Codex.$name";path=$path;content=$content;changes=@($name)}}}
$changes=@($candidates|ForEach-Object{@{target=$_.target;path=$_.path;changes=$_.changes}});if($ValidateOnly-or-not$Apply){Result $(if($ValidateOnly){'validate'}else{'preview'}) $data.name $Targets $changes @() $null @();exit 0}
$runRoot=Join-Path $BackupRoot "$(Get-Date -Format 'yyyyMMdd-HHmmss.fffffff')-$([guid]::NewGuid().ToString('N'))";New-Item -ItemType Directory -Path $runRoot -Force|Out-Null;$backups=@();$i=0
foreach($c in $candidates){$i++;$backup=Join-Path $runRoot ("{0:D3}-{1}.backup" -f $i,[IO.Path]::GetFileName($c.path));$exists=Test-Path -LiteralPath $c.path -PathType Leaf;if($exists){Copy-Item -LiteralPath $c.path -Destination $backup}else{[IO.File]::WriteAllBytes($backup,[byte[]]@())};$backups+=@{target=$c.target;role=$c.role;path=(Full $c.path);backup=(Full $backup);existed=$exists;sha256=(Hash $backup);size=(Size $backup)}}
$manifestPath=Join-Path $runRoot 'rollback.json';$manifest=@{schemaVersion='ai-model-profile-rollback/v1';transactionId=[guid]::NewGuid().ToString('N');state='pending';profile=$data.name;targets=$Targets;files=$backups;applyErrors=@();rollbackErrors=@()};Write-Manifest $manifestPath $manifest
try{foreach($c in $candidates){Write-Atomic $c.path $c.content};$manifest.state='applied'}catch{$original=$_.Exception.Message;$restore=@();foreach($e in $backups){try{if($e.existed){Write-AtomicBytes $e.path ([IO.File]::ReadAllBytes($e.backup))}elseif(Test-Path -LiteralPath $e.path){Remove-Item -LiteralPath $e.path -Force}}catch{$restore+="$($e.path): $($_.Exception.Message)"}};$manifest.state='failed';$manifest.applyErrors=@($original);$manifest.rollbackErrors=$restore;Write-Manifest $manifestPath $manifest;throw "Apply failed: $original. Restoration failures: $($restore -join '; ')"}
Write-Manifest $manifestPath $manifest;Result 'apply' $data.name $Targets $changes $backups $manifestPath $Targets
