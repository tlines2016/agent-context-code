#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────
# AGENT Context Local — Prerequisite Installer (macOS / Linux / WSL)
#
# Checks for Python 3.12+, uv, and git. Offers to install anything
# missing. Every install is opt-in — nothing happens without your "y".
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/prereqs.sh | bash
#   # or locally:
#   bash scripts/prereqs.sh
# ─────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { printf "  ${GREEN}[OK]${NC}    %s\n" "$1"; }
skip() { printf "  ${YELLOW}[SKIP]${NC}  %s\n" "$1"; }
fail() { printf "  ${RED}[MISS]${NC}  %s\n" "$1"; }
info() { printf "  ${CYAN}[INFO]${NC}  %s\n" "$1"; }

NEED_PYTHON=0
NEED_UV=0
NEED_GIT=0
MIN_PY_MAJOR=3
MIN_PY_MINOR=12

printf "\n${BOLD}AGENT Context Local — Prerequisite Check${NC}\n\n"

if [[ "$IS_WSL" -eq 1 ]]; then
  info "Running under WSL2. Prerequisites are checked inside WSL,"
  info "not on the Windows host. These are separate environments."
  echo ""
fi

# ── Detect platform ──────────────────────────────────────────────────
OS="$(uname -s)"
IS_MAC=0; IS_LINUX=0; IS_WSL=0
case "$OS" in
  Darwin) IS_MAC=1 ;;
  Linux)
    IS_LINUX=1
    if [[ -f /proc/version ]] && grep -Eiq "microsoft|wsl" /proc/version 2>/dev/null; then
      IS_WSL=1
    fi
    ;;
esac

HAS_BREW=0
if command -v brew >/dev/null 2>&1; then HAS_BREW=1; fi

HAS_APT=0
if command -v apt >/dev/null 2>&1; then HAS_APT=1; fi

HAS_DNF=0
if command -v dnf >/dev/null 2>&1; then HAS_DNF=1; fi

# ── 1. Check Python ─────────────────────────────────────────────────
check_python_version() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then return 1; fi
  local ver
  ver="$("$cmd" --version 2>&1 | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')" || return 1
  local major minor
  major="$(echo "$ver" | cut -d. -f1)"
  minor="$(echo "$ver" | cut -d. -f2)"
  if [[ "$major" -gt "$MIN_PY_MAJOR" ]] || { [[ "$major" -eq "$MIN_PY_MAJOR" ]] && [[ "$minor" -ge "$MIN_PY_MINOR" ]]; }; then
    echo "$ver"
    return 0
  fi
  return 1
}

PYTHON_CMD=""
PYTHON_VER=""
for candidate in python3 python; do
  if ver="$(check_python_version "$candidate")"; then
    PYTHON_CMD="$candidate"
    PYTHON_VER="$ver"
    break
  fi
done

if [[ -n "$PYTHON_CMD" ]]; then
  ok "Python $PYTHON_VER ($PYTHON_CMD)"
else
  fail "Python 3.12+ not found"
  NEED_PYTHON=1
fi

# ── 2. Check uv ─────────────────────────────────────────────────────
if command -v uv >/dev/null 2>&1; then
  UV_VER="$(uv --version 2>&1 | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')" || UV_VER="unknown"
  ok "uv $UV_VER"
else
  fail "uv not found"
  NEED_UV=1
fi

# ── 3. Check git ────────────────────────────────────────────────────
if command -v git >/dev/null 2>&1; then
  GIT_VER="$(git --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')" || GIT_VER="unknown"
  ok "git $GIT_VER"
else
  fail "git not found"
  NEED_GIT=1
fi

# ── Summary ─────────────────────────────────────────────────────────
echo ""
if [[ "$NEED_PYTHON" -eq 0 ]] && [[ "$NEED_UV" -eq 0 ]] && [[ "$NEED_GIT" -eq 0 ]]; then
  printf "${GREEN}${BOLD}All prerequisites satisfied!${NC}\n"
  printf "You're ready to install AGENT Context Local.\n\n"
  exit 0
fi

MISSING=()
[[ "$NEED_PYTHON" -eq 1 ]] && MISSING+=("Python 3.12+")
[[ "$NEED_UV" -eq 1 ]]     && MISSING+=("uv")
[[ "$NEED_GIT" -eq 1 ]]    && MISSING+=("git")
printf "${YELLOW}Missing: ${MISSING[*]}${NC}\n\n"

# ── Helper: ask yes/no ──────────────────────────────────────────────
NON_INTERACTIVE=0
if [ ! -t 0 ]; then NON_INTERACTIVE=1; fi

if [[ "$NON_INTERACTIVE" -eq 1 ]]; then
  printf "${YELLOW}${BOLD}Running non-interactively (piped from curl).${NC}\n"
  printf "The script will check prerequisites but cannot install them in this mode.\n"
  printf "To install missing items, download and run locally:\n\n"
  printf "  ${CYAN}curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/prereqs.sh -o prereqs.sh${NC}\n"
  printf "  ${CYAN}bash prereqs.sh${NC}\n\n"
fi

ask() {
  local prompt="$1"
  if [[ "$NON_INTERACTIVE" -eq 1 ]]; then
    skip "$prompt (non-interactive — run locally to install)"
    return 1
  fi
  printf "%s [y/N] " "$prompt"
  read -r answer
  case "$answer" in
    [yY]|[yY][eE][sS]) return 0 ;;
    *) return 1 ;;
  esac
}

# ── Install Python ──────────────────────────────────────────────────
if [[ "$NEED_PYTHON" -eq 1 ]]; then
  printf "${BOLD}Install Python 3.12+${NC}\n"
  if [[ "$IS_MAC" -eq 1 ]]; then
    if [[ "$HAS_BREW" -eq 1 ]]; then
      info "Will run: brew install python@3.13"
      if ask "Install Python 3.13 via Homebrew?"; then
        brew install python@3.13
        # Refresh PATH so brew-installed Python is visible this session
        eval "$(brew shellenv)" 2>/dev/null || true
        hash -r 2>/dev/null || true
        ok "Python installed via Homebrew"
        # Note: PATH is updated for this session via 'eval "$(brew shellenv)"' above.
        # If you ran this script via 'curl | bash', open a new terminal window
        # before running the main installer so your shell profile picks up the
        # new Homebrew Python path automatically.
      else
        skip "Python install skipped"
      fi
    else
      info "Homebrew not found. Install Homebrew first (https://brew.sh),"
      info "then run: brew install python@3.13"
      info "Or download from: https://www.python.org/downloads/macos/"
      skip "Python install skipped (no package manager)"
    fi
  elif [[ "$IS_LINUX" -eq 1 ]]; then
    if [[ "$HAS_APT" -eq 1 ]]; then
      # Check if system python3 is already 3.12+. If not, try the
      # deadsnakes PPA which provides newer Python for older Ubuntu.
      SYS_PY_OK=0
      if ver="$(check_python_version python3)"; then SYS_PY_OK=1; fi

      if [[ "$SYS_PY_OK" -eq 1 ]]; then
        info "System Python ($ver) meets the requirement."
        info "Will run: sudo apt install -y python3-venv"
        if ask "Install python3-venv (needed by uv)?"; then
          sudo apt update && sudo apt install -y python3-venv
          ok "python3-venv installed"
        else
          skip "python3-venv install skipped"
        fi
      else
        info "System python3 is too old for this project."
        info "Will add the deadsnakes PPA and install Python 3.13."
        info "Commands:"
        info "  sudo apt update"
        info "  sudo apt install -y software-properties-common"
        info "  sudo add-apt-repository -y ppa:deadsnakes/ppa"
        info "  sudo apt install -y python3.13 python3.13-venv"
        echo ""
        if ask "Install Python 3.13 via deadsnakes PPA?"; then
          sudo apt update
          sudo apt install -y software-properties-common
          sudo add-apt-repository -y ppa:deadsnakes/ppa
          sudo apt update
          sudo apt install -y python3.13 python3.13-venv
          ok "Python 3.13 installed via deadsnakes PPA"
        else
          skip "Python install skipped"
        fi
      fi
    elif [[ "$HAS_DNF" -eq 1 ]]; then
      info "Will run: sudo dnf install -y python3.13"
      if ask "Install Python 3.13 via dnf?"; then
        sudo dnf install -y python3.13 || sudo dnf install -y python3
        ok "Python installed via dnf"
      else
        skip "Python install skipped"
      fi
    else
      info "No supported package manager found (apt/dnf)."
      info "Download from: https://www.python.org/downloads/"
      skip "Python install skipped (no package manager)"
    fi
  fi
  echo ""
fi

# ── Install uv ──────────────────────────────────────────────────────
if [[ "$NEED_UV" -eq 1 ]]; then
  printf "${BOLD}Install uv (Python package manager)${NC}\n"
  info "uv is a fast Python package manager from Astral."
  info "No admin/sudo required. Installs to ~/.local/bin."
  info "Will run: curl -LsSf https://astral.sh/uv/install.sh | sh"
  if ask "Install uv?"; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Source the env file if it exists so uv is available immediately
    if [[ -f "$HOME/.local/bin/env" ]]; then
      # shellcheck disable=SC1091
      . "$HOME/.local/bin/env" 2>/dev/null || true
    fi
    # Also add to PATH for this session
    export PATH="$HOME/.local/bin:$PATH"
    if command -v uv >/dev/null 2>&1; then
      ok "uv installed successfully"
    else
      info "uv installed but not yet on PATH."
      info "Restart your terminal or run: export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
  else
    skip "uv install skipped"
  fi
  echo ""
fi

# ── Install git ─────────────────────────────────────────────────────
if [[ "$NEED_GIT" -eq 1 ]]; then
  printf "${BOLD}Install git${NC}\n"
  if [[ "$IS_MAC" -eq 1 ]]; then
    info "Will run: xcode-select --install"
    info "(This installs Apple's Command Line Tools which includes git.)"
    if ask "Install git via Xcode Command Line Tools?"; then
      xcode-select --install 2>/dev/null || true
      info "A system dialog may have appeared. Follow the prompts to complete."
      info "After it finishes, restart your terminal and re-run this script."
    else
      skip "git install skipped"
    fi
  elif [[ "$IS_LINUX" -eq 1 ]]; then
    if [[ "$HAS_APT" -eq 1 ]]; then
      info "Will run: sudo apt update && sudo apt install -y git"
      if ask "Install git via apt?"; then
        sudo apt update && sudo apt install -y git
        ok "git installed via apt"
      else
        skip "git install skipped"
      fi
    elif [[ "$HAS_DNF" -eq 1 ]]; then
      info "Will run: sudo dnf install -y git"
      if ask "Install git via dnf?"; then
        sudo dnf install -y git
        ok "git installed via dnf"
      else
        skip "git install skipped"
      fi
    else
      info "No supported package manager found."
      info "Download from: https://git-scm.com/downloads"
      skip "git install skipped"
    fi
  fi
  echo ""
fi

# ── Final check ─────────────────────────────────────────────────────
printf "${BOLD}Final verification${NC}\n\n"
ALL_GOOD=1

if ver="$(check_python_version python3)" || ver="$(check_python_version python)"; then
  ok "Python $ver"
else
  fail "Python 3.12+ still not found"
  ALL_GOOD=0
fi

if command -v uv >/dev/null 2>&1; then
  ok "uv $(uv --version 2>&1 | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')"
else
  fail "uv still not found"
  ALL_GOOD=0
fi

if command -v git >/dev/null 2>&1; then
  ok "git $(git --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')"
else
  fail "git still not found"
  ALL_GOOD=0
fi

echo ""
if [[ "$ALL_GOOD" -eq 1 ]]; then
  printf "${GREEN}${BOLD}All prerequisites satisfied!${NC}\n"
  printf "You're ready to install AGENT Context Local.\n\n"
  printf "${BOLD}Next step:${NC}\n"
  printf "  curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.sh | bash\n\n"
else
  printf "${YELLOW}Some prerequisites are still missing.${NC}\n"
  printf "Install them manually, restart your terminal, then re-run:\n"
  printf "  ${CYAN}bash scripts/prereqs.sh${NC}\n\n"
fi
