# ─────────────────────────────────────────────────────────────────────
# AGENT Context Local — Prerequisite Installer (Windows PowerShell)
#
# Checks for Python 3.12+, uv, and git. Offers to install anything
# missing. Every install is opt-in — nothing happens without your "y".
#
# Usage:
#   irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/prereqs.ps1 | iex
#   # or locally:
#   powershell -ExecutionPolicy Bypass -File scripts\prereqs.ps1
# ─────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

function Write-OK    { param([string]$Msg) Write-Host "  [OK]    $Msg" -ForegroundColor Green }
function Write-Skip  { param([string]$Msg) Write-Host "  [SKIP]  $Msg" -ForegroundColor Yellow }
function Write-Miss  { param([string]$Msg) Write-Host "  [MISS]  $Msg" -ForegroundColor Red }
function Write-Info  { param([string]$Msg) Write-Host "  [INFO]  $Msg" -ForegroundColor Cyan }
function Write-Bold  { param([string]$Msg) Write-Host $Msg -ForegroundColor White }

$NonInteractive = $false
try {
    if ([Console]::IsInputRedirected) { $NonInteractive = $true }
} catch {
    # Console class may not be available in all hosts
}
if (-not [Environment]::UserInteractive) { $NonInteractive = $true }

function Ask-YesNo {
    param([string]$Prompt)
    if ($NonInteractive) {
        Write-Skip "$Prompt (non-interactive - run locally to install)"
        return $false
    }
    $answer = Read-Host "$Prompt [y/N]"
    return ($answer -match '^[yY]')
}

# Check if winget is available
function Test-Winget {
    try {
        $null = Get-Command winget -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

# Parse Python version from output string
function Get-PythonVersion {
    param([string]$Cmd)
    try {
        $output = & $Cmd --version 2>&1
        if ($output -match '(\d+)\.(\d+)\.(\d+)') {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            $patch = [int]$Matches[3]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 12)) {
                return "$major.$minor.$patch"
            }
        }
    } catch {}
    return $null
}

Write-Host ""
Write-Bold "AGENT Context Local - Prerequisite Check"
Write-Host ""

$NeedPython = $false
$NeedUV     = $false
$NeedGit    = $false
$HasWinget  = Test-Winget

# ── 1. Check Python ─────────────────────────────────────────────────
$PythonVer = $null
$PythonCmd = $null
foreach ($candidate in @("python", "python3", "py")) {
    $ver = Get-PythonVersion $candidate
    if ($ver) {
        $PythonVer = $ver
        $PythonCmd = $candidate
        break
    }
}

# Also try the Python Launcher (py -3) on Windows
if (-not $PythonVer) {
    try {
        $output = py -3 --version 2>&1
        if ($output -match '(\d+)\.(\d+)\.(\d+)') {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 12)) {
                $PythonVer = "$($Matches[1]).$($Matches[2]).$($Matches[3])"
                $PythonCmd = "py -3"
            }
        }
    } catch {}
}

if ($PythonVer) {
    Write-OK "Python $PythonVer ($PythonCmd)"
} else {
    Write-Miss "Python 3.12+ not found"
    $NeedPython = $true
}

# ── 2. Check uv ─────────────────────────────────────────────────────
if (Get-Command uv -ErrorAction SilentlyContinue) {
    $uvOutput = uv --version 2>&1
    if ($uvOutput -match '(\d+\.\d+\.\d+)') {
        Write-OK "uv $($Matches[1])"
    } else {
        Write-OK "uv (version unknown)"
    }
} else {
    Write-Miss "uv not found"
    $NeedUV = $true
}

# ── 3. Check git ────────────────────────────────────────────────────
if (Get-Command git -ErrorAction SilentlyContinue) {
    $gitOutput = git --version 2>&1
    if ($gitOutput -match '(\d+\.\d+\.\d+)') {
        Write-OK "git $($Matches[1])"
    } else {
        Write-OK "git (version unknown)"
    }
} else {
    Write-Miss "git not found"
    $NeedGit = $true
}

# ── Summary ─────────────────────────────────────────────────────────
Write-Host ""
if (-not $NeedPython -and -not $NeedUV -and -not $NeedGit) {
    Write-Host "All prerequisites satisfied!" -ForegroundColor Green
    Write-Host "You're ready to install AGENT Context Local.`n"
    exit 0
}

$missing = @()
if ($NeedPython) { $missing += "Python 3.12+" }
if ($NeedUV)     { $missing += "uv" }
if ($NeedGit)    { $missing += "git" }
Write-Host "Missing: $($missing -join ', ')" -ForegroundColor Yellow
Write-Host ""

# ── Install Python ──────────────────────────────────────────────────
if ($NeedPython) {
    Write-Bold "Install Python"
    Write-Host ""
    if ($HasWinget) {
        Write-Info "Option 1 (recommended): Install via winget (built into Windows)"
        Write-Info "Will run: winget install -e --id Python.Python.3.13"
        Write-Host ""
        if (Ask-YesNo "Install Python 3.13 via winget?") {
            try {
                winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements
                Write-OK "Python installed via winget"
                Write-Info "You may need to restart your terminal for 'python' to be on PATH."
            } catch {
                Write-Host "  winget install failed: $_" -ForegroundColor Red
                Write-Info "Try downloading manually from https://www.python.org/downloads/"
            }
        } else {
            Write-Skip "Python install skipped"
        }
    } else {
        Write-Info "winget not available on this system."
        Write-Info "Download Python from: https://www.python.org/downloads/"
        Write-Info "During install, check 'Add python.exe to PATH'."
        Write-Host ""
        if (Ask-YesNo "Open the Python download page in your browser?") {
            Start-Process "https://www.python.org/downloads/"
            Write-Info "Install Python, then restart your terminal and re-run this script."
        } else {
            Write-Skip "Python install skipped"
        }
    }
    Write-Host ""
}

# ── Install uv ──────────────────────────────────────────────────────
if ($NeedUV) {
    Write-Bold "Install uv (Python package manager)"
    Write-Host ""
    Write-Info "uv is a fast Python package manager from Astral."
    Write-Info "No admin required. Installs to $env:USERPROFILE\.local\bin."
    Write-Info "Will run: irm https://astral.sh/uv/install.ps1 | iex"
    Write-Host ""
    if (Ask-YesNo "Install uv?") {
        try {
            $installScript = (Invoke-WebRequest -Uri "https://astral.sh/uv/install.ps1" -UseBasicParsing).Content
            Invoke-Expression $installScript

            # Add to PATH for this session
            $uvPath = Join-Path $env:USERPROFILE ".local\bin"
            if (Test-Path $uvPath) {
                $env:PATH = "$uvPath;$env:PATH"
            }
            # Also check cargo/bin path (alternate install location)
            $cargoPath = Join-Path $env:USERPROFILE ".cargo\bin"
            if (Test-Path $cargoPath) {
                $env:PATH = "$cargoPath;$env:PATH"
            }

            if (Get-Command uv -ErrorAction SilentlyContinue) {
                Write-OK "uv installed successfully"
            } else {
                Write-Info "uv installed but not yet on PATH."
                Write-Info "Restart your terminal, then re-run this script."
            }
        } catch {
            Write-Host "  uv install failed: $_" -ForegroundColor Red
            Write-Info "Try manually: https://docs.astral.sh/uv/getting-started/installation/"
        }
    } else {
        Write-Skip "uv install skipped"
    }
    Write-Host ""
}

# ── Install git ─────────────────────────────────────────────────────
if ($NeedGit) {
    Write-Bold "Install git"
    Write-Host ""
    if ($HasWinget) {
        Write-Info "Will run: winget install --id Git.Git -e --source winget"
        Write-Host ""
        if (Ask-YesNo "Install git via winget?") {
            try {
                winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements
                Write-OK "git installed via winget"
                Write-Info "You may need to restart your terminal for 'git' to be on PATH."
            } catch {
                Write-Host "  winget install failed: $_" -ForegroundColor Red
                Write-Info "Download manually from: https://git-scm.com/downloads/win"
            }
        } else {
            Write-Skip "git install skipped"
        }
    } else {
        Write-Info "winget not available on this system."
        Write-Info "Download git from: https://git-scm.com/downloads/win"
        Write-Host ""
        if (Ask-YesNo "Open the git download page in your browser?") {
            Start-Process "https://git-scm.com/downloads/win"
            Write-Info "Install git, then restart your terminal and re-run this script."
        } else {
            Write-Skip "git install skipped"
        }
    }
    Write-Host ""
}

# ── Final check ─────────────────────────────────────────────────────
Write-Bold "Final verification"
Write-Host ""
$AllGood = $true

# Re-check Python
$FinalPython = $null
foreach ($candidate in @("python", "python3", "py")) {
    $ver = Get-PythonVersion $candidate
    if ($ver) { $FinalPython = $ver; break }
}
if ($FinalPython) {
    Write-OK "Python $FinalPython"
} else {
    Write-Miss "Python 3.12+ still not found"
    $AllGood = $false
}

# Re-check uv
if (Get-Command uv -ErrorAction SilentlyContinue) {
    $uvOut = uv --version 2>&1
    if ($uvOut -match '(\d+\.\d+\.\d+)') { Write-OK "uv $($Matches[1])" }
    else { Write-OK "uv" }
} else {
    Write-Miss "uv still not found"
    $AllGood = $false
}

# Re-check git
if (Get-Command git -ErrorAction SilentlyContinue) {
    $gitOut = git --version 2>&1
    if ($gitOut -match '(\d+\.\d+\.\d+)') { Write-OK "git $($Matches[1])" }
    else { Write-OK "git" }
} else {
    Write-Miss "git still not found"
    $AllGood = $false
}

Write-Host ""
if ($AllGood) {
    Write-Host "All prerequisites satisfied!" -ForegroundColor Green
    Write-Host "You're ready to install AGENT Context Local.`n"
    Write-Bold "Next step:"
    Write-Host '  irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.ps1 | iex'
    Write-Host ""
} else {
    Write-Host "Some prerequisites are still missing." -ForegroundColor Yellow
    Write-Host "Install them manually, restart your terminal, then re-run:"
    Write-Host '  powershell -File scripts\prereqs.ps1'
    Write-Host ""
}
