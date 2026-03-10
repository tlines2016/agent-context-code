# Task: Deep-Dive Review of LanceDB Setup — Data Handling, Optimizations & Security

You are reviewing the AGENT Context Local codebase — a local MCP-based semantic code search tool that stores code chunk embeddings in LanceDB. The entire system runs locally on user hardware with no cloud services, which is a significant security advantage. Your job is to validate our LanceDB usage, identify optimization opportunities, check data handling correctness, and assess security posture within the local-only threat model.

## Important Context

- This tool targets non-technical users on work PCs (often CPU-only) as well as developers with GPUs.
- All data stays local under `~/.claude_code_search/`. No network calls, no auth tokens, no cloud storage.
- The default embedding model is `Qwen/Qwen3-Embedding-0.6B` (1024-d vectors). An optional GPU model is `unsloth/Qwen3-Embedding-4B` (2560-d vectors).
- LanceDB is used in serverless/embedded mode — `lancedb.connect(path)` opens a local directory.
- The current minimum version pin is `lancedb>=0.20.0`.

---

## Part 1: Research Phase

Before reviewing code, build expertise on LanceDB capabilities and our embedding models. Use web fetches and searches for each of these.

### 1A: LanceDB Documentation Review

Research the current LanceDB documentation. Key topics to investigate:

1. **Indexing strategies** — What ANN index types does LanceDB support (IVF_PQ, IVF_HNSW_SQ, IVF_HNSW_PQ, etc.)? What are the tradeoffs? What are the recommended configurations for datasets of 1K–500K vectors? Our codebase currently uses NO explicit index configuration — LanceDB applies defaults. Is this optimal, or should we create an explicit index?

2. **Schema best practices** — We use a Pydantic LanceModel with `Vector(dim)` for the vector column and string columns for metadata. Are there better column types we should use? Does LanceDB support full-text search indexes on string columns? Would a hybrid search (vector + full-text) improve our results?

3. **Compaction and optimization** — LanceDB stores data in Lance format (columnar, append-only fragments). After many incremental add/delete cycles, does the table accumulate fragmentation? Is there a `compact_files()` or `optimize()` API we should call periodically? What about `cleanup_old_versions()`?

4. **Filtering performance** — We use SQL WHERE clauses with LIKE patterns for file path filtering and exact matches for chunk types. Does LanceDB support secondary indexes on scalar columns? Would creating a scalar index on `file_path` or `chunk_type` improve filter performance?

5. **Storage efficiency** — Our vectors are stored as float32. Does LanceDB support quantized vector storage (float16, int8) at the storage level? Would this meaningfully reduce disk usage for our use case?

6. **Versioning and concurrent access** — LanceDB has MVCC (multi-version concurrency control). How does this interact with our single-writer pattern? Are old versions automatically cleaned up, or do they accumulate on disk?

7. **Migration and schema evolution** — If we add columns to our schema in a future release, does LanceDB support schema evolution (adding nullable columns to existing tables)? Or do we need to rebuild?

8. **Delete performance** — We use `table.delete(where_clause)` for row-level deletes during incremental reindexing. How efficient is this? Does it create tombstones? Does it require subsequent compaction?

### 1B: Unsloth Qwen3 Embedding Documentation

Visit the Unsloth embedding models collection at https://huggingface.co/collections/unsloth/embedding-models and research:

1. **Available models** — What Qwen3 embedding model variants does Unsloth offer? What are the dimension sizes, parameter counts, and recommended use cases?

2. **Quantization** — Does Unsloth provide quantized versions (4-bit, 8-bit) of the embedding models? How do quantized embeddings compare to full-precision in retrieval quality? If quantized models output float32 embeddings (just from a smaller model), does that affect how we should store them?

3. **Normalization** — Are Qwen3 embeddings L2-normalized by default? This matters for our cosine distance metric — if vectors are pre-normalized, cosine distance equals 1 - dot product, and we might get better performance using the `dot` metric instead of `cosine`.

4. **Recommended similarity metrics** — What does the model card recommend for similarity search? Cosine, dot product, or L2?

5. **Max sequence length** — What is the max input token length? Are there truncation concerns for large code chunks? Do the Unsloth versions differ from the base Qwen3 models here?

6. **Instruction prefixes** — Does Qwen3-Embedding require instruction prefixes for queries vs. documents (asymmetric embedding)? If so, are we using them correctly?

---

## Part 2: Code Review

With your research complete, review the actual implementation. Read all files listed below in full before making any claims.

### Critical Files to Read

- `search/indexer.py` — Core LanceDB index manager (schema, CRUD, search, stats)
- `search/searcher.py` — Search orchestration and result formatting
- `search/incremental_indexer.py` — Merkle-driven incremental indexing (add/delete cycles)
- `mcp_server/code_search_server.py` — MCP tool surface (cross-project search, index management)
- `embeddings/embedder.py` — CodeEmbedder wrapper
- `embeddings/sentence_transformer.py` — SentenceTransformer model loading
- `embeddings/model_catalog.py` — Model registry
- `common_utils.py` — Storage path helpers
- `tests/test_lancedb_schema.py` — Schema and storage tests
- `tests/unit/test_indexer.py` — Indexer unit tests
- `conftest.py` — Test fixtures

### Review Checklist

For each area, note whether the current implementation is correct, what could be improved, and what the effort/impact tradeoff looks like.

#### A. Schema & Data Types
- Is the schema well-designed for our query patterns?
- Are string columns that we filter on (file_path, chunk_type, tags) candidates for scalar indexes?
- Is storing `content` and `content_preview` as separate columns redundant? What's the storage cost?
- The `tags`, `folder_structure`, `decorators`, and `imports` columns store JSON-encoded strings. Would a native list type be better for filtering?
- Is `Vector(dim)` with float32 the right choice, or should we consider float16 storage?

#### B. Index Configuration
- We create NO explicit ANN index. LanceDB applies a default (brute-force for small tables, auto-IVF for larger ones). Should we explicitly create an index? At what table size does this matter?
- Our search uses `.metric("cosine")`. Given that Qwen3 embeddings are L2-normalized, would `.metric("dot")` be faster with identical results?
- We fetch 10× candidates when filters are active (`fetch_k = k * 10`). Is this a good heuristic, or does LanceDB have a better pre-filter or post-filter mechanism?

#### C. Write Path
- `add_embeddings()` does batch inserts via `table.add(rows)`. Is this optimal, or should we use a different batch API?
- We convert numpy arrays to Python lists before insertion (`.tolist()`). Is there a zero-copy path using Arrow arrays directly?
- No explicit flush or sync after writes. Does LanceDB guarantee durability after `add()` returns?

#### D. Delete Path
- `remove_file_chunks()` uses `table.delete(where_clause)` with string matching on file paths. Is this efficient?
- After incremental cycles (delete old + add new for many files), does the table need compaction?
- Is there a risk of the Lance format growing unbounded with version history?

#### E. Search Path
- The cosine distance → similarity conversion `1.0 - distance` is correct for LanceDB's cosine metric. Verify this.
- The search falls back to empty results on any exception. Should we distinguish recoverable vs. fatal errors?
- `get_chunk_by_id()` uses `.search().where(...)` without a vector — is this the right API for non-vector lookups, or should we use a different method?

#### F. Statistics & Maintenance
- `_compute_stats()` uses `to_lance().to_table(columns=[...])` to skip vectors. Is this the best API for column projection?
- Stats are cached in `_stats_cache` and invalidated on mutations. Is this cache invalidation correct? Are there edge cases (concurrent MCP calls)?
- Should we implement periodic compaction? If so, when (after N deletes? on startup? on explicit command)?

#### G. Security (Local Threat Model)
Our security perimeter is "the local filesystem". Within that model, review:
- **Path traversal** — Could a crafted `file_path` in a WHERE clause escape the intended project scope? We use string substitution in WHERE clauses (e.g., `f"file_path = '{safe_path}'"`). Is this SQL-injection-safe within LanceDB's query engine?
- **Input sanitization** — We escape single quotes with `replace("'", "''")`. Is this sufficient for LanceDB's WHERE parser?
- **Storage permissions** — The `~/.claude_code_search/` directory is created with default permissions. Should we set restrictive permissions (0700)?
- **Temp file handling** — Are there any temp files or intermediate states where index data could leak?
- **Denial of service** — Could a very large project (millions of files) cause OOM during indexing? Are there any unbounded allocations?
- **Data integrity** — If the process crashes mid-write, does LanceDB's MVCC protect against corruption? Or could we end up with a half-written fragment?

---

## Part 3: Consolidation & Recommendations

After completing Parts 1 and 2, provide:

1. **Critical issues** — Anything that's broken, data-corrupting, or a security vulnerability (even within the local model)
2. **High-impact optimizations** — Changes that would meaningfully improve search quality, storage efficiency, or indexing speed. Include effort estimates (small/medium/large).
3. **Schema improvements** — Any column type changes, new indexes, or structural changes to recommend
4. **Maintenance operations** — Should we add compaction, version cleanup, or integrity checks? When should they run?
5. **Embedding model alignment** — Based on the Unsloth/Qwen3 docs, are we storing and searching embeddings optimally? (metric choice, normalization, instruction prefixes)
6. **Test gaps** — What's not tested that should be? Especially around edge cases in delete cycles, large datasets, and schema evolution.
7. **Future considerations** — What should we plan for as the codebase grows? (hybrid search, scalar indexes, storage format upgrades)

## Important Notes

- This is a research and review task. Do NOT make code changes — just report findings and recommendations.
- Read the actual source files before making claims about what the code does.
- Use web searches and fetches for current LanceDB and Unsloth documentation — don't rely on training data alone.
- Prioritize recommendations by impact. The audience is non-technical users who just want search to work — performance and correctness matter more than exotic features.
- Keep the local-only architecture as a given. Do not recommend cloud services or hosted vector databases.
