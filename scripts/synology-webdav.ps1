<#
.SYNOPSIS
    Connect to Synology WebDAV to list and download annexes.
.DESCRIPTION
    Uses environment variables for credentials:
    - SYNOLOGY_WEBDAV_URL: Base URL (e.g., https://pukitavir.synology.me:5006/APAP)
    - SYNOLOGY_WEBDAV_USER: Username
    - SYNOLOGY_WEBDAV_PASS: Password
.PARAMETER Action
    Action to perform: list, download, download-all
.PARAMETER Path
    Remote path relative to base URL (e.g., "Produccion/Anexos")
.PARAMETER LocalPath
    Local destination path for downloads
.EXAMPLE
    .\synology-webdav.ps1 -Action list -Path "Produccion/Anexos"
    .\synology-webdav.ps1 -Action download -Path "Produccion/Anexos/foto.jpg" -LocalPath "C:\temp\foto.jpg"
    .\synology-webdav.ps1 -Action download-all -Path "Produccion/Anexos" -LocalPath "C:\temp\anexos"
#>

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("list", "download", "download-all")]
    [string]$Action,

    [Parameter(Mandatory=$false)]
    [string]$Path = "",

    [Parameter(Mandatory=$false)]
    [string]$LocalPath = ""
)

# Load environment variables
$baseUrl = [System.Environment]::GetEnvironmentVariable("SYNOLOGY_WEBDAV_URL", "User")
$user = [System.Environment]::GetEnvironmentVariable("SYNOLOGY_WEBDAV_USER", "User")
$pass = [System.Environment]::GetEnvironmentVariable("SYNOLOGY_WEBDAV_PASS", "User")

if (-not $baseUrl -or -not $user -or -not $pass) {
    Write-Error "Missing environment variables. Set SYNOLOGY_WEBDAV_URL, SYNOLOGY_WEBDAV_USER, SYNOLOGY_WEBDAV_PASS."
    exit 1
}

function Invoke-WebDAVRequest {
    param(
        [string]$Url,
        [string]$Method = "PROPFIND",
        [string]$Depth = "1",
        [string]$OutFile = $null
    )
    try {
        $request = [System.Net.HttpWebRequest]::Create($Url)
        $request.Method = $Method
        $request.Timeout = 30000
        $auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("${user}:${pass}"))
        $request.Headers.Add("Authorization", "Basic $auth")
        $request.Headers.Add("Depth", $Depth)

        if ($OutFile) {
            $response = $request.GetResponse()
            $stream = $response.GetResponseStream()
            $fileStream = [System.IO.File]::Create($OutFile)
            $stream.CopyTo($fileStream)
            $fileStream.Close()
            $stream.Close()
            $response.Close()
            return $true
        } else {
            $response = $request.GetResponse()
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            $body = $reader.ReadToEnd()
            $reader.Close()
            $response.Close()
            return $body
        }
    } catch {
        Write-Error "WebDAV request failed: $_"
        return $null
    }
}

function Parse-WebDAVResponse {
    param([string]$XmlContent)
    [xml]$xml = $XmlContent
    $nsManager = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
    $nsManager.AddNamespace("D", "DAV:")
    $responses = $xml.SelectNodes("//D:response", $nsManager)
    $items = @()
    foreach ($r in $responses) {
        $href = $r.SelectSingleNode("D:href", $nsManager).InnerText
        $isCollection = $r.SelectSingleNode("D:resourcetype/D:collection", $nsManager) -ne $null
        $size = 0
        $sizeNode = $r.SelectSingleNode("D:getcontentlength", $nsManager)
        if ($sizeNode) { [long]::TryParse($sizeNode.InnerText, [ref]$size) | Out-Null }
        $modified = ""
        $modNode = $r.SelectSingleNode("D:getlastmodified", $nsManager)
        if ($modNode) { $modified = $modNode.InnerText }
        # URL decode using uri::UnescapeDataString
        try { $decoded = [uri]::UnescapeDataString($href) } catch { $decoded = $href }
        $items += [PSCustomObject]@{
            Path = $decoded
            IsDirectory = $isCollection
            Size = $size
            Modified = $modified
        }
    }
    return $items
}

function Get-FileSize {
    param([long]$Bytes)
    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    elseif ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    elseif ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    else { return "$Bytes bytes" }
}

# Main logic
switch ($Action) {
    "list" {
        $fullUrl = "$baseUrl/$Path".TrimEnd('/')
        Write-Host "Listing: $fullUrl" -ForegroundColor Cyan
        $xml = Invoke-WebDAVRequest -Url $fullUrl -Method "PROPFIND" -Depth "1"
        if ($xml) {
            $items = Parse-WebDAVResponse -XmlContent $xml
            $items | Where-Object { $_.Path -ne "$Path/" -and $_.Path -ne "$Path" -and $_.Path -ne "/" -and $_.Path -ne "" } | ForEach-Object {
                $type = if ($_.IsDirectory) { "[DIR] " } else { "      " }
                $size = if ($_.IsDirectory) { "" } else { Get-FileSize -Bytes $_.Size }
                $name = $_.Path -replace ".*/([^/]+)/?$", '$1'
                Write-Host "$type$name  $size  $($_.Modified)"
            }
        }
    }
    "download" {
        if (-not $LocalPath) { Write-Error "LocalPath is required for download"; exit 1 }
        $downloadUrl = "$baseUrl/$Path"
        Write-Host "Downloading: $downloadUrl" -ForegroundColor Cyan
        $dir = Split-Path $LocalPath -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $result = Invoke-WebDAVRequest -Url $downloadUrl -Method "GET" -OutFile $LocalPath
        if ($result) { Write-Host "  Saved to: $LocalPath" -ForegroundColor Green }
    }
    "download-all" {
        if (-not $LocalPath) { Write-Error "LocalPath is required for download-all"; exit 1 }
        $fullUrl = "$baseUrl/$Path".TrimEnd('/')
        Write-Host "Listing remote files: $fullUrl" -ForegroundColor Cyan
        $xml = Invoke-WebDAVRequest -Url $fullUrl -Method "PROPFIND" -Depth "1"
        if ($xml) {
            $items = Parse-WebDAVResponse -XmlContent $xml
            $files = $items | Where-Object { -not $_.IsDirectory }
            Write-Host "Found $($files.Count) files to download" -ForegroundColor Yellow
            if (-not (Test-Path $LocalPath)) { New-Item -ItemType Directory -Path $LocalPath -Force | Out-Null }
            $downloaded = 0
            foreach ($file in $files) {
                $name = $file.Path -replace ".*/([^/]+)$", '$1'
                $dest = Join-Path $LocalPath $name
                $result = Invoke-WebDAVRequest -Url $file.Path -Method "GET" -OutFile $dest
                if ($result) {
                    Write-Host "  Downloaded: $name" -ForegroundColor Green
                    $downloaded++
                }
            }
            Write-Host "Done: $downloaded/$($files.Count) files downloaded to $LocalPath" -ForegroundColor Green
        }
    }
}
