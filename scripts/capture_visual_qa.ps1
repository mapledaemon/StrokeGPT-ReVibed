param(
    [string]$Url = $env:STROKEGPT_VISUAL_QA_URL,
    [string]$OutputPath = "",
    [int]$Width = 1280,
    [int]$Height = 720,
    [int]$TimeoutSeconds = 30,
    [int]$VirtualTimeBudgetMilliseconds = 0,
    [string]$BrowserPath = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Resolve-VisualQaBrowser {
    if ($BrowserPath) {
        if (Test-Path -LiteralPath $BrowserPath) {
            return (Resolve-Path -LiteralPath $BrowserPath).Path
        }
        $command = Get-Command $BrowserPath -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
        throw "BrowserPath was not found: $BrowserPath"
    }

    $commandCandidates = @("msedge.exe", "chrome.exe", "chromium.exe")
    foreach ($name in $commandCandidates) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    $pathCandidates = @(
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    )
    foreach ($path in $pathCandidates) {
        if (Test-Path -LiteralPath $path) {
            return $path
        }
    }

    throw "No Chromium browser was found. Install Microsoft Edge or Google Chrome, or pass -BrowserPath."
}

function Resolve-VisualQaOutputPath {
    param([string]$Path)
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    if (-not $Path) {
        $screenRoot = Join-Path $ProjectRoot "user_data\visual_qa\screenshots"
        New-Item -ItemType Directory -Force -Path $screenRoot | Out-Null
        return (Join-Path $screenRoot "visual-qa-$timestamp.png")
    }
    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path (Get-Location) $Path))
}

function New-VisualQaTempDirectory {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $path = Join-Path ([IO.Path]::GetTempPath()) "strokegpt-visual-qa-browser-$timestamp-$suffix"
    New-Item -ItemType Directory -Force -Path $path | Out-Null
    return $path
}

function Remove-VisualQaTempDirectory {
    param([string]$Path)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) {
        return
    }
    $fullPath = [IO.Path]::GetFullPath($Path)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $leaf = Split-Path -Leaf $fullPath
    if (-not $fullPath.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        return
    }
    if (-not $leaf.StartsWith("strokegpt-visual-qa-browser-", [StringComparison]::OrdinalIgnoreCase)) {
        return
    }
    Remove-Item -LiteralPath $fullPath -Recurse -Force -ErrorAction SilentlyContinue
}

function Get-VisualQaLogTail {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }
    return @(Get-Content -LiteralPath $Path -Tail 40 -ErrorAction SilentlyContinue)
}

function ConvertTo-VisualQaProcessArgument {
    param([string]$Value)
    if ($null -eq $Value) {
        return '""'
    }
    if ($Value -notmatch '[\s"]') {
        return $Value
    }
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Start-VisualQaBrowserProcess {
    param(
        [string]$Path,
        [string[]]$Arguments
    )
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Path
    $startInfo.Arguments = ($Arguments | ForEach-Object { ConvertTo-VisualQaProcessArgument $_ }) -join " "
    $startInfo.WorkingDirectory = $ProjectRoot
    $startInfo.UseShellExecute = $true
    $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    return [System.Diagnostics.Process]::Start($startInfo)
}

if (-not $Url) {
    throw "Pass -Url or set STROKEGPT_VISUAL_QA_URL."
}

try {
    $uri = [Uri]$Url
    if ($uri.Scheme -ne "http" -and $uri.Scheme -ne "https") {
        throw "Unsupported URL scheme: $($uri.Scheme)"
    }
}
catch {
    throw "Invalid URL: $Url"
}

Set-Location -LiteralPath $ProjectRoot

$browser = Resolve-VisualQaBrowser
$screenshotPath = Resolve-VisualQaOutputPath -Path $OutputPath
$screenshotParent = Split-Path -Parent $screenshotPath
if ($screenshotParent) {
    New-Item -ItemType Directory -Force -Path $screenshotParent | Out-Null
}

$runRoot = Join-Path $ProjectRoot "user_data\visual_qa"
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stdoutLog = Join-Path $runRoot "headless-browser-$timestamp.out.log"
$stderrLog = Join-Path $runRoot "headless-browser-$timestamp.err.log"
$profileDir = New-VisualQaTempDirectory

$arguments = @(
    "--headless=new",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--no-first-run",
    "--no-default-browser-check",
    "--hide-scrollbars",
    "--ignore-certificate-errors",
    "--allow-insecure-localhost",
    "--window-size=$Width,$Height",
    "--user-data-dir=$profileDir",
    "--screenshot=$screenshotPath"
)
if ($VirtualTimeBudgetMilliseconds -gt 0) {
    $arguments += "--virtual-time-budget=$VirtualTimeBudgetMilliseconds"
}
$arguments += $Url

$startedAt = Get-Date
try {
    Set-Content -LiteralPath $stdoutLog -Encoding UTF8 -Value @(
        "[VISUAL_QA] Browser: $browser",
        "[VISUAL_QA] URL: $Url",
        "[VISUAL_QA] Screenshot: $screenshotPath"
    )
    Set-Content -LiteralPath $stderrLog -Encoding UTF8 -Value @()

    $process = Start-VisualQaBrowserProcess -Path $browser -Arguments $arguments

    if (-not $process.WaitForExit([Math]::Max(5, $TimeoutSeconds) * 1000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Headless browser screenshot timed out after $TimeoutSeconds seconds."
    }

    if ($process.ExitCode -ne 0) {
        $tail = Get-VisualQaLogTail -Path $stderrLog
        $message = "Headless browser screenshot failed with exit code $($process.ExitCode)."
        if ($tail.Count) {
            $message += "`n--- browser stderr ---`n$($tail -join "`n")"
        }
        throw $message
    }

    if (-not (Test-Path -LiteralPath $screenshotPath)) {
        throw "Headless browser exited successfully but did not write a screenshot: $screenshotPath"
    }

    $file = Get-Item -LiteralPath $screenshotPath
    if ($file.Length -le 0) {
        throw "Headless browser wrote an empty screenshot: $screenshotPath"
    }

    $elapsed = [int]((Get-Date) - $startedAt).TotalMilliseconds
    $result = [ordered]@{
        status = "captured"
        url = $Url
        output_path = (Resolve-Path -LiteralPath $screenshotPath).Path
        browser_path = $browser
        width = $Width
        height = $Height
        elapsed_ms = $elapsed
        stdout_log = (Resolve-Path -LiteralPath $stdoutLog).Path
        stderr_log = (Resolve-Path -LiteralPath $stderrLog).Path
    }

    if ($Json) {
        $result | ConvertTo-Json -Depth 3
    }
    else {
        Write-Host "STROKEGPT_VISUAL_QA_SCREENSHOT=$($result.output_path)"
        Write-Host "STROKEGPT_VISUAL_QA_BROWSER=$($result.browser_path)"
        Write-Host "STROKEGPT_VISUAL_QA_ELAPSED_MS=$($result.elapsed_ms)"
        Write-Host "STROKEGPT_VISUAL_QA_STDOUT=$($result.stdout_log)"
        Write-Host "STROKEGPT_VISUAL_QA_STDERR=$($result.stderr_log)"
    }
}
finally {
    Remove-VisualQaTempDirectory -Path $profileDir
}
