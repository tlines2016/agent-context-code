# AGENTS.md — Guidance for AI Agents Working on agent-context-code

## Project Overview

This repository is **AGENT Context Local** (`agent-context-code`), a fully
local semantic code search service accessible via MCP.

It provides **100% local** semantic code search over project source files:

- No external vector database service
- No API key required for search itself
- No index data written into user workspaces

## Current-State Architecture (Source of Truth)

- **Search backend:** LanceDB in `search/indexer.py`
- **Retrieval & ranking:** `search/searcher.py` (IntelligentSearcher)
- **Default search graph policy:** `search_code` returns lightweight graph relationship enrichment in normal search responses when available (bounded hints, not deep traversal)
- **Deep graph policy:** `get_graph_context` is the separate endpoint for deeper symbol/edge neighborhood traversal (`max_depth`) when an agent explicitly needs structural expansion
- **Embedding runtime:** SentenceTransformers in `embeddings/embedder.py`
- **Model presets:** `embeddings/model_catalog.py` (MODEL_CATALOG dict, prefix config)
- **Multi-language chunking:** `chunking/multi_language_chunker.py` (tree-sitter AST)
- **MCP service layer:** `mcp_server/server.py` (entry point) + `mcp_server/code_search_server.py` (business logic)
- **Incremental indexing:** `search/incremental_indexer.py` + `merkle/` (Merkle-DAG change detection)
- **Storage & config helpers:** `common_utils.py` (VERSION, get_storage_dir, install_config I/O)
- **HuggingFace auth:** `embeddings/huggingface_auth.py` (token discovery, error messaging)

### Storage Invariants (Must Preserve)

All index artifacts must stay under:

```text
~/.agent_code_search/                   # override with CODE_SEARCH_STORAGE
├── models/
├── install_config.json
├── merkle/                             # Merkle snapshots/metadata (global)
│   ├── {project_hash}_snapshot.json
│   └── {project_hash}_metadata.json
└── projects/
    └── {project_name}_{hash}/
        ├── project_info.json
        ├── index/
        │   ├── lancedb/
        │   │   └── code_chunks.lance/
        │   └── stats.json
```

Invariants:

1. Never write database files into the indexed workspace.
2. Keep project isolation via `{name}_{hash}` folders.
3. Preserve compatibility with existing storage locations.

## Model Selection Reality

- **Default today:** `Qwen/Qwen3-Embedding-0.6B`
- **Supported alternatives:** catalog in `embeddings/model_catalog.py`
- **Installer-selected model:** persisted in `install_config.json`
- **Override:** `CODE_SEARCH_MODEL` environment variable

For Qwen-family embedding models, preserve asymmetric prefix behavior:
query prefix may be required; document prefix may be intentionally empty.

## Installer and Setup Source Files

When updating setup behavior, keep these in sync:

- `scripts/install.sh`
- `scripts/install.ps1`
- `scripts/cli.py` (`setup-guide`, `doctor`, help text)
- `scripts/download_model_standalone.py`
- `README.md` setup examples

Canonical public repository URL in user-facing docs/scripts:
`https://github.com/tlines2016/agent-context-code`

## Agent Constraints for Safe Changes

- Do not reintroduce FAISS-specific runtime assumptions in docs/install messaging.
- Keep `claude mcp add code-search ...` examples valid for current client flows.
- Add equivalent MCP registration examples for non-Claude clients where docs are user-facing.
- Treat model download failures as recoverable; install can complete but must
  clearly report not-ready-for-indexing state.
- Preserve non-destructive update behavior in installer flows.

## Comment Convention for Code Edits

All code edits should include brief comments where logic is non-obvious.
Comments should explain:

1. Why a decision exists now.
2. Compatibility constraints being preserved.
3. Future intent if behavior is transitional.

Avoid redundant comments on straightforward assignments or control flow.

## Local Development Environment (Machine-Specific)

### GPU PyTorch (Critical for this machine)

This development machine has an **NVIDIA GeForce RTX 5080**. PyTorch CUDA support requires the `cu128` extra on **every** `uv run` and `uv sync` command:

```bash
# CORRECT — uses GPU torch (RTX 5080 CUDA 12.8)
uv run --extra cu128 python <script>
uv run --extra cu128 --extra test python -m pytest tests/

# WRONG — reverts torch to CPU-only, embedding will be extremely slow
uv run python <script>
```

**Why**: `pyproject.toml` routes `torch` to the CUDA index only when `--extra cu128` is active. Without it, `torch>=2.10.0` resolves from PyPI (CPU-only wheels). See `docs/gpu-install-investigation.md` for the full investigation and open fix items.

## Useful Validation Commands

```bash
# Full test suite (GPU + test deps)
uv run --extra cu128 --extra test python -m pytest tests/ -v

# Individual test files
uv run --extra cu128 --extra test python -m pytest tests/unit/test_cli.py -v
uv run --extra cu128 --extra test python -m pytest tests/test_lancedb_schema.py -v

# Sync dependencies after pyproject.toml changes
uv sync --extra cu128 --extra test
```
