param(
    [switch]$PersistEnv,
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu128"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv-parakeet\Scripts\python.exe"

Set-Location $ProjectRoot

function Test-PythonCommand {
    param(
        [string[]]$Command,
        [int]$MinimumMinor = 10
    )

    $exe = $Command[0]
    $prefix = @()
    if ($Command.Count -gt 1) {
        $prefix = $Command[1..($Command.Count - 1)]
    }

    $oldErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        & $exe @prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, $MinimumMinor) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
}

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        if (Test-PythonCommand @("py", "-3.11") -MinimumMinor 11) {
            return @("py", "-3.11")
        }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        if (Test-PythonCommand @("python")) {
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
Write-Host "Using PyTorch wheel index: $TorchIndexUrl"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install --upgrade --force-reinstall --index-url $TorchIndexUrl torch torchvision torchaudio
& $VenvPython -m pip install -r requirements-parakeet.txt
Write-Host "Repairing CUDA PyTorch stack after NeMo dependency resolution..."
& $VenvPython -m pip install --upgrade --force-reinstall --no-deps --index-url $TorchIndexUrl torch torchvision torchaudio
Write-Host "Reapplying NeMo dependency pins..."
& $VenvPython -m pip install "fsspec==2024.12.0" "setuptools>=79.0.0"
Write-Host "Checking Python package dependency consistency..."
& $VenvPython -m pip check

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
Write-Host "The app auto-detects this repo-local runtime. For a custom runtime, set:"
Write-Host "  `$env:STROKEGPT_PARAKEET_PYTHON = `"$VenvPython`""
Write-Host "Then start the normal app from .venv with:"
Write-Host "  .\.venv\Scripts\python.exe app.py"
