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

## Search and Graph Architecture

- `search_code` is the default retrieval tool and includes lightweight
  graph enrichment when available (relationship hints only; bounded payload).
  Enrichment is non-mutating — it never creates graph DB files when absent.
- `get_graph_context` is the separate deep graph endpoint for full structural
  neighborhood expansion around a specific `chunk_id` up to `max_depth`.
  Returns `found: false` with `miss_reason` when the seed chunk is not in the graph.
- Keep this two-tier model: lightweight graph context in default search, deep
  graph only when explicitly requested.
- Graph edge types currently implemented: `contains`, `inherits`.
  `imports` and `calls` are reserved but not yet extracted.
- Indexing uses a consistency barrier: snapshot metadata is only advanced when
  both vector and graph stores succeed.  `get_index_status` exposes
  `sync_status` ("synced" / "degraded") for observability.
- `clear_index` returns per-store outcomes: `vector_cleared`, `graph_cleared`,
  `snapshot_cleared`.

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

- `search/indexer.py`: LanceDB index manager (compaction, scalar indexes, FTS index, hybrid search)
- `search/searcher.py`: retrieval and ranking (passes query text for hybrid search)
- `search/incremental_indexer.py`: Merkle-driven incremental flow (calls `optimize()` after indexing)
- `mcp_server/code_search_server.py`: indexing/search business logic
- `scripts/install.sh`, `scripts/install.ps1`: installer/update workflows
- `scripts/uninstall.sh`, `scripts/uninstall.ps1`: safe uninstall with path guards
- `scripts/download_model_standalone.py`: model bootstrap
- `common_utils.py`: storage/config helpers

## Storage Model

All user data stays under `~/.agent_code_search` (or `CODE_SEARCH_STORAGE`):

- `models/` for local model cache
- `install_config.json` for persisted model choice
- `projects/{project}_{hash}/` for per-project vector index and graph DB
- `merkle/` for Merkle DAG snapshot and metadata files (keyed by project path hash)

Directory permissions are set to `0700` on Unix/macOS (owner-only).
Never move index database files into the target workspace.

LanceDB tables are automatically compacted after each indexing session
(`optimize()` with 1-day version retention). Scalar indexes (BTREE on
`relative_path`/`chunk_id`, BITMAP on `chunk_type`) accelerate filtered queries.
A full-text search (FTS) index on the `text` column enables BM25 keyword
matching for hybrid search (rebuilt during `optimize()`).

## Model Notes

- Default embedding model: `mixedbread-ai/mxbai-embed-xsmall-v1`
- Default reranker (when enabled): `cross-encoder/ms-marco-MiniLM-L-6-v2`
- Embedding catalog: `embeddings/model_catalog.py`
- Reranker catalog: `reranking/reranker_catalog.py`
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
