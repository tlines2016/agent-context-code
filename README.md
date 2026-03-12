```text
         __| |____________________________________________________________| |__
         __   ____________________________________________________________   __
           | |                                                            | |  
           | |         ___                    __                          | |  
           | |        /   | ____ ____  ____  / /_                         | |  
           | |       / /| |/ __ `/ _ \/ __ \/ __/                         | |  
           | |      / ___ / /_/ /  __/ / / / /_                           | |  
           | |     /_/  |_\__, /\___/_/ /_/\__/                           | |  
           | |           /____/                                           | |  
           | |               ______            __            __           | |  
           | |              / ____/___  ____  / /____  _  __/ /_          | |  
           | |             / /   / __ \/ __ \/ __/ _ \| |/_/ __/          | |  
           | |            / /___/ /_/ / / / / /_/  __/>  </ /_            | |  
           | |            \____/\____/_/ /_/\__/\___/_/|_|\__/            | |  
           | |                              __                     __     | |  
           | |                             / /   ____  _________ _/ /     | |  
           | |                            / /   / __ \/ ___/ __ `/ /      | |  
           | |                           / /___/ /_/ / /__/ /_/ / /       | |  
           | |                          /_____/\____/\___/\__,_/_/        | |  
         __| |____________________________________________________________| |__
         __   ____________________________________________________________   __
           | |                                                            | |  
```

AGENT Context Local is a local MCP code-search service that helps agents find
the right code by meaning instead of exact strings. Your embeddings, vector
index, and project metadata stay on your machine.

The canonical repository is
[tlines2016/agent-context-code](https://github.com/tlines2016/agent-context-code).

## Why This Exists

Coding agents are great at reasoning but tend to struggle when they need to find
something specific in a large codebase — they burn through context or fall back
to grep. This project gives them a local semantic search layer so they can look
things up by meaning, not just by filename or string match.

- **Search by intent** — ask for `where do we validate auth tokens?` instead of guessing filenames.
- **Everything stays local** — your source code never leaves your machine. No hosted services, no uploads.
- **Persistent index** — the index survives across sessions, so you don't have to re-explain your repo every time.
- **Agent-agnostic** — built on MCP, so any compatible agent client can use it (Claude Code is the best-tested today).

## What It Uses Today

| Component | Details |
|-----------|---------|
| **Vector database** | LanceDB (embedded, serverless — like SQLite for vectors) |
| **Relational graph** | SQLite (structural relationships: containment + cross-file inheritance today; calls/imports are planned) |
| **Search** | Hybrid (BM25 keyword + vector similarity), automatically enabled |
| **Storage** | `~/.claude_code_search` (or `CODE_SEARCH_STORAGE` env var) |
| **Per-project index** | `~/.claude_code_search/projects/{name}_{hash}` |
| **Chunking** | Python AST, tree-sitter, and structured config parsing |
| **Change detection** | Merkle DAG (content hashes — only changed files are re-indexed) |
| **Default embedding model** | `Qwen/Qwen3-Embedding-0.6B` (non-gated, runs on CPU or GPU) |
| **Default reranker** | `cross-encoder/ms-marco-MiniLM-L-6-v2` (22.7M, opt-in) |
| **Primary client** | Claude Code via MCP |

## System Requirements

The default setup is designed to run on any modern laptop or desktop — no GPU
required. If you have a GPU, larger models are available for higher quality.

### Minimum (CPU-only, default install)

| Resource | Requirement |
|----------|-------------|
| **CPU** | Any x86_64 or ARM64 (Apple Silicon, etc.) |
| **RAM** | 4 GB free (embedding model uses ~1.2 GB) |
| **Disk** | ~2 GB free (model files + index storage) |
| **GPU** | Not required |
| **Python** | 3.12+ |
| **OS** | Windows 10+, macOS 12+, Linux (glibc 2.31+) |

### Recommended configurations

| Setup | Embedding Model | Reranker (optional) | RAM / VRAM | Quality |
|-------|----------------|---------------------|------------|---------|
| **Default** | Qwen3-Embedding-0.6B (1024-d) | — | ~1.2 GB RAM | Good — runs on any modern PC |
| **Default + reranker** | Qwen3-Embedding-0.6B (1024-d) | MiniLM-L-6-v2 (22.7M) | ~1.5 GB RAM | Better — adds precision for ~90 MB extra |
| **GPU starter** | Qwen3-Embedding-0.6B (1024-d) | Qwen3-Reranker-0.6B | ~4 GB VRAM | High — Qwen 0.6B pair, great entry GPU setup |
| **GPU mid-tier** | Qwen3-Embedding-4B (2560-d) | Qwen3-Reranker-0.6B | ~10 GB VRAM | Higher — bigger embeddings, same fast reranker |
| **GPU high-end** | Qwen3-Embedding-8B (4096-d) | Qwen3-Reranker-4B | ~28 GB VRAM | Maximum — top MTEB scores |

The **Default** setup works out of the box on any modern PC — no GPU needed, no
extra configuration. Hybrid search (BM25 keyword matching + vector similarity) is
always enabled automatically.

**Reranking is optional** and adds a second-pass quality boost. Enable it anytime
with `python scripts/cli.py config reranker on`. You can choose any reranker model
independently from your embedding model — see
[Optional: Two-Stage Reranker](#optional-two-stage-reranker) for the full list.

## How It Works

Traditional code search (grep, ripgrep, `Ctrl+F`) matches exact strings. That
works when you know the variable name or error message, but falls short when
you're looking for *concepts* — "where does the app handle retries?" won't match
`except ConnectionError: time.sleep(backoff)`.

AGENT Context Local bridges that gap with **hybrid search** — combining keyword
matching with semantic understanding:

1. **Chunk** — your source files are split into meaningful pieces (functions,
   classes, config blocks) using language-aware parsers (tree-sitter AST), not
   arbitrary line counts.
2. **Graph** — structural relationships extracted from the AST chunks (class
   hierarchies, method containment, cross-file inheritance) are stored in a
   SQLite relational graph. This lets you navigate from a search result to its
   parent/child symbols and inherited classes via `get_graph_context` today.
3. **Embed** — each chunk is passed through a local embedding model that converts
   the code into a high-dimensional vector capturing its semantic meaning.
4. **Index** — the vectors are stored in a LanceDB table alongside the original
   code and metadata (file path, line numbers, chunk type, etc.). A full-text
   search (FTS) index is also built for BM25 keyword matching.
5. **Search** — when you ask a question, two searches run in parallel:
   - **BM25 keyword search** finds chunks containing your exact terms
   - **Vector similarity search** finds chunks with related *meaning*
   - Results are combined via **Reciprocal Rank Fusion (RRF)** for the best of both
6. **Rerank** (optional) — a lightweight cross-encoder re-scores the top
   candidates for even more precise ranking.

This hybrid approach significantly improves retrieval quality over vector-only search.
The embedding model runs locally (no API calls), and LanceDB writes directly to
disk with no server process, so the whole pipeline has minimal overhead.

The index is also **incremental**: a Merkle DAG (directed acyclic graph of file
content hashes) tracks exactly which files changed between runs, so re-indexing
only processes files that actually changed. Combined with automatic **compaction**
(which cleans up old versions and deleted data), the index stays lean over time
without any manual maintenance.

### Graph Retrieval Policy

To keep agent responses both accurate and fast, the project uses a two-tier graph
policy:

- Graph indexing is **always on** during indexing runs, so structural context is
  consistently available per project.
- `search_code` can include lightweight relationship hints for top results.
- `get_graph_context` remains the dedicated deep-traversal tool when an agent
  needs richer structural neighborhoods around a specific chunk.

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

If you have a GPU and want higher-quality embeddings, you can pick a different
model by setting `CODE_SEARCH_MODEL` before running the installer:

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
- `unsloth/Qwen3-Embedding-8B`: top MTEB multilingual quality, needs GPU with ~18 GB VRAM
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

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `index_directory("/path")` | Index a project (incremental by default) |
| `search_code("query")` | Hybrid semantic + keyword search |
| `find_similar_code(chunk_id)` | Find code similar to a known chunk |
| `get_graph_context(chunk_id)` | Navigate structural relationships (contains/inherits today; other edge types when available) |
| `get_index_status` | Index statistics, model info, graph stats |
| `list_projects` | List all indexed projects |
| `switch_project("/path")` | Change the active project |
| `clear_index` | Clear the vector index and relational graph |
| `index_test_project` | Index the built-in sample project |

## Recommended: Add to Your Project

You can help Claude (and other agents) automatically discover and use code
search by dropping a short snippet into your project's instruction file.

### For CLAUDE.md (Claude Code reads this automatically)

```markdown
## Code Search

This project has a local semantic code index via AGENT Context Local.
When exploring the codebase or looking for code by meaning, use the
`search_code` MCP tool instead of grep/find. Examples:
- "search for authentication logic"
- "find error handling patterns"
- "where is the database connection configured?"

To explore how a specific function connects to the rest of the codebase
(parent classes, containment, and additional edge types when available), use `get_graph_context(chunk_id)` with
a chunk_id from a `search_code` result.

If the index seems stale, run `index_directory` to refresh it.
Use `get_index_status` to check index health and model info.
```

### For agents.md (other MCP-aware agents)

Same content as above — `agents.md` is read by other agent frameworks that
support MCP.

## If Model Download Failed

Don't worry — the installer separates software installation from model download.
Your install is fine; the model just needs another try.

To retry the model download:

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
~/.claude_code_search/          # 0700 on Unix/macOS (owner-only access)
├── models/
├── install_config.json
└── projects/
    └── {project_name}_{hash}/
        ├── project_info.json
        ├── index/
        │   ├── lancedb/
        │   │   └── code_chunks.lance/   # vector + FTS index
        │   ├── code_graph.db            # SQLite relational graph
        │   └── stats.json
        └── snapshots/                   # Merkle DAG snapshots for change detection
```

Your project workspace stays clean — all database files live in this central
directory, never inside the project being indexed.

On Unix and macOS the storage directory is locked down to your user (`0700`
permissions) so other accounts on a shared machine can't read your indexed
source. On Windows the default ACLs already handle this.

### Index Maintenance

You shouldn't need to think about this, but it's here if you're curious.
Each time you add, modify, or delete files, LanceDB creates new internal
fragments and version snapshots. The indexer automatically compacts these
after each session — cleaning up old versions (keeping one day of history)
and reclaiming disk space. The SQLite relational graph (`code_graph.db`) is
also kept in sync: modified or deleted files have their symbols and edges
removed before the updated chunks are re-inserted. If you ever want to check
how things look, run `get_index_status` to see the current storage size,
version count, and graph statistics.

## Optional: Two-Stage Reranker

If you want even more precise results, you can turn on a second-pass reranker.
It works like this: vector search first pulls back a broad set of candidates,
then a reranker model reads each candidate against your query and re-scores
them for relevance.

1. **Recall** — vector/hybrid search returns the top 50 candidates
2. **Rerank** — the reranker reads each (query, passage) pair and re-scores
3. **Return** — the best results after reranking

### Available reranker models

| Model | Size | Best for | Requirements |
|-------|------|----------|-------------|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | 22.7M | **Default** — fast CPU reranking | ~90 MB RAM, ~200ms for 50 passages |
| `Qwen/Qwen3-Reranker-0.6B` | 0.6B | GPU mid-tier, 32K context | ~2 GB VRAM |
| `BAAI/bge-reranker-v2-m3` | ~600M | Multilingual codebases | ~2 GB VRAM |
| `Qwen/Qwen3-Reranker-4B` | 4B | Maximum quality | ~10 GB VRAM |

### Install the reranker model

```bash
python scripts/cli.py models install minilm-reranker
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

- The default reranker (`ms-marco-MiniLM-L-6-v2`) runs on CPU with negligible overhead
- Larger rerankers (0.6B+) need a GPU for acceptable latency
- The reranker is entirely optional — search works great without it

## AMD GPU Support (ROCm)

If you have an AMD GPU, it should work out of the box once you install the
ROCm build of PyTorch. The existing device detection picks it up automatically —
no configuration needed on our side.

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

## Uninstall

To completely remove AGENT Context Local (app files, indexes, models, and MCP
registration), run the uninstall script. Shared tools (uv, Python, git) are
**not** removed.

Review the scripts first if you want:
[`scripts/uninstall.sh`](https://github.com/tlines2016/agent-context-code/blob/main/scripts/uninstall.sh)
and
[`scripts/uninstall.ps1`](https://github.com/tlines2016/agent-context-code/blob/main/scripts/uninstall.ps1)

### macOS / Linux / Git Bash / WSL

```bash
curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/uninstall.sh | bash -s -- --force
```

Or if you have a local clone (interactive — will prompt for confirmation):

```bash
./scripts/uninstall.sh
```

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/uninstall.ps1 | iex
```

Or if you have a local clone:

```powershell
.\scripts\uninstall.ps1
```

### Options

| Flag / Parameter | Bash | PowerShell | Description |
|------------------|------|------------|-------------|
| Dry-run | `--dry-run` | `-WhatIf` | Preview what would be removed without deleting |
| Force | `--force` | `-Force` | Skip confirmation prompt |
| Skip MCP | `--skip-mcp-remove` | `-SkipMcpRemove` | Don't deregister the MCP server |
| Custom project dir | `--project-dir DIR` | `-ProjectDir DIR` | Override app checkout path |
| Custom storage dir | `--storage-dir DIR` | `-StorageDir DIR` | Override storage root path |

### What gets removed

- **App checkout**: `~/.local/share/agent-context-code` (Unix) or `%LOCALAPPDATA%\agent-context-code` (Windows)
- **Storage root**: `~/.claude_code_search` (or `CODE_SEARCH_STORAGE` override) — includes models, indexes, and config
- **MCP registration**: the `code-search` server entry

### What is NOT removed

- **uv**, **Python**, **git** — these are shared system tools
- Any project source code you indexed (only the index is removed, not your code)

## Repository

Canonical public repo:
[tlines2016/agent-context-code](https://github.com/tlines2016/agent-context-code)

## Acknowledgements

This project was originally inspired by the foundational concepts of
claude-context-local. It has since been significantly reworked into a standalone
tool supporting agent-agnostic workflows, a dedicated vector database, reranking,
and local embedding models.
