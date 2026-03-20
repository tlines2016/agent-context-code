param(
    [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [int]$Port = 7432,
    [string]$UvExtra = "cu128",
    [switch]$SkipBuild,
    [switch]$NoBrowser,
    [switch]$DryRun,
    [switch]$ForceKill
)

$ErrorActionPreference = "Stop"

function Write-Section {
    param([string]$Message)
    Write-Host ""
    Write-Host "=================================================="
    Write-Host $Message
    Write-Host "=================================================="
    Write-Host ""
}

function Write-Step {
    param([string]$Message)
    Write-Host "-> $Message"
}

function Fail {
    param([string]$Message)
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Test-RepoLayout {
    param([string]$Path)
    $serverPath = Join-Path $Path "ui_server\server.py"
    $uiPkg = Join-Path $Path "ui\package.json"
    return (Test-Path $serverPath) -and (Test-Path $uiPkg)
}

function Get-ListeningPids {
    param([int]$TargetPort)
    $listeners = Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction SilentlyContinue
    if (-not $listeners) {
        return @()
    }
    return $listeners | Select-Object -ExpandProperty OwningProcess -Unique
}

function Wait-ForDashboard {
    param(
        [int]$TargetPort,
        [int]$TimeoutSeconds = 60
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $healthUrl = "http://127.0.0.1:$TargetPort/api/v1/health"

    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2 -Method Get
            if ($resp.status) {
                return $true
            }
        } catch {
            Start-Sleep -Milliseconds 700
        }
    }
    return $false
}

Write-Section "Restart Agent Context Dashboard"

if (-not (Test-RepoLayout -Path $RepoPath)) {
    Fail "Repo path '$RepoPath' does not look like this project (missing ui_server/server.py or ui/package.json)."
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Fail "uv is required but was not found in PATH."
}

if (-not $SkipBuild) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Fail "npm is required for frontend build but was not found in PATH. Re-run with -SkipBuild to bypass build."
    }
}

Write-Step "Repo path: $RepoPath"
Write-Step "UI port: $Port"
Write-Step "UV extra: $UvExtra"
if ($DryRun) {
    Write-Host "Dry-run mode enabled (no processes will be killed or started)."
}

# Step 1: stop any process currently listening on the target port.
$pids = Get-ListeningPids -TargetPort $Port
if ($pids.Count -gt 0) {
    Write-Step "Found listener(s) on port ${Port}: $($pids -join ', ')"
    foreach ($procId in $pids) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        $procName = if ($proc) { $proc.ProcessName } else { "unknown" }

        # Safety guard: by default only auto-kill likely dashboard-related processes.
        $safeNames = @("python", "python3", "uv", "agent-context-local-ui", "uvicorn")
        $safeToKill = $safeNames -contains $procName.ToLowerInvariant()
        if (-not $safeToKill -and -not $ForceKill) {
            Fail "PID $procId ('$procName') is listening on $Port. Re-run with -ForceKill to allow terminating non-standard process names."
        }

        if ($DryRun) {
            Write-Host "DRY-RUN: would stop PID $procId ('$procName')."
        } else {
            Write-Host "Stopping PID $procId ('$procName')..."
            Stop-Process -Id $procId -Force
        }
    }
    if (-not $DryRun) {
        Start-Sleep -Milliseconds 500
    }
} else {
    Write-Step "No existing listener on port $Port."
}

# Step 2: rebuild frontend static assets.
if (-not $SkipBuild) {
    $uiPath = Join-Path $RepoPath "ui"
    if ($DryRun) {
        Write-Host "DRY-RUN: would run npm --prefix `"$uiPath`" run build"
    } else {
        Write-Step "Building frontend assets..."
        npm --prefix "$uiPath" run build
        if ($LASTEXITCODE -ne 0) {
            Fail "Frontend build failed."
        }
    }
} else {
    Write-Step "Skipping frontend build (-SkipBuild)."
}

# Step 3: start dashboard server.
$uvArgs = @("run")
if ($UvExtra) {
    $uvArgs += @("--extra", $UvExtra)
}
$uvArgs += @("--directory", $RepoPath, "python", "ui_server/server.py")
if ($NoBrowser) {
    $uvArgs += "--no-browser"
}

if ($DryRun) {
    Write-Host "DRY-RUN: would launch: uv $($uvArgs -join ' ')"
    Write-Host "DRY-RUN complete."
    exit 0
}

Write-Step "Starting dashboard server..."
$proc = Start-Process -FilePath "uv" -ArgumentList $uvArgs -PassThru -WindowStyle Hidden
Write-Host "Started PID $($proc.Id). Waiting for health endpoint..."

if (-not (Wait-ForDashboard -TargetPort $Port -TimeoutSeconds 60)) {
    if ($proc -and -not $proc.HasExited) {
        Write-Host "Dashboard did not become healthy in time; stopping launched PID $($proc.Id)..."
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    Fail "Dashboard did not become healthy on port $Port within 60 seconds."
}

Write-Host ""
Write-Host "Dashboard restarted successfully." -ForegroundColor Green
Write-Host "URL: http://127.0.0.1:$Port/"
Write-Host ""
Write-Host "Quick verify:"
Write-Host "  Invoke-RestMethod http://127.0.0.1:$Port/api/v1/health"
