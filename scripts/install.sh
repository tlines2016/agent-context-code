#!/usr/bin/env bash
set -euo pipefail

# Remote installer for AGENT Context Local
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.sh | bash

REPO_URL="https://github.com/tlines2016/agent-context-code"
PROJECT_DIR="${HOME}/.local/share/agent-context-code"
STORAGE_DIR="${CODE_SEARCH_STORAGE:-${HOME}/.claude_code_search}"
MODEL_NAME="${CODE_SEARCH_MODEL:-Qwen/Qwen3-Embedding-0.6B}"

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
    msg "ERROR: uv installation failed or not found in PATH."
    exit 1
  fi
fi

# ── Repository setup: three cases ──────────────────────────────────────────
# 1) Fresh install  : PROJECT_DIR does not exist → git clone
# 2) Update (clean) : .git exists, no local changes → git pull
# 3) Update (dirty) : .git exists, uncommitted changes → interactive
#    (stash+pull / keep / delete+reclone; default=stash when non-interactive)
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

# FAISS package management is intentionally removed.
# Why: runtime search backend is LanceDB, so installer should not claim or
# mutate FAISS packages. We keep optional GPU detection only as a performance hint.
if [[ "${SKIP_GPU:-0}" == "1" ]]; then
  msg "Skipping GPU detection (SKIP_GPU=1)."
else
  if command -v nvidia-smi >/dev/null 2>&1; then
    msg "NVIDIA GPU detected. Embedding generation may be faster with CUDA-enabled PyTorch."
  else
    msg "No NVIDIA GPU detected. Install still works on CPU."
  fi
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
  RERANKER_NAME="${CODE_SEARCH_RERANKER:-Qwen/Qwen3-Reranker-4B}"
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
printf "  Model downloaded: %s\n" "${MODEL_STATUS}"
printf "  Reranker downloaded: %s\n" "${RERANKER_STATUS}"
printf "  Ready for indexing: %s\n\n" "${READY_STATUS}"

if [[ "${STASHED_CHANGES}" == "1" ]]; then
  printf "${YELLOW}ℹ Local changes were stashed before update.${NC}\n"
  printf "  Inspect with: git -C %s stash list\n\n" "${PROJECT_DIR}"
fi

if [[ "${IS_UPDATE}" -eq 1 ]]; then
  printf "${YELLOW}Recommended after update:${NC}\n"
  printf "  1) claude mcp remove code-search\n"
  printf "  2) claude mcp add code-search --scope user -- uv run --directory %s python mcp_server/server.py\n" "${PROJECT_DIR}"
  printf "  3) claude mcp list\n\n"
else
  printf "${BOLD}Next steps:${NC}\n"
  printf "  1) claude mcp add code-search --scope user -- uv run --directory %s python mcp_server/server.py\n" "${PROJECT_DIR}"
  printf "  2) claude mcp list\n"
  printf "  3) In Claude Code: index this codebase\n\n"
fi

printf "${YELLOW}Notes:${NC}\n"
printf "%s\n" "• Selected embedding model: ${MODEL_NAME}"
printf "%s\n" "• Model preference file: ${STORAGE_DIR}/install_config.json"
printf "%s\n" "• To change models: set CODE_SEARCH_MODEL and re-run installer"
printf "%s\n" "• Run diagnostics: uv run --directory ${PROJECT_DIR} python scripts/cli.py doctor"

if [[ "${IS_WSL}" -eq 1 ]]; then
  printf "\n${YELLOW}${BOLD}🐧 WSL2 detected${NC}\n"
  printf "%s\n" "• If Claude Desktop runs on Windows, register MCP in a Windows terminal too."
  printf "%s\n" "• Windows-cached Hugging Face tokens may not be visible in WSL."
  printf "%s\n" "• Set HF_TOKEN explicitly in WSL when needed."
fi
