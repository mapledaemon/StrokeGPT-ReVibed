param(
    [string]$PythonPath = "",
    [switch]$SkipTests,
    [switch]$SkipCompile,
    [switch]$NoRun
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

Set-Location $ProjectRoot

function Test-PythonCommand {
    param([string[]]$CommandParts)

    $exe = $CommandParts[0]
    $prefix = @()
    if ($CommandParts.Count -gt 1) {
        $prefix = $CommandParts[1..($CommandParts.Count - 1)]
    }

    try {
        & $exe @prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Find-Python {
    if ($PythonPath) {
        if ((Test-Path $PythonPath) -or (Get-Command $PythonPath -ErrorAction SilentlyContinue)) {
            $candidate = @($PythonPath)
            if (Test-PythonCommand $candidate) {
                return $candidate
            }
        }
        throw "PythonPath must point to Python 3.10+."
    }

    if (Test-Path $VenvPython) {
        $candidate = @($VenvPython)
        if (Test-PythonCommand $candidate) {
            return $candidate
        }
        throw "The existing .venv Python could not start. Run .\scripts\install_windows.ps1 again, or pass -PythonPath."
    }

    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidate = @("py", "-3.11")
        if (Test-PythonCommand $candidate) {
            return $candidate
        }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        $candidate = @("python")
        if (Test-PythonCommand $candidate) {
            return $candidate
        }
    }

    throw "Python 3.10+ was not found. Run .\scripts\install_windows.ps1 first, or pass -PythonPath."
}

function Invoke-SelectedPython {
    param([string[]]$Arguments)

    $exe = $script:PythonCommand[0]
    $prefix = @()
    if ($script:PythonCommand.Count -gt 1) {
        $prefix = $script:PythonCommand[1..($script:PythonCommand.Count - 1)]
    }

    & $exe @prefix @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

Write-Host "== StrokeGPT-ReVibed test and run =="

$script:PythonCommand = @(Find-Python)
Write-Host "Using Python command: $($script:PythonCommand -join ' ')"

if (-not $SkipTests) {
    Write-Host ""
    Write-Host "Running unit tests..."
    Invoke-SelectedPython @("-m", "unittest", "discover", "-s", "tests")
}

if (-not $SkipCompile) {
    Write-Host ""
    Write-Host "Compile-checking Python files..."
    $CompileFiles = @("app.py")
    $CompileFiles += Get-ChildItem -Path "strokegpt", "tests" -Filter "*.py" -File -Recurse | ForEach-Object { $_.FullName }
    Invoke-SelectedPython (@("-m", "py_compile") + $CompileFiles)
}

if ($NoRun) {
    Write-Host ""
    Write-Host "Validation complete. Skipping app launch because -NoRun was supplied."
    exit 0
}

Write-Host ""
Write-Host "Starting the app. Open the URL printed below, usually http://127.0.0.1:5000."
Invoke-SelectedPython @("app.py")
