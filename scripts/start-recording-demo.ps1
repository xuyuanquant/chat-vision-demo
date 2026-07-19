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

$argsList = @(
    "-ProjectDir", $ProjectDir,
    "-Port", "$Port",
    "-Bind", $Bind,
    "-ForegroundWindow",
    "-SkipGitPull"
)

if ($PublicUrl) {
    $argsList += @("-PublicUrl", $PublicUrl)
}

& (Join-Path $PSScriptRoot "start-windows-demo.ps1") @argsList
