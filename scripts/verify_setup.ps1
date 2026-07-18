param(
    [string]$PythonPath = "",
    [string]$OllamaBaseUrl = "http://127.0.0.1:11434",
    [int]$Port = 5000,
    [switch]$SkipOllama,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$script:Results = @()
$script:PythonDiscoveryWarning = ""

Set-Location $ProjectRoot

function Add-Check {
    param(
        [string]$Id,
        [string]$Label,
        [ValidateSet("ok", "warning", "error", "skipped")]
        [string]$Status,
        [string]$Detail
    )

    $script:Results += [pscustomobject]@{
        id = $Id
        label = $Label
        status = $Status
        detail = $Detail
    }
}

function Test-PythonCommand {
    param([string[]]$CommandParts)

    $exe = $CommandParts[0]
    $prefix = @()
    if ($CommandParts.Count -gt 1) {
        $prefix = $CommandParts[1..($CommandParts.Count - 1)]
    }

    try {
        & $exe @prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
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
        $script:PythonDiscoveryWarning = "The existing .venv Python could not start; trying system Python. Run .\scripts\install_windows.ps1 if the fallback does not include app dependencies."
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

    $oldErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $exe @prefix @Arguments 2>&1
        return [pscustomobject]@{
            ExitCode = $LASTEXITCODE
            Output = ($output | ForEach-Object { "$_" }) -join "`n"
        }
    }
    catch {
        return [pscustomobject]@{
            ExitCode = 1
            Output = $_.Exception.Message
        }
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
}

function Test-PythonModule {
    param(
        [string]$Id,
        [string]$Label,
        [string]$ModuleName,
        [switch]$Required
    )

    $code = "import importlib; name = '$ModuleName'; module = importlib.import_module(name); print(getattr(module, '__file__', None) or 'available')"
    $result = Invoke-SelectedPython @("-c", $code)
    if ($result.ExitCode -eq 0) {
        Add-Check $Id $Label "ok" "$ModuleName is importable."
    } elseif ($Required) {
        Add-Check $Id $Label "error" "$ModuleName is missing. Run .\scripts\install_windows.ps1 or python -m pip install -r requirements.txt."
    } else {
        Add-Check $Id $Label "warning" "$ModuleName is not importable. The related optional feature may be unavailable."
    }
}

function Test-TorchRuntime {
    $spec = Invoke-SelectedPython @("-c", "import importlib.util, sys; raise SystemExit(0 if importlib.util.find_spec('torch') else 1)")
    if ($spec.ExitCode -ne 0) {
        Add-Check "torch-cuda" "Torch / CUDA" "warning" "torch is not importable. Local Chatterbox voice will be unavailable until Torch is installed."
        return
    }

    $code = "import torch; print('torch ' + str(torch.__version__)); print('cuda_available=' + str(torch.cuda.is_available())); print('cuda_version=' + str(torch.version.cuda)); print('device=' + (torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none'))"
    $result = Invoke-SelectedPython @("-c", $code)
    if ($result.ExitCode -eq 0 -and $result.Output -match "cuda_available=True") {
        Add-Check "torch-cuda" "Torch / CUDA" "ok" ($result.Output -replace "`r?`n", "; ")
    } elseif ($result.ExitCode -eq 0) {
        Add-Check "torch-cuda" "Torch / CUDA" "warning" (($result.Output -replace "`r?`n", "; ") + "; CUDA is not available, so local voice may be slow.")
    } else {
        Add-Check "torch-cuda" "Torch / CUDA" "warning" ($result.Output -replace "`r?`n", "; ")
    }
}

function Test-Ollama {
    if ($SkipOllama) {
        Add-Check "ollama" "Ollama server" "skipped" "Skipped because -SkipOllama was supplied."
        return
    }

    try {
        $uri = ($OllamaBaseUrl.TrimEnd("/")) + "/api/tags"
        $response = Invoke-WebRequest -UseBasicParsing -Uri $uri -TimeoutSec 4
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
            Add-Check "ollama" "Ollama server" "ok" "Ollama answered $uri."
        } else {
            Add-Check "ollama" "Ollama server" "warning" "Ollama returned HTTP $($response.StatusCode) from $uri."
        }
    }
    catch {
        Add-Check "ollama" "Ollama server" "warning" "Ollama did not answer at $OllamaBaseUrl. Start Ollama before chatting or downloading models."
    }
}

function Test-PortAvailability {
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        $listener.Stop()
        Add-Check "port" "Local app port" "ok" "Port $Port is available on 127.0.0.1."
    }
    catch {
        Add-Check "port" "Local app port" "warning" "Port $Port is already in use. The app can choose the next free local port."
    }
}

function Test-WritableFolder {
    param(
        [string]$Id,
        [string]$Label,
        [string]$RelativePath
    )

    $path = Join-Path $ProjectRoot $RelativePath
    $testFile = Join-Path $path ".strokegpt-verify.tmp"
    try {
        New-Item -ItemType Directory -Force -Path $path *> $null
        Set-Content -LiteralPath $testFile -Value "ok" -NoNewline -Encoding ASCII
        Remove-Item -LiteralPath $testFile -Force
        Add-Check $Id $Label "ok" "$RelativePath is writable."
    }
    catch {
        Add-Check $Id $Label "error" "$RelativePath is not writable: $($_.Exception.Message)"
    }
}

function Write-HumanReport {
    Write-Host "== StrokeGPT-ReVibed setup verifier =="
    Write-Host "Project: $ProjectRoot"
    Write-Host "Python: $($script:PythonCommand -join ' ')"
    Write-Host ""

    foreach ($item in $script:Results) {
        $prefix = @{
            ok = "[OK]"
            warning = "[WARN]"
            error = "[ERROR]"
            skipped = "[SKIP]"
        }[$item.status]
        Write-Host "$prefix $($item.label): $($item.detail)"
    }

    $errors = @($script:Results | Where-Object { $_.status -eq "error" }).Count
    $warnings = @($script:Results | Where-Object { $_.status -eq "warning" }).Count
    Write-Host ""
    if ($errors -gt 0) {
        Write-Host "Setup verifier found $errors error(s) and $warnings warning(s)."
    } elseif ($warnings -gt 0) {
        Write-Host "Setup verifier found $warnings warning(s)."
    } else {
        Write-Host "Setup verifier passed."
    }
}

try {
    $script:PythonCommand = @(Find-Python)
    $version = Invoke-SelectedPython @("-c", "import sys; print(f'{sys.executable} ({sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro})')")
    if ($version.ExitCode -eq 0) {
        Add-Check "python" "Python runtime" "ok" $version.Output
        if ($script:PythonDiscoveryWarning) {
            Add-Check "python-venv" "Project virtualenv" "warning" $script:PythonDiscoveryWarning
        }
    } else {
        Add-Check "python" "Python runtime" "error" $version.Output
    }

    Test-PythonModule "flask" "Flask dependency" "flask" -Required
    Test-PythonModule "requests" "Requests dependency" "requests" -Required
    Test-PythonModule "cryptography" "Cryptography dependency" "cryptography" -Required
    Test-PythonModule "elevenlabs" "ElevenLabs dependency" "elevenlabs" -Required
    Test-PythonModule "faster-whisper" "faster-whisper voice input" "faster_whisper"
    Test-PythonModule "chatterbox" "Chatterbox local voice" "chatterbox"
    Test-PythonModule "chatterbox-turbo" "Chatterbox Turbo local voice" "chatterbox.tts_turbo"
    Test-TorchRuntime
}
catch {
    Add-Check "python" "Python runtime" "error" $_.Exception.Message
}

Test-Ollama
Test-PortAvailability
Test-WritableFolder "user-data" "User data folder" "user_data"
Test-WritableFolder "diagnostics-folder" "Diagnostics folder" "user_data\diagnostics"
Test-WritableFolder "voice-samples" "Voice sample folder" "voice_samples"

if ($Json) {
    [pscustomobject]@{
        project_root = $ProjectRoot
        python_command = $script:PythonCommand
        checks = $script:Results
    } | ConvertTo-Json -Depth 5
} else {
    Write-HumanReport
}

$errorCount = @($script:Results | Where-Object { $_.status -eq "error" }).Count
if ($errorCount -gt 0) {
    exit 1
}
exit 0
