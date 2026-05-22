param(
    [string]$InstallRoot = (Join-Path ([Environment]::GetFolderPath("MyDocuments")) "StrokeGPT-ReVibed"),
    [ValidateSet("Prompt", "Yes", "No")]
    [string]$InstallGit = "Prompt",
    [string]$RepositoryUrl = "https://github.com/mapledaemon/StrokeGPT-ReVibed.git",
    [string]$ZipUrl = "https://github.com/mapledaemon/StrokeGPT-ReVibed/archive/refs/heads/master.zip",
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"

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

function Find-Git {
    $command = Get-Command git -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $commonPaths = @(
        "$env:ProgramFiles\Git\cmd\git.exe",
        "${env:ProgramFiles(x86)}\Git\cmd\git.exe",
        "$env:LocalAppData\Programs\Git\cmd\git.exe"
    )
    foreach ($path in $commonPaths) {
        if ($path -and (Test-Path $path)) {
            return $path
        }
    }

    return $null
}

function Install-GitIfRequested {
    $shouldInstall = Confirm-Step `
        -Mode $InstallGit `
        -Question "Git was not found. Install Git for Windows with winget so future updates can use scripts\update_windows.ps1?" `
        -DefaultYes $true

    if (-not $shouldInstall) {
        return $null
    }

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Warning "winget was not found. Falling back to a ZIP download without Git update support."
        return $null
    }

    Write-Host "Installing Git for Windows with winget..."
    & winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        throw "Git install failed."
    }

    Refresh-PathFromRegistry
    return Find-Git
}

function Download-ZipCheckout {
    $parent = Split-Path -Parent $InstallRoot
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }

    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("strokegpt-bootstrap-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
    $zipPath = Join-Path $tempRoot "StrokeGPT-ReVibed.zip"

    Write-Host "Downloading StrokeGPT-ReVibed ZIP..."
    Invoke-WebRequest -UseBasicParsing -Uri $ZipUrl -OutFile $zipPath
    Expand-Archive -LiteralPath $zipPath -DestinationPath $tempRoot

    $expanded = Get-ChildItem -LiteralPath $tempRoot -Directory |
        Where-Object { $_.Name -like "StrokeGPT-ReVibed-*" } |
        Select-Object -First 1
    if (-not $expanded) {
        throw "Could not find the extracted StrokeGPT-ReVibed folder."
    }

    Move-Item -LiteralPath $expanded.FullName -Destination $InstallRoot
}

function Ensure-Checkout {
    param([string]$GitCommand)

    if (Test-Path $InstallRoot) {
        $installScript = Join-Path $InstallRoot "scripts\install_windows.ps1"
        if (Test-Path (Join-Path $InstallRoot ".git")) {
            Write-Host "Existing Git checkout found at $InstallRoot."
            if ($GitCommand) {
                Write-Host "Updating existing checkout..."
                & $GitCommand -C $InstallRoot pull --ff-only
                if ($LASTEXITCODE -ne 0) {
                    throw "Could not fast-forward the existing checkout. Commit, stash, or move local edits, then rerun this script."
                }
            }
            return
        }
        if (Test-Path $installScript) {
            Write-Warning "Existing non-Git StrokeGPT-ReVibed folder found. Running its installer, but scripts\update_windows.ps1 needs a Git checkout."
            return
        }
        throw "Install folder already exists and is not StrokeGPT-ReVibed: $InstallRoot"
    }

    if ($GitCommand) {
        $parent = Split-Path -Parent $InstallRoot
        if ($parent) {
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
        }
        Write-Host "Running git clone..."
        & $GitCommand clone --branch master $RepositoryUrl $InstallRoot
        if ($LASTEXITCODE -ne 0) {
            throw "Git clone failed."
        }
        return
    }

    Download-ZipCheckout
}

Write-Host "== StrokeGPT-ReVibed Windows bootstrap =="
Write-Host "Install folder: $InstallRoot"
Write-Host "Administrator PowerShell is not required. Windows may still show UAC prompts for winget-installed packages."

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$gitCommand = Find-Git
if (-not $gitCommand) {
    $gitCommand = Install-GitIfRequested
}

Ensure-Checkout -GitCommand $gitCommand

$installScript = Join-Path $InstallRoot "scripts\install_windows.ps1"
if (-not (Test-Path $installScript)) {
    throw "Installer was not found after download: $installScript"
}

Write-Host ""
Write-Host "Starting StrokeGPT-ReVibed installer..."
& $installScript
if ($LASTEXITCODE -ne 0) {
    throw "StrokeGPT-ReVibed installer failed."
}

Write-Host ""
Write-Host "Bootstrap complete."
Write-Host "Installed at: $InstallRoot"
