param(
    [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$ServerName = "code-search",
    [string]$Scope = "user",
    [string]$UvExtra = "cu128",
    [switch]$SkipStopProcess,
    [switch]$DryRun
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
    $serverPath = Join-Path $Path "mcp_server\server.py"
    $cliPath = Join-Path $Path "scripts\cli.py"
    return (Test-Path $serverPath) -and (Test-Path $cliPath)
}

function Stop-McpServerProcesses {
    param([string]$TargetRepo)

    $normalizedRepo = $TargetRepo.ToLowerInvariant().Replace("\", "/")

    # Stop only python processes whose command line includes this repo + mcp_server/server.py.
    # This avoids killing unrelated Python jobs on the machine.
    $candidates = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $cmdLine = $_.CommandLine
            if (-not $cmdLine) { return $false }
            $normalizedCmd = $cmdLine.ToLowerInvariant().Replace("\", "/")
            ($_.Name -match "^python(\d+)?\.exe$|^python(\d+)?$") -and
            $normalizedCmd.Contains("mcp_server/server.py") -and
            $normalizedCmd.Contains($normalizedRepo)
        }

    if (-not $candidates) {
        Write-Step "No running local MCP server process found for this repo."
        return
    }

    Write-Step "Stopping existing local MCP server process(es): $($candidates.ProcessId -join ', ')"
    foreach ($proc in $candidates) {
        if ($DryRun) {
            Write-Host "DRY-RUN: would stop PID $($proc.ProcessId) ($($proc.Name))."
            continue
        }
        Stop-Process -Id $proc.ProcessId -Force
    }
}

Write-Section "Restart MCP Registration"

if (-not (Test-RepoLayout -Path $RepoPath)) {
    Fail "Repo path '$RepoPath' does not look like this project (missing mcp_server/server.py or scripts/cli.py)."
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Fail "uv is required but was not found in PATH."
}

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Fail "claude CLI is required for MCP registration but was not found in PATH."
}

if ($Scope -notin @("user", "project", "local")) {
    Fail "Invalid scope '$Scope'. Use one of: user, project, local."
}

Write-Step "Repo path: $RepoPath"
Write-Step "Server name: $ServerName"
Write-Step "Scope: $Scope"
Write-Step "UV extra: $UvExtra"
if ($DryRun) {
    Write-Host "Dry-run mode enabled (no process stop or registration changes)."
}

if (-not $SkipStopProcess) {
    Stop-McpServerProcesses -TargetRepo $RepoPath
} else {
    Write-Step "Skipping process stop (-SkipStopProcess)."
}

# Re-register MCP server so the client points to this local checkout + runtime.
$cmdParts = @("run")
if ($UvExtra) {
    $cmdParts += @("--extra", $UvExtra)
}
$cmdParts += @("--directory", $RepoPath, "python", "mcp_server/server.py")

if ($DryRun) {
    Write-Host "DRY-RUN: would run:"
    Write-Host "  claude mcp remove $ServerName --scope $Scope"
    Write-Host "  claude mcp add $ServerName --scope $Scope -- uv $($cmdParts -join ' ')"
    exit 0
}

Write-Step "Removing existing MCP registration (if present)..."
try {
    claude mcp remove $ServerName --scope $Scope *> $null
} catch {
    # Non-fatal: remove fails when entry is missing or CLI emits warning.
}

Write-Step "Adding fresh MCP registration..."
claude mcp add $ServerName --scope $Scope -- uv @cmdParts
if ($LASTEXITCODE -ne 0) {
    Fail "Failed to add MCP registration for '$ServerName'."
}

Write-Step "Verifying MCP registration appears in 'claude mcp list'..."
$listOut = claude mcp list 2>&1 | Out-String
$foundExactServer = $false
foreach ($line in ($listOut -split "`r?`n")) {
    $tokens = $line.Trim() -split "\s+"
    if ($tokens -contains $ServerName) {
        $foundExactServer = $true
        break
    }
}
if (-not $foundExactServer) {
    Fail "Registration command succeeded but '$ServerName' was not found in 'claude mcp list'."
}

Write-Host ""
Write-Host "MCP registration refreshed successfully." -ForegroundColor Green
Write-Host "Server: $ServerName (scope: $Scope)"
Write-Host "Command: uv $($cmdParts -join ' ')"
Write-Host ""
Write-Host "Tip: run this to validate setup:"
Write-Host "  uv run --extra $UvExtra --directory `"$RepoPath`" python scripts/cli.py doctor"
