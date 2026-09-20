BeforeAll {
    $script:Adapter=Join-Path (Join-Path (Split-Path -Parent $PSScriptRoot) 'adapters') 'Set-OpenCodeTierMapping.ps1'
    $script:Fixture=Join-Path $PSScriptRoot 'fixtures\opencode.json'
    function script:New-Config {$r=Join-Path ([IO.Path]::GetTempPath()) "adapter-$([guid]::NewGuid().ToString('N'))";New-Item -ItemType Directory $r|Out-Null;$p=Join-Path $r 'opencode.json';Copy-Item $script:Fixture $p;[pscustomobject]@{root=$r;path=$p}}
}
Describe 'candidate-only OpenCode tier adapter' {
    It 'returns candidate bytes without writing' {$c=New-Config;try{$h=(Get-FileHash $c.path).Hash;$r=&$script:Adapter -Provider openai -Tier powerful -ConfigPath $c.path -CandidateOnly -SkipRuntimeValidation -InternalNoCatalog|ConvertFrom-Json;$r.candidateBase64|Should -Not -BeNullOrEmpty;(Get-FileHash $c.path).Hash|Should -Be $h}finally{Remove-Item $c.root -Recurse -Force}}
    It 'rejects direct apply' {$c=New-Config;try{{&$script:Adapter -Provider openai -Tier cheap -ConfigPath $c.path -Apply -SkipRuntimeValidation -InternalNoCatalog}|Should -Throw '*candidate-only*'}finally{Remove-Item $c.root -Recurse -Force}}
    It 'reports scope without writing' {$c=New-Config;try{$r=&$script:Adapter -WhatIfScope -ConfigPath $c.path -CandidateOnly -InternalNoCatalog|ConvertFrom-Json;$r.scope|Should -Not -Contain general}finally{Remove-Item $c.root -Recurse -Force}}
    It 'lists all mappings without resolving config or invoking a live catalog' {$c=New-Config;try{$r=&$script:Adapter -ListModels -ConfigPath (Join-Path $c.root 'missing.json') -CandidateOnly -InternalNoCatalog|ConvertFrom-Json;$r.mappings.Count|Should -Be 132;$r.catalogCheck|Should -Be skipped}finally{Remove-Item $c.root -Recurse -Force}}
    It 'isolates every adapter invocation from the live catalog' {$calls=@(Get-Content -LiteralPath $PSCommandPath|Where-Object{$_ -match '&\$script:Adapter\s'});$calls.Count|Should -Be 4;@($calls|Where-Object{$_ -notmatch '-InternalNoCatalog\b'}).Count|Should -Be 0}
}
