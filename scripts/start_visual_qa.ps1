param(
    [int]$Port = 5011,
    [string]$HostName = "127.0.0.1",
    [string]$PythonPath = "",
    [string]$LogPath = "",
    [int]$TimeoutSeconds = 45,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Resolve-VisualQaPython {
    if ($PythonPath) {
        if ((Test-Path -LiteralPath $PythonPath) -or (Get-Command $PythonPath -ErrorAction SilentlyContinue)) {
            return $PythonPath
        }
        throw "PythonPath was not found: $PythonPath"
    }
    if (Test-Path -LiteralPath $VenvPython) {
        return $VenvPython
    }
    throw "The app virtual environment was not found at $VenvPython. Run .\scripts\install_windows.ps1 first."
}

function ConvertTo-CmdLiteral {
    param([string]$Value)
    return $Value.Replace("%", "%%")
}

function Get-VisualQaAppUrl {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }
    $text = Get-Content -LiteralPath $Path -Raw -ErrorAction SilentlyContinue
    if (-not $text) {
        return ""
    }
    $patterns = @(
        "Open\s+(https?://[^\s]+)",
        "Running on\s+(https?://[^\s]+)"
    )
    foreach ($pattern in $patterns) {
        $matches = [regex]::Matches($text, $pattern)
        if ($matches.Count -gt 0) {
            return $matches[$matches.Count - 1].Groups[1].Value.TrimEnd("/")
        }
    }
    return ""
}

function Test-VisualQaUrl {
    param([string]$Url)
    if (-not $Url) {
        return $false
    }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        return [int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 500
    }
    catch {
        return $false
    }
}

function Get-VisualQaListenerPid {
    param([string]$Url)
    try {
        $uri = [Uri]$Url
        $port = $uri.Port
        if ($port -le 0) {
            return $null
        }
        $escapedHostPort = [regex]::Escape(":$port")
        $line = netstat -ano -p TCP | Select-String -Pattern "$escapedHostPort\s+.*LISTENING\s+\d+" | Select-Object -Last 1
        if ($line -and $line.Line -match "LISTENING\s+(\d+)\s*$") {
            return [int]$matches[1]
        }
    }
    catch {
        return $null
    }
    return $null
}

function Get-VisualQaLogTail {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }
    return @(Get-Content -LiteralPath $Path -Tail 40 -ErrorAction SilentlyContinue)
}

Set-Location -LiteralPath $ProjectRoot

$python = Resolve-VisualQaPython
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logRoot = Join-Path $ProjectRoot "user_data\visual_qa"
if (-not $LogPath) {
    New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
    $LogPath = Join-Path $logRoot "visual-qa-app-$timestamp.log"
}
else {
    $logParent = Split-Path -Parent $LogPath
    if ($logParent) {
        New-Item -ItemType Directory -Force -Path $logParent | Out-Null
    }
}

$cmdPath = Join-Path ([IO.Path]::GetTempPath()) "strokegpt-visual-qa-$timestamp-$PID.cmd"
$cmdLines = @(
    "@echo off",
    "cd /d ""$(ConvertTo-CmdLiteral $ProjectRoot)""",
    "set ""STROKEGPT_OPEN_BROWSER=0""",
    "set ""STROKEGPT_HOST=$(ConvertTo-CmdLiteral $HostName)""",
    "set ""STROKEGPT_PORT=$Port""",
    "echo [VISUAL_QA] Starting StrokeGPT-ReVibed at %DATE% %TIME% > ""$(ConvertTo-CmdLiteral $LogPath)""",
    "echo [VISUAL_QA] Python: $(ConvertTo-CmdLiteral $python) >> ""$(ConvertTo-CmdLiteral $LogPath)""",
    "echo [VISUAL_QA] Preferred URL: http://$(ConvertTo-CmdLiteral $HostName):$Port >> ""$(ConvertTo-CmdLiteral $LogPath)""",
    """$(ConvertTo-CmdLiteral $python)"" app.py >> ""$(ConvertTo-CmdLiteral $LogPath)"" 2>&1",
    "echo [VISUAL_QA] App exited with code %ERRORLEVEL% at %DATE% %TIME% >> ""$(ConvertTo-CmdLiteral $LogPath)"""
)
Set-Content -LiteralPath $cmdPath -Encoding ASCII -Value $cmdLines

$launcher = Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/c", "`"$cmdPath`"") -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru

$deadline = (Get-Date).AddSeconds([Math]::Max(5, $TimeoutSeconds))
$url = ""
while ((Get-Date) -lt $deadline) {
    $url = Get-VisualQaAppUrl -Path $LogPath
    if ($url -and (Test-VisualQaUrl -Url $url)) {
        break
    }
    if ($launcher.HasExited) {
        break
    }
    Start-Sleep -Milliseconds 500
}

if (-not $url -or -not (Test-VisualQaUrl -Url $url)) {
    $tail = Get-VisualQaLogTail -Path $LogPath
    $message = "Visual QA app did not become reachable within $TimeoutSeconds seconds. Log: $LogPath"
    if ($tail.Count) {
        $message += "`n--- log tail ---`n$($tail -join "`n")"
    }
    throw $message
}

$listenerPid = Get-VisualQaListenerPid -Url $url
$result = [ordered]@{
    status = "ready"
    url = $url
    log_path = (Resolve-Path -LiteralPath $LogPath).Path
    launcher_pid = $launcher.Id
    listener_pid = $listenerPid
    cleanup_command = if ($listenerPid) { "Stop-Process -Id $listenerPid -Force" } else { "Stop-Process -Id $($launcher.Id) -Force" }
}

if ($Json) {
    $result | ConvertTo-Json -Depth 3
}
else {
    Write-Host "STROKEGPT_VISUAL_QA_URL=$($result.url)"
    Write-Host "STROKEGPT_VISUAL_QA_LOG=$($result.log_path)"
    Write-Host "STROKEGPT_VISUAL_QA_LAUNCHER_PID=$($result.launcher_pid)"
    if ($result.listener_pid) {
        Write-Host "STROKEGPT_VISUAL_QA_LISTENER_PID=$($result.listener_pid)"
    }
    Write-Host "STROKEGPT_VISUAL_QA_CLEANUP=$($result.cleanup_command)"
}
