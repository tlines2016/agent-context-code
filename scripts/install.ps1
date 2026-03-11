param(
    [string]$RepoUrl = "https://github.com/tlines2016/agent-context-code",
    [string]$ProjectDir = "$env:LOCALAPPDATA\agent-context-code",
    [string]$StorageDir = $(if ($env:CODE_SEARCH_STORAGE) { $env:CODE_SEARCH_STORAGE } else { "$env:USERPROFILE\.claude_code_search" }),
    [string]$ModelName = $(if ($env:CODE_SEARCH_MODEL) { $env:CODE_SEARCH_MODEL } else { "Qwen/Qwen3-Embedding-0.6B" })
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

# Why these explicit statuses exist:
# install/update may succeed while model download fails (usually auth mismatch),
# so users need a clear "ready for indexing" summary instead of a single success line.
$repoStatus = "pending"
$depsStatus = "pending"
$modelStatus = "pending"
$readyStatus = "pending"
$stashedChanges = $false

Write-Section "Installing AGENT Context Local"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is required. Please install git and re-run."
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv not found. Installing uv..."
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $uvBinary = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (Test-Path $uvBinary) {
        $env:PATH = "$($env:USERPROFILE)\.local\bin;$env:PATH"
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv installation failed or was not added to PATH."
    }
}

$skipUpdate = $false
$isUpdate = $false

# Repository setup: three cases
# 1) Fresh install  : ProjectDir does not exist or has no .git   -> git clone
# 2) Update (clean) : .git exists, no local changes              -> git pull
# 3) Update (dirty) : .git exists, uncommitted changes           -> interactive
#    (stash+pull / keep / delete+reclone; default=stash in non-interactive sessions)
if (Test-Path (Join-Path $ProjectDir ".git")) {
    $isUpdate = $true
    Write-Host "Found existing installation at $ProjectDir"
    Push-Location $ProjectDir
    try {
        git diff-index --quiet HEAD --
        $hasChanges = $LASTEXITCODE -ne 0
    } finally {
        Pop-Location
    }

    if ($hasChanges) {
        Write-Warning "You have uncommitted changes in $ProjectDir"
        $choice = Read-Host "Options: [U]pdate anyway (stash changes), [K]eep current version, [D]elete and reinstall"
        if ([string]::IsNullOrWhiteSpace($choice)) {
            $choice = "U"
        }
        switch ($choice.ToUpperInvariant()) {
            "K" {
                $skipUpdate = $true
                $repoStatus = "kept-current"
            }
            "D" {
                Remove-Item -Recurse -Force $ProjectDir
                git clone $RepoUrl $ProjectDir
                $isUpdate = $false
                $repoStatus = "ok"
            }
            default {
                Push-Location $ProjectDir
                try {
                    git stash push -m "Auto-stash before installer update $(Get-Date -Format s)"
                    git remote set-url origin $RepoUrl
                    git fetch --tags --prune
                    git pull --ff-only
                    $stashedChanges = $true
                    $repoStatus = "ok"
                } finally {
                    Pop-Location
                }
            }
        }
    }
    elseif (-not $skipUpdate) {
        Push-Location $ProjectDir
        try {
            git remote set-url origin $RepoUrl
            git fetch --tags --prune
            git pull --ff-only
            $repoStatus = "ok"
        } finally {
            Pop-Location
        }
    }
}
else {
    $projectParent = Split-Path -Parent $ProjectDir
    if ($projectParent) {
        New-Item -ItemType Directory -Force -Path $projectParent | Out-Null
    }
    if (Test-Path $ProjectDir) {
        Remove-Item -Recurse -Force $ProjectDir
    }
    git clone $RepoUrl $ProjectDir
    $repoStatus = "ok"
}

if (-not $skipUpdate) {
    Write-Host "Installing Python dependencies with uv sync"
    Push-Location $ProjectDir
    try {
        uv sync
        $depsStatus = "ok"
    } finally {
        Pop-Location
    }
}
else {
    $depsStatus = "skipped"
}

# We keep GPU detection as guidance only.
# Why: search backend is LanceDB, so installer should not perform FAISS package mutations.
$skipGpu = $env:SKIP_GPU -eq "1"
if (-not $skipGpu) {
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        Write-Host "NVIDIA GPU detected. Embedding generation may be faster with CUDA-enabled PyTorch."
    }
    else {
        Write-Host "No NVIDIA GPU detected. Install still works on CPU."
    }
}
else {
    Write-Host "Skipping GPU detection (SKIP_GPU=1)."
}

Write-Host "Downloading embedding model to $StorageDir"
New-Item -ItemType Directory -Force -Path $StorageDir | Out-Null

# Disk space check — warn if less than 2 GB free (don't block)
try {
    $drive = (Get-Item $StorageDir -ErrorAction SilentlyContinue).PSDrive
    if (-not $drive) { $drive = (Get-Item (Split-Path $StorageDir -Qualifier)).PSDrive }
    if ($drive -and $drive.Free -lt 2GB) {
        $freeMB = [math]::Round($drive.Free / 1MB)
        Write-Warning "Low disk space: ${freeMB} MB free on $($drive.Name): (recommend at least 2 GB)"
    }
} catch {
    # Non-critical — skip if drive info unavailable
}
$downloadSucceeded = $true
Push-Location $ProjectDir
try {
    uv run scripts/download_model_standalone.py --storage-dir $StorageDir --model $ModelName -v
    if ($LASTEXITCODE -ne 0) {
        $downloadSucceeded = $false
    }
} finally {
    Pop-Location
}

if ($downloadSucceeded) {
    $modelStatus = "ok"
}
else {
    $modelStatus = "failed"
    Write-Host ""
    Write-Host "========================================================" -ForegroundColor Red
    Write-Host "  MODEL DOWNLOAD FAILED" -ForegroundColor Red
    Write-Host "  Indexing/search is blocked until this is fixed." -ForegroundColor Red
    Write-Host "========================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Recovery:"
    Write-Host "  1) Check disk space (need ~1-2 GB)"
    Write-Host "  2) If using a gated model, authenticate: hf auth login"
    Write-Host "  3) Retry:"
    Write-Host "     uv run --directory `"$ProjectDir`" python scripts/download_model_standalone.py --storage-dir `"$StorageDir`" --model `"$ModelName`" -v"
}

# ── Optional reranker download ────────────────────────────────────────
# Controlled by CODE_SEARCH_PROFILE (default: base).
# Profiles: base = embedding only, reranker = +reranker, full = everything
$Profile = if ($env:CODE_SEARCH_PROFILE) { $env:CODE_SEARCH_PROFILE } else { "base" }
$rerankerStatus = "skipped"
if ($Profile -in @("reranker", "full")) {
    $RerankerName = if ($env:CODE_SEARCH_RERANKER) { $env:CODE_SEARCH_RERANKER } else { "cross-encoder/ms-marco-MiniLM-L-6-v2" }
    Write-Host "Downloading reranker model: $RerankerName"
    $rerankerSuccess = $true
    Push-Location $ProjectDir
    try {
        uv run scripts/download_reranker_standalone.py --storage-dir $StorageDir --model $RerankerName -v
        if ($LASTEXITCODE -ne 0) {
            $rerankerSuccess = $false
        }
    } finally {
        Pop-Location
    }
    if ($rerankerSuccess) {
        $rerankerStatus = "ok"
    } else {
        $rerankerStatus = "failed"
        Write-Warning "Reranker download did not complete."
        Write-Host "The reranker is optional - search still works with embedding-only mode."
        Write-Host "Retry: uv run --directory `"$ProjectDir`" python scripts/download_reranker_standalone.py --storage-dir `"$StorageDir`" --model `"$RerankerName`" -v"
    }
}

if (($repoStatus -in @("ok", "kept-current")) -and ($depsStatus -in @("ok", "skipped")) -and ($modelStatus -eq "ok")) {
    $readyStatus = "yes"
}
else {
    $readyStatus = "not-yet"
}

Write-Section ($(if ($isUpdate) { "Update flow complete" } else { "Install flow complete" }))
Write-Host "Project: $ProjectDir"
Write-Host "Storage: $StorageDir"
Write-Host "Selected embedding model: $ModelName"
Write-Host "Local install model config: $(Join-Path $StorageDir 'install_config.json')"
Write-Host ""
Write-Host "Final status summary:"
Write-Host "  Repo installed/updated: $repoStatus"
Write-Host "  Dependencies installed: $depsStatus"
Write-Host "  Model downloaded: $modelStatus"
Write-Host "  Reranker downloaded: $rerankerStatus"
Write-Host "  Ready for indexing: $readyStatus"
Write-Host ""

if ($stashedChanges) {
    Write-Host "Local changes were stashed before update."
    Write-Host "Inspect stashes: git -C `"$ProjectDir`" stash list"
    Write-Host ""
}

Write-Host "Next steps:"
if ($isUpdate) {
    Write-Host "1) Remove old server: claude mcp remove code-search"
    Write-Host "2) Add updated server: claude mcp add code-search --scope user -- uv run --directory `"$ProjectDir`" python mcp_server/server.py"
    Write-Host "3) Verify connection: claude mcp list"
    Write-Host "4) In Claude Code: index this codebase"
    Write-Host "5) To switch models later, set CODE_SEARCH_MODEL and re-run this installer"
}
else {
    Write-Host "1) Add MCP server: claude mcp add code-search --scope user -- uv run --directory `"$ProjectDir`" python mcp_server/server.py"
    Write-Host "2) Verify connection: claude mcp list"
    Write-Host "3) In Claude Code: index this codebase"
    Write-Host "4) To switch models later, set CODE_SEARCH_MODEL and re-run this installer"
}
Write-Host ""
Write-Host "Diagnostics: uv run --directory `"$ProjectDir`" python scripts/cli.py doctor"
Write-Host "Setup guide: uv run --directory `"$ProjectDir`" python scripts/cli.py setup-guide"
Write-Host "Uninstall:   irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/uninstall.ps1 | iex"
