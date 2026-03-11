<#
.SYNOPSIS
    Uninstall AGENT Context Local - removes app checkout, storage data, and MCP registration.

.DESCRIPTION
    This script removes AGENT Context Local artifacts:
      - App checkout directory (default: %LOCALAPPDATA%\agent-context-code)
      - Storage root with indexes, models, and config (default: %USERPROFILE%\.claude_code_search)
      - MCP server registration (code-search)

    Shared prerequisites (uv, Python, git) are intentionally NOT removed.

.PARAMETER ProjectDir
    Path to the app checkout directory.
    Default: $env:LOCALAPPDATA\agent-context-code

.PARAMETER StorageDir
    Path to the storage root (indexes, models, config).
    Default: CODE_SEARCH_STORAGE env var, or $env:USERPROFILE\.claude_code_search

.PARAMETER Force
    Skip interactive confirmation and proceed immediately.

.PARAMETER SkipMcpRemove
    Skip the MCP server deregistration step.

.PARAMETER WhatIf
    Preview what would be removed without actually deleting anything.
#>
param(
    [string]$ProjectDir = "$env:LOCALAPPDATA\agent-context-code",
    [string]$StorageDir = $(if ($env:CODE_SEARCH_STORAGE) { $env:CODE_SEARCH_STORAGE } else { "$env:USERPROFILE\.claude_code_search" }),
    [switch]$Force,
    [switch]$SkipMcpRemove,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

# Helpers

function Write-Section {
    param([string]$Message)
    Write-Host ""
    Write-Host "=================================================="
    Write-Host $Message
    Write-Host "=================================================="
    Write-Host ""
}

function Resolve-SafePath {
    <#
    .SYNOPSIS
        Resolve and validate a path for safe deletion.
        Returns $null if the path is dangerous (too broad or unexpected).
    #>
    param([string]$Path, [string]$Label)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        Write-Host "  [$Label] Path is empty - skipping." -ForegroundColor Yellow
        return $null
    }

    # Expand environment variables and normalize
    $resolved = [System.Environment]::ExpandEnvironmentVariables($Path)
    $resolved = [System.IO.Path]::GetFullPath($resolved)

    # Guard: refuse to delete drive roots, user home, or system directories
    $dangerous = @(
        $env:USERPROFILE,
        $env:LOCALAPPDATA,
        $env:APPDATA,
        $env:SystemRoot,
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)},
        "C:\",
        "D:\",
        $env:HOMEDRIVE + "\"
    ) | Where-Object { $_ } | ForEach-Object { $_.TrimEnd('\') }

    $resolvedTrimmed = $resolved.TrimEnd('\')

    foreach ($d in $dangerous) {
        if ($resolvedTrimmed -eq $d) {
            Write-Host "  [$Label] BLOCKED: '$resolved' matches a protected system path. Refusing to delete." -ForegroundColor Red
            return $null
        }
    }

    return $resolved
}

function Test-ProjectPathSignature {
    param([string]$Path)
    # Accept the standard folder name or a folder that clearly looks like this repo install.
    if ([System.IO.Path]::GetFileName($Path).ToLowerInvariant() -eq "agent-context-code") {
        return $true
    }

    $serverPath = Join-Path $Path "mcp_server\server.py"
    $cliPath = Join-Path $Path "scripts\cli.py"
    return (Test-Path $serverPath) -and (Test-Path $cliPath)
}

function Test-StoragePathSignature {
    param([string]$Path)
    # Accept the canonical storage root name or marker files/dirs used by this product.
    if ([System.IO.Path]::GetFileName($Path).ToLowerInvariant() -eq ".claude_code_search") {
        return $true
    }

    # Require at least two storage markers for non-canonical directory names.
    # This avoids deleting unrelated folders that might only have "models" or "projects".
    $markerCount = 0
    if (Test-Path (Join-Path $Path "install_config.json")) { $markerCount += 1 }
    if (Test-Path (Join-Path $Path "models")) { $markerCount += 1 }
    if (Test-Path (Join-Path $Path "projects")) { $markerCount += 1 }
    return $markerCount -ge 2
}

# Status tracking

$results = [ordered]@{
    "MCP registration" = "skipped"
    "Project directory" = "skipped"
    "Storage directory" = "skipped"
}

# Resolve and validate paths

$safeProjectDir = Resolve-SafePath -Path $ProjectDir -Label "Project"
$safeStorageDir = Resolve-SafePath -Path $StorageDir -Label "Storage"

$projectExists = $safeProjectDir -and (Test-Path $safeProjectDir)
$storageExists = $safeStorageDir -and (Test-Path $safeStorageDir)
$projectTrusted = $projectExists -and (Test-ProjectPathSignature -Path $safeProjectDir)
$storageTrusted = $storageExists -and (Test-StoragePathSignature -Path $safeStorageDir)

# Preview

Write-Section "AGENT Context Local - Uninstall"

if ($WhatIf) {
    Write-Host "  [DRY-RUN MODE] No files will be deleted." -ForegroundColor Cyan
    Write-Host ""
}

Write-Host "Planned actions:" -ForegroundColor White

if (-not $SkipMcpRemove) {
    Write-Host "  MCP registration : remove 'code-search' server"
} else {
    Write-Host "  MCP registration : skip (-SkipMcpRemove)"
}

if ($projectExists -and $projectTrusted) {
    Write-Host "  Project directory: DELETE $safeProjectDir"
} elseif ($projectExists) {
    Write-Host "  Project directory: BLOCKED (path does not look like AGENT Context Local install)"
} elseif ($safeProjectDir) {
    Write-Host "  Project directory: not found ($safeProjectDir) - nothing to do"
} else {
    Write-Host "  Project directory: path invalid - skipping"
}

if ($storageExists -and $storageTrusted) {
    Write-Host "  Storage directory: DELETE $safeStorageDir"
} elseif ($storageExists) {
    Write-Host "  Storage directory: BLOCKED (path does not look like AGENT Context Local storage)"
} elseif ($safeStorageDir) {
    Write-Host "  Storage directory: not found ($safeStorageDir) - nothing to do"
} else {
    Write-Host "  Storage directory: path invalid - skipping"
}

Write-Host ""
Write-Host "NOT removed (shared tools): uv, Python, git" -ForegroundColor DarkGray

# Nothing to do?
if (-not $projectExists -and -not $storageExists -and $SkipMcpRemove) {
    Write-Host ""
    Write-Host "Nothing to remove. AGENT Context Local does not appear to be installed." -ForegroundColor Yellow
    exit 0
}

# Dry-run exit

if ($WhatIf) {
    Write-Host ""
    Write-Host "Dry-run complete. Re-run without -WhatIf to perform the uninstall." -ForegroundColor Cyan
    exit 0
}

# Confirmation gate

if (-not $Force) {
    Write-Host ""
    $answer = Read-Host "Proceed with uninstall? This will permanently delete the above directories [y/N]"
    if ($answer -notin @("y", "Y", "yes", "Yes", "YES")) {
        Write-Host "Aborted. No changes were made." -ForegroundColor Yellow
        exit 0
    }
}

# Step 1: MCP deregistration

if (-not $SkipMcpRemove) {
    Write-Host ""
    Write-Host "Removing MCP server registration..."
    if (Get-Command claude -ErrorAction SilentlyContinue) {
        try {
            claude mcp remove code-search --scope user 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                $results["MCP registration"] = "removed"
                Write-Host "  MCP 'code-search' registration removed." -ForegroundColor Green
            } else {
                $results["MCP registration"] = "failed"
                Write-Host "  WARNING: 'claude mcp remove code-search --scope user' failed." -ForegroundColor Yellow
                Write-Host "  Manual step: claude mcp remove code-search --scope user" -ForegroundColor Yellow
            }
        } catch {
            $results["MCP registration"] = "failed"
            Write-Host "  WARNING: 'claude mcp remove code-search --scope user' failed." -ForegroundColor Yellow
            Write-Host "  Manual step: claude mcp remove code-search --scope user" -ForegroundColor Yellow
        }
    } else {
        $results["MCP registration"] = "skipped (claude CLI not found)"
        Write-Host "  'claude' CLI not found - skipping MCP removal." -ForegroundColor Yellow
        Write-Host "  If you install Claude Code later, run: claude mcp remove code-search --scope user" -ForegroundColor Yellow
    }
}

# Step 2: Delete project directory

if ($projectExists -and $projectTrusted) {
    Write-Host ""
    Write-Host "Removing project directory: $safeProjectDir"
    try {
        Remove-Item -Recurse -Force -Path $safeProjectDir
        $results["Project directory"] = "removed"
        Write-Host "  Removed." -ForegroundColor Green
    } catch {
        $results["Project directory"] = "failed"
        Write-Host "  FAILED to remove project directory: $_" -ForegroundColor Red
    }
} elseif ($projectExists) {
    $results["Project directory"] = "blocked"
} elseif ($safeProjectDir) {
    $results["Project directory"] = "not found"
}

# Step 3: Delete storage directory

if ($storageExists -and $storageTrusted) {
    Write-Host ""
    Write-Host "Removing storage directory: $safeStorageDir"
    try {
        Remove-Item -Recurse -Force -Path $safeStorageDir
        $results["Storage directory"] = "removed"
        Write-Host "  Removed." -ForegroundColor Green
    } catch {
        $results["Storage directory"] = "failed"
        Write-Host "  FAILED to remove storage directory: $_" -ForegroundColor Red
    }
} elseif ($storageExists) {
    $results["Storage directory"] = "blocked"
} elseif ($safeStorageDir) {
    $results["Storage directory"] = "not found"
}

# Summary

Write-Section "Uninstall Summary"

foreach ($key in $results.Keys) {
    $status = $results[$key]
    $color = switch -Wildcard ($status) {
        "removed"    { "Green" }
        "not found"  { "DarkGray" }
        "blocked"    { "Yellow" }
        "skipped*"   { "Yellow" }
        "failed*"    { "Red" }
        default      { "White" }
    }
    Write-Host "  ${key}: $status" -ForegroundColor $color
}

$anyFailed = $results.Values | Where-Object { $_ -like "failed*" }
$anyBlocked = $results.Values | Where-Object { $_ -eq "blocked" }
Write-Host ""
if ($anyFailed) {
    Write-Host "Uninstall completed with errors. See details above." -ForegroundColor Yellow
    exit 1
} elseif ($anyBlocked) {
    Write-Host "Uninstall stopped by safety checks for one or more paths." -ForegroundColor Yellow
    Write-Host "Review path overrides, then retry with a valid AGENT Context Local path." -ForegroundColor Yellow
    exit 1
} else {
    Write-Host "AGENT Context Local has been removed." -ForegroundColor Green
    Write-Host "Shared tools (uv, Python, git) were left in place." -ForegroundColor DarkGray
}
