# MCP Setup Guide — AGENT Context Local

This guide covers registering **AGENT Context Local** (`agent-context-local`) as
an MCP server in every supported coding tool. The server exposes local semantic
code search to any MCP-capable client.

GitHub: <https://github.com/tlines2016/agent-context-code>

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Install Modes — PyPI vs Source](#install-modes)
- [Tool Setup](#tool-setup)
  - [Claude Code](#claude-code)
  - [GitHub Copilot CLI](#github-copilot-cli)
  - [Gemini CLI](#gemini-cli)
  - [Cursor](#cursor)
  - [OpenAI Codex CLI](#openai-codex-cli)
  - [OpenCode](#opencode)
  - [Cline (VS Code)](#cline-vs-code)
  - [Roo Code (VS Code)](#roo-code-vs-code)
- [Cline CLI](#cline-cli)
  - [Roo CLI](#roo-cli)
- [Server Configuration](#server-configuration)
  - [Idle Memory Management](#idle-memory-management)
  - [Configuration via CLI Args](#configuration-via-cli-args)
  - [Configuration via Environment Variables](#configuration-via-environment-variables)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Python 3.12+

AGENT Context Local requires **Python 3.12 or later**. Verify your version:

```bash
python --version
```

If you see a version below 3.12, install or upgrade Python before continuing.

### uv (Python package manager)

`uv` is required for both install modes — as the runtime for source checkouts,
and as the recommended installer for the PyPI package.

| OS | Install command |
|----|----------------|
| macOS | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Linux | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Windows (PowerShell) | `irm https://astral.sh/uv/install.ps1 \| iex` |

After installing, confirm `uv` is available:

```bash
uv --version
```

### Common Pitfalls

**Windows PATH issues** — The `uv` installer adds itself to your user PATH, but
new terminal windows may be required for the change to take effect. If `uv` is
not found after install, close all terminals and open a fresh one. If the
problem persists, manually add `%USERPROFILE%\.local\bin` (or the path shown by
the installer) to your system PATH.

**macOS Gatekeeper** — On first run, macOS may block the `uv` binary with a
"cannot be opened because the developer cannot be verified" dialog. Open
**System Settings > Privacy & Security**, scroll to the blocked-app notice, and
click **Open Anyway**. Alternatively, run:

```bash
xattr -d com.apple.quarantine "$(which uv)"
```

**WSL interop** — If you use Windows Subsystem for Linux, install `uv` and
`agent-context-local` *inside* the WSL distribution. Paths like `/mnt/c/...`
are Windows filesystem mounts and will work for indexing, but the MCP server
binary itself must live in the Linux filesystem for reliable operation.

---

## Install Modes

There are two ways to install AGENT Context Local. Every tool-setup section
below shows commands for **both** modes.

### PyPI Install (recommended)

Install the package from PyPI:

```bash
uv tool install agent-context-local
```

This makes the MCP server available as a standalone command:

```
agent-context-local-mcp
```

### Source Checkout

Clone the repository and sync dependencies:

```bash
git clone https://github.com/tlines2016/agent-context-code.git
cd agent-context-code
uv sync
```

The MCP server is launched through `uv run`. On GPU machines, add the
appropriate `--extra` flag (e.g. `--extra cu128`) so PyTorch resolves to the
GPU build. The install script does this automatically when it auto-registers.

| OS | Default install directory | MCP command |
|----|--------------------------|-------------|
| macOS / Linux | `~/.local/share/agent-context-code` | `uv run --directory ~/.local/share/agent-context-code python mcp_server/server.py` |
| Windows | `%LOCALAPPDATA%\agent-context-code` | `uv run --directory "%LOCALAPPDATA%\agent-context-code" python mcp_server/server.py` |

Throughout this guide the following placeholders are used:

| Placeholder | Meaning |
|-------------|---------|
| `<pypi-cmd>` | `agent-context-local-mcp` |
| `<source-cmd>` | The full `uv run --directory ...` command for your OS (see table above) |

---

## Tool Setup

### Claude Code

Claude Code registers MCP servers via the `claude mcp add` CLI command.

**PyPI install:**

```bash
claude mcp add code-search --scope user -- agent-context-local-mcp
```

**Source checkout (macOS / Linux):**

```bash
claude mcp add code-search --scope user -- \
  uv run --directory ~/.local/share/agent-context-code python mcp_server/server.py
```

**Source checkout (Windows — PowerShell):**

```powershell
claude mcp add code-search --scope user -- `
  uv run --directory "$env:LOCALAPPDATA\agent-context-code" python mcp_server/server.py
```

**Verify registration:**

```bash
claude mcp list
```

You should see `code-search` in the output with a status of `enabled`.

---

### GitHub Copilot CLI

Copilot CLI supports MCP server registration via `copilot mcp add` or a JSON
config file.

#### Option A — CLI command

**PyPI install:**

```bash
copilot mcp add code-search -- agent-context-local-mcp
```

**Source checkout (macOS / Linux):**

```bash
copilot mcp add code-search -- \
  uv run --directory ~/.local/share/agent-context-code python mcp_server/server.py
```

**Source checkout (Windows — PowerShell):**

```powershell
copilot mcp add code-search -- `
  uv run --directory "$env:LOCALAPPDATA\agent-context-code" python mcp_server/server.py
```

#### Option B — JSON config file

Edit (or create) `~/.copilot/mcp-config.json`:

**PyPI install:**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "agent-context-local-mcp"
    }
  }
}
```

**Source checkout (macOS / Linux):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "~/.local/share/agent-context-code",
        "python", "mcp_server/server.py"
      ]
    }
  }
}
```

**Source checkout (Windows):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "%LOCALAPPDATA%\\agent-context-code",
        "python", "mcp_server/server.py"
      ]
    }
  }
}
```

---

### Gemini CLI

Gemini CLI reads MCP configuration from `~/.gemini/settings.json`.

Edit (or create) the file and add a `"mcpServers"` entry:

**PyPI install:**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "agent-context-local-mcp"
    }
  }
}
```

**Source checkout (macOS / Linux):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "~/.local/share/agent-context-code",
        "python", "mcp_server/server.py"
      ]
    }
  }
}
```

**Source checkout (Windows):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "%LOCALAPPDATA%\\agent-context-code",
        "python", "mcp_server/server.py"
      ]
    }
  }
}
```

---

### Cursor

Cursor supports MCP configuration at two levels:

| Scope | Config file |
|-------|-------------|
| Global (all projects) | `~/.cursor/mcp.json` |
| Per-project | `.cursor/mcp.json` in the project root |

Edit the appropriate file:

**PyPI install:**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "agent-context-local-mcp"
    }
  }
}
```

**Source checkout (macOS / Linux):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "~/.local/share/agent-context-code",
        "python", "mcp_server/server.py"
      ]
    }
  }
}
```

**Source checkout (Windows):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "%LOCALAPPDATA%\\agent-context-code",
        "python", "mcp_server/server.py"
      ]
    }
  }
}
```

After saving the file, restart Cursor or use the command palette
(**Ctrl+Shift+P** / **Cmd+Shift+P**) and run **MCP: Restart Servers**.

---

### OpenAI Codex CLI

Codex CLI uses a TOML configuration file at `~/.codex/config.toml`.

**PyPI install:**

```toml
[mcp_servers.code-search]
command = "agent-context-local-mcp"
args = []
```

**Source checkout (macOS / Linux):**

```toml
[mcp_servers.code-search]
command = "uv"
args = [
  "run", "--directory",
  "~/.local/share/agent-context-code",
  "python", "mcp_server/server.py"
]
```

**Source checkout (Windows):**

```toml
[mcp_servers.code-search]
command = "uv"
args = [
  "run", "--directory",
  "C:\\Users\\<YOUR_USERNAME>\\AppData\\Local\\agent-context-code",
  "python", "mcp_server/server.py"
]
```

Replace `<YOUR_USERNAME>` with your actual Windows username, or use the
expanded value of `%LOCALAPPDATA%`.

---

### OpenCode

OpenCode reads MCP configuration from `~/.config/opencode/opencode.json`.

Edit (or create) the file:

**PyPI install:**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "agent-context-local-mcp"
    }
  }
}
```

**Source checkout (macOS / Linux):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "~/.local/share/agent-context-code",
        "python", "mcp_server/server.py"
      ]
    }
  }
}
```

**Source checkout (Windows):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "%LOCALAPPDATA%\\agent-context-code",
        "python", "mcp_server/server.py"
      ]
    }
  }
}
```

---

### Cline (VS Code)

Cline can be configured through the VS Code UI or by editing its JSON config
directly.

#### Option A — VS Code UI

1. Open VS Code and navigate to the Cline sidebar panel.
2. Open **MCP Servers** settings (gear icon).
3. Click **Add MCP Server**.
4. Set the server name to `code-search`.
5. Enter the command and arguments as shown below.

#### Option B — JSON config

The config file is located in VS Code's globalStorage directory:

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` |
| Linux | `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` |
| Windows | `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json` |

**PyPI install:**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "agent-context-local-mcp",
      "args": [],
      "disabled": false
    }
  }
}
```

**Source checkout (macOS / Linux):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "~/.local/share/agent-context-code",
        "python", "mcp_server/server.py"
      ],
      "disabled": false
    }
  }
}
```

**Source checkout (Windows):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "%LOCALAPPDATA%\\agent-context-code",
        "python", "mcp_server/server.py"
      ],
      "disabled": false
    }
  }
}
```

After saving, restart the Cline MCP servers from the Cline sidebar or reload
the VS Code window.

---

### Roo Code (VS Code)

Roo Code can be configured through the VS Code UI or by editing its JSON config
directly.

#### Option A — VS Code UI

1. Open VS Code and navigate to the Roo Code sidebar panel.
2. Open **MCP Servers** settings (gear icon).
3. Click **Add MCP Server**.
4. Set the server name to `code-search`.
5. Enter the command and arguments as shown below.

#### Option B — JSON config

The config file is located in VS Code's globalStorage directory:

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json` |
| Linux | `~/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json` |
| Windows | `%APPDATA%\Code\User\globalStorage\rooveterinaryinc.roo-cline\settings\mcp_settings.json` |

**PyPI install:**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "agent-context-local-mcp",
      "args": [],
      "disabled": false
    }
  }
}
```

**Source checkout (macOS / Linux):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "~/.local/share/agent-context-code",
        "python", "mcp_server/server.py"
      ],
      "disabled": false
    }
  }
}
```

**Source checkout (Windows):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "%LOCALAPPDATA%\\agent-context-code",
        "python", "mcp_server/server.py"
      ],
      "disabled": false
    }
  }
}
```

After saving, restart the Roo Code MCP servers from the sidebar or reload
the VS Code window.

---

### Cline CLI

Cline is also available as a standalone CLI tool (outside VS Code). It reads
MCP configuration from `~/.cline/mcp_settings.json`.

**PyPI install:**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "agent-context-local-mcp"
    }
  }
}
```

**Source checkout (macOS / Linux):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "~/.local/share/agent-context-code",
        "python", "mcp_server/server.py"
      ]
    }
  }
}
```

**Source checkout (Windows):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "%LOCALAPPDATA%\\agent-context-code",
        "python", "mcp_server/server.py"
      ]
    }
  }
}
```

---

### Roo CLI

Roo Code also ships a standalone CLI. It reads MCP configuration from
`~/.roo/mcp_settings.json`.

**PyPI install:**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "agent-context-local-mcp"
    }
  }
}
```

**Source checkout (macOS / Linux):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "~/.local/share/agent-context-code",
        "python", "mcp_server/server.py"
      ]
    }
  }
}
```

**Source checkout (Windows):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "%LOCALAPPDATA%\\agent-context-code",
        "python", "mcp_server/server.py"
      ]
    }
  }
}
```

---

## Server Configuration

### Idle Memory Management

The MCP server includes a two-tier idle memory management system that
automatically reclaims GPU VRAM (and system RAM) when the server is idle:

| Tier | Default | Behavior | Restore time |
|------|---------|----------|--------------|
| **Warm offload** | 15 min | Models move from GPU to CPU RAM | ~50-100ms |
| **Cold unload** | 30 min | Models fully destroyed, memory freed | ~5-30s (cold start) |

After warm offload, models stay in system RAM for fast restore. After cold
unload, the next query triggers a full model reload from the local disk cache.

Both tiers are **enabled by default**. Set a tier's value to `0` to disable
it. When both are active, the cold threshold must be greater than the warm
threshold.

### Configuration via CLI Args

The easiest way to customize idle thresholds is to pass `--idle-offload` and
`--idle-unload` as server arguments. These appear in the `"args"` field of
your MCP client config.

**Claude Code (PyPI):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "agent-context-local-mcp",
      "args": ["--idle-offload", "20", "--idle-unload", "45"]
    }
  }
}
```

**Cursor / Cline / Roo Code (PyPI):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "agent-context-local-mcp",
      "args": ["--idle-offload", "20", "--idle-unload", "45"],
      "disabled": false
    }
  }
}
```

**GitHub Copilot CLI (PyPI):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "agent-context-local-mcp",
      "args": ["--idle-offload", "20", "--idle-unload", "45"]
    }
  }
}
```

**OpenAI Codex CLI (PyPI):**

```toml
[mcp_servers.code-search]
command = "agent-context-local-mcp"
args = ["--idle-offload", "20", "--idle-unload", "45"]
```

**Gemini CLI (PyPI):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "agent-context-local-mcp",
      "args": ["--idle-offload", "20", "--idle-unload", "45"]
    }
  }
}
```

**Source checkout example (macOS / Linux):**

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "run", "--directory",
        "~/.local/share/agent-context-code",
        "python", "mcp_server/server.py",
        "--idle-offload", "20",
        "--idle-unload", "45"
      ]
    }
  }
}
```

### Configuration via install_config.json

Idle thresholds can also be set persistently using the CLI tool:

```bash
# Set warm CPU offload to 20 minutes
python scripts/cli.py config idle offload 20

# Set cold full unload to 45 minutes
python scripts/cli.py config idle unload 45

# Disable warm offload (only cold unload remains)
python scripts/cli.py config idle offload 0
```

These values are stored in `~/.agent_code_search/install_config.json` and
apply to all future server starts.

### Configuration via Environment Variables

Environment variables override `install_config.json` when no idle CLI args are
provided:

```bash
export CODE_SEARCH_IDLE_OFFLOAD_MINUTES=20   # warm offload after 20 min
export CODE_SEARCH_IDLE_UNLOAD_MINUTES=45    # cold unload after 45 min
```

You can also pass these via the `"env"` field in your MCP config:

```json
{
  "mcpServers": {
    "code-search": {
      "command": "agent-context-local-mcp",
      "env": {
        "CODE_SEARCH_IDLE_OFFLOAD_MINUTES": "20",
        "CODE_SEARCH_IDLE_UNLOAD_MINUTES": "45"
      }
    }
  }
}
```

### Configuration Priority

When multiple sources set the same value, the server resolves them in this
order (highest priority first):

1. **CLI args** (`--idle-offload`, `--idle-unload`)
2. **Environment variable** (`CODE_SEARCH_IDLE_OFFLOAD_MINUTES`, `CODE_SEARCH_IDLE_UNLOAD_MINUTES`)
3. **install_config.json** (`idle_offload_minutes`, `idle_unload_minutes`)
4. **Hardcoded default** (15 min offload, 30 min unload)

Invalid or negative values are ignored with a warning and fall back to the
hardcoded defaults.

---

## Troubleshooting

### `uv: command not found`

**Cause:** `uv` is not installed or not on your PATH.

**Fix:**
1. Install `uv` using the commands in the [Prerequisites](#prerequisites)
   section.
2. Close and reopen your terminal so the PATH update takes effect.
3. On Windows, if the problem persists, add the `uv` install directory
   (typically `%USERPROFILE%\.local\bin`) to your system PATH manually via
   **Settings > System > About > Advanced system settings > Environment
   Variables**.

### Python version mismatch

**Symptom:** Errors mentioning unsupported Python version, or `uv` selecting a
Python older than 3.12.

**Fix:**
1. Run `python --version` (or `python3 --version`) to confirm the active
   version.
2. If below 3.12, install Python 3.12+ from <https://www.python.org/downloads/>
   or via your system package manager.
3. If multiple Python versions are installed, `uv` will typically find the
   correct one. You can force a version with `uv python pin 3.12` inside the
   project directory.

### Server won't start

**Symptom:** The MCP server process exits immediately or prints an import error.

**Fix (PyPI install):**
1. Verify the package is installed: `uv tool list | grep agent-context-local`.
2. Run the server manually to see error output:
   ```bash
   agent-context-local-mcp
   ```
3. If you see dependency errors, reinstall:
   ```bash
   uv tool install --force agent-context-local
   ```

**Fix (source checkout):**
1. Ensure you are in the correct directory and dependencies are synced:
   ```bash
   cd ~/.local/share/agent-context-code   # or %LOCALAPPDATA%\agent-context-code on Windows
   uv sync
   ```
2. Run the server manually to see error output:
   ```bash
   uv run python mcp_server/server.py
   ```
3. If the embedding model has not been downloaded yet, run setup:
   ```bash
   uv run python scripts/cli.py doctor
   uv run python scripts/cli.py setup-guide
   ```

### Tool can't connect to the MCP server

**Symptom:** The coding tool reports the MCP server is unreachable, times out,
or shows "server not found."

**Fix:**
1. Confirm the server starts successfully when run manually (see above).
2. Double-check the command and arguments in your tool's config. A single
   misplaced quote or wrong path will prevent the tool from launching the
   server.
3. Make sure you are using the correct path separator for your OS (`/` on
   macOS/Linux, `\\` in JSON strings on Windows).
4. For VS Code extensions (Cline, Roo Code), reload the VS Code window after
   config changes (**Ctrl+Shift+P** / **Cmd+Shift+P** then
   **Developer: Reload Window**).
5. Some tools cache MCP server state. Restart the tool entirely if a config
   change does not take effect after reloading.

### Windows: `uv` or `agent-context-local-mcp` not recognized in PowerShell

**Cause:** The tool's PATH does not include the directory where `uv` or PyPI
scripts are installed.

**Fix:**
1. Find the install location:
   ```powershell
   where.exe uv
   where.exe agent-context-local-mcp
   ```
2. If `where.exe` cannot find the executable, locate it manually (commonly
   `%USERPROFILE%\.local\bin` or `%USERPROFILE%\.cargo\bin` for `uv`).
3. Add the directory to your user PATH and restart your terminal.
4. As a workaround, use the full absolute path to the executable in your MCP
   config instead of just the command name.

### macOS: "cannot be opened because the developer cannot be verified"

**Cause:** macOS Gatekeeper is blocking an unsigned binary.

**Fix:**
```bash
xattr -d com.apple.quarantine "$(which uv)"
```

Or navigate to **System Settings > Privacy & Security** and click
**Open Anyway** next to the blocked application.

### Embedding model not downloaded

**Symptom:** The server starts but search returns errors about a missing model.

**Fix:**
```bash
# PyPI install
agent-context-local-mcp   # first run triggers download

# Source checkout
uv run --directory ~/.local/share/agent-context-code python scripts/cli.py setup-guide
```

The default model (`mixedbread-ai/mxbai-embed-xsmall-v1`) is not gated and will
download automatically on first use. If you are behind a corporate proxy, ensure
`HTTPS_PROXY` is set in your environment.
