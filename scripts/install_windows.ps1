param(
    [ValidateSet("Prompt", "Yes", "No")]
    [string]$InstallPython = "Prompt",
    [ValidateSet("Prompt", "Yes", "No")]
    [string]$InstallOllama = "Prompt",
    [ValidateSet("Prompt", "Yes", "No")]
    [string]$InstallCudaTorch = "Prompt",
    [ValidateSet("Prompt", "Yes", "No")]
    [string]$InstallParakeet = "Prompt",
    [ValidateSet("Prompt", "No", "Default", "GemmaE4B", "GemmaE2B", "Granite3B", "Granite8B")]
    [string]$DownloadOllamaModel = "Prompt",
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
$DefaultOllamaModelChoices = @(
    @{
        Id = "GemmaE4B"
        Key = "1"
        Label = "Gemma e4b Aggressive"
        Model = "nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b"
        SizeLabel = "6.3 GB"
        SizeBytes = [int64](6.3 * 1024 * 1024 * 1024)
        Note = "default, strongest default option"
    },
    @{
        Id = "GemmaE2B"
        Key = "2"
        Label = "Gemma e2b Aggressive"
        Model = "nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e2b"
        SizeLabel = "4.4 GB"
        SizeBytes = [int64](4.4 * 1024 * 1024 * 1024)
        Note = "smaller Gemma option"
    },
    @{
        Id = "Granite3B"
        Key = "3"
        Label = "Granite 3B Abliterated"
        Model = "huihui_ai/granite4.1-abliterated:3b"
        SizeLabel = "2.1 GB"
        SizeBytes = [int64](2.1 * 1024 * 1024 * 1024)
        Note = "lowest VRAM/storage option"
    },
    @{
        Id = "Granite8B"
        Key = "4"
        Label = "Granite 8B Abliterated"
        Model = "huihui_ai/granite4.1-abliterated:8b"
        SizeLabel = "5.3 GB"
        SizeBytes = [int64](5.3 * 1024 * 1024 * 1024)
        Note = "larger Granite option"
    }
)

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

function Invoke-WingetInstall {
    param(
        [string]$Description,
        [string[]]$Arguments
    )

    $exitCode = 1
    $logPath = Join-Path $env:TEMP ("strokegpt-winget-{0}.log" -f ([guid]::NewGuid().ToString("N")))

    Write-Host "$Description..."
    Write-Host "Winget output is hidden because its progress bar can render poorly in this PowerShell bootstrap window."
    Write-Host "This can take a few minutes."

    try {
        & winget @Arguments *> $logPath
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            Write-Warning "winget failed with exit code $exitCode. Last output:"
            if (Test-Path -LiteralPath $logPath) {
                Get-Content -LiteralPath $logPath -Tail 40 | ForEach-Object { Write-Host $_ }
                Write-Host "Full winget log: $logPath"
            }
        }
        return $exitCode
    } finally {
        if ($exitCode -eq 0 -and (Test-Path -LiteralPath $logPath)) {
            Remove-Item -LiteralPath $logPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Format-Bytes {
    param([int64]$Bytes)

    if ($Bytes -le 0) {
        return ""
    }
    $units = @("B", "KB", "MB", "GB", "TB")
    $size = [double]$Bytes
    $unit = $units[0]
    foreach ($candidate in $units) {
        $unit = $candidate
        if ($size -lt 1024 -or $candidate -eq $units[-1]) {
            break
        }
        $size = $size / 1024
    }
    if ($unit -eq "B") {
        return "$([int]$size) $unit"
    }
    return "{0:N1} {1}" -f $size, $unit
}

function Find-Ollama {
    $command = Get-Command ollama -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidatePaths = @()
    if ($env:LocalAppData) {
        $candidatePaths += (Join-Path $env:LocalAppData "Programs\Ollama\ollama.exe")
    }
    if ($env:ProgramFiles) {
        $candidatePaths += (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    }
    foreach ($path in $candidatePaths) {
        if ((Test-Path $path)) {
            return $path
        }
    }

    return $null
}

function Get-NvidiaVramInfo {
    $result = @{
        Detected = $false
        Name = ""
        Bytes = [int64]0
        Label = ""
    }
    if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
        return $result
    }

    $rows = @(& nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $rows) {
        return $result
    }

    foreach ($row in $rows) {
        $parts = "$row".Split(",", 2)
        if ($parts.Count -lt 2) {
            continue
        }
        $memoryMb = 0
        if (-not [int]::TryParse($parts[1].Trim(), [ref]$memoryMb)) {
            continue
        }
        $bytes = [int64]$memoryMb * 1024 * 1024
        if ($bytes -gt [int64]$result.Bytes) {
            $result.Detected = $true
            $result.Name = $parts[0].Trim()
            $result.Bytes = $bytes
            $result.Label = Format-Bytes $bytes
        }
    }
    return $result
}

function Test-PythonCommand {
    param([string[]]$Command)

    $exe = $Command[0]
    $prefix = @()
    if ($Command.Count -gt 1) {
        $prefix = $Command[1..($Command.Count - 1)]
    }

    $oldErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        & $exe @prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
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

    $pythonInstallExitCode = Invoke-WingetInstall `
        -Description "Installing Python 3.11 with winget" `
        -Arguments @(
            "install", "--id", $PythonWingetId, "-e", "--source", "winget",
            "--accept-package-agreements", "--accept-source-agreements",
            "--disable-interactivity"
        )
    if ($pythonInstallExitCode -ne 0) {
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

function Write-OllamaModelChoices {
    param([hashtable]$VramInfo)

    Write-Host ""
    Write-Host "Default Ollama model choices:"
    foreach ($choice in $DefaultOllamaModelChoices) {
        Write-Host ("  {0}. {1} - {2} - {3}" -f $choice.Key, $choice.Label, $choice.SizeLabel, $choice.Model)
        Write-Host ("     {0}" -f $choice.Note)
    }
    if ($VramInfo.Detected) {
        Write-Host ""
        Write-Host ("Detected NVIDIA GPU memory: {0} ({1})." -f $VramInfo.Label, $VramInfo.Name)
    } else {
        Write-Host ""
        Write-Host "No NVIDIA VRAM capacity was detected. Compare the model size to your GPU memory manually."
    }
    Write-Warning "VRAM capacity warning: model size is only the model file size. Context and runtime overhead need additional memory; if a model is close to or above GPU VRAM, Ollama may partly run in system memory and be slow."
}

function Find-OllamaModelChoice {
    param([string]$ChoiceId)

    if ($ChoiceId -eq "Default") {
        return $DefaultOllamaModelChoices[0]
    }
    foreach ($choice in $DefaultOllamaModelChoices) {
        if ($choice.Id -eq $ChoiceId -or $choice.Key -eq $ChoiceId) {
            return $choice
        }
    }
    return $null
}

function Select-OllamaModelForDownload {
    param([hashtable]$VramInfo)

    if ($DownloadOllamaModel -eq "No" -or $SkipModelPull) {
        return $null
    }
    if ($PullModel -and $DownloadOllamaModel -eq "Prompt") {
        return Find-OllamaModelChoice "Default"
    }
    if ($DownloadOllamaModel -ne "Prompt") {
        return Find-OllamaModelChoice $DownloadOllamaModel
    }
    if ($NonInteractive) {
        return $null
    }

    Write-OllamaModelChoices -VramInfo $VramInfo
    while ($true) {
        $answer = (Read-Host "Download one of these Ollama models now? Enter 1-4, or N to skip [N]").Trim()
        if (-not $answer -or $answer -match "^(n|no|skip)$") {
            return $null
        }
        $choice = Find-OllamaModelChoice $answer
        if ($choice) {
            return $choice
        }
        Write-Host "Please enter 1, 2, 3, 4, or N."
    }
}

function Download-OllamaModelIfRequested {
    param([hashtable]$VramInfo)

    $choice = Select-OllamaModelForDownload -VramInfo $VramInfo
    if (-not $choice) {
        Write-Host "Skipping Ollama model download. Use Settings > Model > Download Model after starting the app."
        return
    }

    $ollamaCommand = Find-Ollama
    if (-not $ollamaCommand) {
        Write-Warning "Ollama was not found on PATH. Start or reinstall Ollama, then use Settings > Model > Download Model after launching the app."
        return
    }

    if ($VramInfo.Detected -and $choice.SizeBytes -ge ([double]$VramInfo.Bytes * 0.85)) {
        Write-Warning ("Selected model {0} is {1}, close to detected GPU VRAM {2}. Ollama may partially run it in system memory and be slow." -f $choice.Model, $choice.SizeLabel, $VramInfo.Label)
    }

    Write-Host ""
    Write-Host ("Downloading Ollama model: {0} ({1})" -f $choice.Model, $choice.SizeLabel)
    Write-Host "Ollama will show download progress below."
    & $ollamaCommand pull $choice.Model
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Ollama model download failed. Start Ollama and use Settings > Model > Download Model after launching the app."
        return
    }
    Write-Host ("Ollama model downloaded: {0}" -f $choice.Model)
}

function Install-OllamaIfRequested {
    if (Find-Ollama) {
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

    $ollamaInstallExitCode = Invoke-WingetInstall `
        -Description "Installing Ollama with winget" `
        -Arguments @(
            "install", "--id", "Ollama.Ollama", "-e", "--source", "winget",
            "--accept-package-agreements", "--accept-source-agreements",
            "--disable-interactivity"
        )
    if ($ollamaInstallExitCode -ne 0) {
        throw "Ollama install failed."
    }
    Refresh-PathFromRegistry
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
    Write-Host "Legacy model download switch detected."
    Write-Host "  -PullModel now downloads the default Ollama model."
    Write-Host "  -SkipModelPull skips Ollama model downloads."
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
$VramInfo = Get-NvidiaVramInfo
if ($NvidiaDetected) {
    Write-Host "NVIDIA GPU detected."
} else {
    Write-Host "No NVIDIA GPU was detected through nvidia-smi."
}

Install-OllamaIfRequested
Download-OllamaModelIfRequested -VramInfo $VramInfo

Write-Host ""
Write-Host "Installing Python dependencies..."
Invoke-VenvPython @("-m", "pip", "install", "--upgrade", "pip")
Invoke-VenvPython @("-m", "pip", "install", "-r", "requirements.txt")

Install-CudaTorchIfRequested -NvidiaDetected $NvidiaDetected
Install-ParakeetIfRequested -NvidiaDetected $NvidiaDetected

Write-Host ""
Write-Host "Install complete."
Write-Host "Start the app later by double-clicking:"
Write-Host "  Run StrokeGPT-ReVibed.cmd"
Write-Host ""
Write-Host "Use the app's Model or Voice settings for any model downloads you skipped during setup."
