param(
    [string]$ProjectDir = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$ApiKey = $env:CHAT_VISION_API_KEY,
    [ValidateSet("http", "sdk")]
    [string]$Driver = "http",
    [int]$Port = 8080,
    [string]$Bind = "127.0.0.1",
    [string]$ScreenRect = "",
    [string]$WindowProcess = "",
    [string]$WindowTitle = "",
    [switch]$ForegroundWindow,
    [string]$PublicUrl = "",
    [switch]$SkipGitPull,
    [switch]$NoInstall
)

$ErrorActionPreference = "Stop"

function Get-PrimaryLanUrl {
    param([int]$Port)
    $addresses = @(Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.IPAddress -notlike "172.16.*" -and
            $_.IPAddress -notlike "172.17.*" -and
            $_.IPAddress -notlike "172.18.*" -and
            $_.IPAddress -notlike "172.19.*" -and
            $_.IPAddress -notlike "172.2?.*" -and
            $_.IPAddress -notlike "172.3?.*" -and
            $_.InterfaceAlias -notmatch "vEthernet|WSL|Docker|Loopback|VPN"
        } |
        Sort-Object InterfaceMetric |
        Select-Object -ExpandProperty IPAddress)
    if ($addresses.Count -gt 0) {
        return "http://$($addresses[0]):$Port"
    }
    return ""
}

Set-Location $ProjectDir

$envFile = Join-Path $ProjectDir ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            $name = $parts[0].Trim()
            $value = $parts[1].Trim()
            if ($name -and -not [Environment]::GetEnvironmentVariable($name, "Process")) {
                [Environment]::SetEnvironmentVariable($name, $value, "Process")
            }
        }
    }
    if (-not $ApiKey) {
        $ApiKey = $env:CHAT_VISION_API_KEY
    }
}

$runDir = Join-Path $ProjectDir ".run"
$logDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $runDir, $logDir | Out-Null

$pidFile = Join-Path $runDir "chat-vision-demo.pid"
if (Test-Path $pidFile) {
    $oldPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($oldPid) {
        $oldProcess = Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue
        if ($oldProcess) {
            Stop-Process -Id $oldProcess.Id -Force
            Start-Sleep -Milliseconds 500
        }
    }
}

if (-not $SkipGitPull) {
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "git pull failed with exit code $LASTEXITCODE" }
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "python venv creation failed with exit code $LASTEXITCODE" }
}

if (-not $NoInstall) {
    .\.venv\Scripts\python.exe -m pip install -e ".[dev,windows]"
    if ($LASTEXITCODE -ne 0) { throw "pip install failed with exit code $LASTEXITCODE" }
}

if (-not $ApiKey) {
    throw "CHAT_VISION_API_KEY is missing. Set it in the environment or pass -ApiKey."
}

if (-not $PublicUrl -and $Bind -ne "127.0.0.1" -and $Bind -ne "localhost") {
    $PublicUrl = Get-PrimaryLanUrl -Port $Port
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stdout = Join-Path $logDir "chat-vision-demo-$timestamp.out.log"
$stderr = Join-Path $logDir "chat-vision-demo-$timestamp.err.log"
$meta = Join-Path $logDir "chat-vision-demo-$timestamp.meta.txt"

$env:CHAT_VISION_API_KEY = $ApiKey

$argsList = @(
    "-u",
    "-m", "chat_vision_demo.cli",
    "--driver", $Driver,
    "--bind", $Bind,
    "--port", "$Port"
)

if ($PublicUrl) {
    $argsList += @("--public-url", $PublicUrl)
}

if ($ScreenRect) {
    $argsList += @("--screen-rect", $ScreenRect)
} else {
    if ($WindowProcess) {
        $argsList += @("--windows-window-process", $WindowProcess)
    }
    if ($WindowTitle) {
        $argsList += @("--windows-window-title", $WindowTitle)
    }
}
if ($ForegroundWindow) {
    $argsList += "--foreground-window"
}

$process = Start-Process `
    -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList $argsList `
    -WorkingDirectory $ProjectDir `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

$process.Id | Set-Content $pidFile
$stdout | Set-Content (Join-Path $runDir "latest-stdout.txt")
$stderr | Set-Content (Join-Path $runDir "latest-stderr.txt")
$meta | Set-Content (Join-Path $runDir "latest-meta.txt")

@"
Started Chat Vision Demo
PID: $($process.Id)
Driver: $Driver
Mode: screen
Local: http://127.0.0.1:$Port
Public: $PublicUrl
Bind: $Bind
Warning: If Bind is 0.0.0.0, this demo is reachable from the LAN. Never expose it to the public internet.
Stdout: $stdout
Stderr: $stderr
PID file: $pidFile
StartedAt: $(Get-Date -Format o)

Use:
  Get-Content -Wait "$stdout"
  Get-Content -Wait "$stderr"
"@ | Tee-Object -FilePath $meta
