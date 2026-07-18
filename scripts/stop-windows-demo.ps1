param(
    [string]$ProjectDir = (Resolve-Path "$PSScriptRoot\..").Path
)

$pidFile = Join-Path $ProjectDir ".run\chat-vision-demo.pid"
if (-not (Test-Path $pidFile)) {
    Write-Host "No pid file found: $pidFile"
    exit 0
}

$pidValue = Get-Content $pidFile -ErrorAction SilentlyContinue
if (-not $pidValue) {
    Remove-Item $pidFile -Force
    exit 0
}

$process = Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
if ($process) {
    Stop-Process -Id $process.Id -Force
    Write-Host "Stopped Chat Vision Demo PID $($process.Id)"
} else {
    Write-Host "Process $pidValue is not running"
}
Remove-Item $pidFile -Force
