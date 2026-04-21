param(
    [switch]$SkipModelPull
)

$ErrorActionPreference = "Stop"

$DefaultModel = "nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

Set-Location $ProjectRoot

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return @("py", "-3.11")
        }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return @("python")
        }
    }

    throw "Python 3.10+ was not found. Install Python 3.11 and enable 'Add python.exe to PATH'."
}

function Invoke-SelectedPython {
    param([string[]]$Arguments)

    $exe = $script:PythonCommand[0]
    $prefix = @()
    if ($script:PythonCommand.Count -gt 1) {
        $prefix = $script:PythonCommand[1..($script:PythonCommand.Count - 1)]
    }

    & $exe @prefix @Arguments
}

Write-Host "== StrokeGPT-ReVibed Windows installer =="

$script:PythonCommand = Find-Python
Write-Host "Using Python command: $($script:PythonCommand -join ' ')"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment..."
    Invoke-SelectedPython @("-m", "venv", ".venv")
}

$PythonVersion = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($PythonVersion -ne "3.11") {
    Write-Warning "Virtual environment is Python $PythonVersion. Local Chatterbox voice works best with Python 3.11."
}

Write-Host "Installing Python dependencies..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt

if (-not $SkipModelPull) {
    if (Get-Command ollama -ErrorAction SilentlyContinue) {
        Write-Host "Pulling default Ollama model: $DefaultModel"
        & ollama pull $DefaultModel
    } else {
        Write-Warning "Ollama was not found on PATH. Install Ollama, then run: ollama pull $DefaultModel"
    }
}

Write-Host ""
Write-Host "Install complete."
Write-Host "Start the app with:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  python app.py"
