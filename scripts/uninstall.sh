#!/usr/bin/env bash
set -euo pipefail

# Uninstall AGENT Context Local.
# Removes app checkout, storage data, and MCP registration.
# Shared prerequisites (uv, Python, git) are intentionally NOT removed.

PROJECT_DIR="${HOME}/.local/share/agent-context-code"
STORAGE_DIR="${CODE_SEARCH_STORAGE:-${HOME}/.agent_code_search}"
FORCE=0
DRY_RUN=0
SKIP_MCP=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

msg() { printf "%b\n" "$1"; }
hr()  { msg "\n==================================================\n"; }

require_value() {
    local flag="$1"
    local maybe_value="${2:-}"
    if [[ -z "$maybe_value" || "$maybe_value" == --* ]]; then
        echo "ERROR: ${flag} requires a value." >&2
        exit 1
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-dir)
            require_value "$1" "${2:-}"
            PROJECT_DIR="$2"
            shift 2
            ;;
        --storage-dir)
            require_value "$1" "${2:-}"
            STORAGE_DIR="$2"
            shift 2
            ;;
        --force) FORCE=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --skip-mcp-remove) SKIP_MCP=1; shift ;;
        -h|--help)
            echo "Usage: uninstall.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --project-dir DIR    App checkout directory (default: ~/.local/share/agent-context-code)"
            echo "  --storage-dir DIR    Storage root directory (default: ~/.agent_code_search)"
            echo "  --force              Skip confirmation prompt"
            echo "  --dry-run            Preview what would be removed without deleting"
            echo "  --skip-mcp-remove    Skip MCP server deregistration"
            echo "  -h, --help           Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

MCP_STATUS="skipped"
PROJECT_STATUS="skipped"
STORAGE_STATUS="skipped"

is_safe_path() {
    local path="$1"
    local label="$2"

    if [[ -z "$path" ]]; then
        echo "  [$label] Path is empty - skipping." >&2
        return 1
    fi

    local resolved
    if command -v realpath >/dev/null 2>&1; then
        resolved="$(realpath -m "$path" 2>/dev/null)" || resolved="$path"
    elif command -v readlink >/dev/null 2>&1; then
        resolved="$(readlink -f "$path" 2>/dev/null)" || resolved="$path"
    else
        resolved="$(cd "$(dirname "$path")" 2>/dev/null && pwd)/$(basename "$path")" 2>/dev/null || resolved="$path"
    fi

    local dangerous_paths=("$HOME" "/" "/usr" "/usr/local" "/tmp" "/var" "/etc" "/opt")
    for d in "${dangerous_paths[@]}"; do
        local norm_d="${d%/}"
        local norm_r="${resolved%/}"
        if [[ "$norm_r" == "$norm_d" ]]; then
            echo "  [$label] BLOCKED: '$resolved' matches a protected system path. Refusing to delete." >&2
            return 1
        fi
    done

    echo "$resolved"
}

project_path_looks_like_install() {
    local path="$1"
    local base
    base="$(basename "$path")"
    if [[ "$base" == "agent-context-code" ]]; then
        return 0
    fi
    [[ -f "$path/mcp_server/server.py" && -f "$path/scripts/cli.py" ]]
}

storage_path_looks_like_context_storage() {
    local path="$1"
    local base
    base="$(basename "$path")"
    if [[ "$base" == ".agent_code_search" || "$base" == ".claude_code_search" ]]; then
        return 0
    fi

    # Require at least two markers for non-canonical directory names.
    # This avoids deleting unrelated folders that only have "models" or "projects".
    local marker_count=0
    [[ -f "$path/install_config.json" ]] && marker_count=$((marker_count + 1))
    [[ -d "$path/models" ]] && marker_count=$((marker_count + 1))
    [[ -d "$path/projects" ]] && marker_count=$((marker_count + 1))
    [[ "$marker_count" -ge 2 ]]
}

SAFE_PROJECT_DIR=""
SAFE_STORAGE_DIR=""
PROJECT_EXISTS=0
STORAGE_EXISTS=0
PROJECT_TRUSTED=0
STORAGE_TRUSTED=0

if result=$(is_safe_path "$PROJECT_DIR" "Project"); then
    SAFE_PROJECT_DIR="$result"
fi

if result=$(is_safe_path "$STORAGE_DIR" "Storage"); then
    SAFE_STORAGE_DIR="$result"
fi

[[ -n "$SAFE_PROJECT_DIR" && -d "$SAFE_PROJECT_DIR" ]] && PROJECT_EXISTS=1
[[ -n "$SAFE_STORAGE_DIR" && -d "$SAFE_STORAGE_DIR" ]] && STORAGE_EXISTS=1

if [[ "$PROJECT_EXISTS" -eq 1 ]] && project_path_looks_like_install "$SAFE_PROJECT_DIR"; then
    PROJECT_TRUSTED=1
fi

if [[ "$STORAGE_EXISTS" -eq 1 ]] && storage_path_looks_like_context_storage "$SAFE_STORAGE_DIR"; then
    STORAGE_TRUSTED=1
fi

hr
msg "${BOLD}AGENT Context Local - Uninstall${NC}"
hr

if [[ "$DRY_RUN" -eq 1 ]]; then
    msg "  ${CYAN}[DRY-RUN MODE] No files will be deleted.${NC}"
    echo ""
fi

msg "${BOLD}Planned actions:${NC}"
if [[ "$SKIP_MCP" -eq 0 ]]; then
    msg "  MCP registration : remove 'code-search' server"
else
    msg "  MCP registration : skip (--skip-mcp-remove)"
fi

if [[ "$PROJECT_EXISTS" -eq 1 && "$PROJECT_TRUSTED" -eq 1 ]]; then
    msg "  Project directory: DELETE $SAFE_PROJECT_DIR"
elif [[ "$PROJECT_EXISTS" -eq 1 ]]; then
    msg "  Project directory: BLOCKED (path does not look like AGENT Context Local install)"
elif [[ -n "$SAFE_PROJECT_DIR" ]]; then
    msg "  Project directory: not found ($SAFE_PROJECT_DIR) - nothing to do"
else
    msg "  Project directory: path invalid - skipping"
fi

if [[ "$STORAGE_EXISTS" -eq 1 && "$STORAGE_TRUSTED" -eq 1 ]]; then
    msg "  Storage directory: DELETE $SAFE_STORAGE_DIR"
elif [[ "$STORAGE_EXISTS" -eq 1 ]]; then
    msg "  Storage directory: BLOCKED (path does not look like AGENT Context Local storage)"
elif [[ -n "$SAFE_STORAGE_DIR" ]]; then
    msg "  Storage directory: not found ($SAFE_STORAGE_DIR) - nothing to do"
else
    msg "  Storage directory: path invalid - skipping"
fi

echo ""
msg "${DIM}NOT removed (shared tools): uv, Python, git${NC}"

if [[ "$PROJECT_EXISTS" -eq 0 && "$STORAGE_EXISTS" -eq 0 && "$SKIP_MCP" -eq 1 ]]; then
    echo ""
    msg "${YELLOW}Nothing to remove. AGENT Context Local does not appear to be installed.${NC}"
    exit 0
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo ""
    msg "${CYAN}Dry-run complete. Re-run without --dry-run to perform the uninstall.${NC}"
    exit 0
fi

if [[ "$FORCE" -eq 0 ]]; then
    echo ""
    printf "Proceed with uninstall? This will permanently delete the above directories [y/N]: "
    if [ -t 0 ]; then
        read -r answer
    else
        msg "${YELLOW}Non-interactive session detected. Use --force to proceed without confirmation.${NC}"
        msg "Aborted. No changes were made."
        exit 0
    fi
    case "$answer" in
        y|Y|yes|Yes|YES) ;;
        *)
            msg "${YELLOW}Aborted. No changes were made.${NC}"
            exit 0
            ;;
    esac
fi

if [[ "$SKIP_MCP" -eq 0 ]]; then
    echo ""
    msg "Removing MCP server registration..."
    if command -v claude >/dev/null 2>&1; then
        if claude mcp remove code-search --scope user 2>/dev/null; then
            MCP_STATUS="removed"
            msg "  ${GREEN}MCP 'code-search' registration removed.${NC}"
        else
            MCP_STATUS="failed"
            msg "  ${YELLOW}WARNING: 'claude mcp remove code-search --scope user' failed.${NC}"
            msg "  ${YELLOW}Manual step: claude mcp remove code-search --scope user${NC}"
        fi
    else
        MCP_STATUS="skipped (claude CLI not found)"
        msg "  ${YELLOW}'claude' CLI not found - skipping MCP removal.${NC}"
        msg "  ${YELLOW}If you install Claude Code later, run: claude mcp remove code-search --scope user${NC}"
    fi
fi

if [[ "$PROJECT_EXISTS" -eq 1 && "$PROJECT_TRUSTED" -eq 1 ]]; then
    echo ""
    msg "Removing project directory: $SAFE_PROJECT_DIR"
    if rm -rf "$SAFE_PROJECT_DIR"; then
        PROJECT_STATUS="removed"
        msg "  ${GREEN}Removed.${NC}"
    else
        PROJECT_STATUS="failed"
        msg "  ${RED}FAILED to remove project directory.${NC}"
    fi
elif [[ "$PROJECT_EXISTS" -eq 1 ]]; then
    PROJECT_STATUS="blocked"
elif [[ -n "$SAFE_PROJECT_DIR" ]]; then
    PROJECT_STATUS="not found"
fi

if [[ "$STORAGE_EXISTS" -eq 1 && "$STORAGE_TRUSTED" -eq 1 ]]; then
    echo ""
    msg "Removing storage directory: $SAFE_STORAGE_DIR"
    if rm -rf "$SAFE_STORAGE_DIR"; then
        STORAGE_STATUS="removed"
        msg "  ${GREEN}Removed.${NC}"
    else
        STORAGE_STATUS="failed"
        msg "  ${RED}FAILED to remove storage directory.${NC}"
    fi
elif [[ "$STORAGE_EXISTS" -eq 1 ]]; then
    STORAGE_STATUS="blocked"
elif [[ -n "$SAFE_STORAGE_DIR" ]]; then
    STORAGE_STATUS="not found"
fi

hr
msg "${BOLD}Uninstall Summary${NC}"
hr

print_status() {
    local label="$1"
    local status="$2"
    local color="$NC"
    case "$status" in
        removed) color="$GREEN" ;;
        "not found") color="$DIM" ;;
        blocked) color="$YELLOW" ;;
        skipped*) color="$YELLOW" ;;
        failed*) color="$RED" ;;
    esac
    msg "  ${label}: ${color}${status}${NC}"
}

print_status "MCP registration " "$MCP_STATUS"
print_status "Project directory" "$PROJECT_STATUS"
print_status "Storage directory" "$STORAGE_STATUS"

echo ""
ANY_FAILED=0
ANY_BLOCKED=0
for s in "$MCP_STATUS" "$PROJECT_STATUS" "$STORAGE_STATUS"; do
    [[ "$s" == failed* ]] && ANY_FAILED=1
    [[ "$s" == blocked ]] && ANY_BLOCKED=1
done

if [[ "$ANY_FAILED" -eq 1 ]]; then
    msg "${YELLOW}Uninstall completed with errors. See details above.${NC}"
    exit 1
elif [[ "$ANY_BLOCKED" -eq 1 ]]; then
    msg "${YELLOW}Uninstall stopped by safety checks for one or more paths.${NC}"
    msg "${YELLOW}Review path overrides, then retry with a valid AGENT Context Local path.${NC}"
    exit 1
else
    msg "${GREEN}AGENT Context Local has been removed.${NC}"
    msg "${DIM}Shared tools (uv, Python, git) were left in place.${NC}"
fi
