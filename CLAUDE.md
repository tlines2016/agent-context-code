# CLAUDE.md

> **Scope:** Source checkout of `agent-context-local`. For PyPI install
> troubleshooting (`uv tool install agent-context-local`), see [README](README.md).

## Quick Reference

```bash
uv sync                            # install deps
uv run python tests/run_tests.py   # run all tests
uv run python -m pytest tests/unit/test_cli.py -v
uv run python -m pytest tests/test_lancedb_schema.py -v
```

## Using Code Search on This Project

This project is indexed. When you're exploring unfamiliar code, investigating
a bug, or scoping a change, `search_code` can save you significant time
compared to manual file reading — it finds relevant code by meaning, not just
keywords. Use it when it would help; skip it when you already know where to look.

**When it helps most:** Understanding how a feature works across files, finding
where a concept is implemented, locating callers/callees of a function, or
discovering related code you didn't know existed.

| Area | What lives here |
|------|----------------|
| `chunking/` | Tree-sitter AST chunking — `base_chunker.py`, `multi_language_chunker.py`, `code_chunk.py` |
| `embeddings/` | Model loading and encoding — `sentence_transformer.py`, `model_catalog.py` |
| `search/` | LanceDB indexing and retrieval — `indexer.py`, `searcher.py`, `incremental_indexer.py` |
| `graph/` | SQLite relational graph — `code_graph.py` |
| `mcp_server/` | MCP tool surface — `code_search_server.py`, `code_search_mcp.py`, `strings.yaml` |
| `reranking/` | Opt-in reranker — `reranker.py`, `reranker_catalog.py` |
| `scripts/` | Install, uninstall, CLI — `install.sh`, `install.ps1`, `cli.py` |
| `ui/` | React dashboard frontend |
| `ui_server/` | Dashboard backend server |

**Query examples** (use code vocabulary, not natural language questions):

```
search_code("tree sitter chunk extract metadata")        → chunking/base_chunker.py
search_code("resolve cross file edges inheritance")      → graph/code_graph.py
search_code("incremental index merkle snapshot")         → search/incremental_indexer.py
search_code("MCP tool registration setup")               → mcp_server/code_search_mcp.py
search_code("embedding model load device dtype float16") → embeddings/sentence_transformer.py
search_code("reranker causal LM prompt build")           → reranking/reranker.py
```

**Drill-down:** After finding a chunk, `get_graph_context(chunk_id, max_depth=1)`
maps sibling methods and parent classes. `find_similar_code(chunk_id)` finds
other implementations of the same interface.

**Score calibration:** >= 0.80 is reliable. Below 0.40, rephrase using
method/class names instead of natural-language descriptions.

## Architecture

Two stores, one pipeline:

- **LanceDB** (`search/indexer.py`) — vector embeddings + BM25 FTS for hybrid search.
- **SQLite** (`graph/code_graph.py`) — relational graph: `contains`, `inherits`, `calls` edges.
  `imports` is reserved but not yet extracted.

Key design rules:
- `search_code` includes lightweight graph hints. `get_graph_context` does deep BFS traversal.
  Keep this two-tier model — don't merge them.
- Snapshot metadata only advances when both vector and graph stores succeed (consistency barrier).
- Graph enrichment is non-mutating — never creates graph DB files on read paths.
- `get_connected_subgraph()` returns edges prioritized by signal value (`contains` > `inherits` > `calls`),
  capped at `max_edges` (default 50). Response includes truncation metadata when capped.
- `resolve_call_edges()` skips ambiguous names (> `MAX_CALLEE_AMBIGUITY` matches) to reduce noise
  in versioned or large codebases.
- Graph edge resolution is two-pass: `contains` edges are inserted per-file inside `index_file_chunks()`.
  `inherits` and `calls` edges are resolved globally after all files are indexed — `resolve_cross_file_edges()`
  then `resolve_call_edges()` run last in both `_full_index()` and `incremental_index()`. New edge types
  must follow this same two-pass pattern.

## Storage

All data under `~/.agent_code_search` (or `CODE_SEARCH_STORAGE`):
`models/`, `install_config.json`, `projects/{name}_{hash}/`, `merkle/`.
Never move DB files into the target workspace.

## Models

- CPU default: `mixedbread-ai/mxbai-embed-xsmall-v1` (384-dim)
- GPU default: `Qwen/Qwen3-Embedding-0.6B` (1024-dim)
- Reranker: opt-in only, never auto-enabled.

## MCP Registration

Install script auto-registers. Manual:

```bash
# macOS/Linux
claude mcp add code-search --scope user -- uv run --directory ~/.local/share/agent-context-code python mcp_server/server.py
# Windows PowerShell
claude mcp add code-search --scope user -- uv run --directory "$env:LOCALAPPDATA\agent-context-code" python mcp_server/server.py
```

GPU machines: add `--extra cu128` (or `cu126`) after `uv run`.

## Testing

- Run tests after each logical change. Don't batch all changes and test at the end.
- `tests/unit/` — fast, no external deps. `tests/integration/` — needs models/indexes.
- `tests/run_tests.py` runs both suites. Use `-m pytest <path> -v` for targeted runs.
- Known: `test_prereqs_sh.py` skips on Windows (shell scripts). This is expected.
- When mocking `get_connected_subgraph()`, the return dict must include
  `total_edges_found`, `truncated`, and `omitted_by_type` alongside `symbols`/`edges`.

## Working Rules

- `mcp_server/strings.yaml` is deliberately tight — read `mcp_server/AGENTS.md` before editing.
  Every sentence must pass: "Would removing this cause an agent to make a mistake?"
  These descriptions are loaded into agent context on every tool call — minimize token cost.
- Keep docs and installer messaging aligned with actual behavior.
- When modifying setup flow, update `README.md`, installers, and `scripts/cli.py` together.
- Prefer compatibility-preserving changes over path/command renames.
- When modifying `graph/code_graph.py`, keep the `EDGE_PRIORITY` dict and `MAX_CALLEE_AMBIGUITY`
  constant in sync with any new edge types added.
- All MCP tool methods in `code_search_server.py` must return `json.dumps(...)` as a string, not a
  raw dict. MCP clients expect string payloads; returning a dict silently breaks on some clients.
