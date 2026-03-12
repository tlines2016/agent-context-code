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

![PyPI version](https://img.shields.io/pypi/v/agent-context-local)
![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)
![MCP Compatible](https://img.shields.io/badge/MCP-compatible-blueviolet.svg)

**Local semantic code search for AI coding assistants.**

AGENT Context Local is an MCP server that indexes your codebase using
tree-sitter AST-aware chunking and searches it with hybrid BM25 keyword +
vector similarity ranking, combined via Reciprocal Rank Fusion. Your AI
coding assistant can find code by meaning — "where do we validate auth
tokens?" — instead of relying on grep or burning context on file-by-file
exploration. Everything runs on your machine. No API keys, no uploads,
no hosted services.

The canonical repository is
[tlines2016/agent-context-code](https://github.com/tlines2016/agent-context-code).

## Key Features

- **Hybrid search** — BM25 keyword matching and vector similarity combined via Reciprocal Rank Fusion (RRF) for results that are both precise and semantically relevant.
- **AST-aware chunking** — Tree-sitter parses your code into functions, classes, and methods. No arbitrary line splits, no broken context.
- **100% local** — Embeddings generated on-device, LanceDB embedded database (think SQLite for vectors), zero API calls, zero uploads.
- **Incremental indexing** — A Merkle DAG tracks file-level content hashes. Only modified files get re-indexed, so re-indexing a large repo after a small change takes seconds.
- **Graph-enriched results** — Search results include structural context: class hierarchy, method containment, and cross-file inheritance.
- **23 file types** — Python, JS/TS, Go, Rust, Java, Kotlin, C/C++, C#, Svelte, Markdown, YAML, TOML, and JSON.
- **Optional reranking** — Two-stage retrieval with a cross-encoder second pass for higher-precision results when you need them.
- **Lightweight default model** — Ships with mxbai-embed-xsmall-v1 (22.7M params, 384-dim). Non-gated, CPU-optimised, no GPU required. Indexes large repos fast.

## Who Is This For?

- **Developers using AI coding assistants** — Give Claude, Copilot, Codex, or Gemini actual semantic understanding of your codebase instead of relying on file-tree context or text search.
- **Teams working in large codebases** — When grep and built-in search stop scaling, hybrid vector + keyword search over AST-parsed chunks finds what you actually need.
- **Privacy-conscious engineers** — If your code can't leave your machine — compliance, proprietary IP, air-gapped environments — this runs entirely local with no external dependencies.

## Supported Clients

Works with any tool that speaks [MCP](https://modelcontextprotocol.io/) (Model Context Protocol):

| Client | Notes |
|--------|-------|
| **Claude Code** | Built-in MCP support (best-tested) |
| **Cursor** | MCP server configuration |
| **Codex CLI** | MCP server configuration |
| **Gemini CLI** | MCP server configuration |
| **VS Code** — Copilot Chat | MCP extension support |
| **VS Code** — Cline / Roo | MCP server configuration |
| **VS Code** — Continue | MCP server configuration |

If your tool supports MCP, it can use AGENT Context Local.
See [docs/MCP_SETUP.md](docs/MCP_SETUP.md) for detailed per-tool setup instructions.

## Getting Started

From zero to working code search in five steps. All commands below run in
your **regular terminal** — not inside an AI assistant session.

> **Terminal basics:** On macOS, open **Terminal** (in Applications > Utilities).
> On Windows, open **PowerShell** or **Windows Terminal** (search for it in the
> Start menu). On Linux, open your preferred terminal emulator.
>
> Useful commands if you're new to the terminal:
> - `pwd` (macOS/Linux) or `cd` with no arguments (Windows) — print your current directory
> - `cd /path/to/folder` — change directory
> - `ls` (macOS/Linux) or `dir` (Windows) — list files in the current directory

### Quick Install (PyPI)

If you have Python 3.12+ and uv (or pipx) already installed, the fastest path:

```bash
# Install the package
uv tool install agent-context-local
# or: pipx install agent-context-local

# Register with Claude Code
claude mcp add code-search --scope user -- agent-context-local-mcp

# Verify
agent-context-local doctor
```

The PyPI install gives you two commands: `agent-context-local` (CLI) and
`agent-context-local-mcp` (MCP server). No git clone needed.

For other MCP clients (Cursor, Copilot, Gemini CLI, Codex, etc.), see
[docs/MCP_SETUP.md](docs/MCP_SETUP.md) for per-tool registration instructions.

<details>
<summary>Development / Source Install (git clone)</summary>

### Step 1: Prerequisites

You need three things: **Python 3.12+**, **uv** (Python package manager), and **git**.

**Automatic setup (recommended)** — run the script for your OS. It checks what you
already have and only offers to install what's missing.

macOS / Linux / WSL:

```bash
curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/prereqs.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/prereqs.ps1 | iex
```

If PowerShell blocks script execution:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/prereqs.ps1 | iex"
```

The script will tell you when everything is ready and print the next step.

<details>
<summary>Manual setup (if you prefer)</summary>

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

### Step 2: Install

The default model (`mixedbread-ai/mxbai-embed-xsmall-v1`) is **not gated** — no
HuggingFace account or token needed. Just run the installer.

You can review the scripts first if you want:
[`install.sh`](https://github.com/tlines2016/agent-context-code/blob/main/scripts/install.sh) /
[`install.ps1`](https://github.com/tlines2016/agent-context-code/blob/main/scripts/install.ps1)

macOS / Linux / Git Bash:

```bash
curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.ps1 | iex
```

If PowerShell blocks script execution:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.ps1 | iex"
```

Windows `cmd.exe`:

```bat
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.ps1 | iex"
```

WSL2:

```bash
curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.sh | bash
```

> **WSL2 note:** If Claude Desktop or Claude Code runs on the Windows side, you'll
> want to register the MCP server from a Windows terminal in Step 3.

### Step 3: Register the MCP Server

> **Important:** Run this command in your **regular terminal**, not inside Claude
> Code, Codex, or any other AI assistant session. When you type `claude` or `codex`
> in your terminal, it opens the assistant as an interactive session — you can't run
> shell setup commands from inside that session. Run the registration command below
> **first**, then open your assistant afterward.

**For Claude Code:**

macOS / Linux / Git Bash / WSL:

```bash
claude mcp add code-search --scope user -- uv run --directory ~/.local/share/agent-context-code python mcp_server/server.py
```

Windows PowerShell:

```powershell
claude mcp add code-search --scope user -- uv run --directory "$env:LOCALAPPDATA\agent-context-code" python mcp_server/server.py
```

**For other MCP clients** (Cursor, Codex CLI, Gemini CLI, VS Code extensions, etc.):

Use your client's MCP configuration format and point it at this server command:

```bash
# macOS / Linux / WSL
uv run --directory ~/.local/share/agent-context-code python mcp_server/server.py
```

```powershell
# Windows PowerShell
uv run --directory "$env:LOCALAPPDATA\agent-context-code" python mcp_server/server.py
```

Check your client's documentation for where to add MCP server entries. The server
command above is the same regardless of client — only the configuration format differs.

### Step 4: Verify

For Claude Code, check that the server is registered:

```bash
claude mcp list
```

You should see `code-search` in the list. You can also run diagnostics:

```bash
# macOS / Linux / Git Bash / WSL
uv run --directory ~/.local/share/agent-context-code python scripts/cli.py doctor
```

```powershell
# Windows PowerShell
uv run --directory "$env:LOCALAPPDATA\agent-context-code" python scripts/cli.py doctor
```

`doctor` checks your Python version, model status, storage paths, and MCP registration.

### Step 5: Use It

Open your AI coding assistant (e.g., type `claude` in your terminal) and navigate
to your project directory. Then tell the assistant:

```text
index this codebase
```

The first indexing run processes every file. Subsequent runs are incremental — only
changed files are re-indexed. Once indexed, try:

```text
search for authentication logic
```

```text
where is the database connection configured?
```

```text
find error handling patterns
```

The assistant uses the `search_code` MCP tool behind the scenes. You can also ask
it to `get_index_status` to check index health, or `clear_index` to start fresh.

</details>

## How It Works

Traditional code search (grep, ripgrep, `Ctrl+F`) matches exact strings. That
works when you know the variable name or error message, but falls short when
you're looking for *concepts* — "where does the app handle retries?" won't match
`except ConnectionError: time.sleep(backoff)`.

AGENT Context Local bridges that gap with **hybrid search** — combining keyword
matching with semantic understanding:

1. **Chunk** — source files are split into meaningful pieces (functions, classes,
   config blocks) using language-aware parsers (tree-sitter AST), not arbitrary
   line counts.
2. **Graph** — structural relationships extracted from the AST chunks (class
   hierarchies, method containment, cross-file inheritance) are stored in a
   SQLite relational graph for structural navigation.
3. **Embed** — each chunk is passed through a local embedding model that converts
   the code into a high-dimensional vector capturing its semantic meaning.
4. **Index** — vectors are stored in a LanceDB table alongside the original code
   and metadata (file path, line numbers, chunk type). A full-text search (FTS)
   index is also built for BM25 keyword matching.
5. **Search** — when you ask a question, two searches run in parallel:
   - **BM25 keyword search** finds chunks containing your exact terms
   - **Vector similarity search** finds chunks with related *meaning*
   - Results are combined via **Reciprocal Rank Fusion (RRF)** for the best of both
6. **Rerank** (optional) — a cross-encoder re-scores the top candidates for even
   more precise ranking.

The embedding model runs locally (no API calls), and LanceDB writes directly to
disk with no server process, so the whole pipeline has minimal overhead.

The index is also **incremental**: a Merkle DAG (directed acyclic graph of file
content hashes) tracks exactly which files changed between runs, so re-indexing
only processes what actually changed. Combined with automatic **compaction**
(which cleans up old versions and reclaims disk space), the index stays lean
over time without manual maintenance.

## Available MCP Tools

These tools are available inside your AI assistant session after MCP registration.

| Tool | Description |
|------|-------------|
| `index_directory("/path")` | Index a project (incremental by default) |
| `search_code("query")` | Hybrid semantic + keyword search with lightweight graph enrichment |
| `find_similar_code(chunk_id)` | Find code similar to a known chunk |
| `get_graph_context(chunk_id)` | Deep structural context: full neighborhood traversal up to `max_depth` |
| `get_index_status` | Index statistics, model info, and graph stats |
| `list_projects` | List all indexed projects |
| `switch_project("/path")` | Change the active project |
| `clear_index` | Clear the vector index and relational graph |
| `index_test_project` | Index the built-in sample project (useful for testing) |

**Typical workflow:** `index_directory` your project once, then use `search_code`
for queries. Use `get_index_status` to check health. If you need to explore the
structural neighborhood around a result (parent class, contained methods, inherited
members), pass the `chunk_id` to `get_graph_context`.

### Graph Retrieval Policy

The project uses a two-tier graph model to balance speed and depth:

- `search_code` **includes lightweight graph enrichment by default** — relationship
  hints are attached to results (bounded payload, no full expansion). This is enough
  for most searches.
- `get_graph_context` is the dedicated deep-traversal tool for when an agent needs
  the full structural neighborhood around a specific chunk (symbols + edges up to
  `max_depth`).

## Recommended: Add to Your Project

Help your AI assistant automatically discover and use code search by adding a
snippet to your project's instruction file.

### For CLAUDE.md (Claude Code reads this automatically)

```markdown
## Code Search

This project has a local semantic code index via AGENT Context Local.
When exploring the codebase or looking for code by meaning, use the
`search_code` MCP tool instead of grep/find. Examples:
- "search for authentication logic"
- "find error handling patterns"
- "where is the database connection configured?"

`search_code` already returns lightweight graph enrichment in normal results
when available (relationship hints only, bounded payload).

For deeper structural exploration of a specific result (full neighborhood up to
`max_depth`), use `get_graph_context(chunk_id)` with a chunk_id from a
`search_code` result.

If the index seems stale, run `index_directory` to refresh it.
Use `get_index_status` to check index health and model info.
```

### For agents.md (other MCP-aware agents)

Same content as above — `agents.md` is read by other agent frameworks that
support MCP.

## Supported Languages

The chunker supports 23 file extensions across:

- Python (`.py`)
- JavaScript and TypeScript (`.js`, `.jsx`, `.ts`, `.tsx`)
- Java and Kotlin (`.java`, `.kt`, `.kts`)
- Go (`.go`) and Rust (`.rs`)
- C, C++, and C# (`.c`, `.cpp`, `.cc`, `.cxx`, `.c++`, `.cs`)
- Svelte (`.svelte`)
- Markdown (`.md`)
- YAML, TOML, and JSON (`.yaml`, `.yml`, `.toml`, `.json`)

All programming languages use tree-sitter for AST-aware parsing.
Configuration files (YAML, TOML, JSON) use a structured key-path parser
that chunks by top-level sections.

## System Requirements

The default setup runs on any modern laptop or desktop — no GPU required.

### Minimum (CPU-only, default install)

| Resource | Requirement |
|----------|-------------|
| **CPU** | Any x86_64 or ARM64 (Apple Silicon, etc.) |
| **RAM** | 2 GB free (default embedding model uses ~200 MB) |
| **Disk** | ~500 MB free (model ~90 MB + index storage) |
| **GPU** | Not required |
| **Python** | 3.12+ |
| **OS** | Windows 10+, macOS 12+, Linux (glibc 2.31+) |

### Recommended configurations

| Setup | Embedding Model | Reranker (optional) | RAM / VRAM | Quality |
|-------|----------------|---------------------|------------|---------|
| **Default** | mxbai-embed-xsmall-v1 (384-d, 22.7M) | — | ~200 MB RAM | Good — fastest CPU indexing on any PC |
| **Default + reranker** | mxbai-embed-xsmall-v1 (384-d) | MiniLM-L-6-v2 (22.7M) | ~400 MB RAM | Better — adds precision with minimal overhead |
| **CPU quality** | Qwen3-Embedding-0.6B (1024-d) | MiniLM-L-6-v2 (22.7M) | ~1.5 GB RAM | Higher quality on CPU, slower indexing |
| **GPU starter** | Qwen3-Embedding-0.6B (1024-d) | Qwen3-Reranker-0.6B | ~4 GB VRAM | High — Qwen 0.6B pair, great entry GPU setup |
| **GPU mid-tier** | Qwen3-Embedding-4B (2560-d) | Qwen3-Reranker-0.6B | ~10 GB VRAM | Higher — bigger embeddings, same fast reranker |
| **GPU high-end** | Qwen3-Embedding-8B (4096-d) | Qwen3-Reranker-4B | ~28 GB VRAM | Maximum — top MTEB scores |

The **Default** setup works out of the box. Hybrid search (BM25 keyword matching +
vector similarity) is enabled by default — no extra configuration needed.

**Reranking is optional** and adds a second-pass quality boost. Enable it anytime
with `python scripts/cli.py config reranker on`. See
[Optional: Two-Stage Reranker](#optional-two-stage-reranker) for the full list
of reranker models.

## Advanced Configuration

### Choosing a Different Embedding Model

If you have a GPU and want higher-quality embeddings, set `CODE_SEARCH_MODEL`
before running the installer:

```bash
export CODE_SEARCH_MODEL="unsloth/Qwen3-Embedding-4B"
curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.sh | bash
```

```powershell
$env:CODE_SEARCH_MODEL="unsloth/Qwen3-Embedding-4B"
irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.ps1 | iex
```

Available models:

| Model | Short name | Notes |
|-------|------------|-------|
| `mixedbread-ai/mxbai-embed-xsmall-v1` | `mxbai-xsmall` | **Default** — 22.7M params, 384-dim, 4K context, fastest CPU indexing |
| `Qwen/Qwen3-Embedding-0.6B` | `qwen-embed-0.6b` | 600M params, 1024-dim — higher quality, slower on CPU |
| `unsloth/Qwen3-Embedding-4B` | `qwen-embed-4b` | Needs GPU ~8 GB VRAM |
| `unsloth/Qwen3-Embedding-8B` | `qwen-embed-8b` | Top MTEB quality, needs GPU ~18 GB VRAM |
| `Salesforce/SFR-Embedding-Code-400M_R` | `sfr-code-400m` | Code-search-focused alternative |
| `google/embeddinggemma-300m` | `gemma-300m` | Legacy (gated — requires HuggingFace auth, see below) |

The selected model is persisted to `~/.agent_code_search/install_config.json`.
You can change models later by re-running the installer with a different
`CODE_SEARCH_MODEL` value.

### Optional: Two-Stage Reranker

A reranker adds a second pass after the initial search: vector/hybrid search
returns the top 50 candidates, then a cross-encoder model reads each candidate
against your query and re-scores them for relevance.

#### Available reranker models

| Model | Size | Best for | Requirements |
|-------|------|----------|-------------|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | 22.7M | **Default** — fast CPU reranking | ~90 MB RAM, ~200ms for 50 passages |
| `Qwen/Qwen3-Reranker-0.6B` | 0.6B | GPU mid-tier, 32K context | ~2 GB VRAM |
| `BAAI/bge-reranker-v2-m3` | ~600M | Multilingual codebases | ~2 GB VRAM |
| `Qwen/Qwen3-Reranker-4B` | 4B | Maximum quality | ~10 GB VRAM |

#### Install and enable

```bash
python scripts/cli.py models install minilm-reranker
python scripts/cli.py config reranker on
```

Or during initial install, set the profile:

```bash
export CODE_SEARCH_PROFILE=reranker
# then run the installer
```

To disable: `python scripts/cli.py config reranker off`

The default reranker (`ms-marco-MiniLM-L-6-v2`) runs on CPU with negligible
overhead. Larger rerankers (0.6B+) need a GPU for acceptable latency. The
reranker is entirely optional — search works well without it.

### AMD GPU Support (ROCm)

AMD GPUs work out of the box once you install the ROCm build of PyTorch. The
device detection picks it up automatically.

```bash
pip install torch --index-url https://download.pytorch.org/whl/rocm7.1
```

Or with uv:

```bash
uv pip install torch --index-url https://download.pytorch.org/whl/rocm7.1
```

> **Note:** ROCm 6.2+ is the minimum for AMD Strix Halo APUs (Ryzen AI Max
> series). For other AMD GPUs, ROCm 7.x is recommended. Integrated GPUs on
> APUs share system memory, so VRAM limits depend on your system RAM allocation.

Verify with `python scripts/cli.py doctor` — it reports your GPU type
(NVIDIA CUDA / AMD ROCm / Apple MPS / CPU).

### Using Gated Models (HuggingFace Auth)

The legacy model (`google/embeddinggemma-300m`) is **gated** on HuggingFace.
If you explicitly choose it via `CODE_SEARCH_MODEL`, you need to authenticate first.

<details>
<summary>Gated model setup instructions</summary>

1. Create a HuggingFace account at https://huggingface.co/join
2. Visit https://huggingface.co/google/embeddinggemma-300m and click
   **"Agree and access repository"** to accept Google's Gemma license.
   Access is granted immediately — no manual review.
3. Create an access token at https://huggingface.co/settings/tokens

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

If you switch shells after logging in, the token may not be visible in the new
shell. Set `HF_TOKEN` in the same shell that runs the installer. The project
also accepts `HUGGING_FACE_HUB_TOKEN`.

</details>

## Storage Layout

```text
~/.agent_code_search/           # 0700 on Unix/macOS (owner-only access)
├── models/
├── install_config.json
├── merkle/                     # Merkle snapshots/metadata (global per-machine store)
│   ├── {project_hash}_snapshot.json
│   └── {project_hash}_metadata.json
└── projects/
    └── {project_name}_{hash}/
        ├── project_info.json
        ├── index/
        │   ├── lancedb/
        │   │   └── code_chunks.lance/   # vector + FTS index
        │   ├── code_graph.db            # SQLite relational graph
        │   └── stats.json
```

Your project workspace stays clean — all database files live in this central
directory, never inside the project being indexed. Override the storage location
with the `CODE_SEARCH_STORAGE` environment variable.

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
removed before the updated chunks are re-inserted. Run `get_index_status`
to see the current storage size, version count, and graph statistics.

## CLI Reference

The CLI handles setup, diagnostics, and configuration.
Indexing and search happen through the MCP tools inside your AI assistant.

If installed via PyPI, use `agent-context-local <command>` directly. For source installs:

```bash
# macOS / Linux / WSL
uv run --directory ~/.local/share/agent-context-code python scripts/cli.py <command>
```

```powershell
# Windows PowerShell
uv run --directory "$env:LOCALAPPDATA\agent-context-code" python scripts/cli.py <command>
```

### Setup and diagnostics

| Command | Description |
|---------|-------------|
| `help` | Show all available commands |
| `doctor` | Check Python version, model status, storage paths, MCP registration |
| `setup-guide` | Step-by-step setup walkthrough |
| `status` | Show current project and index status |
| `paths` | Print storage and install paths |
| `mcp-check` | Verify MCP server registration |
| `troubleshoot` | Interactive HuggingFace auth and model download help |

### Model management

| Command | Description |
|---------|-------------|
| `models list` | List all available embedding and reranker models |
| `models active` | Show currently configured models |
| `models install <short-name>` | Download a model by short name |
| `config model <short-name>` | Switch the active embedding model |
| `config reranker <on\|off>` | Enable or disable the reranker |
| `config reranker model <short-name>` | Switch the reranker model |

## Troubleshooting

Run `python scripts/cli.py troubleshoot` for interactive guidance.

### Common errors

| Error | Fix |
|-------|-----|
| `401` / Access denied | Only applies to gated models — see [Using Gated Models](#using-gated-models-huggingface-auth) |
| Token not found | Run `uv run huggingface-cli login` or set `HF_TOKEN` env var |
| Token exists but download fails | Export `HF_TOKEN` in the same shell running the installer |
| Download incomplete / timeout | Check disk space (~1-2 GB needed) and network connection |
| Import errors after install | Run `uv sync` in the project directory |
| `claude mcp list` missing `code-search` | Remove and re-add the MCP server entry (see Step 3) |
| No search results | Re-index the project; check with `python scripts/cli.py status` |

### If model download failed

The installer separates software installation from model download. Your install
is fine; the model just needs another try.

macOS / Linux / Git Bash / WSL:

```bash
uv run --directory ~/.local/share/agent-context-code python scripts/download_model_standalone.py --storage-dir ~/.agent_code_search --model "mixedbread-ai/mxbai-embed-xsmall-v1" -v
```

Windows PowerShell:

```powershell
uv run --directory "$env:LOCALAPPDATA\agent-context-code" python scripts/download_model_standalone.py --storage-dir "$env:USERPROFILE\.agent_code_search" --model "mixedbread-ai/mxbai-embed-xsmall-v1" -v
```

### For AI agents debugging MCP issues

If you're an AI agent and code search tools aren't working:

1. Ask the user to run `claude mcp list` (or their client's equivalent) in their
   terminal to verify the server is registered.
2. Ask the user to run `python scripts/cli.py doctor` for a full diagnostic check
   (Python version, model status, storage paths, MCP registration).
3. Check if the model was downloaded: `python scripts/cli.py models active` shows
   the configured model and whether it's available locally.
4. If the index seems empty, run `index_directory` on the project path to rebuild it.
5. Use `get_index_status` to check if the current project has an index and how many
   chunks it contains.

### WSL2 notes

- **HuggingFace tokens:** Windows-cached tokens are NOT visible inside WSL.
  Set `HF_TOKEN` explicitly in your WSL shell.
- **MCP registration:** If Claude Desktop runs on the Windows side, register
  the MCP server from a Windows terminal, or use `claude.exe` from WSL
  (note the `.exe` suffix when calling Windows binaries from WSL).

## Uninstall

To completely remove AGENT Context Local (app files, indexes, models, and MCP
registration), run the uninstall script. Shared tools (uv, Python, git) are
**not** removed.

You can review the scripts first:
[`uninstall.sh`](https://github.com/tlines2016/agent-context-code/blob/main/scripts/uninstall.sh) /
[`uninstall.ps1`](https://github.com/tlines2016/agent-context-code/blob/main/scripts/uninstall.ps1)

macOS / Linux / Git Bash / WSL:

```bash
curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/uninstall.sh | bash -s -- --force
```

Or if you have a local clone (interactive — will prompt for confirmation):

```bash
./scripts/uninstall.sh
```

Windows PowerShell:

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
- **Storage root**: `~/.agent_code_search` (or `CODE_SEARCH_STORAGE` override) — includes models, indexes, and config
- **MCP registration**: the `code-search` server entry

### What is NOT removed

- **uv**, **Python**, **git** — these are shared system tools
- Any project source code you indexed (only the index is removed, not your code)

## Repository

Canonical public repo:
[tlines2016/agent-context-code](https://github.com/tlines2016/agent-context-code)

## License

MIT — see [LICENSE](LICENSE) for details.

## Acknowledgements

This project was originally inspired by the foundational concepts of
claude-context-local. It has since been reworked into a standalone tool
supporting agent-agnostic workflows, a dedicated vector database, hybrid
search, reranking, and local embedding models.
