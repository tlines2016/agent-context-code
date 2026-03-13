param(
    [string]$RepoUrl = "https://github.com/tlines2016/agent-context-code",
    [string]$ProjectDir = "$env:LOCALAPPDATA\agent-context-code",
    [string]$StorageDir = $(if ($env:CODE_SEARCH_STORAGE) { $env:CODE_SEARCH_STORAGE } else { "$env:USERPROFILE\.agent_code_search" }),
    [string]$ModelName = $(if ($env:CODE_SEARCH_MODEL) { $env:CODE_SEARCH_MODEL } else { "mixedbread-ai/mxbai-embed-xsmall-v1" })
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
        $isInteractive = [Environment]::UserInteractive -and -not ([Console]::IsInputRedirected)
        if ($isInteractive) {
            $choice = Read-Host "Options: [U]pdate anyway (stash changes), [K]eep current version, [D]elete and reinstall"
        } else {
            Write-Host "Non-interactive mode: auto-selecting stash-and-update"
            $choice = "U"
        }
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
            # --ff-only prevents silent overwrites of local work.
            # Edge case: if someone manually committed inside the install dir and
            # the branch has diverged, this will throw and abort the script.
            # Fix: re-run the installer and choose [D]elete and reinstall at the prompt.
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
        # Safety: verify the directory looks like a previous install before deleting
        $serverPath = Join-Path $ProjectDir "mcp_server\server.py"
        $cliPath = Join-Path $ProjectDir "scripts\cli.py"
        $looksLikeInstall = (Test-Path $serverPath) -and (Test-Path $cliPath)
        $dirName = [System.IO.Path]::GetFileName($ProjectDir).ToLowerInvariant()
        if (-not $looksLikeInstall -and $dirName -ne "agent-context-code") {
            throw "ERROR: '$ProjectDir' exists but does not look like an AGENT Context Local install. Remove it manually or choose a different -ProjectDir."
        }
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

# ── GPU-accelerated PyTorch installation ──────────────────────────────────
# Detect GPU vendor and install the matching PyTorch build so embeddings
# run on the accelerator instead of CPU.
#
# How GPU persistence works:
# pyproject.toml defines GPU extras (cu126, cu128) with [tool.uv.sources]
# and [tool.uv.conflicts] that route torch to GPU-specific PyTorch indexes.
# `uv sync --extra cu128` installs GPU torch.  The MCP server command
# includes `--extra <name>` so `uv run` syncs GPU torch automatically.
#
# Supported:  NVIDIA (CUDA), AMD (ROCm on Windows via HIP), CPU fallback
# Apple Silicon is macOS-only and handled by install.sh.
$gpuVendor = "cpu"
$torchIndexUrl = ""
$gpuStatus = "cpu-only"
$skipGpu = $env:SKIP_GPU -eq "1"

if ($skipGpu) {
    Write-Host "Skipping GPU detection (SKIP_GPU=1)."
}
elseif (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $gpuVendor = "nvidia"
    # Parse CUDA version from nvidia-smi header
    $nvsmiOutput = nvidia-smi 2>&1 | Out-String
    $cudaMatch = [regex]::Match($nvsmiOutput, 'CUDA Version:\s*(\d+)\.(\d+)')
    $gpuNameLine = nvidia-smi --query-gpu=name --format=csv,noheader 2>&1 | Select-Object -First 1
    $gpuName = if ($gpuNameLine) { $gpuNameLine.ToString().Trim() } else { "unknown" }

    if ($cudaMatch.Success) {
        $cudaMajor = [int]$cudaMatch.Groups[1].Value
        $cudaMinor = [int]$cudaMatch.Groups[2].Value
        Write-Host "NVIDIA GPU detected: $gpuName (driver CUDA $cudaMajor.$cudaMinor)"

        # Map driver CUDA version to the best available PyTorch index
        if ($cudaMajor -ge 13 -or ($cudaMajor -eq 12 -and $cudaMinor -ge 8)) {
            $torchIndexUrl = "https://download.pytorch.org/whl/cu128"
            $gpuStatus = "nvidia-cu128"
        }
        elseif ($cudaMajor -eq 12 -and $cudaMinor -ge 6) {
            $torchIndexUrl = "https://download.pytorch.org/whl/cu126"
            $gpuStatus = "nvidia-cu126"
        }
        elseif ($cudaMajor -eq 12 -and $cudaMinor -ge 4) {
            $torchIndexUrl = "https://download.pytorch.org/whl/cu124"
            $gpuStatus = "nvidia-cu124"
        }
        elseif ($cudaMajor -eq 12) {
            $torchIndexUrl = "https://download.pytorch.org/whl/cu121"
            $gpuStatus = "nvidia-cu121"
        }
        elseif ($cudaMajor -eq 11 -and $cudaMinor -ge 8) {
            $torchIndexUrl = "https://download.pytorch.org/whl/cu118"
            $gpuStatus = "nvidia-cu118"
        }
        else {
            Write-Host "CUDA $cudaMajor.$cudaMinor is older than 11.8 - falling back to CPU PyTorch."
            Write-Host "Consider updating your NVIDIA drivers for GPU acceleration."
        }
    }
    else {
        Write-Host "NVIDIA GPU detected ($gpuName) but could not parse CUDA version."
        Write-Host "Falling back to CPU PyTorch. Update drivers for GPU acceleration."
    }
}
elseif (Get-Command rocm-smi -ErrorAction SilentlyContinue) {
    $gpuVendor = "amd"
    $gpuName = "unknown"
    try {
        $rocmOutput = rocm-smi --showproductname 2>&1 | Out-String
        $nameMatch = [regex]::Match($rocmOutput, 'GPU\[\d+\]\s*:\s*(.*)')
        if ($nameMatch.Success) { $gpuName = $nameMatch.Groups[1].Value.Trim() }
    } catch {}

    Write-Host "AMD GPU detected: $gpuName"
    # ROCm PyTorch wheels are Linux-only; skip GPU torch install on Windows.
    Write-Warning "ROCm PyTorch is Linux-only. Falling back to CPU PyTorch on Windows."
    Write-Host "  For AMD GPU acceleration on Windows, install HIP SDK and re-run on Linux, or wait for a future DirectML release."
    $torchIndexUrl = ""
    $gpuVendor = "cpu"
    $gpuStatus = "amd-rocm-windows-unsupported"
}
else {
    # Check for AMD GPU via WMI even without ROCm tools
    try {
        $gpuInfo = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match "AMD|Radeon" } |
            Select-Object -First 1
        if ($gpuInfo) {
            Write-Host "AMD GPU detected: $($gpuInfo.Name)"
            Write-Host "  ROCm/HIP SDK not found. Install AMD HIP SDK for GPU acceleration:"
            Write-Host "  https://rocm.docs.amd.com/projects/install-on-windows/"
            Write-Host "  After installing HIP SDK, re-run this installer for GPU support."
            $gpuStatus = "amd-no-rocm"
        }
        else {
            Write-Host "No GPU detected. Embedding generation will use CPU (still works fine)."
        }
    } catch {
        Write-Host "No GPU detected. Embedding generation will use CPU (still works fine)."
    }
}

# Map torchIndexUrl to pyproject.toml extra name.
# Only cu126, cu128, and rocm7.1 have torch>=2.10.0 wheels.
# Older CUDA and ROCm <7.1 fall back to uv pip install.
$gpuExtra = ""
if ($torchIndexUrl -match '/cu126$')   { $gpuExtra = "cu126" }
elseif ($torchIndexUrl -match '/cu128$')   { $gpuExtra = "cu128" }
elseif ($torchIndexUrl -match '/rocm7\.1$') { $gpuExtra = "rocm"  }

# Install GPU-accelerated PyTorch via pyproject.toml extras.
if ($gpuExtra) {
    Write-Host "Installing GPU-accelerated PyTorch ($gpuStatus, extra: $gpuExtra)..."
    Push-Location $ProjectDir
    $syncOk = $false
    try {
        uv sync --extra $gpuExtra 2>&1 | Out-Host
        $syncOk = $LASTEXITCODE -eq 0
    } catch {
        $syncOk = $false
    }
    if ($syncOk) {
        Write-Host "GPU-accelerated PyTorch installed successfully."
    }
    else {
        Write-Warning "uv sync --extra $gpuExtra failed - trying uv pip install fallback..."
        try {
            uv pip install torch --index-url $torchIndexUrl --reinstall --quiet 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "GPU PyTorch installed via fallback (uv pip install)."
                # Clear gpuExtra since pip-installed torch is outside uv's extras system
                $gpuExtra = ""
            }
            else {
                Write-Warning "GPU PyTorch installation failed - falling back to CPU."
                Write-Host "  You can retry later: uv run --directory `"$ProjectDir`" python scripts/cli.py gpu-setup"
                $gpuStatus = "cpu-fallback"
                $gpuExtra = ""
            }
        } catch {
            Write-Warning "GPU PyTorch installation failed - falling back to CPU."
            Write-Host "  You can retry later: uv run --directory `"$ProjectDir`" python scripts/cli.py gpu-setup"
            $gpuStatus = "cpu-fallback"
            $gpuExtra = ""
        }
    }
    Pop-Location
}
elseif ($torchIndexUrl -and $gpuVendor -ne "cpu" -and $gpuVendor -ne "mps") {
    # Older CUDA/ROCm without a pyproject.toml extra - use uv pip install directly
    Write-Host "Installing GPU-accelerated PyTorch via pip ($gpuStatus)..."
    Push-Location $ProjectDir
    try {
        uv pip install torch --index-url $torchIndexUrl --reinstall --quiet 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "GPU PyTorch installed via uv pip install."
            Write-Host "Note: older CUDA versions require --no-sync in uv run to prevent torch downgrade."
        }
        else {
            Write-Warning "GPU PyTorch installation failed - falling back to CPU."
            Write-Host "  You can retry later: uv run --directory `"$ProjectDir`" python scripts/cli.py gpu-setup"
            $gpuStatus = "cpu-fallback"
        }
    } catch {
        Write-Warning "GPU PyTorch installation failed - falling back to CPU."
        $gpuStatus = "cpu-fallback"
    }
    Pop-Location
}

# ── Auto-save GPU-appropriate model defaults ────────────────────────────
# When a GPU was detected and no explicit model choice exists in
# install_config.json, pre-configure the GPU-optimised embedding model
# and reranker so the MCP server uses them on first run.
$gpuRerankerAuto = ""
if ($gpuVendor -ne "cpu" -and $gpuStatus -ne "cpu-fallback") {
    $configFile = Join-Path $StorageDir "install_config.json"
    $hasEmbedding = $false
    if (Test-Path $configFile) {
        try {
            $existingConfig = Get-Content $configFile -Raw | ConvertFrom-Json
            if ($existingConfig.embedding_model) { $hasEmbedding = $true }
        } catch {}
    }

    if (-not $hasEmbedding) {
        $gpuEmbedModel = "Qwen/Qwen3-Embedding-0.6B"
        $gpuRerankerModel = "Qwen/Qwen3-Reranker-0.6B"
        Write-Host "GPU detected - saving GPU-optimised model defaults to install_config.json"
        Write-Host "  Embedding: $gpuEmbedModel"
        Write-Host "  Reranker:  $gpuRerankerModel (pre-configured, opt-in - run 'agent-context-local config reranker on' to enable)"
        # Write config using uv run python (stdlib only) to avoid
        # ConvertFrom-Json -AsHashtable which requires PowerShell 7+.
        New-Item -ItemType Directory -Force -Path $StorageDir | Out-Null
        uv run --directory $ProjectDir python -c @"
import json, sys, os
config_path = sys.argv[1]
config = {}
if os.path.exists(config_path):
    try:
        config = json.load(open(config_path))
    except Exception:
        pass
config['embedding_model'] = {'model_name': sys.argv[2], 'auto_configured': True}
config['reranker'] = {'model_name': sys.argv[3], 'enabled': False, 'recall_k': 50, 'auto_configured': True}
config['gpu'] = {'vendor': sys.argv[4], 'torch_index_url': sys.argv[5], 'status': sys.argv[6], 'extra': sys.argv[7]}
with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
"@ $configFile $gpuEmbedModel $gpuRerankerModel $gpuVendor $(if ($torchIndexUrl) { $torchIndexUrl } else { "" }) $gpuStatus $(if ($gpuExtra) { $gpuExtra } else { "" }) 2>&1 | Out-Null
        # Update ModelName so the download step fetches the GPU model
        $ModelName = $gpuEmbedModel
        $gpuRerankerAuto = $gpuRerankerModel
    }
}

# ── GPU reranker pre-download ─────────────────────────────────────────
# Pre-download the GPU reranker model so it is ready when the user enables it.
if ($gpuRerankerAuto) {
    Write-Host "Downloading GPU reranker model: $gpuRerankerAuto"
    Push-Location $ProjectDir
    try {
        uv run scripts/download_reranker_standalone.py --storage-dir $StorageDir --model $gpuRerankerAuto -v
        if ($LASTEXITCODE -eq 0) {
            $rerankerStatus = "ok"
        } else {
            $rerankerStatus = "failed"
            Write-Warning "GPU reranker download did not complete."
            Write-Host "The reranker is optional - search still works with embedding-only mode."
        }
    } finally {
        Pop-Location
    }
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
if (-not $rerankerStatus) { $rerankerStatus = "skipped" }
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
Write-Host "  GPU acceleration: $gpuStatus"
Write-Host "  Model downloaded: $modelStatus"
Write-Host "  Reranker downloaded: $rerankerStatus"
Write-Host "  Ready for indexing: $readyStatus"
Write-Host ""

if ($stashedChanges) {
    Write-Host "Local changes were stashed before update."
    Write-Host "Inspect stashes: git -C `"$ProjectDir`" stash list"
    Write-Host ""
}

$uvExtraFlag = ""
if ($gpuExtra) {
    $uvExtraFlag = "--extra $gpuExtra "
}

$mcpCmd = "uv run ${uvExtraFlag}--directory `"$ProjectDir`" python mcp_server/server.py"

Write-Host "MCP server command:"
Write-Host "  $mcpCmd"
Write-Host "  If installed via PyPI: agent-context-local-mcp"
Write-Host ""

# Auto-register MCP server with Claude Code
if (Get-Command claude -ErrorAction SilentlyContinue) {
    Write-Host "Auto-registering MCP server with Claude Code..."
    claude mcp remove code-search --scope user 2>$null
    $mcpArgs = @("run")
    if ($gpuExtra) { $mcpArgs += "--extra", $gpuExtra }
    $mcpArgs += "--directory", $ProjectDir, "python", "mcp_server/server.py"
    $regResult = claude mcp add code-search --scope user -- uv @mcpArgs 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  MCP server registered. Verify with: claude mcp list"
    } else {
        Write-Host "  Auto-registration failed. Register manually:"
        Write-Host "    claude mcp add code-search --scope user -- $mcpCmd"
    }
    Write-Host ""
} else {
    Write-Host "Next steps (Claude Code):"
    if ($isUpdate) {
        Write-Host "1) Remove old server: claude mcp remove code-search"
        Write-Host "2) Add updated server: claude mcp add code-search --scope user -- $mcpCmd"
        Write-Host "3) Verify connection: claude mcp list"
        Write-Host "4) In Claude Code: index this codebase"
    }
    else {
        Write-Host "1) Add MCP server: claude mcp add code-search --scope user -- $mcpCmd"
        Write-Host "2) Verify connection: claude mcp list"
        Write-Host "3) In Claude Code: index this codebase"
    }
    Write-Host ""
}
Write-Host "For other MCP clients (Cursor, Copilot, Gemini CLI, Codex, etc.):"
Write-Host "  uv run ${uvExtraFlag}--directory `"$ProjectDir`" python scripts/cli.py setup-mcp"
Write-Host ""
Write-Host "Diagnostics: uv run ${uvExtraFlag}--directory `"$ProjectDir`" python scripts/cli.py doctor"
Write-Host "Setup guide: uv run ${uvExtraFlag}--directory `"$ProjectDir`" python scripts/cli.py setup-guide"
Write-Host "Uninstall:   irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/uninstall.ps1 | iex"
