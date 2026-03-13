<img width="1024" height="434" alt="image" src="https://github.com/user-attachments/assets/ca9fdded-ad76-4906-80e8-45060547749e" />

![PyPI version](https://img.shields.io/pypi/v/agent-context-local)
![Release status](https://img.shields.io/badge/status-beta-orange)
![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)
![MCP Compatible](https://img.shields.io/badge/MCP-compatible-blueviolet.svg)

**Local semantic code search for AI coding assistants.**

> **Release status:** `0.9.0` beta. The project is well-tested and actively used, but broader real-world usage may surface edge cases we have not encountered yet.

AGENT Context Local is an MCP server that gives your AI coding assistant semantic understanding of your codebase. It parses code into functions and classes using tree-sitter, then combines keyword matching with vector similarity so you can search by meaning — *"where do we validate auth tokens?"* — instead of relying on grep or burning context window limits on file-by-file exploration.

Everything runs completely on your local machine. No API keys, no telemetry, no cloud dependencies.

Source: [tlines2016/agent-context-code](https://github.com/tlines2016/agent-context-code)

## Key Features

- **Hybrid search** — Keyword matching and vector similarity combined for results that are both precise and semantically relevant.
- **AST-aware chunking** — Tree-sitter parses your code into functions, classes, and methods. No arbitrary line splits, no broken context.
- **100% local** — Embeddings generated on-device, embedded vector database, zero API calls, zero uploads. Works perfectly in air-gapped, compliance-restricted, and proprietary IP environments.
- **Incremental indexing** — Content-hash tracking ensures only modified files get re-indexed. Re-indexing after a small change takes seconds.
- **Graph-enriched results** — Search results include structural context like class hierarchies, method containment, and cross-file inheritance.
- **29 languages** — Python, TypeScript, Go, Rust, Java, C/C++, and [23 more](#supported-languages).
- **Hardware auto-tuning** — Runs fast on any CPU out of the box (22.7M param model). Automatically upgrades to higher-quality Qwen models if it detects a compatible GPU (NVIDIA, AMD ROCm, Apple MPS).

## Getting Started

> **Note:** [uv](https://docs.astral.sh/uv/) is required to install and manage AGENT Context Local. We use it to ensure a fast, globally isolated Python environment that won't conflict with your other tools.

Three commands to get working code search. Run these in your **regular terminal** — not inside an AI assistant session.

> **New to the terminal?** On macOS, open **Terminal** (Applications > Utilities).
> On Windows, open **PowerShell** or **Windows Terminal**. On Linux, use your
> preferred terminal emulator.

### Quick Install (PyPI)

Requires Python 3.12+ and `uv`:

```bash
# Install the package globally
uv tool install agent-context-local

# Register with Claude Code
# IMPORTANT: Run this in your regular terminal, not inside the interactive Claude Code session!
claude mcp add code-search --scope user -- agent-context-local-mcp

# Verify your installation
agent-context-local doctor
```

That's it. The PyPI install gives you two commands: `agent-context-local` (for managing your models and configuration) and `agent-context-local-mcp` (the actual MCP server process). No git clone is necessary.

For other MCP clients (Cursor, Copilot, Gemini CLI, Codex, etc.), see [docs/MCP_SETUP.md](docs/MCP_SETUP.md) for per-tool registration instructions.

<details>
<summary>Development / Source Install (git clone)</summary>

If you prefer to run from source or contribute to development:

### Step 1: Prerequisites

You need **Python 3.12+**, **uv**, and **git**.

**Automatic setup script:**
macOS / Linux / WSL:
```bash
curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/prereqs.sh | bash
```

Windows PowerShell:
```powershell
irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/prereqs.ps1 | iex
```

### Step 2: Install

Run the installer to set up the default model (no HuggingFace token needed).

macOS / Linux / Git Bash:
```bash
curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.sh | bash
```

Windows PowerShell:
```powershell
irm https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.ps1 | iex
```

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

**For other MCP clients**, use the server commands above in your client's specific configuration file.

### Step 4: Verify

```bash
uv run --directory ~/.local/share/agent-context-code python scripts/cli.py doctor
```
*(On Windows, use `$env:LOCALAPPDATA\agent-context-code`)*

### Step 5: Use It

Open your AI coding assistant (e.g., type `claude` in your terminal) and navigate
to your project directory. Then tell the assistant:

```text
index this codebase
```

The first indexing run processes every file and generates embeddings for each code
chunk. This initial run may take a few minutes depending on your codebase size and
hardware (GPU installs are significantly faster). Once the embeddings are built,
they are stored locally and subsequent runs are incremental — only changed files
are re-indexed, making future indexing near-instant. Once indexed, try:

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

## CLI Reference

The CLI handles setup, diagnostics, and configuration. Indexing and searching happen directly through the MCP tools inside your AI assistant.

If installed via PyPI, use `agent-context-local <command>`.
> **Source install tip:** If you installed via git clone, replace `agent-context-local` with `uv run python scripts/cli.py` in your project directory.

### Setup and diagnostics

| Command | Description |
|---------|-------------|
| `agent-context-local help` | Show all available commands |
| `agent-context-local doctor` | Check Python version, model status, storage paths, and MCP registration |
| `agent-context-local setup-guide` | Step-by-step setup walkthrough |
| `agent-context-local status` | Show current project and index status |
| `agent-context-local paths` | Print storage and install paths |
| `agent-context-local mcp-check` | Verify MCP server registration |
| `agent-context-local troubleshoot` | Interactive HuggingFace auth and model download help |

### Model management

| Command | Description |
|---------|-------------|
| `agent-context-local models list` | List all available embedding and reranker models |
| `agent-context-local models active` | Show currently configured models |
| `agent-context-local models install <short-name>` | Download a model by short name |
| `agent-context-local config model <short-name>` | Switch the active embedding model |
| `agent-context-local config reranker <on\|off>` | Enable or disable the reranker |
| `agent-context-local config reranker model <short-name>` | Switch the reranker model |
| `agent-context-local config idle offload <minutes>` | Set warm GPU-to-CPU offload threshold (0=disable) |
| `agent-context-local config idle unload <minutes>` | Set cold full-unload threshold (0=disable) |

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

See [docs/MCP_SETUP.md](docs/MCP_SETUP.md) for per-tool setup instructions.

## How It Works

Traditional code search (grep, ripgrep, `Ctrl+F`) matches exact strings. That works when you know the specific variable name or error message, but falls short when you're looking for *concepts* — "where does the app handle retries?" won't match `except ConnectionError: time.sleep(backoff)`.

AGENT Context Local bridges that gap with **hybrid search** — combining keyword matching with semantic understanding:

1. **Chunk** — Source files are split into meaningful pieces (functions, classes, config blocks) using language-aware parsers (tree-sitter AST), not arbitrary line counts.
2. **Graph** — Structural relationships extracted from the AST chunks (class hierarchies, method containment, cross-file inheritance) are stored in a SQLite relational graph for structural navigation.
3. **Embed** — Each chunk is passed through a local embedding model that converts the code into a high-dimensional vector capturing its semantic meaning.
4. **Index** — Vectors are stored in a LanceDB table alongside the original code and metadata (file path, line numbers, chunk type). A full-text search (FTS) index is also built for BM25 keyword matching.
5. **Search** — When you ask a question, two searches run in parallel:
   - **BM25 keyword search** finds chunks containing your exact terms.
   - **Vector similarity search** finds chunks with related *meaning*.
   - Results are combined via **Reciprocal Rank Fusion (RRF)** for the best of both.
6. **Rerank** (optional) — A cross-encoder reads each candidate against your query and re-scores them for even more precise ranking.

The embedding model runs entirely locally (no API calls), and LanceDB writes directly to disk with no background server process, keeping the whole pipeline extremely lightweight.

The index is also **incremental**: a Merkle DAG (directed acyclic graph of file content hashes) tracks exactly which files changed between runs. Re-indexing only processes what actually changed, and automatic **compaction** reclaims disk space over time.

## Available MCP Tools

These tools are exposed to your AI assistant session after MCP registration.

| Tool | Description |
|------|-------------|
| `index_directory("/path")` | Index a project (incremental by default). Optional `max_file_bytes` overrides the structured file size limit. |
| `search_code("query")` | Hybrid semantic + keyword search with lightweight graph enrichment. `file_pattern` supports true glob patterns (`*.py`, `src/**/*.ts`). |
| `find_similar_code(chunk_id)` | Find code similar to a known chunk |
| `get_graph_context(chunk_id)` | Deep structural context: full neighborhood traversal up to `max_depth` |
| `get_index_status` | Compact index statistics, model info, and graph stats. |
| `list_projects` | List all indexed projects |
| `switch_project("/path")` | Change the active project |
| `clear_index` | Clear the vector index and relational graph |
| `index_test_project` | Index the built-in sample project (useful for testing) |

**Typical workflow:** `index_directory` your project once, then use `search_code` for queries. Use `get_index_status` to check health. If you need to explore the structural neighborhood around a result, pass its `chunk_id` to `get_graph_context`.

## Recommended: Add to Your Project

Help your AI assistant automatically discover and use code search by adding this snippet to your project's instruction file (`CLAUDE.md`, `agents.md`, or `.cursorrules`).

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

## Supported Languages

**29 languages, 39 file extensions** — all programming languages use tree-sitter for AST-aware parsing.

| Category | Languages |
|----------|-----------|
| **Web** | JavaScript, JSX, TypeScript, TSX, HTML, CSS, Svelte, PHP |
| **Systems** | C, C++, Rust, Go |
| **JVM** | Java, Kotlin, Scala |
| **Scripting** | Python, Ruby, Lua, Elixir, Bash/Shell |
| **Mobile** | Swift, Kotlin |
| **Other** | C#, SQL, Terraform/HCL, Haskell |
| **Data/Docs** | YAML, TOML, JSON, Markdown |

Structured data files (YAML, TOML, JSON) use a key-path parser that chunks by top-level sections rather than full AST parsing.

## System Requirements & Models

The default setup runs beautifully on any modern laptop or desktop — no GPU required.

### Minimum Configuration (CPU-only, default install)

- **CPU:** Any x86_64 or ARM64 (Apple Silicon, etc.)
- **RAM:** 2 GB free (default model uses ~200 MB)
- **Disk:** ~500 MB free (model ~90 MB + index storage)
- **GPU:** Not required
- **Python:** 3.12+
- **OS:** Windows 10+, macOS 12+, Linux (glibc 2.31+)

### Recommended Configurations

Here's how different setups scale. Note the memory requirements for larger models.

| Setup | Embedding Model | Reranker (optional) | VRAM/RAM Need | Why this model? |
|-------|----------------|---------------------|---------------|-----------------|
| **Default** | `mxbai-embed-xsmall-v1` (384-d, 22.7M) | — | ~200 MB RAM | Fast CPU indexing anywhere. A tiny model that still significantly outperforms grep. |
| **Default + reranker** | `mxbai-embed-xsmall-v1` (384-d) | `MiniLM-L-6-v2` (22.7M) | ~400 MB RAM | Adds a second-pass precision boost with virtually zero latency overhead. |
| **CPU quality** | `Qwen3-Embedding-0.6B` (1024-d) | `MiniLM-L-6-v2` (22.7M) | ~1.5 GB RAM | Higher quality embeddings but runs slower on CPU. |
| **GPU starter** | `Qwen3-Embedding-0.6B` (1024-d) | `Qwen3-Reranker-0.6B` | ~4 GB VRAM | Punches way above its weight class. A brilliant balance of speed and retrieval accuracy for entry-level GPUs. |
| **GPU mid-tier** | `Qwen3-Embedding-4B` (2560-d) | `Qwen3-Reranker-0.6B` | ~10 GB VRAM | A massive jump in semantic understanding, catching highly nuanced codebase patterns. |
| **GPU high-end** | `Qwen3-Embedding-8B` (4096-d) | `Qwen3-Reranker-4B` | ~28 GB VRAM | Top-tier MTEB scores. If you have the VRAM, this is as good as local retrieval gets. |

The **Default** setup works out of the box. Hybrid search (BM25 + vector similarity) is automatically enabled.

**Reranking is optional**. It adds a cross-encoder pass to score top candidates. Enable it anytime with:
```bash
agent-context-local config reranker on
```

### GPU Auto-Detection

When a supported GPU backend is available (NVIDIA CUDA, AMD ROCm on Linux, or Apple MPS), the system automatically upgrades your defaults for better quality:

- **Embedding model**: Upgrades from `mxbai-embed-xsmall-v1` to `Qwen3-Embedding-0.6B` when a GPU is detected.
- **Reranker**: Pre-configures `Qwen3-Reranker-0.6B` for GPU installs (written to config as disabled). You just need to opt-in: `agent-context-local config reranker on`.

Verify your hardware status with `agent-context-local doctor`.

## Advanced Configuration

### Choosing a Different Embedding Model

If you have a GPU and want higher-quality embeddings, you can set the model via environment variable before running an install script, or change it via CLI after installing:

```bash
agent-context-local config model qwen-embed-4b
```

Available models via CLI short-names:

| Model | Short name | Notes |
|-------|------------|-------|
| `mixedbread-ai/mxbai-embed-xsmall-v1` | `mxbai-xsmall` | **Default** — 22.7M params, 384-dim, 4K context |
| `Qwen/Qwen3-Embedding-0.6B` | `qwen-embed-0.6b` | 600M params, 1024-dim, 8K context |
| `unsloth/Qwen3-Embedding-4B` | `qwen-embed-4b` | 4B params, 2560-dim, 32K context. Needs GPU ~8 GB VRAM |
| `unsloth/Qwen3-Embedding-8B` | `qwen-embed-8b` | 8B params, 4096-dim, 32K context. Top MTEB quality, needs GPU ~18 GB VRAM |
| `Salesforce/SFR-Embedding-Code-400M_R` | `sfr-code-400m` | Code-search-focused alternative |
| `google/embeddinggemma-300m` | `gemma-300m` | Legacy (gated — requires HuggingFace auth) |

### Idle Memory Management

During active queries, models use GPU VRAM (or RAM on CPU installs). A two-tier idle management system automatically frees memory between sessions:

| Tier | Default | What happens | Restore time |
|------|---------|--------------|--------------|
| **Warm offload** | 15 min | Models move from GPU → CPU RAM | ~50-100ms |
| **Cold unload** | 30 min | Models fully destroyed, memory freed | ~5-30s (cold start) |

Thresholds are configurable via CLI args or environment variables:

```bash
# Configure via CLI
agent-context-local config idle offload 20   # warm offload after 20 min
agent-context-local config idle unload 45    # cold unload after 45 min

# Or via environment variables
export CODE_SEARCH_IDLE_OFFLOAD_MINUTES=20
export CODE_SEARCH_IDLE_UNLOAD_MINUTES=45
```

Set either value to `0` to disable that tier.

### AMD GPU Support (ROCm)

AMD GPU acceleration currently requires Linux with ROCm 7.1+. ROCm PyTorch wheels are Linux-only right now, so AMD GPUs on Windows are not yet supported and will automatically fall back to CPU mode.

To force ROCm installation:
```bash
uv pip install torch --index-url https://download.pytorch.org/whl/rocm7.1
```

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
├── models/                     # Cached HuggingFace models
├── install_config.json         # Active user configuration
├── merkle/                     # Global metadata and file hashes
└── projects/
    └── {project_name}_{hash}/  # Isolated per-project storage
        ├── project_info.json
        └── index/
            ├── lancedb/        # Vector + FTS database
            ├── code_graph.db   # SQLite relational graph
            └── stats.json
```

Your project workspace stays completely clean. All database files live in this central directory. You can override this location using the `CODE_SEARCH_STORAGE` environment variable.

On Unix and macOS, the storage directory is locked down to your user account (`0700` permissions).

### Index Maintenance

You shouldn't need to think about this, but it's here if you're curious.
Each time you add, modify, or delete files, LanceDB creates new internal
fragments and version snapshots. The indexer automatically compacts these
after each session — cleaning up old versions (keeping one day of history)
and reclaiming disk space. The SQLite relational graph (`code_graph.db`) is
also kept in sync: modified or deleted files have their symbols and edges
removed before the updated chunks are re-inserted. Run `get_index_status`
to see the current storage size, version count, and graph statistics.

## Troubleshooting

Run `agent-context-local troubleshoot` for interactive guidance on common issues.

### Common errors

| Error | Fix |
|-------|-----|
| `claude mcp list` missing `code-search` | Ensure you ran the `claude mcp add` command from your regular terminal, not from inside Claude Code. |
| Import errors / module not found | Run `uv tool install agent-context-local --reinstall` |
| No search results | Run the `index_directory` MCP tool in your assistant to rebuild the index. |
| Gated model access denied | If using Gemma, run `uv run huggingface-cli login` to authenticate. |

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

<details>
<summary>For AI agents debugging MCP issues</summary>

If you're an AI agent and code search tools aren't working:

1. Ask the user to run `claude mcp list` (or their client's equivalent) in their
   terminal to verify the server is registered.
2. Ask the user to run `agent-context-local doctor` for a full diagnostic check
   (Python version, model status, storage paths, MCP registration).
3. Check if the model was downloaded: `agent-context-local models active` shows
   the configured model and whether it's available locally.
4. If the index seems empty, run `index_directory` on the project path to rebuild it.
5. Use `get_index_status` to check if the current project has an index and how many
   chunks it contains.

</details>

### WSL2 notes

- **HuggingFace tokens:** Windows-cached tokens are NOT visible inside WSL. Set `HF_TOKEN` explicitly in your WSL shell if using gated models.
- **MCP registration:** If Claude Desktop runs on the Windows side, register the MCP server from a Windows PowerShell terminal.

## Uninstall

To completely remove AGENT Context Local (app files, indexes, models, and MCP registration), you can uninstall the uv tool and delete the storage directory:

```bash
# Remove the CLI and server package
uv tool uninstall agent-context-local

# Remove Claude Code registration (if applicable)
claude mcp remove code-search

# Delete all indices and models
rm -rf ~/.agent_code_search
```

For source installs, run the bundled uninstaller:
```bash
curl -fsSL https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/uninstall.sh | bash -s -- --force
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

## License

MIT — see [LICENSE](LICENSE) for details.

## Acknowledgements

Built with [tree-sitter](https://tree-sitter.github.io/) for parsing, [LanceDB](https://lancedb.github.io/lancedb/) for vector storage, [sentence-transformers](https://www.sbert.net/) for embeddings, and the [Model Context Protocol](https://modelcontextprotocol.io/) for AI assistant integration.
