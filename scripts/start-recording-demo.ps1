param(
    [string]$ProjectDir = (Resolve-Path "$PSScriptRoot\..").Path,
    [int]$Port = 8080,
    [string]$Bind = "127.0.0.1",
    [string]$PublicUrl = ""
)

$ErrorActionPreference = "Stop"

Set-Location $ProjectDir

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
}

$startArgs = @{
    ProjectDir = $ProjectDir
    Port = $Port
    Bind = $Bind
    ForegroundWindow = $true
    SkipGitPull = $true
}

if ($PublicUrl) {
    $startArgs.PublicUrl = $PublicUrl
}

& (Join-Path $PSScriptRoot "start-windows-demo.ps1") @startArgs
