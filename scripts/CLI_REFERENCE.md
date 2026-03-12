# CLI Reference — AGENT Context Local

All CLI commands are available through three invocation styles depending on your setup.

## How to Run Commands

### Source install (dev / local clone — not yet published)
```powershell
# Windows PowerShell
uv run python scripts/cli.py <command>
```
```bash
# macOS / Linux / WSL
uv run python scripts/cli.py <command>
```

### Installed via installer script (git clone to default location)
```powershell
# Windows PowerShell
uv run --directory "$env:LOCALAPPDATA\agent-context-code" python scripts/cli.py <command>
```
```bash
# macOS / Linux / WSL
uv run --directory ~/.local/share/agent-context-code python scripts/cli.py <command>
```

### Installed via PyPI (`uv tool install` / `pipx install`)
```bash
agent-context-local <command>
```

---

The examples below use `python scripts/cli.py` (source install style). Substitute the
appropriate prefix for your setup.

---

## Diagnostics & Setup

### `doctor`
Check installation health — Python version, dependencies, storage, model status, GPU, MCP registration.
```powershell
uv run python scripts/cli.py doctor
```

### `version`
Print version and platform info.
```powershell
uv run python scripts/cli.py version
```

### `status`
Show all indexed projects, chunk counts, and file counts.
```powershell
uv run python scripts/cli.py status
```

### `paths`
Print all storage and install paths used by the tool.
```powershell
uv run python scripts/cli.py paths
```

### `setup-guide`
Print step-by-step setup instructions tailored to your OS (install, MCP registration, verify, first use).
```powershell
uv run python scripts/cli.py setup-guide
```

### `setup-mcp`
Print MCP registration instructions for all supported clients (Claude Code, Cursor, Codex CLI, Gemini CLI, Cline, Roo, etc.).
```powershell
# List all supported clients
uv run python scripts/cli.py setup-mcp

# Instructions for a specific client
uv run python scripts/cli.py setup-mcp claude-code
uv run python scripts/cli.py setup-mcp cursor
uv run python scripts/cli.py setup-mcp copilot-cli
uv run python scripts/cli.py setup-mcp gemini-cli
uv run python scripts/cli.py setup-mcp codex-cli
uv run python scripts/cli.py setup-mcp opencode
uv run python scripts/cli.py setup-mcp cline
uv run python scripts/cli.py setup-mcp roo-code
```

### `mcp-check`
Verify MCP server registration via the Claude CLI.
```powershell
uv run python scripts/cli.py mcp-check
```

### `troubleshoot`
Interactive guidance for HuggingFace auth issues and model download failures.
```powershell
uv run python scripts/cli.py troubleshoot
```

### `gpu-setup`
Detect GPU (NVIDIA CUDA / AMD ROCm / Apple MPS) and install the matching PyTorch build.
After this runs, the embedder automatically uses GPU — no other config needed.
```powershell
uv run python scripts/cli.py gpu-setup
```

---

## Model Management

### `models list`
List all available embedding and reranker models with short names, dimensions, and descriptions.
```powershell
uv run python scripts/cli.py models list
```

### `models active`
Show the currently configured embedding model and reranker (with enabled/disabled state).
```powershell
uv run python scripts/cli.py models active
```

### `models install <short-name>`
Download a model by its short name into `~/.agent_code_search/models/`.

**Embedding models:**
```powershell
uv run python scripts/cli.py models install mxbai-xsmall      # Default — 22.7M, CPU-optimised
uv run python scripts/cli.py models install qwen-embed-0.6b   # 600M, 1024-dim, higher quality CPU
uv run python scripts/cli.py models install qwen-embed-4b     # GPU — ~8 GB VRAM
uv run python scripts/cli.py models install qwen-embed-8b     # GPU — ~18 GB VRAM
uv run python scripts/cli.py models install sfr-code-400m     # Code-search-focused alternative
```

**Reranker models:**
```powershell
uv run python scripts/cli.py models install minilm-reranker     # Default — 22.7M, CPU-friendly
uv run python scripts/cli.py models install qwen-reranker-0.6b  # GPU — ~2 GB VRAM, 32K context
uv run python scripts/cli.py models install bge-reranker-m3     # GPU — multilingual
uv run python scripts/cli.py models install qwen-reranker-4b    # GPU — max quality, ~10 GB VRAM
```

---

## Configuration

### `config model <short-name>`
Switch the active embedding model (persisted to `install_config.json`).
Download the model first with `models install`, then switch.
```powershell
uv run python scripts/cli.py config model mxbai-xsmall
uv run python scripts/cli.py config model qwen-embed-0.6b
uv run python scripts/cli.py config model qwen-embed-4b
```
> Restart the MCP server for the change to take effect.

### `config reranker on|off`
Enable or disable the reranker. Uses the currently configured reranker model (defaults to `minilm-reranker` on first enable).
```powershell
uv run python scripts/cli.py config reranker on
uv run python scripts/cli.py config reranker off
```

### `config reranker model <short-name>`
Switch the reranker model without changing its enabled/disabled state.
Download the model first with `models install`, then switch.
```powershell
uv run python scripts/cli.py config reranker model minilm-reranker
uv run python scripts/cli.py config reranker model qwen-reranker-0.6b
uv run python scripts/cli.py config reranker model bge-reranker-m3
uv run python scripts/cli.py config reranker model qwen-reranker-4b
```
> Restart the MCP server for the change to take effect.

---

## Common Workflows

### Fresh install + verify
```powershell
# Run the installer (uses default model: mxbai-embed-xsmall-v1)
irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.ps1 | iex

# Register MCP server (Claude Code)
claude mcp add code-search --scope user -- uv run --directory "$env:LOCALAPPDATA\agent-context-code" python mcp_server/server.py

# Verify everything
uv run --directory "$env:LOCALAPPDATA\agent-context-code" python scripts/cli.py doctor
```

### Install with a specific embedding model
```powershell
$env:CODE_SEARCH_MODEL="Qwen/Qwen3-Embedding-0.6B"
irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.ps1 | iex
```

### Switch embedding model after install
```powershell
uv run python scripts/cli.py models install qwen-embed-0.6b
uv run python scripts/cli.py config model qwen-embed-0.6b
# Restart MCP server
```

### Enable reranker (CPU default)
```powershell
uv run python scripts/cli.py models install minilm-reranker
uv run python scripts/cli.py config reranker on
```

### Enable reranker with GPU model (RTX 5080 / high VRAM)
```powershell
uv run python scripts/cli.py models install qwen-reranker-0.6b
uv run python scripts/cli.py config reranker on
uv run python scripts/cli.py config reranker model qwen-reranker-0.6b
```

### Enable GPU acceleration
```powershell
uv run python scripts/cli.py gpu-setup
# Restart MCP server — embedder auto-detects CUDA/ROCm/MPS
```

### Re-download a model after a failed install
```powershell
# macOS / Linux / WSL
uv run --directory ~/.local/share/agent-context-code python scripts/download_model_standalone.py \
  --storage-dir ~/.agent_code_search \
  --model "mixedbread-ai/mxbai-embed-xsmall-v1" -v

# Windows PowerShell
uv run --directory "$env:LOCALAPPDATA\agent-context-code" python scripts/download_model_standalone.py `
  --storage-dir "$env:USERPROFILE\.agent_code_search" `
  --model "mixedbread-ai/mxbai-embed-xsmall-v1" -v
```

### Full recommended setup (GPU machine, RTX 5080)
```powershell
# 1. Install with Qwen 0.6B embedding (better quality than default on GPU)
$env:CODE_SEARCH_MODEL="Qwen/Qwen3-Embedding-0.6B"
irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.ps1 | iex

# 2. Enable GPU
uv run --directory "$env:LOCALAPPDATA\agent-context-code" python scripts/cli.py gpu-setup

# 3. Download and enable Qwen reranker
uv run --directory "$env:LOCALAPPDATA\agent-context-code" python scripts/cli.py models install qwen-reranker-0.6b
uv run --directory "$env:LOCALAPPDATA\agent-context-code" python scripts/cli.py config reranker on
uv run --directory "$env:LOCALAPPDATA\agent-context-code" python scripts/cli.py config reranker model qwen-reranker-0.6b

# 4. Register MCP and verify
claude mcp add code-search --scope user -- uv run --directory "$env:LOCALAPPDATA\agent-context-code" python mcp_server/server.py
uv run --directory "$env:LOCALAPPDATA\agent-context-code" python scripts/cli.py doctor
```

### Uninstall
```powershell
# Windows PowerShell
irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/uninstall.ps1 | iex

# macOS / Linux / WSL
curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/uninstall.sh | bash -s -- --force
```

---

## Model Quick Reference

### Embedding Models

| Short name | Model | Params | Dim | GPU req | Notes |
|---|---|---|---|---|---|
| `mxbai-xsmall` | mixedbread-ai/mxbai-embed-xsmall-v1 | 22.7M | 384 | No | **Default** — fastest CPU indexing |
| `qwen-embed-0.6b` | Qwen/Qwen3-Embedding-0.6B | 600M | 1024 | No | Higher quality, slower on CPU |
| `qwen-embed-4b` | unsloth/Qwen3-Embedding-4B | 4B | 2560 | ~8 GB VRAM | GPU high-quality |
| `qwen-embed-8b` | unsloth/Qwen3-Embedding-8B | 8B | 4096 | ~18 GB VRAM | Top MTEB quality |
| `sfr-code-400m` | Salesforce/SFR-Embedding-Code-400M_R | 400M | — | No | Code-search focused |
| `gemma-300m` | google/embeddinggemma-300m | 300M | 768 | No | Legacy — gated (HF auth required) |

### Reranker Models

| Short name | Model | Params | GPU req | Notes |
|---|---|---|---|---|
| `minilm-reranker` | cross-encoder/ms-marco-MiniLM-L-6-v2 | 22.7M | No | **Default** — ~90 MB RAM, ~200ms/50 passages |
| `qwen-reranker-0.6b` | Qwen/Qwen3-Reranker-0.6B | 600M | ~2 GB VRAM | 32K context, pairs with Qwen embedder |
| `bge-reranker-m3` | BAAI/bge-reranker-v2-m3 | ~600M | ~2 GB VRAM | Multilingual codebases |
| `qwen-reranker-4b` | Qwen/Qwen3-Reranker-4B | 4B | ~10 GB VRAM | Maximum quality |
