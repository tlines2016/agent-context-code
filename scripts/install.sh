#!/usr/bin/env bash
set -euo pipefail

# Remote installer for AGENT Context Local
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.sh | bash

REPO_URL="https://github.com/tlines2016/agent-context-code"
PROJECT_DIR="${HOME}/.local/share/agent-context-code"
STORAGE_DIR="${CODE_SEARCH_STORAGE:-${HOME}/.agent_code_search}"
MODEL_NAME="${CODE_SEARCH_MODEL:-mixedbread-ai/mxbai-embed-xsmall-v1}"

# msg: wrapper around printf for consistent single-line output.
# Named 'msg' instead of 'print' to avoid shadowing the bash builtin.
msg() { printf "%b\n" "$1"; }
hr() { msg "\n==================================================\n"; }

# Why we track explicit status flags:
# installs can succeed while model download fails (auth/network),
# and the summary must make readiness explicit for users.
REPO_STATUS="pending"
DEPS_STATUS="pending"
MODEL_STATUS="pending"
READY_STATUS="pending"
SKIP_UPDATE=0
STASHED_CHANGES=0

IS_WSL=0
if [[ -f /proc/version ]] && grep -Eiq "microsoft|wsl" /proc/version 2>/dev/null; then
  IS_WSL=1
fi

# ANSI color codes — defined early so all printf calls below can use them.
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

hr
msg "Installing AGENT Context Local"
hr

if ! command -v git >/dev/null 2>&1; then
  msg "ERROR: git is required. Please install git and re-run."
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  msg "uv not found. Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  if ! command -v uv >/dev/null 2>&1; then
    for candidate in "$HOME/.local/bin" "$HOME/.cargo/bin" "/usr/local/bin"; do
      if [[ -x "$candidate/uv" ]]; then
        export PATH="$candidate:$PATH"
        msg "Found uv at $candidate"
        break
      fi
    done
    if ! command -v uv >/dev/null 2>&1; then
      msg "ERROR: uv was installed but is not in your PATH."
      msg "Try adding ~/.local/bin or ~/.cargo/bin to your PATH, then re-run."
      exit 1
    fi
  fi
fi

# ── Repository setup: three cases ──────────────────────────────────────────
# 1) Fresh install  : PROJECT_DIR does not exist → git clone
# 2) Update (clean) : .git exists, no local changes → git pull
# 3) Update (dirty) : .git exists, uncommitted changes → interactive
#    (stash+pull / keep / delete+reclone; default=stash when non-interactive)

# Guard: if PROJECT_DIR exists but is not a git repo, check before proceeding
if [[ -d "${PROJECT_DIR}" && ! -d "${PROJECT_DIR}/.git" ]]; then
  if [[ -n "$(ls -A "${PROJECT_DIR}" 2>/dev/null)" ]]; then
    # Non-empty, non-git directory — check for project signature
    if [[ -f "${PROJECT_DIR}/mcp_server/server.py" && -f "${PROJECT_DIR}/scripts/cli.py" ]]; then
      msg "WARNING: ${PROJECT_DIR} looks like a previous install without .git"
      msg "Removing and re-cloning..."
      rm -rf "${PROJECT_DIR}"
    else
      msg "ERROR: ${PROJECT_DIR} exists and contains unrelated files."
      msg "Please move or delete it, or set a different PROJECT_DIR."
      exit 1
    fi
  fi
fi

mkdir -p "${PROJECT_DIR}"
IS_UPDATE=0
if [[ -d "${PROJECT_DIR}/.git" ]]; then
  msg "Found existing installation at ${PROJECT_DIR}"
  IS_UPDATE=1

  if ! git -C "${PROJECT_DIR}" diff-index --quiet HEAD -- 2>/dev/null; then
    msg "WARNING: You have uncommitted changes in ${PROJECT_DIR}"
    if [ -t 0 ]; then
      printf "Options:\n  [u] Update anyway (stash changes)\n  [k] Keep current version\n  [d] Delete and reinstall\nChoice [u/k/d]: "
      read -r choice
    else
      msg "Auto-selecting: Update anyway (stash changes)"
      choice="u"
    fi
    case "${choice}" in
      k|K)
        msg "Keeping current installation. Skipping git/dependency update."
        SKIP_UPDATE=1
        REPO_STATUS="kept-current"
        ;;
      d|D)
        msg "Removing ${PROJECT_DIR} for clean reinstall..."
        rm -rf "${PROJECT_DIR}"
        git clone "${REPO_URL}" "${PROJECT_DIR}"
        IS_UPDATE=0
        REPO_STATUS="ok"
        ;;
      u|U|*)
        msg "Stashing changes and updating..."
        git -C "${PROJECT_DIR}" stash push -m "Auto-stash before installer update $(date)"
        STASHED_CHANGES=1
        git -C "${PROJECT_DIR}" remote set-url origin "${REPO_URL}"
        git -C "${PROJECT_DIR}" fetch --tags --prune
        git -C "${PROJECT_DIR}" pull --ff-only
        REPO_STATUS="ok"
        msg "Your changes are stashed. Run 'git stash list' in ${PROJECT_DIR} to inspect them."
        ;;
    esac
  else
    msg "Updating repository..."
    git -C "${PROJECT_DIR}" remote set-url origin "${REPO_URL}"
    git -C "${PROJECT_DIR}" fetch --tags --prune
    git -C "${PROJECT_DIR}" pull --ff-only
    REPO_STATUS="ok"
  fi
else
  msg "Cloning ${REPO_URL} to ${PROJECT_DIR}"
  git clone "${REPO_URL}" "${PROJECT_DIR}"
  REPO_STATUS="ok"
  IS_UPDATE=0
fi

if [[ "${SKIP_UPDATE}" != "1" ]]; then
  msg "Installing Python dependencies with uv sync"
  (cd "${PROJECT_DIR}" && uv sync)
  DEPS_STATUS="ok"
else
  DEPS_STATUS="skipped"
fi

# ── GPU-accelerated PyTorch installation ──────────────────────────────────
# Detect GPU vendor and install the matching PyTorch build so embeddings
# run on the accelerator instead of CPU.  Falls back gracefully to CPU
# if detection fails or SKIP_GPU=1.
#
# Supported:
#   NVIDIA (CUDA)    — detected via nvidia-smi; parses driver CUDA version
#   AMD (ROCm)       — detected via rocminfo / rocm-smi; includes Strix Halo APUs
#   Apple Silicon    — detected via uname; MPS is included in standard PyTorch
#   CPU              — default fallback
GPU_VENDOR="cpu"
TORCH_INDEX_URL=""
GPU_STATUS="cpu-only"

if [[ "${SKIP_GPU:-0}" == "1" ]]; then
  msg "Skipping GPU detection (SKIP_GPU=1)."
elif [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
  # Apple Silicon (M1/M2/M3/M4) — MPS is included in the default PyTorch
  # macOS ARM64 build.  No special index URL needed.
  GPU_VENDOR="mps"
  GPU_STATUS="apple-mps"
  msg "Apple Silicon detected — PyTorch MPS acceleration will be used automatically."
elif command -v nvidia-smi >/dev/null 2>&1; then
  GPU_VENDOR="nvidia"
  # Parse the CUDA version from nvidia-smi header (e.g. "CUDA Version: 12.8")
  CUDA_VER=$(nvidia-smi 2>/dev/null | grep -oP 'CUDA Version:\s*\K[0-9]+\.[0-9]+' | head -1)
  GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
  msg "NVIDIA GPU detected: ${GPU_NAME:-unknown} (driver CUDA ${CUDA_VER:-unknown})"

  # Map driver CUDA version to the best available PyTorch CUDA index.
  # PyTorch publishes wheels for specific CUDA minor versions; we pick the
  # highest that the driver supports.  Newer drivers are backwards-compatible.
  if [[ -n "${CUDA_VER}" ]]; then
    CUDA_MAJOR="${CUDA_VER%%.*}"
    CUDA_MINOR="${CUDA_VER#*.}"
    if [[ "${CUDA_MAJOR}" -ge 13 ]] || { [[ "${CUDA_MAJOR}" -eq 12 ]] && [[ "${CUDA_MINOR}" -ge 8 ]]; }; then
      TORCH_INDEX_URL="https://download.pytorch.org/whl/cu128"
      GPU_STATUS="nvidia-cu128"
    elif [[ "${CUDA_MAJOR}" -eq 12 ]] && [[ "${CUDA_MINOR}" -ge 6 ]]; then
      TORCH_INDEX_URL="https://download.pytorch.org/whl/cu126"
      GPU_STATUS="nvidia-cu126"
    elif [[ "${CUDA_MAJOR}" -eq 12 ]] && [[ "${CUDA_MINOR}" -ge 4 ]]; then
      TORCH_INDEX_URL="https://download.pytorch.org/whl/cu124"
      GPU_STATUS="nvidia-cu124"
    elif [[ "${CUDA_MAJOR}" -eq 12 ]]; then
      TORCH_INDEX_URL="https://download.pytorch.org/whl/cu121"
      GPU_STATUS="nvidia-cu121"
    elif [[ "${CUDA_MAJOR}" -eq 11 ]] && [[ "${CUDA_MINOR}" -ge 8 ]]; then
      TORCH_INDEX_URL="https://download.pytorch.org/whl/cu118"
      GPU_STATUS="nvidia-cu118"
    else
      msg "CUDA ${CUDA_VER} is older than 11.8 — falling back to CPU PyTorch."
      msg "Consider updating your NVIDIA drivers for GPU acceleration."
    fi
  fi
elif command -v rocminfo >/dev/null 2>&1 || command -v rocm-smi >/dev/null 2>&1; then
  GPU_VENDOR="amd"
  # Detect ROCm version
  ROCM_VER=""
  if command -v rocminfo >/dev/null 2>&1; then
    ROCM_VER=$(rocminfo 2>/dev/null | grep -oP 'HSA Runtime Version:\s*\K[0-9]+\.[0-9]+' | head -1)
  fi
  if [[ -z "${ROCM_VER}" ]] && command -v rocm-smi >/dev/null 2>&1; then
    ROCM_VER=$(rocm-smi --showdriverversion 2>/dev/null | grep -oP '[0-9]+\.[0-9]+' | head -1)
  fi
  GPU_NAME=$(rocm-smi --showproductname 2>/dev/null | grep -oP 'GPU\[\d+\]\s*:\s*\K.*' | head -1)
  msg "AMD GPU detected: ${GPU_NAME:-unknown} (ROCm ${ROCM_VER:-unknown})"

  # ROCm PyTorch wheels — pick the best available index.
  # Strix Halo APUs (Ryzen AI Max) require ROCm 6.2+.
  if [[ -n "${ROCM_VER}" ]]; then
    ROCM_MAJOR="${ROCM_VER%%.*}"
    ROCM_MINOR="${ROCM_VER#*.}"
    if [[ "${ROCM_MAJOR}" -ge 7 ]]; then
      TORCH_INDEX_URL="https://download.pytorch.org/whl/rocm6.2.4"
      GPU_STATUS="amd-rocm6.2"
    elif [[ "${ROCM_MAJOR}" -eq 6 ]] && [[ "${ROCM_MINOR}" -ge 2 ]]; then
      TORCH_INDEX_URL="https://download.pytorch.org/whl/rocm6.2.4"
      GPU_STATUS="amd-rocm6.2"
    elif [[ "${ROCM_MAJOR}" -eq 6 ]]; then
      TORCH_INDEX_URL="https://download.pytorch.org/whl/rocm6.1"
      GPU_STATUS="amd-rocm6.1"
    else
      msg "ROCm ${ROCM_VER} is older than 6.0 — falling back to CPU PyTorch."
      msg "Update ROCm for GPU acceleration: https://rocm.docs.amd.com/"
    fi
  else
    # ROCm tools found but version unknown — try the latest stable index
    TORCH_INDEX_URL="https://download.pytorch.org/whl/rocm6.2.4"
    GPU_STATUS="amd-rocm-auto"
  fi
else
  msg "No GPU detected. Embedding generation will use CPU (still works fine)."
fi

# Install GPU-accelerated PyTorch if a compatible GPU was found
if [[ -n "${TORCH_INDEX_URL}" ]]; then
  msg "Installing GPU-accelerated PyTorch (${GPU_STATUS})..."
  if (cd "${PROJECT_DIR}" && uv pip install torch --index-url "${TORCH_INDEX_URL}" --reinstall --quiet 2>&1); then
    msg "GPU-accelerated PyTorch installed successfully."
  else
    printf "${YELLOW}⚠ GPU PyTorch installation failed — falling back to CPU.${NC}\n"
    printf "  You can retry later: uv pip install torch --index-url %s --reinstall\n" "${TORCH_INDEX_URL}"
    GPU_STATUS="cpu-fallback"
  fi
elif [[ "${GPU_VENDOR}" == "mps" ]]; then
  msg "Apple Silicon MPS: standard PyTorch build includes MPS support — no extra install needed."
fi

msg "Downloading embedding model to ${STORAGE_DIR}"
mkdir -p "${STORAGE_DIR}"

# Disk space check — warn if less than 2 GB free (don't block)
if command -v df >/dev/null 2>&1; then
  FREE_KB=$(df -k "${STORAGE_DIR}" 2>/dev/null | awk 'NR==2 {print $4}')
  if [[ -n "${FREE_KB}" ]] && [[ "${FREE_KB}" -lt 2097152 ]]; then
    FREE_MB=$((FREE_KB / 1024))
    printf "${YELLOW}⚠ Low disk space: %s MB free in %s (recommend at least 2 GB)${NC}\n" "${FREE_MB}" "${STORAGE_DIR}"
  fi
fi
if (cd "${PROJECT_DIR}" && uv run scripts/download_model_standalone.py --storage-dir "${STORAGE_DIR}" --model "${MODEL_NAME}" -v); then
  MODEL_STATUS="ok"
else
  MODEL_STATUS="failed"
  printf "\n${RED}${BOLD}╔══════════════════════════════════════════════════╗${NC}\n"
  printf "${RED}${BOLD}║  MODEL DOWNLOAD FAILED                           ║${NC}\n"
  printf "${RED}${BOLD}║  Indexing/search is blocked until this is fixed.  ║${NC}\n"
  printf "${RED}${BOLD}╚══════════════════════════════════════════════════╝${NC}\n\n"
  msg "Recovery steps:"
  msg "  1) Check disk space (need ~1-2 GB)"
  msg "  2) If using a gated model, authenticate: hf auth login"
  msg "  3) Retry model download:"
  msg "     uv run --directory ${PROJECT_DIR} python scripts/download_model_standalone.py --storage-dir ${STORAGE_DIR} --model ${MODEL_NAME} -v"
fi

# ── Optional reranker download ────────────────────────────────────────
# Controlled by CODE_SEARCH_PROFILE (default: base).
# Profiles: base = embedding only, reranker = +reranker, full = everything
PROFILE="${CODE_SEARCH_PROFILE:-base}"
RERANKER_STATUS="skipped"
if [[ "$PROFILE" == "reranker" || "$PROFILE" == "full" ]]; then
  RERANKER_NAME="${CODE_SEARCH_RERANKER:-cross-encoder/ms-marco-MiniLM-L-6-v2}"
  msg "Downloading reranker model: ${RERANKER_NAME}"
  if (cd "${PROJECT_DIR}" && uv run scripts/download_reranker_standalone.py --storage-dir "${STORAGE_DIR}" --model "${RERANKER_NAME}" -v); then
    RERANKER_STATUS="ok"
  else
    RERANKER_STATUS="failed"
    msg "WARNING: Reranker download did not complete."
    msg "The reranker is optional — search still works with embedding-only mode."
    msg "Retry: uv run --directory ${PROJECT_DIR} python scripts/download_reranker_standalone.py --storage-dir ${STORAGE_DIR} --model ${RERANKER_NAME} -v"
  fi
fi

if [[ "${REPO_STATUS}" == "ok" || "${REPO_STATUS}" == "kept-current" ]] && [[ "${DEPS_STATUS}" == "ok" || "${DEPS_STATUS}" == "skipped" ]] && [[ "${MODEL_STATUS}" == "ok" ]]; then
  READY_STATUS="yes"
else
  READY_STATUS="not-yet"
fi

if [[ "${IS_UPDATE}" -eq 1 ]]; then
  hr
  printf "${GREEN}${BOLD}✅ Update flow complete${NC}\n"
  hr
else
  hr
  printf "${GREEN}${BOLD}✅ Install flow complete${NC}\n"
  hr
fi

printf "${BLUE}📍 Locations:${NC}\n"
printf "  Project: %s\n" "${PROJECT_DIR}"
printf "  Storage: %s\n\n" "${STORAGE_DIR}"

printf "${BOLD}Final status summary:${NC}\n"
printf "  Repo installed/updated: %s\n" "${REPO_STATUS}"
printf "  Dependencies installed: %s\n" "${DEPS_STATUS}"
printf "  GPU acceleration: %s\n" "${GPU_STATUS}"
printf "  Model downloaded: %s\n" "${MODEL_STATUS}"
printf "  Reranker downloaded: %s\n" "${RERANKER_STATUS}"
printf "  Ready for indexing: %s\n\n" "${READY_STATUS}"

if [[ "${STASHED_CHANGES}" == "1" ]]; then
  printf "${YELLOW}ℹ Local changes were stashed before update.${NC}\n"
  printf "  Inspect with: git -C %s stash list\n\n" "${PROJECT_DIR}"
fi

printf "${BOLD}MCP server command:${NC}\n"
printf "  uv run --directory %s python mcp_server/server.py\n\n" "${PROJECT_DIR}"
printf "  If installed via PyPI: agent-context-local-mcp\n\n"

if [[ "${IS_UPDATE}" -eq 1 ]]; then
  printf "${YELLOW}Recommended after update (Claude Code):${NC}\n"
  printf "  1) claude mcp remove code-search\n"
  printf "  2) claude mcp add code-search --scope user -- uv run --directory %s python mcp_server/server.py\n" "${PROJECT_DIR}"
  printf "  3) claude mcp list\n\n"
else
  printf "${BOLD}Next steps (Claude Code):${NC}\n"
  printf "  1) claude mcp add code-search --scope user -- uv run --directory %s python mcp_server/server.py\n" "${PROJECT_DIR}"
  printf "  2) claude mcp list\n"
  printf "  3) In Claude Code: index this codebase\n\n"
fi
printf "  For other MCP clients (Cursor, Copilot, Gemini CLI, Codex, etc.):\n"
printf "  uv run --directory %s python scripts/cli.py setup-mcp\n\n" "${PROJECT_DIR}"

printf "${YELLOW}Notes:${NC}\n"
printf "%s\n" "• Selected embedding model: ${MODEL_NAME}"
printf "%s\n" "• Model preference file: ${STORAGE_DIR}/install_config.json"
printf "%s\n" "• To change models: set CODE_SEARCH_MODEL and re-run installer"
printf "%s\n" "• Run diagnostics: uv run --directory ${PROJECT_DIR} python scripts/cli.py doctor"
printf "%s\n" "• To uninstall: curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/uninstall.sh | bash"

if [[ "${IS_WSL}" -eq 1 ]]; then
  printf "\n${YELLOW}${BOLD}🐧 WSL2 detected${NC}\n"
  printf "%s\n" "• If Claude Desktop runs on Windows, register MCP in a Windows terminal too."
  printf "%s\n" "• Windows-cached Hugging Face tokens may not be visible in WSL."
  printf "%s\n" "• Set HF_TOKEN explicitly in WSL when needed."
fi
