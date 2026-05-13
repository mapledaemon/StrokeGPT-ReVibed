param(
    [switch]$SkipGitPull,
    [switch]$SkipDependencies,
    [switch]$UpdateParakeet,
    [switch]$RunValidation,
    [switch]$AllowLocalChanges
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$InstallScript = Join-Path $PSScriptRoot "install_windows.ps1"
$ParakeetInstallScript = Join-Path $PSScriptRoot "install_parakeet.ps1"
$ValidationScript = Join-Path $PSScriptRoot "test_and_run.ps1"

Set-Location $ProjectRoot

function Find-Git {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        return "git"
    }

    throw "Git was not found on PATH. Install Git for Windows, or update from a fresh ZIP/download instead."
}

function Invoke-Git {
    param([string[]]$Arguments)

    & $script:GitCommand @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($Arguments -join ' ')"
    }
}

function Get-UpstreamRef {
    $upstream = (& $script:GitCommand rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>$null)
    if ($LASTEXITCODE -eq 0 -and $upstream) {
        return $upstream.Trim()
    }

    $defaultRef = (& $script:GitCommand symbolic-ref --short "refs/remotes/origin/HEAD" 2>$null)
    if ($LASTEXITCODE -eq 0 -and $defaultRef) {
        return $defaultRef.Trim()
    }

    return "origin/master"
}

function Assert-CleanTrackedWorktree {
    $trackedChanges = (& $script:GitCommand status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect Git status."
    }

    if ($trackedChanges -and -not $AllowLocalChanges) {
        Write-Host ""
        Write-Warning "Tracked local edits are present. The updater will not overwrite them."
        Write-Host $trackedChanges
        Write-Host ""
        throw "Commit, stash, or discard tracked local edits before updating. To attempt the update anyway, rerun with -AllowLocalChanges."
    }
}

Write-Host "== StrokeGPT-ReVibed Windows updater =="
Write-Host "Project: $ProjectRoot"

if (-not $SkipGitPull) {
    if (-not (Test-Path (Join-Path $ProjectRoot ".git"))) {
        throw "This folder is not a Git checkout. Download a fresh copy, or reinstall from the repository."
    }

    $script:GitCommand = Find-Git
    Assert-CleanTrackedWorktree

    Write-Host ""
    Write-Host "Fetching updates from origin..."
    Invoke-Git @("fetch", "origin")

    $upstreamRef = Get-UpstreamRef
    Write-Host "Fast-forwarding from $upstreamRef..."
    Invoke-Git @("merge", "--ff-only", $upstreamRef)
} else {
    Write-Host ""
    Write-Host "Skipping Git update because -SkipGitPull was supplied."
}

if (-not $SkipDependencies) {
    Write-Host ""
    if (-not (Test-Path $VenvPython)) {
        Write-Host "No .venv found. Running the Windows installer without model downloads..."
        & $InstallScript -NonInteractive -InstallOllama No -InstallCudaTorch No -InstallParakeet No -DownloadOllamaModel No
    } else {
        Write-Host "Updating Python dependencies in .venv..."
        & $VenvPython -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) {
            throw "pip upgrade failed."
        }
        & $VenvPython -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) {
            throw "requirements install failed."
        }
    }
} else {
    Write-Host ""
    Write-Host "Skipping Python dependencies because -SkipDependencies was supplied."
}

if ($UpdateParakeet) {
    Write-Host ""
    Write-Host "Updating isolated NVIDIA Parakeet runtime..."
    & $ParakeetInstallScript
    if ($LASTEXITCODE -ne 0) {
        throw "Parakeet runtime update failed."
    }
} else {
    Write-Host ""
    Write-Host "Skipping Parakeet runtime. Use -UpdateParakeet to refresh .venv-parakeet."
}

if ($RunValidation) {
    Write-Host ""
    Write-Host "Running validation checks without launching the app..."
    & $ValidationScript -NoRun
    if ($LASTEXITCODE -ne 0) {
        throw "Validation failed."
    }
}

Write-Host ""
Write-Host "Update complete."
Write-Host "Restart the app with:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  python app.py"
Write-Host ""
Write-Host "Model files are not downloaded by this updater. Use the app's Model or Voice settings to download models with visible progress."
