# STATZ Open in Explorer — statzfile:// protocol handler
# Deploy to: C:\ProgramData\STATZ\open-explorer.ps1
#
# Invoked by the statzfile:// custom URL protocol when a user clicks
# "Open in Explorer" in the STATZ document browser. Resolves the URI path
# segment under %USERPROFILE% and launches Windows Explorer.

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Uri
)

$ErrorActionPreference = 'Stop'

function Write-HandlerLog {
    param([string]$Message)
    $logDir = Join-Path $env:ProgramData 'STATZ\logs'
    if (-not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    $logFile = Join-Path $logDir 'open-explorer.log'
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -LiteralPath $logFile -Value "[$timestamp] $Message"
}

try {
    $raw = $Uri.Trim()
    if ($raw -match '^statzfile:///(.+)$') {
        $encodedPath = $Matches[1]
    } elseif ($raw -match '^statzfile://(.+)$') {
        $encodedPath = $Matches[1].TrimStart('/')
    } else {
        throw "Unrecognized statzfile URI: $Uri"
    }

    $relativePath = [System.Uri]::UnescapeDataString($encodedPath)
    $relativePath = $relativePath -replace '/', '\'
    $fullPath = Join-Path $env:USERPROFILE $relativePath

    Write-HandlerLog "Opening: $fullPath"

    if (-not (Test-Path -LiteralPath $fullPath)) {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show(
            "The local OneDrive folder was not found:`n`n$fullPath`n`nEnsure OneDrive is synced and the Statz - V87 library is available on this PC.",
            'STATZ — Open in Explorer',
            'OK',
            'Warning'
        ) | Out-Null
        exit 1
    }

    Start-Process explorer.exe -ArgumentList @($fullPath)
    exit 0
}
catch {
    Write-HandlerLog "ERROR: $($_.Exception.Message)"
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "Could not open the folder in Explorer.`n`n$($_.Exception.Message)",
        'STATZ — Open in Explorer',
        'OK',
        'Error'
    ) | Out-Null
    exit 1
}
