param(
    [string]$ProjectDir = (Resolve-Path "$PSScriptRoot\..").Path,
    [int]$Port = 8080
)

function Stop-ProcessTree {
    param([int]$ProcessId)
    $children = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ParentProcessId -eq $ProcessId })
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId)
    }
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $process.Id -Force
        Write-Host "Stopped Chat Vision Demo PID $($process.Id)"
    }
}

$pidFile = Join-Path $ProjectDir ".run\chat-vision-demo.pid"
if (-not (Test-Path $pidFile)) {
    Write-Host "No pid file found: $pidFile"
} else {
    $pidValue = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($pidValue) {
        Stop-ProcessTree -ProcessId ([int]$pidValue)
    }
    Remove-Item $pidFile -Force
}

$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
foreach ($listener in $listeners) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
    if ($proc -and $proc.CommandLine -like "*chat_vision_demo.cli*") {
        Stop-ProcessTree -ProcessId ([int]$listener.OwningProcess)
    }
}
