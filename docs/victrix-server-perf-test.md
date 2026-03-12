# Victrix-Server Performance Test — Bug Report

**Date:** 2026-03-12
**Tested by:** Claude Code (claude-sonnet-4-6) via MCP
**Project indexed:** `C:\Users\tline\EchosReforged\Main\Victrix-Server`

Full test report: `C:\Users\tline\EchosReforged\Main\Victrix-Server\CODE_SEARCH_TEST_REPORT.md`

---

## Bug 1 — `file_pattern` Filter Returns 0 Results on Windows (CRITICAL)

**Reproduction:**
```python
search_code("NPC combat attack", file_pattern="*.kt")  # → 0 results
search_code("NPC combat attack", file_pattern="*.toml")  # → 0 results
search_code("NPC combat attack", file_pattern="**/*.toml")  # → 0 results
search_code("NPC combat attack")  # → correct results
```

**Root cause:** The indexer stores file paths using Windows backslash separators (e.g., `game-server\src\main\kotlin\org\alter\Foo.kt`). The `file_pattern` glob matcher uses Unix-style forward-slash paths, so `*.kt` never matches `game-server\src\main\kotlin\Foo.kt`.

**Fix location:** Normalize stored/compared file paths to forward slashes before glob matching. Likely in `search/searcher.py` where the file_pattern filter is applied.

**Workaround for users:** Omit `file_pattern` entirely on Windows-indexed projects. Include type/language keywords in the query text instead.

---

## Bug 2 — `get_index_status` Response Too Large for Inline Delivery (OPERATIONAL)

**Reproduction:** Index a project with 970+ files, then call `get_index_status`. The response includes a `file_chunk_counts` dict with one entry per indexed file. For Victrix-Server (971 files), the response is ~112,564 characters — exceeding MCP inline response limits.

**Observed behavior:** Claude Code receives the response as a file path to a temp file rather than inline JSON, requiring extra read steps.

**Fix:** Add a `summary_only: bool = False` parameter that returns only top-level metrics (total_chunks, files_indexed, storage_size_mb, sync_status, model_information) without `file_chunk_counts`, `top_folders`, or `revision_observability` detail.

---

## Bug 3 — Large Structured Files Silently Excluded (NOTABLE)

**Context:** Victrix-Server has large pipeline-generated TOML files:
- `drop_tables.toml` = 14.2 MB — **NOT indexed** (exceeds `max_structured_file_bytes: 5,000,000`)
- `npc_spawns.toml` = 4.9 MB — NOT indexed
- `items.toml` = 2.2 MB — NOT indexed (likely excluded as build-dir file)
- `npc_combat.toml` = 2.2 MB — NOT indexed
- `shops.toml` = 613 KB — NOT indexed

Only 18 of 47 TOML files were indexed. The largest and most important ones were skipped with no warning to the user.

**Fix suggestions:**
1. Warn at index time when files are skipped due to size limits
2. Expose `max_structured_file_bytes` as a user-configurable parameter (CLI / `index_directory` arg)
3. Add chunked indexing for large structured files (split by top-level key/section)

---

## Observation — Structured Data Snippet Quality

TOML/YAML chunks return `"snippet": "Path: <key_path>"` instead of actual content values. This weakens semantic matching for config data.

**Example:**
```json
{
  "file": "gradle/libs.versions.toml",
  "snippet": "Path: plugins.kotlin-serialization.version"
}
```

The actual line `kotlin-serialization = "2.0.0"` would be far more useful for semantic retrieval.

---

## Observation — Large Constant Files Pollute High-k Results

`Sound.kt` (4,995 chunks, all single-line `const val FOO = 123`) and `xteas.json` (5,118 JSON key chunks) dominate results at k > 20 for queries containing words that appear in constant names.

**Example:** `"combat damage calculation hit and miss"` at k=100 returned ~30 `Sound.kt` entries like `DEMON_HIT`, `BEAR_HIT`, `ICE_WARRIOR_HIT` at scores of 0.50 — correct threshold, but these are not useful results.

**Suggestion:** Per-file result diversity cap option (e.g., `max_results_per_file=3` or `diversity_penalty`).

---

## Performance Data

| Operation | Result |
|-----------|--------|
| Full re-index (972 files, 24,131 chunks) | 334 seconds |
| Semantic search (k=5–10) | < 2 sec |
| `find_similar_code` (k=10) | < 2 sec |
| `get_graph_context` (depth=2) | < 1 sec |
| Index storage | 115.71 MB (LanceDB) |
