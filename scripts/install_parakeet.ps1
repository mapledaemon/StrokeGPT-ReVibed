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

    $directPaths = @()
    if ($env:LocalAppData) {
        $directPaths += (Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe")
    }
    if ($env:ProgramFiles) {
        $directPaths += (Join-Path $env:ProgramFiles "Python311\python.exe")
    }
    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    if ($programFilesX86) {
        $directPaths += (Join-Path $programFilesX86 "Python311\python.exe")
    }

    foreach ($path in $directPaths) {
        if ((Test-Path -LiteralPath $path) -and (Test-PythonCommand @($path) -MinimumMinor 11)) {
            return @($path)
        }
    }

    throw "Python 3.10+ was not found. Install Python 3.11 and enable 'Add python.exe to PATH'."
}

function Invoke-SelectedPython {
    param([string[]]$Arguments)

    $command = @($script:PythonCommand)
    $exe = $command[0]
    $prefix = @()
    if ($command.Count -gt 1) {
        $prefix = $command[1..($command.Count - 1)]
    }

    & $exe @prefix @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

function Invoke-ParakeetPython {
    param([string[]]$Arguments)

    & $VenvPython @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Parakeet Python command failed: $($Arguments -join ' ')"
    }
}

function Test-ParakeetProtobufRuntime {
    $probePath = [System.IO.Path]::ChangeExtension([System.IO.Path]::GetTempFileName(), ".py")
    $probe = @'
import google.protobuf
print("Protobuf runtime:", google.protobuf.__version__)
import onnx
print("ONNX:", onnx.__version__)
'@
    try {
        Set-Content -LiteralPath $probePath -Value $probe -Encoding UTF8
        Invoke-ParakeetPython @($probePath)
    } finally {
        Remove-Item -LiteralPath $probePath -ErrorAction SilentlyContinue
    }
}

Write-Host "== StrokeGPT-ReVibed NVIDIA Parakeet installer =="
Write-Host "This creates .venv-parakeet so NeMo dependencies do not conflict with the main app environment."

$env:PYTHONNOUSERSITE = "1"
$script:PythonCommand = @(Find-Python)
Write-Host "Using Python command: $($script:PythonCommand -join ' ')"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating Parakeet virtual environment..."
    Invoke-SelectedPython @("-m", "venv", ".venv-parakeet")
}

Write-Host "Installing CUDA PyTorch and Parakeet dependencies..."
Write-Host "Using PyTorch wheel index: $TorchIndexUrl"
Invoke-ParakeetPython @("-m", "pip", "install", "--upgrade", "pip")
Invoke-ParakeetPython @("-m", "pip", "install", "--upgrade", "--force-reinstall", "--index-url", $TorchIndexUrl, "torch", "torchvision", "torchaudio")
Invoke-ParakeetPython @("-m", "pip", "install", "-r", "requirements-parakeet.txt")
Write-Host "Repairing CUDA PyTorch stack after NeMo dependency resolution..."
Invoke-ParakeetPython @("-m", "pip", "install", "--upgrade", "--force-reinstall", "--no-deps", "--index-url", $TorchIndexUrl, "torch", "torchvision", "torchaudio")
Write-Host "Reapplying NeMo and ONNX dependency pins..."
Invoke-ParakeetPython @("-m", "pip", "install", "--upgrade", "--force-reinstall", "--no-cache-dir", "fsspec==2024.12.0", "setuptools>=79.0.0,<82", "protobuf>=6.31.1,<7")
Write-Host "Checking Python package dependency consistency..."
Invoke-ParakeetPython @("-m", "pip", "check")
Write-Host "Checking ONNX protobuf runtime compatibility..."
Test-ParakeetProtobufRuntime

if ($PersistEnv) {
    [Environment]::SetEnvironmentVariable("STROKEGPT_PARAKEET_PYTHON", $VenvPython, "User")
    Write-Host "Saved STROKEGPT_PARAKEET_PYTHON for the current Windows user."
}

$env:STROKEGPT_PARAKEET_PYTHON = $VenvPython
Write-Host ""
Write-Host "Checking the Parakeet runtime..."
Invoke-ParakeetPython @("-m", "strokegpt.parakeet_worker", "check")

Write-Host ""
Write-Host "Parakeet runtime path:"
Write-Host "  $VenvPython"
Write-Host "The app auto-detects this repo-local runtime. For a custom runtime, set:"
Write-Host "  `$env:STROKEGPT_PARAKEET_PYTHON = `"$VenvPython`""
Write-Host "Then start the normal app from .venv with:"
Write-Host "  .\.venv\Scripts\python.exe app.py"
