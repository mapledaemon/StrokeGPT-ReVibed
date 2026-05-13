param(
    [ValidateSet("Prompt", "Yes", "No")]
    [string]$InstallPython = "Prompt",
    [ValidateSet("Prompt", "Yes", "No")]
    [string]$InstallOllama = "Prompt",
    [ValidateSet("Prompt", "Yes", "No")]
    [string]$InstallCudaTorch = "Prompt",
    [ValidateSet("Prompt", "Yes", "No")]
    [string]$InstallParakeet = "Prompt",
    [string]$PythonWingetId = "Python.Python.3.11",
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu128",
    [switch]$NonInteractive,
    [switch]$PullModel,
    [switch]$SkipModelPull
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ParakeetInstallScript = Join-Path $PSScriptRoot "install_parakeet.ps1"

Set-Location $ProjectRoot

function Confirm-Step {
    param(
        [string]$Mode,
        [string]$Question,
        [bool]$DefaultYes = $false
    )

    if ($Mode -eq "Yes") {
        return $true
    }
    if ($Mode -eq "No") {
        return $false
    }
    if ($NonInteractive) {
        return $DefaultYes
    }

    $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    while ($true) {
        $answer = (Read-Host "$Question $suffix").Trim().ToLowerInvariant()
        if (-not $answer) {
            return $DefaultYes
        }
        if ($answer -in @("y", "yes")) {
            return $true
        }
        if ($answer -in @("n", "no")) {
            return $false
        }
        Write-Host "Please answer yes or no."
    }
}

function Refresh-PathFromRegistry {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = (@($machinePath, $userPath, $env:Path) | Where-Object { $_ }) -join ";"
}

function Test-PythonCommand {
    param([string[]]$Command)

    $exe = $Command[0]
    $prefix = @()
    if ($Command.Count -gt 1) {
        $prefix = $Command[1..($Command.Count - 1)]
    }

    & $exe @prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

function Find-PythonCandidate {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        if (Test-PythonCommand @("py", "-3.11")) {
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
        if ((Test-Path $path) -and (Test-PythonCommand @($path))) {
            return @($path)
        }
    }

    return $null
}

function Install-PythonIfRequested {
    $shouldInstall = Confirm-Step `
        -Mode $InstallPython `
        -Question "Python 3.11 was not found. Install Python 3.11 with winget now?" `
        -DefaultYes $true

    if (-not $shouldInstall) {
        throw "Python 3.10+ is required. Install Python 3.11 from https://www.python.org/downloads/windows/, then rerun this script."
    }

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget was not found. Install Python 3.11 from https://www.python.org/downloads/windows/, enable 'Add python.exe to PATH', then rerun this script."
    }

    Write-Host "Installing Python 3.11 with winget..."
    & winget install --id $PythonWingetId -e --source winget
    if ($LASTEXITCODE -ne 0) {
        throw "Python install failed."
    }

    Refresh-PathFromRegistry
}

function Find-Python {
    $candidate = Find-PythonCandidate
    if ($candidate) {
        return $candidate
    }

    Install-PythonIfRequested

    $candidate = Find-PythonCandidate
    if ($candidate) {
        return $candidate
    }

    throw "Python 3.10+ was not found after install. Restart PowerShell, then rerun this script."
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

function Invoke-VenvPython {
    param([string[]]$Arguments)

    & $VenvPython @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Virtual environment command failed: $($Arguments -join ' ')"
    }
}

function Test-NvidiaGpu {
    if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
        return $false
    }

    & nvidia-smi -L 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Install-OllamaIfRequested {
    if (Get-Command ollama -ErrorAction SilentlyContinue) {
        Write-Host "Ollama is already available on PATH."
        return
    }

    $shouldInstall = Confirm-Step `
        -Mode $InstallOllama `
        -Question "Ollama was not found. Install Ollama with winget now?" `
        -DefaultYes $true

    if (-not $shouldInstall) {
        Write-Warning "Skipping Ollama install. Install Ollama manually before using local chat."
        return
    }

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Warning "winget was not found. Install Ollama manually from https://ollama.com/download/windows."
        return
    }

    Write-Host "Installing Ollama with winget..."
    & winget install --id Ollama.Ollama -e --source winget
    if ($LASTEXITCODE -ne 0) {
        throw "Ollama install failed."
    }
    Write-Host "Ollama install finished. Restart PowerShell if the ollama command is not available yet."
}

function Install-CudaTorchIfRequested {
    param([bool]$NvidiaDetected)

    $question = if ($NvidiaDetected) {
        "NVIDIA GPU detected. Install CUDA PyTorch for faster local Chatterbox voice?"
    } else {
        "Install CUDA PyTorch for local Chatterbox voice? Choose no unless this machine has an NVIDIA GPU."
    }
    $shouldInstall = Confirm-Step `
        -Mode $InstallCudaTorch `
        -Question $question `
        -DefaultYes $NvidiaDetected

    if (-not $shouldInstall) {
        Write-Host "Skipping CUDA PyTorch install. Local Chatterbox voice can still use CPU Torch if available."
        return
    }

    Write-Host "Installing CUDA PyTorch in .venv..."
    Write-Host "Using PyTorch wheel index: $TorchIndexUrl"
    Invoke-VenvPython @("-m", "pip", "install", "--upgrade", "--force-reinstall", "--index-url", $TorchIndexUrl, "torch", "torchvision", "torchaudio")
    Invoke-VenvPython @("-c", "import torch; print('Torch:', torch.__version__); print('CUDA available:', torch.cuda.is_available()); print('CUDA build:', torch.version.cuda)")
}

function Install-ParakeetIfRequested {
    param([bool]$NvidiaDetected)

    $question = if ($NvidiaDetected) {
        "Install the isolated NVIDIA Parakeet voice-input runtime? This is large but fastest on compatible NVIDIA GPUs."
    } else {
        "Install the isolated NVIDIA Parakeet voice-input runtime? Choose no unless this machine has a compatible NVIDIA GPU."
    }
    $shouldInstall = Confirm-Step `
        -Mode $InstallParakeet `
        -Question $question `
        -DefaultYes $NvidiaDetected

    if (-not $shouldInstall) {
        Write-Host "Skipping NVIDIA Parakeet runtime. Local faster-whisper remains available as the portable voice-input path."
        return
    }

    & $ParakeetInstallScript -TorchIndexUrl $TorchIndexUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Parakeet installer failed."
    }
}

Write-Host "== StrokeGPT-ReVibed Windows installer =="
Write-Host "Project: $ProjectRoot"

if ($PullModel -or $SkipModelPull) {
    Write-Host "Model download switches are no longer used by the Windows installer."
    Write-Host "Download Ollama, local voice, and voice-input models from inside the app so progress is visible."
}

$script:PythonCommand = Find-Python
Write-Host "Using Python command: $($script:PythonCommand -join ' ')"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment..."
    Invoke-SelectedPython @("-m", "venv", ".venv")
}

$PythonVersion = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) {
    throw "The virtual environment Python could not start."
}
if ($PythonVersion -ne "3.11") {
    Write-Warning "Virtual environment is Python $PythonVersion. Local Chatterbox voice works best with Python 3.11."
}

$NvidiaDetected = Test-NvidiaGpu
if ($NvidiaDetected) {
    Write-Host "NVIDIA GPU detected."
} else {
    Write-Host "No NVIDIA GPU was detected through nvidia-smi."
}

Install-OllamaIfRequested

Write-Host ""
Write-Host "Installing Python dependencies..."
Invoke-VenvPython @("-m", "pip", "install", "--upgrade", "pip")
Invoke-VenvPython @("-m", "pip", "install", "-r", "requirements.txt")

Install-CudaTorchIfRequested -NvidiaDetected $NvidiaDetected
Install-ParakeetIfRequested -NvidiaDetected $NvidiaDetected

Write-Host ""
Write-Host "Install complete."
Write-Host "Start the app with:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  python app.py"
Write-Host ""
Write-Host "Model files are not downloaded by this installer. Use the app's Model or Voice settings to download models with visible progress."
