```text
+-----------------------------------------------------------------------+
|  >_ SYSTEM INITIALIZATION...                                          |
|                                                                       |
|      _    ____ _____ _   _ _____                                      |
|     / \  / ___| ____| \ | |_   _|                                     |
|    / _ \| |  _|  _| |  \| | | |                                       |
|   / ___ \ |_| | |___| |\  | | |                                       |
|  /_/   \_\____|_____|_| \_| |_|                                       |
|                                                                       |
|    ____ ___  _   _ _____ _____ __  _______                            |
|   / ___/ _ \| \ | |_   _| ____|\ \/ /_   _|                           |
|  | |  | | | |  \| | | | |  _|   \  /  | |                             |
|  | |__| |_| | |\  | | | | |___  /  \  | |                             |
|   \____\___/|_| \_| |_| |_____|/_/\_\ |_|                             |
|                                                                       |
|   _     ___   ____    _    _                                          |
|  | |   / _ \ / ___|  / \  | |                                         |
|  | |  | | | | |     / _ \ | |                                         |
|  | |__| |_| | |___ / ___ \| |___                                      |
|  |_____\___/ \____/_/   \_\_____|                                     |
|                                                                       |
|  [ STATUS: ONLINE ] [ MODULES: LOADED ] [ CONNECTION ESTABLISHED ]    |
+-----------------------------------------------------------------------+
```

AGENT Context Local is a local MCP code-search service that helps agents find
the right code by meaning instead of exact strings. Your embeddings, vector
index, and project metadata stay on your machine.

The canonical repository is
[tlines2016/agent-context-code](https://github.com/tlines2016/agent-context-code).

## Why This Exists

Most coding agents are great at reasoning, but weak at searching large codebases
without burning context. This project gives them a local semantic search layer.

- Ask for concepts like `where do we validate auth tokens?` instead of guessing filenames.
- Keep your source code local instead of shipping it to a hosted search service.
- Reuse a persistent local index across sessions instead of re-explaining the repo.
- Work through MCP so the same backend can support more than one agent client over time.

## What It Uses Today

- **Vector database:** LanceDB
- **Storage root:** `~/.claude_code_search` or `CODE_SEARCH_STORAGE`
- **Per-project storage:** `~/.claude_code_search/projects/{name}_{hash}`
- **Chunking:** Python AST plus tree-sitter and structured config chunking
- **Default model:** `Qwen/Qwen3-Embedding-0.6B` (non-gated, works on CPU or GPU)
- **Best-documented client today:** Claude Code via MCP

## Quick Start

Five steps from zero to working code search:

1. **Install prerequisites** (Python 3.12+, uv, git)
2. **Run the installer** (one command)
3. **Register the MCP server** (run this in your terminal, not inside Claude)
4. **Verify** (`claude mcp list`)
5. **Use it** ("index this codebase" inside Claude Code)

## 1. Prerequisites

You need three things: **Python 3.12+**, **uv**, and **git**.

### Automatic setup (recommended)

Run the prerequisite script for your OS. It checks what you already have and
only offers to install what's missing — nothing happens without your approval.

**macOS / Linux / WSL:**

```bash
curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/prereqs.sh | bash
```

**Windows PowerShell:**

```powershell
irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/prereqs.ps1 | iex
```

If PowerShell blocks script execution:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/prereqs.ps1 | iex"
```

The script will tell you when everything is ready and print the next step.

### Manual setup (if you prefer)

<details>
<summary>Click to expand manual install instructions</summary>

#### Python 3.12+

Check: `python --version` — if you see 3.12 or higher, you're set.

| Platform | How to install |
|----------|---------------|
| **Windows** | `winget install -e --id Python.Python.3.13` or download from https://www.python.org/downloads/ (check **"Add python.exe to PATH"** during install) |
| **macOS** | `brew install python@3.13` ([install Homebrew](https://brew.sh) first if needed) or download from https://www.python.org/downloads/ |
| **Ubuntu/Debian** | `sudo apt install python3 python3-venv` |
| **Fedora** | `sudo dnf install python3` |

#### uv (Python package manager)

This project uses [uv](https://docs.astral.sh/uv/) instead of pip. It's fast
and handles everything automatically. No admin/sudo required.

```bash
# macOS / Linux / WSL
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal after installing so the `uv` command is available.

#### git

Check: `git --version`

| Platform | How to install |
|----------|---------------|
| **Windows** | `winget install --id Git.Git -e --source winget` or download from https://git-scm.com/downloads/win |
| **macOS** | `xcode-select --install` (includes git) or `brew install git` |
| **Ubuntu/Debian** | `sudo apt install git` |
| **Fedora** | `sudo dnf install git` |

#### Verify everything

```bash
python --version    # 3.12+
uv --version        # any version
git --version       # any version
```

</details>

## 2. Install

The default model (`Qwen/Qwen3-Embedding-0.6B`) is **not gated** — no
HuggingFace account or token needed. Just run the installer.

Review the scripts first if you want:
[`scripts/install.sh`](https://github.com/tlines2016/agent-context-code/blob/main/scripts/install.sh)
and
[`scripts/install.ps1`](https://github.com/tlines2016/agent-context-code/blob/main/scripts/install.ps1)

### macOS / Linux / Git Bash

```bash
curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.sh | bash
```

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.ps1 | iex
```

If PowerShell blocks script execution:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.ps1 | iex"
```

### Windows `cmd.exe`

```bat
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.ps1 | iex"
```

### WSL2

```bash
curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.sh | bash
```

If Claude Desktop or Claude Code runs on the Windows side, you may still want
to register the MCP server from a Windows terminal afterward.

### Choosing a different model

To use a higher-end model (e.g. for GPU), set `CODE_SEARCH_MODEL` before install:

```bash
export CODE_SEARCH_MODEL="unsloth/Qwen3-Embedding-4B"
curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.sh | bash
```

```powershell
$env:CODE_SEARCH_MODEL="unsloth/Qwen3-Embedding-4B"
irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.ps1 | iex
```

Other options:

- `Qwen/Qwen3-Embedding-0.6B`: default, non-gated, CPU-friendly
- `unsloth/Qwen3-Embedding-4B`: higher quality, needs GPU with ~8 GB VRAM
- `google/embeddinggemma-300m`: legacy default (gated — requires HF auth, see [Advanced: Using Gated Models](#advanced-using-gated-models))
- `Salesforce/SFR-Embedding-Code-400M_R`: code-search-focused alternative

The selected model is persisted to `~/.claude_code_search/install_config.json`.

## 3. Register The MCP Server

> **Important:** Run this command in your terminal, outside any Claude Code
> session. Once registered, the tools are available inside Claude automatically.

### macOS / Linux / Git Bash / WSL

```bash
claude mcp add code-search --scope user -- uv run --directory ~/.local/share/agent-context-code python mcp_server/server.py
```

### Windows PowerShell

```powershell
claude mcp add code-search --scope user -- uv run --directory "$env:LOCALAPPDATA\agent-context-code" python mcp_server/server.py
```

## 4. Verify The Install

```bash
claude mcp list
```

You should see `code-search` listed as connected. You can also run diagnostics:

### macOS / Linux / Git Bash / WSL

```bash
uv run --directory ~/.local/share/agent-context-code python scripts/cli.py doctor
```

### Windows PowerShell

```powershell
uv run --directory "$env:LOCALAPPDATA\agent-context-code" python scripts/cli.py doctor
```

## 5. Use It

Open Claude Code in your project and say:

```text
index this codebase
```

Then try questions like:

```text
search for authentication logic
```

## CLI vs MCP Tools

There are two ways to interact with AGENT Context Local:

- **CLI** (`python scripts/cli.py`) — terminal commands for setup and
  diagnostics. Run these in your terminal directly.
  Examples: `doctor`, `setup-guide`, `models list`, `mcp-check`

- **MCP tools** — used inside Claude Code sessions for indexing and searching.
  These are available automatically after MCP registration.
  Examples: `index_directory`, `search_code`, `get_index_status`

## Recommended: Add to Your Project

Help Claude (and other agents) discover and use code search automatically by
adding a snippet to your project's instruction file.

### For CLAUDE.md (Claude Code reads this automatically)

```markdown
## Code Search

This project has a local semantic code index via AGENT Context Local.
When exploring the codebase or looking for code by meaning, use the
`search_code` MCP tool instead of grep/find. Examples:
- "search for authentication logic"
- "find error handling patterns"
- "where is the database connection configured?"

If the index seems stale, run `index_directory` to refresh it.
Use `get_index_status` to check index health and model info.
```

### For agents.md (other MCP-aware agents)

Same content as above — `agents.md` is read by other agent frameworks that
support MCP.

## If Model Download Failed

The installer treats software install and model readiness as separate states.
Repo install can succeed even if model download needs fixing.

Retry model download directly:

### macOS / Linux / Git Bash / WSL

```bash
uv run --directory ~/.local/share/agent-context-code python scripts/download_model_standalone.py --storage-dir ~/.claude_code_search --model "Qwen/Qwen3-Embedding-0.6B" -v
```

### Windows PowerShell

```powershell
uv run --directory "$env:LOCALAPPDATA\agent-context-code" python scripts/download_model_standalone.py --storage-dir "$env:USERPROFILE\.claude_code_search" --model "Qwen/Qwen3-Embedding-0.6B" -v
```

## Storage Layout

```text
~/.claude_code_search/
├── models/
├── install_config.json
└── projects/
    └── {project_name}_{hash}/
        ├── project_info.json
        ├── index/
        │   ├── lancedb/
        │   │   └── code_chunks.lance/
        │   └── stats.json
        └── snapshots/
```

The indexed workspace should stay clean. Database files belong in the central
storage directory, not inside the project being indexed.

## Optional: Two-Stage Reranker

For higher precision, you can enable an optional Qwen3-Reranker-4B that
re-scores vector search candidates. This is a two-stage pipeline:

1. **Recall:** Vector search returns top-N candidates (N=50 default)
2. **Rerank:** Qwen3-Reranker-4B scores each (query, passage) pair
3. **Return:** Top-K reranked results

### Install the reranker model

```bash
python scripts/cli.py models install qwen-reranker-4b
```

Or during initial install, set the profile:

```bash
export CODE_SEARCH_PROFILE=reranker
# then run the installer
```

### Enable/disable

```bash
python scripts/cli.py config reranker on
python scripts/cli.py config reranker off
```

### Requirements

- ~8 GB VRAM on GPU, or CPU with higher latency (30-60s for 50 passages)
- Dual model (embedding 4B + reranker 4B) needs ~16 GB VRAM total
- The reranker is fully optional — search works without it

## AMD GPU Support (ROCm)

AMD GPUs are supported through PyTorch's ROCm build. When ROCm is installed,
`torch.cuda.is_available()` returns `True` and the existing device detection
works automatically — no code changes needed.

### Install PyTorch with ROCm support

```bash
pip install torch --index-url https://download.pytorch.org/whl/rocm7.1
```

Or with uv:

```bash
uv pip install torch --index-url https://download.pytorch.org/whl/rocm7.1
```

> **Note:** ROCm 6.2+ is the minimum for AMD Strix Halo APUs (Ryzen AI Max
> series). For other AMD GPUs, ROCm 7.x is recommended. The integrated GPU
> on APUs shares system memory, so VRAM limits depend on your system RAM
> allocation.

After installing, verify with `python scripts/cli.py doctor` — it will report
your GPU type (NVIDIA CUDA / AMD ROCm / Apple MPS / CPU).

## Advanced: Using Gated Models

The legacy default model (`google/embeddinggemma-300m`) is **gated** on
HuggingFace. If you explicitly choose it via `CODE_SEARCH_MODEL`, you must
set up HuggingFace authentication first.

### Gated model setup

1. Create a HuggingFace account at https://huggingface.co/join
2. Visit https://huggingface.co/google/embeddinggemma-300m and click
   **"Agree and access repository"** to accept Google's Gemma license.
   Access is granted immediately — no manual review.
3. Create an access token at https://huggingface.co/settings/tokens

### Authenticate

**Option A — huggingface-cli (bundled with this project, recommended):**

```bash
uv run huggingface-cli login
```

Paste your token when prompted. This saves it to `~/.cache/huggingface/token`.

**Option B — Environment variable:**

```bash
export HF_TOKEN="hf_your_token_here"
```

```powershell
$env:HF_TOKEN="hf_your_token_here"
```

**Option C — Standalone hf CLI:**

```bash
# Install (macOS/Linux)
curl -LsSf https://hf.co/cli/install.sh | bash

# Or on Windows PowerShell
powershell -c "irm https://hf.co/cli/install.ps1 | iex"

# Then
hf auth login
hf auth whoami
```

If you switch shells after logging in, the token may not be visible there.
Set `HF_TOKEN` in the same shell that runs the installer. The project also
accepts `HUGGING_FACE_HUB_TOKEN`.

## Diagnostics

Useful repo-local commands:

- `python scripts/cli.py help`
- `python scripts/cli.py doctor`
- `python scripts/cli.py setup-guide`
- `python scripts/cli.py troubleshoot` — HuggingFace auth & model download help
- `python scripts/cli.py status`
- `python scripts/cli.py paths`
- `python scripts/cli.py mcp-check` — verify MCP server registration

### Model management

- `python scripts/cli.py models list` — list all available embedding and reranker models
- `python scripts/cli.py models active` — show currently configured models
- `python scripts/cli.py models install <short-name>` — download a model by short name
- `python scripts/cli.py config reranker <on|off>` — toggle reranker

If you installed with the one-liner and want to run these from anywhere, use
`uv run --directory ~/.local/share/agent-context-code ...` on macOS/Linux/WSL
or `uv run --directory "$env:LOCALAPPDATA\agent-context-code" ...` on
PowerShell.

## Troubleshooting

Run `python scripts/cli.py troubleshoot` for interactive guidance.

### Common errors

| Error | Fix |
|-------|-----|
| `401` / Access denied | Only applies to gated models — see [Advanced: Using Gated Models](#advanced-using-gated-models) |
| Token not found | Run `uv run huggingface-cli login` or set `HF_TOKEN` env var |
| Token exists but download fails | Export `HF_TOKEN` in the same shell running the installer |
| Download incomplete / timeout | Check disk space (~1-2 GB needed) and network connection |
| Import errors after install | Run `uv sync` in the project directory |
| `claude mcp list` missing `code-search` | Remove and re-add the MCP server entry |
| No search results | Re-index the project; check with `python scripts/cli.py status` |

### WSL2 notes

- **HuggingFace tokens:** Windows-cached tokens are NOT visible inside WSL.
  Set `HF_TOKEN` explicitly in your WSL shell.
- **MCP registration:** If Claude Desktop runs on the Windows side, register
  the MCP server from a Windows terminal, or use `claude.exe` from WSL
  (note the `.exe` suffix).

### WSL2 + Windows filesystem interop

WSL2 instances (including those installed via the Microsoft Store) have full
access to the Windows filesystem and can run Windows executables directly.
This is useful when tools are installed on one side but configured from the other.

- Access Windows files: `ls /mnt/c/Users/$USER/`
- Run Windows commands: `cmd.exe /c dir`
- Call Windows binaries: `docker.exe ps`

For example, if your agent CLI (Codex, Claude Code, etc.) is installed in WSL2
but Docker Desktop is a Windows Store app, you can still configure MCP servers
that call Windows executables:

```toml
[mcp_servers.MCP_DOCKER]
command = "docker.exe"
args = ["mcp", "gateway", "run"]
```

The `.exe` suffix is required when calling Windows binaries from WSL.
Similarly, `claude.exe` works from WSL if the Claude CLI was installed on
the Windows side.

## Supported Languages

The chunker currently supports 22 extensions across:

- Python
- JavaScript and TypeScript
- Java and Kotlin
- Go and Rust
- C, C++, and C#
- Svelte
- Markdown
- YAML, TOML, and JSON

## Repository

Canonical public repo:
[tlines2016/agent-context-code](https://github.com/tlines2016/agent-context-code)

## Acknowledgements

This project was originally inspired by and built upon the foundational concepts of claude-context-local by [Author Name]. It has since been heavily modified and expanded into a standalone tool to support agent-agnostic workflows, dedicated vector databases, reranking, and local embedding models.
