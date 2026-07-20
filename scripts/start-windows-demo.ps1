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
    [switch]$NoForegroundWindow,
    [string]$PublicUrl = "",
    [switch]$SkipGitPull,
    [switch]$NoInstall,
    [switch]$ForceInstall
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
    }
}

function Get-BasePython {
    $cfg = Join-Path $ProjectDir ".venv\pyvenv.cfg"
    if (Test-Path $cfg) {
        foreach ($line in Get-Content $cfg) {
            if ($line -match "^\s*home\s*=\s*(.+?)\s*$") {
                $candidate = Join-Path $Matches[1] "python.exe"
                if (Test-Path $candidate) {
                    return $candidate
                }
            }
        }
    }
    return (Join-Path $ProjectDir ".venv\Scripts\python.exe")
}

function Test-Dependencies {
    $python = Get-BasePython
    $sitePackages = Join-Path $ProjectDir ".venv\Lib\site-packages"
    $env:PYTHONPATH = "$ProjectDir\src;$sitePackages"
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $python -c "import chat_vision_demo, chat_vision, mss, qrcode, pytest; raise SystemExit(0 if getattr(chat_vision, '__version__', '') == '0.1.1' else 1)" *> $null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
}

function New-CleanVenv {
    if (Test-Path ".venv") {
        Write-Host "Existing .venv is incomplete; rebuilding it."
        Remove-Item -Recurse -Force ".venv"
    }
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "python venv creation failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        throw "python venv creation did not produce .venv\Scripts\python.exe"
    }
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
            Stop-ProcessTree -ProcessId $oldProcess.Id
            Start-Sleep -Milliseconds 500
        }
    }
}

if (-not $SkipGitPull) {
    if (Test-Path (Join-Path $ProjectDir ".git")) {
        git pull --ff-only
        if ($LASTEXITCODE -ne 0) { throw "git pull failed with exit code $LASTEXITCODE" }
    } else {
        Write-Host "No .git directory found; skipping git pull."
    }
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    New-CleanVenv
}

if (-not $NoInstall -and ($ForceInstall -or -not (Test-Dependencies))) {
    .\.venv\Scripts\python.exe -m pip install -e ".[dev,windows]"
    if ($LASTEXITCODE -ne 0) { throw "pip install failed with exit code $LASTEXITCODE" }
} elseif (-not $NoInstall) {
    Write-Host "Dependencies already installed; skipping pip install. Use -ForceInstall to reinstall."
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
$runnerScript = Join-Path $runDir "run-chat-vision-demo.py"
$runnerConfig = Join-Path $runDir "run-chat-vision-demo.json"

$env:CHAT_VISION_API_KEY = $ApiKey

$cliArgs = @("--driver", $Driver, "--bind", $Bind, "--port", "$Port")
if ($PublicUrl) {
    $cliArgs += @("--public-url", $PublicUrl)
}
if ($ScreenRect) {
    $cliArgs += @("--screen-rect", $ScreenRect)
} else {
    if ($WindowProcess) {
        $cliArgs += @("--windows-window-process", $WindowProcess)
    }
    if ($WindowTitle) {
        $cliArgs += @("--windows-window-title", $WindowTitle)
    }
}
$useForegroundWindow = $ForegroundWindow -or -not $NoForegroundWindow
if ($useForegroundWindow) {
    $cliArgs += "--foreground-window"
}

$python = Get-BasePython
$sitePackages = Join-Path $ProjectDir ".venv\Lib\site-packages"
$config = @{
    project_dir = $ProjectDir
    site_packages = $sitePackages
    api_key = $ApiKey
    stdout = $stdout
    stderr = $stderr
    args = $cliArgs
}
$config | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $runnerConfig
@'
import json
import os
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
config = json.loads(config_path.read_text(encoding="utf-8-sig"))
project_dir = config["project_dir"]
os.chdir(project_dir)
sys.path.insert(0, str(Path(project_dir) / "src"))
sys.path.insert(0, config["site_packages"])
os.environ["CHAT_VISION_API_KEY"] = config["api_key"]
stdout = open(config["stdout"], "a", buffering=1, encoding="utf-8")
stderr = open(config["stderr"], "a", buffering=1, encoding="utf-8")
sys.stdout = stdout
sys.stderr = stderr

from chat_vision_demo.cli import main

raise SystemExit(main(config["args"]))
'@ | Set-Content -Encoding UTF8 $runnerScript

$process = Start-Process `
    -FilePath $python `
    -ArgumentList @($runnerScript, $runnerConfig) `
    -WorkingDirectory $ProjectDir `
    -PassThru

$listenPid = $null
for ($i = 0; $i -lt 50; $i++) {
    Start-Sleep -Milliseconds 200
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($conn) {
        $listenPid = [int]$conn.OwningProcess
        break
    }
    $process.Refresh()
    if ($process.HasExited) {
        break
    }
}

if (-not $listenPid) {
    $process.Refresh()
    if ($process.HasExited) {
        $errTail = ""
        if (Test-Path $stderr) {
            $errTail = (Get-Content $stderr -Tail 20 -ErrorAction SilentlyContinue) -join "`n"
        }
        throw "Chat Vision Demo exited before listening on port $Port. $errTail"
    }
}

$pidToWrite = if ($listenPid) { $listenPid } else { $process.Id }
$pidToWrite | Set-Content $pidFile
$stdout | Set-Content (Join-Path $runDir "latest-stdout.txt")
$stderr | Set-Content (Join-Path $runDir "latest-stderr.txt")
$meta | Set-Content (Join-Path $runDir "latest-meta.txt")

@"
Started Chat Vision Demo
PID: $pidToWrite
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
