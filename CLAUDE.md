# CLAUDE.md

Claude Code working guide for this repository.

## Project Identity

- Product direction: **AGENT Context Local**
- Canonical repo: `tlines2016/agent-context-code`

## What This Repo Does

Local semantic code search via MCP:

- Multi-language chunking (`chunking/`)
- Local embedding generation (`embeddings/`)
- LanceDB-backed indexing and retrieval (`search/`)
- MCP tool surface for Claude Code (`mcp_server/`)

## Setup Commands

```bash
uv sync
python scripts/cli.py doctor
python scripts/cli.py setup-guide
```

Remote install commands are documented in `README.md`.

## Claude MCP Registration

macOS/Linux:

```bash
claude mcp add code-search --scope user -- uv run --directory ~/.local/share/agent-context-code python mcp_server/server.py
```

PowerShell:

```powershell
claude mcp add code-search --scope user -- uv run --directory "$env:LOCALAPPDATA\agent-context-code" python mcp_server/server.py
```

## Key Paths and Components

- `search/indexer.py`: LanceDB index manager (compaction, scalar indexes, health stats)
- `search/searcher.py`: retrieval and ranking
- `search/incremental_indexer.py`: Merkle-driven incremental flow (calls `optimize()` after indexing)
- `mcp_server/code_search_server.py`: indexing/search business logic
- `scripts/install.sh`, `scripts/install.ps1`: installer/update workflows
- `scripts/download_model_standalone.py`: model bootstrap
- `common_utils.py`: storage/config helpers

## Storage Model

All user data stays under `~/.claude_code_search` (or `CODE_SEARCH_STORAGE`):

- `models/` for local model cache
- `install_config.json` for persisted model choice
- `projects/{project}_{hash}/` for per-project index and snapshots

Directory permissions are set to `0700` on Unix/macOS (owner-only).
Never move index database files into the target workspace.

LanceDB tables are automatically compacted after each indexing session
(`optimize()` with 1-day version retention). Scalar indexes (BTREE on
`relative_path`/`chunk_id`, BITMAP on `chunk_type`) accelerate filtered queries.

## Model Notes

- Default model: `Qwen/Qwen3-Embedding-0.6B`
- Optional models live in `embeddings/model_catalog.py`
- Install-time selection: `CODE_SEARCH_MODEL`
- Persisted selection: `install_config.json`

If model download fails during install, the software install may still succeed.
Treat setup as incomplete until the model is available.

## Test Commands

```bash
uv run python tests/run_tests.py
uv run python -m pytest tests/unit/test_cli.py -v
uv run python -m pytest tests/test_lancedb_schema.py -v
```

## Contributor Guidance for Claude

- Keep docs and installer messaging aligned with actual behavior.
- Prefer compatibility-preserving changes over path/command renames.
- When modifying setup flow, update `README.md`, installers, and
  `scripts/cli.py` together.
