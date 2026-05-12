param(
    [switch]$PersistEnv
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv-parakeet\Scripts\python.exe"

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

Write-Host "== StrokeGPT-ReVibed NVIDIA Parakeet installer =="
Write-Host "This creates .venv-parakeet so NeMo dependencies do not conflict with the main app environment."

$script:PythonCommand = Find-Python
Write-Host "Using Python command: $($script:PythonCommand -join ' ')"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating Parakeet virtual environment..."
    Invoke-SelectedPython @("-m", "venv", ".venv-parakeet")
}

Write-Host "Installing CUDA PyTorch and Parakeet dependencies..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install --index-url https://download.pytorch.org/whl/cu121 torch torchvision torchaudio
& $VenvPython -m pip install -r requirements-parakeet.txt

if ($PersistEnv) {
    [Environment]::SetEnvironmentVariable("STROKEGPT_PARAKEET_PYTHON", $VenvPython, "User")
    Write-Host "Saved STROKEGPT_PARAKEET_PYTHON for the current Windows user."
}

$env:STROKEGPT_PARAKEET_PYTHON = $VenvPython
Write-Host ""
Write-Host "Checking the Parakeet runtime..."
& $VenvPython -m strokegpt.parakeet_worker check

Write-Host ""
Write-Host "Parakeet runtime path:"
Write-Host "  $VenvPython"
Write-Host "For this terminal session:"
Write-Host "  `$env:STROKEGPT_PARAKEET_PYTHON = `"$VenvPython`""
Write-Host "Then start the normal app from .venv with:"
Write-Host "  .\.venv\Scripts\python.exe app.py"
