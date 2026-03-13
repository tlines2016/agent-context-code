# AGENT Context Local — Improvement Plan
## Based on Victrix-Server Integration Test (MCP_EVALUATION.md)

**Date:** 2026-03-12
**Branch target:** revision-1.6 → main
**Source evaluation:** `docs/MCP_EVALUATION.md`

---

## Agent Execution Groups

Tasks are grouped into four sequential sessions, ordered by priority and relatedness.
Complete and verify each group before starting the next.

### Group 1 — Critical fixes (Tasks 7A + 7B + 1) ✅ COMPLETED
Model dtype correctness and filter bug fix. All low-risk, isolated changes.

- **7A** ✅: Float16 for SentenceTransformer on CUDA + SFR `trust_remote_code` fix — `embeddings/sentence_transformer.py`, `embeddings/model_catalog.py`
- **7B** ✅: Float16 for BGE CrossEncoder reranker — `reranking/reranker.py` (`_load_cross_encoder` only)
- **1** ✅: `prefilter=True` for file_pattern filtering — `search/indexer.py` (`_hybrid_search`, `_vector_search`)

### Group 2 — Search quality (Tasks 6 + 2 + 5) ✅ COMPLETED
Deduplication, score transparency, and the strings.yaml update. All additive.

- **6** ✅: Duplicate chunk_id deduplication — `search/searcher.py` (`_semantic_search`, after `_rank_results` and before `_apply_per_file_cap`). Uses a `seen_chunk_ids` set to keep first (highest-ranked) occurrence only. Tests: 2 new tests in `TestDeduplication`.
- **2** ✅: Surface `vector_score` in output — `search/searcher.py` (`_create_search_result` threads `reranked`/`vector_similarity` from metadata into `context_info`), `mcp_server/code_search_server.py` (`_format_result` surfaces `vector_score` when reranked). Tests: 4 new tests in `TestRerankerMetadataThreading` and `TestFormatResultVectorScore`.
- **5** ✅: Score hint + chunk_type tip — `mcp_server/strings.yaml` (one appended line to `search_code` description)

### Group 3 — Min score threshold (Task 3) ✅ COMPLETED
Implemented as a standalone change in `reranking/reranker.py` (`rerank()`) and
`search/searcher.py` (`__init__`, `_semantic_search`). Added targeted tests in
`tests/unit/test_reranker.py` and `tests/unit/test_searcher.py`. Behavior note:
strict thresholds intentionally may return fewer than `k` results. Follow-up
plumbing now persists `min_reranker_score` in install config and threads it via
`CodeSearchServer` into `IntelligentSearcher` with defensive sanitization.

### Group 4 — GPU memory hygiene (Task 4)
Implement last. Agent must apply two corrections from the technical review before
writing any code:

1. **Pseudocode bug in Task 4A** — `batch_inputs`/`batch_outputs` do not exist in
   `embedder.py`. After `batch_embeddings = self._encode_texts(...)`, the correct
   pattern is simply `gc.collect(); torch.cuda.empty_cache()`. No `del` needed.
2. **lru_cache constraint in Task 4 is wrong** — the "Important constraints" section
   says the cache "must be invalidated." It must NOT be. `model.to()` is in-place;
   the cached `CodeReranker` instance remains valid after device moves. Disregard
   that constraint.

---

## Overview

This plan translates the eight evaluation findings into concrete, ranked implementation
tasks. Each task is scoped to be independently mergeable with no breaking changes to
existing users. Tasks are ordered by impact-to-risk ratio.

Items **not** included in this plan, and why:

| Rejected idea | Reason |
|---|---|
| Behavioral verb detection for `property`/`config_entry` chunk penalty | Too speculative; would require NLP query classification with real risk of misfiring on legitimate queries. Existing `chunk_type` filter covers this need explicitly. |
| Idle CPU offload for small embedding models | Default model (`mxbai-embed-xsmall-v1`) is ~85 MB VRAM. Offload complexity not justified for this footprint. Revisit only if a >1B param model becomes the default. |
| SPLADE sparse embeddings | Requires a separate model and a different index schema. High complexity with unclear benefit over the current BM25+vector RRF hybrid. Defer. |
| float16 model loading | Mxbai and the MiniLM reranker are both small CPU models where float32 is the norm. The Qwen GPU models may already load in float16 on some backends. Needs per-model audit before blanket change. |

---

## Task 1 — Fix `file_pattern` Filtering (Root Cause: Missing `prefilter=True`) ✅ COMPLETED

**Evaluation finding:** §4 Finding 1 — BUG, Medium severity
**Files:** `search/indexer.py`
**Risk:** Low — purely additive parameter. Improves filter correctness; no schema changes.
**Status:** Implemented. Added `prefilter=True` to `.where()` in both `_vector_search()` and `_hybrid_search()`. Tests added in `TestPrefilterFlag` (4 tests covering both methods, with and without clauses). All 425 unit tests pass.

### Root cause

`_hybrid_search()` and `_vector_search()` call `.where(where_clause)` without
`prefilter=True`. In LanceDB, the default `.where()` mode in both hybrid and ANN
search is **post-filter**: candidates are ranked first (across all chunks), then the
WHERE clause filters the returned rows. If none of the top-`fetch_k` candidates match
the module path, the filter eliminates all of them and the caller receives fewer than k
results — or in hybrid mode, may fall through to unfiltered results.

With `prefilter=True`, LanceDB reduces the candidate table to only rows that satisfy
the WHERE clause before running vector ANN and BM25. This is the semantically correct
behavior for `file_pattern` — the agent asked for results within a specific module.

### Change

In `_hybrid_search()`:
```python
# Before
if where_clause:
    query_builder = query_builder.where(where_clause)

# After
if where_clause:
    query_builder = query_builder.where(where_clause, prefilter=True)
```

In `_vector_search()`:
```python
# Before
if where_clause:
    query_builder = query_builder.where(where_clause)

# After
if where_clause:
    query_builder = query_builder.where(where_clause, prefilter=True)
```

### Caveat

Prefiltering can reduce ANN recall when the prefiltered set is very small (e.g. a
module with only 5 files). The existing `refine_factor(5)` in `_vector_search` already
improves recall within a filtered candidate set and mitigates this. The existing
`fetch_k = k * 10 when filters are active` also helps by fetching more candidates
before limiting to k.

### Test additions

Add a test to `tests/unit/test_indexer.py` that verifies `_hybrid_search` and
`_vector_search` pass `prefilter=True` to `.where()` when a WHERE clause is present.
Existing filter clause tests in `TestFilterClauses` do not exercise the LanceDB query
builder integration — add a mock-based test for the prefilter flag.

---

## Task 2 — Surface Reranker Score as a Separate Output Field ✅ COMPLETED

**Evaluation finding:** §4 Finding 2 (partial); §7 Potential improvement #4
**Files:** `mcp_server/code_search_server.py`
**Risk:** Additive. New optional field only appears when reranking was used. No fields
removed or renamed.
**Status:** Implemented. Two-part change: (1) `_create_search_result()` in `searcher.py` threads `reranked` and `vector_similarity` from metadata into `context_info`. (2) `_format_result()` in `code_search_server.py` surfaces `vector_score` (rounded to 2 decimals) when reranked. Cross-project search via `_search_project()` also benefits since it uses the same `_format_result()`. Tests: 4 new tests covering both presence and absence of `vector_score`.

### Motivation

Currently `_format_result()` outputs a single `score` field. When a reranker is
active, this is the reranker probability (0–1). The original hybrid RRF score is stored
in `metadata["vector_similarity"]` but never exposed to the MCP caller. Agents cannot
distinguish a keyword-driven rank-1 result (high BM25 hit, poor semantic match) from a
genuinely semantically matched result.

Exposing both scores allows agents (and developers) to see when a result was boosted
by keyword overlap rather than semantic similarity.

### Root cause of reviewer-identified bug

The reviewer confirmed: `SearchResult` (defined in `search/searcher.py:17-33`) has no
`metadata` field — accessing `result.metadata` in `_format_result()` would raise
`AttributeError`. The reranker enrichment keys (`"reranked"`, `"vector_similarity"`)
are set by `reranker.py:rerank()` into the raw metadata dict (lines 165-166), but
`_create_search_result()` in `searcher.py:242-294` does not extract them — they are
silently dropped.

The correct fix is two-part:

**Step 1 — Thread reranker metadata through in `_create_search_result()` (`search/searcher.py`)**

In the `context_info` dict that IS passed to `SearchResult.context_info`, add:

```python
# After the existing context_depth block:
# Thread reranker enrichment data through to the result object
if metadata.get("reranked"):
    context_info["reranked"] = True
    vector_similarity = metadata.get("vector_similarity")
    if vector_similarity is not None:
        context_info["vector_similarity"] = float(vector_similarity)
```

**Step 2 — Read from `result.context_info` in `_format_result()` (`mcp_server/code_search_server.py`)**

```python
    # Expose pre-reranker RRF/vector score when reranking was applied.
    # score stays as the primary sort key (reranker score).
    # vector_score shows what the hybrid search scored before reranking.
    if result.context_info.get("reranked"):
        vector_score = result.context_info.get("vector_similarity")
        if vector_score is not None:
            item['vector_score'] = round(vector_score, 2)
    return item
```

This is the minimal, non-confusing version: `score` stays as the primary sort key,
`vector_score` is surfaced as context only when reranking changed the order.

### Test additions

1. In `tests/unit/test_searcher.py` `TestRerankerIntegration`: assert that when
   the reranker runs, the resulting `SearchResult.context_info` contains `"reranked": True`
   and `"vector_similarity"` with the pre-reranker score.
2. Add a unit test for `_format_result()` asserting that `vector_score` appears in the
   output dict when `context_info["reranked"]` is True, and is absent otherwise.

---

## Task 3 — Configurable Minimum Reranker Score Threshold ✅ COMPLETED

**Evaluation finding:** §4 Finding 2 — High-confidence false positives
**Files:** `reranking/reranker.py`, `search/searcher.py`, `common_utils.py`,
`mcp_server/code_search_server.py`, `scripts/cli.py`
**Risk:** Low-medium. Default 0.0 = no behavior change. Must handle k starvation.
**Status:** Implemented. Added `min_score: float = 0.0` to `CodeReranker.rerank()` and
applied threshold filtering after score sort and before `top_k` truncation. Added
`min_reranker_score: float = 0.0` to `IntelligentSearcher.__init__()` and forwarded it
to reranker calls in `_semantic_search()`. Follow-up completed config plumbing:
`save_reranker_config()` now persists `reranker.min_reranker_score` (default `0.0`),
CLI reranker config rewrite paths preserve this field, and `CodeSearchServer`
sanitizes malformed values (missing/invalid -> `0.0`, negative -> `0.0`) before
passing to `IntelligentSearcher` in both `get_searcher()` and `_search_project()`.
Added unit tests covering persistence, backward compatibility, and server-level
plumbing of configured thresholds.
Verification: `test_common_utils` (25 passed), `test_searcher` (55 passed),
`test_code_search_server` (38 passed), and `test_plan_regressions` (24 passed).

### Motivation

Both cross-encoder (sigmoid-normalized) and causal LM (yes/no softmax) rerankers
produce 0–1 scores. The evaluation observed a poor semantic match scoring 0.96 —
driven by keyword overlap in BM25 rather than semantic relevance. A configurable
minimum score can prune clearly irrelevant results before returning them to the agent.

### Full call chain analysis (downstream effects)

Understanding the full pipeline is essential to placing this filter correctly:

```
index_manager.search(fetch_k=50)       → up to 50 raw (chunk_id, score, meta) tuples
  ↓
reranker.rerank(top_k=k)               → re-sorted, TRUNCATED to k results
  ↓
_create_search_result() × k            → SearchResult objects
  ↓
_rank_results()                        → intent-based re-ordering (does NOT remove results)
  ↓
_apply_per_file_cap()                  → pushes excess to end (does NOT remove results)
  ↓
ranked_results[:k]                     → final trim to k
```

**Key insight**: `reranker.rerank()` receives up to 50 candidates (`reranker_recall_k=50`)
but truncates to `k` before returning. If we apply `min_score` AFTER this truncation,
we only filter from the top-k, not from the full 50. The correct placement is: **filter
within `rerank()` before the top_k truncation**, so the full 50-candidate buffer can
compensate for filtered items.

**k starvation risk**: If more than `50 - k` candidates score below `min_score`,
the caller receives fewer than k results. This is unavoidable without fetching more
candidates. Document this behavior; do not silently pad with empty slots.

**`_rank_results()` is NOT a concern**: It re-orders but never removes results. The
intent-based boost it applies can only raise a result's final rank — it cannot make a
low-scoring result score above a threshold the reranker already rejected.

**Empty result edge case**: If ALL 50 candidates fall below `min_score`, `rerank()`
returns an empty list. The MCP layer must handle this gracefully (return an empty
`results` array with an informative message, not a crash).

### Change in `reranker.py` `rerank()` — filter before truncation

```python
def rerank(
    self,
    query: str,
    passages: List[Tuple[str, float, Dict[str, Any]]],
    top_k: Optional[int] = None,
    min_score: float = 0.0,    # NEW — 0.0 = off (backward compat)
) -> List[Tuple[str, float, Dict[str, Any]]]:
    ...
    # Sort descending by reranker score
    reranked.sort(key=lambda x: x[1], reverse=True)

    # Filter BEFORE truncating so the full recall buffer is used.
    # This is the correct order — do not swap these two blocks.
    if min_score > 0.0:
        reranked = [r for r in reranked if r[1] >= min_score]

    if top_k is not None:
        reranked = reranked[:top_k]

    return reranked
```

### Change in `IntelligentSearcher.__init__()`

Add `min_reranker_score: float = 0.0` and thread it through to `rerank()`:

```python
def __init__(
    self,
    index_manager,
    embedder,
    reranker=None,
    reranker_recall_k: int = 50,
    min_reranker_score: float = 0.0,   # NEW
):
    ...
    self._min_reranker_score = min_reranker_score
```

And in `_semantic_search()`:
```python
raw_results = self._reranker.rerank(
    query, raw_results, top_k=k, min_score=self._min_reranker_score
)
```

### Do NOT expose in MCP tool signature yet

Start with `min_reranker_score=0.0` (off by default). Test internally against a real
multi-module codebase before exposing as an MCP parameter. Once validated:
- Add as optional parameter to `search_code` with default `None` (→ 0.0)
- Document that setting it >0 may return fewer than k results

### Threshold guidance (architecture-specific)

Scores are not on a universal scale — know which architecture you're using:

| Architecture | How scores are generated | Practical "clearly irrelevant" threshold |
|---|---|---|
| `cross_encoder` (MiniLM) | sigmoid(raw_logit), range 0–1 | 0.05–0.15 |
| `causal_lm` (Qwen) | softmax(yes/no logits), range 0–1 | 0.05–0.3 |

0.5 for both architectures means "model is uncertain / coin flip". Start very
conservative (0.05) and raise only after validating against real codebase queries.
At 0.05, only results where the model is near-certain of irrelevance are filtered —
this should have minimal impact on legitimate results while cutting the worst false
positives.

### Test additions

Extend `tests/unit/test_reranker.py` `TestRerank` to verify:
- `min_score=0.0` returns all top_k results unchanged (backward compat)
- `min_score=0.5` with a mix of scores filters correctly AND uses full passage list (not pre-truncated)
- `min_score=1.1` returns empty list — callers must handle this without crashing
- Verify filter occurs before top_k truncation (pass 10 passages, top_k=3, min_score filters to 2 → should return 2, not 3)

---

## Task 4 — Smart GPU Memory Management: Batch Cleanup + Idle Offload

**Evaluation finding:** §8 Memory Management Recommendations
**Files:** `embeddings/` (batch embedding loop), `reranking/reranker.py`,
`mcp_server/code_search_server.py` (idle tracking)
**Risk:** Low-medium. `empty_cache()` is safe; idle offload requires a small state
machine but no threading.

### Two-part strategy

**Part A — Immediate: `empty_cache()` after indexing batches**

During indexing, PyTorch accumulates intermediate tensors (embeddings, attention masks)
in VRAM. These tensors are freed after each batch but the CUDA allocator holds the
cache. Releasing it once per batch (not per chunk) reduces VRAM pressure during long
indexing runs.

Do NOT call inside the per-chunk loop — ~5–6% overhead per call compounds across
thousands of chunks.

```python
import gc, torch

# After each embedding batch completes:
del batch_inputs, batch_outputs
gc.collect()
if torch.cuda.is_available():
    torch.cuda.empty_cache()
```

Apply the same pattern in `reranking/reranker.py` `_score_causal_lm()` after its
forward pass:

```python
# After scores are extracted from outputs:
del inputs, outputs
gc.collect()
if torch.cuda.is_available():
    torch.cuda.empty_cache()
```

Do NOT add `empty_cache()` to `_score_cross_encoder()` — CrossEncoder's
`model.predict()` is CPU-only for the default reranker.

**Part B — Idle-based GPU offload (lazy, no background thread)**

For GPU configurations running Qwen3-Embedding-0.6B + Qwen3-Reranker-0.6B, the
models stay loaded in VRAM continuously for the session. When the user isn't actively
querying (overnight, across meetings), this VRAM is held unnecessarily.

The approach is a **lazy idle check on next query arrival** — no background thread,
no timer daemon. The server records the timestamp of the last completed query. When a
new query arrives, it compares the elapsed time to a configurable idle threshold. If
the threshold has been exceeded, the models are moved to CPU and VRAM is released
before the query runs. After the query, the models stay on CPU until either:
- The next query arrives within the idle window (stay on CPU — they reloaded for this one)
- OR the implementation moves them back to GPU immediately after reload

The simplest, safest version: always reload to the original device on next use.

```python
# In the server or a shared ModelManager:
import time

_last_query_time: float = time.monotonic()
_IDLE_OFFLOAD_SECONDS: int = 300  # 5 min default; read from env/config

def _check_idle_offload(model, device: str):
    """If idle too long, move model to CPU and clear VRAM."""
    elapsed = time.monotonic() - _last_query_time
    if elapsed > _IDLE_OFFLOAD_SECONDS and device == "cuda" and model is not None:
        model.to("cpu")
        torch.cuda.empty_cache()

def _restore_model_device(model, device: str):
    """Move model back to target device before inference."""
    if device == "cuda" and next(model.parameters()).device.type == "cpu":
        model.to("cuda")

# On each query:
_check_idle_offload(embedder_model, device)
_restore_model_device(embedder_model, device)
result = embedder_model.encode(...)
_last_query_time = time.monotonic()
```

### Configuration

Expose via environment variable with a sensible default:
```
CODE_SEARCH_IDLE_OFFLOAD_MINUTES=5   # 0 = disabled (default for CPU installs)
```

The default should be **disabled (0)** for the default CPU install. GPU tiers should
default to 5 minutes, configurable by the user. This matches the pattern already used
by `CODE_SEARCH_MODEL` and `CODE_SEARCH_STORAGE`.

### Important constraints

- The reload (`model.to("cuda")`) adds ~0.5–2 s per first query after an idle period.
  This is acceptable for interactive use; document it in the README.
- Do NOT offload for the default CPU model (`mxbai-embed-xsmall-v1`, ~85 MB RAM).
  Only activate when the device is `cuda` or `mps`.
- Reloader must run synchronously before the query, not asynchronously, to avoid
  serving a query with a half-loaded model.
- The `lru_cache(maxsize=1)` on the `reranker` property in `code_search_server.py`
  must be invalidated (or bypassed) when the model is offloaded and reloaded, or the
  cached instance will point to the CPU copy even after moving back to GPU.

---

## Task 5 — Update Tool Description with Score Guidance ✅ COMPLETED

**Evaluation finding:** §4 Finding 8; §7 Potential improvement #6
**Files:** `mcp_server/strings.yaml` (`search_code` tool description)
**Risk:** Documentation-only. Zero code logic change.
**Status:** Implemented. Appended one compact line to `search_code` description: score interpretation guidance (higher = better, below ~0.4 = weak) and `chunk_type` tip for behavioral queries. Kept under token budget for agent context windows.

### Motivation

Agents currently receive no guidance on how to interpret similarity scores or when
to apply `chunk_type` filtering. Adding brief, directional guidance helps agents
decide when a result is worth reading vs. when to widen or change the query.

### Guiding principle for strings.yaml edits

`strings.yaml` descriptions are already compact and well-structured. Any addition
must earn its payload weight — prefer one sentence that generalises over four bullet
points that over-specify. Avoid thresholds derived from a single codebase: they
may not hold across different embedding models, index sizes, or query styles.

The evaluation observed a uniform-score clustering pattern when a concept is absent.
**Do not add this to the tool description yet.** It needs validation across multiple
codebases and model configurations before it can be stated as reliable agent guidance.
Revisit after additional testing.

### Change

Append two lines to the `search_code` description in `strings.yaml`:

```
    Score: higher is a closer semantic match; scores below ~0.4 are loose hints only. Add chunk_type="function" or "method" to behavioral queries to avoid config/property results ranking above logic.
```

This replaces nothing existing — it appends after the current `Example:` line. The
single sentence covers score interpretation directionally without pinning specific
thresholds, and the `chunk_type` tip is actionable without requiring further context.

### What NOT to add (deferred)

- Specific numeric band labels (≥0.90, 0.60–0.89, etc.) — derived from one test run.
- Uniform-cluster absence signal — needs multi-codebase validation first.
- Per-architecture score scale differences — too detailed for a tool description.

---

## Task 6 — Duplicate Search Result De-duplication ✅ COMPLETED

**Evaluation finding:** Observed during code investigation (not in original evaluation)
**Files:** `search/searcher.py`
**Risk:** Low. Additive post-processing step.
**Status:** Implemented. Added chunk_id deduplication in `_semantic_search()` after `_rank_results()` and before `_apply_per_file_cap()`. Uses a `seen_chunk_ids` set — O(n) per search. Preserves the first (highest-ranked) occurrence. Tests: 2 new tests in `TestDeduplication` (duplicate removal + passthrough for unique results).

### Motivation

During codebase investigation, `search_code` returned duplicate chunk IDs in results
(e.g., `mcp_server/code_search_server.py:318-434:method:search_code` appeared twice
in the same response). This wastes result slots and can confuse agents.

### Root cause

Hybrid search (BM25 + vector) via RRF can return the same document from both the BM25
and vector branches before RRF deduplication. LanceDB's built-in RRF should deduplicate
by chunk ID, but if deduplication isn't being applied (e.g., because of how
`fetch_k` pagination interacts with the result set), duplicates can appear.

### Change

After retrieval and reranking, deduplicate by `chunk_id` before applying the
`max_results_per_file` cap:

```python
# In IntelligentSearcher._semantic_search() or in the result-building path:
seen_chunk_ids: set[str] = set()
deduped_results = []
for result in ranked_results:
    if result.chunk_id not in seen_chunk_ids:
        seen_chunk_ids.add(result.chunk_id)
        deduped_results.append(result)
```

This is a defensive fix that costs O(n) per search with n typically ≤ 100.

### Test additions

Add a test where the mocked retrieval returns two identical chunk IDs and assert the
final output contains each chunk ID exactly once.

---

---

## Task 7 — Float16 Model Loading (Per-Model Audit Results) ✅ PARTS A & B COMPLETED

**Source:** Float16 per-model audit via HuggingFace model cards
**Files:** `embeddings/sentence_transformer.py`, `reranking/reranker.py`
**Risk:** Low-medium. Device-guarded: float16 only activates on CUDA. CPU/MPS paths
unchanged. The causal LM reranker path already does this correctly.
**Status:** Parts A and B implemented. Part C (Flash Attention 2) deferred to separate PR.

**Part A summary:** Added `model_kwargs={"torch_dtype": torch.float16}` to `SentenceTransformer()` when `device == "cuda"`. Added `trust_remote_code` field to `EmbeddingModelConfig` (default `False`), set `True` for `SFR-Embedding-Code-400M_R`, threaded through `embedder.py` → `sentence_transformer.py`. Added `embedding_dimension=1024` to SFR catalog entry. Updated Qwen3-Embedding-4B comment to reflect actual behavior. Tests: 5 new tests in `test_sentence_transformer.py`.

**Part B summary:** Added `model_kwargs={"torch_dtype": torch.float16}` to `CrossEncoder()` in `_load_cross_encoder()` when `device == "cuda" and not self._config.cpu_feasible`. Only `BAAI/bge-reranker-v2-m3` is affected; MiniLM stays float32. Tests: 3 new tests in `TestCrossEncoderDtype` class in `test_device_resolution.py`.

### Audit Summary

| Model | Stored As | Float16 on CUDA | Status |
|---|---|---|---|
| `mxbai-embed-xsmall-v1` | F16 | Not recommended (CPU default; trivial size) | No change |
| `Qwen3-Embedding-0.6B` | BF16 | Recommended | **Gap — not currently applied** |
| `unsloth/Qwen3-Embedding-4B` | BF16 | **Required** (~8 GB FP16 vs ~16 GB FP32) | **Gap — OOM risk** |
| `unsloth/Qwen3-Embedding-8B` | BF16 | **Required** (~16 GB FP16 vs ~32 GB FP32) | **Gap — OOM without it** |
| `SFR-Embedding-Code-400M_R` | BF16 | Likely safe; unverified | Needs verification |
| `ms-marco-MiniLM-L-6-v2` | F32 | Not recommended (CPU default; dtype mismatch bugs) | No change |
| `Qwen3-Reranker-0.6B` | BF16 | Already applied | ✓ Correct |
| `BAAI/bge-reranker-v2-m3` | F32 | Recommended (GPU-only model) | **Gap — not applied** |
| `Qwen3-Reranker-4B` | BF16 | Already applied | ✓ Correct |

### Part A — SentenceTransformer Embedding Models (`sentence_transformer.py`)

**Critical:** Without this fix, `unsloth/Qwen3-Embedding-4B` loads in float32 (~16 GB
weights alone) and `unsloth/Qwen3-Embedding-8B` at float32 (~32 GB) will OOM on any
consumer GPU. The `model_catalog.py` comment already documents the intent; the loading
code just doesn't implement it yet.

Change in `sentence_transformer.py`, in the `model` cached_property, before the
`SentenceTransformer(...)` call:

```python
import torch

# Determine effective device so we can choose dtype before model load.
# SentenceTransformer resolves "auto" internally, but we need it here
# to decide whether to pass float16 model_kwargs.
_effective_device = self._device
if _effective_device == "auto":
    if torch.cuda.is_available():
        _effective_device = "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        _effective_device = "mps"
    else:
        _effective_device = "cpu"

# Pass float16 only on CUDA. CPU float16 is 5–10x slower than float32
# on x86 hardware; MPS uses float32 for stability.
_model_kwargs = {}
if _effective_device == "cuda":
    _model_kwargs["torch_dtype"] = torch.float16

model = SentenceTransformer(
    model_source,
    cache_folder=self.cache_dir,
    device=self._device,
    model_kwargs=_model_kwargs if _model_kwargs else None,
)
```

`SentenceTransformer` supports `model_kwargs` as of sentence-transformers v2.7+ and
passes them through to `AutoModel.from_pretrained`. This is the officially documented
loading path for dtype control.

**SFR-Embedding-Code-400M_R note:** This model requires `trust_remote_code=True`.
The current catalog entry does not flag this requirement, and the `SentenceTransformer`
call does not pass it. This model will fail to load without it. Add
`trust_remote_code: bool = False` to `EmbeddingModelConfig` and set it to `True` for
`SFR-Embedding-Code-400M_R`, then pass it as `SentenceTransformer(...,
trust_remote_code=config.trust_remote_code)`. This is a prerequisite for using that
model — fix alongside the float16 change.

### Part B — CrossEncoder Reranker (`reranking/reranker.py` — `_load_cross_encoder`)

Only `BAAI/bge-reranker-v2-m3` is affected here. `ms-marco-MiniLM-L-6-v2` is a
CPU-default model stored in F32 with known dtype mismatch issues — do NOT apply
float16 to it.

Use the catalog's `cpu_feasible` flag as the guard: if `cpu_feasible=False`, the model
is GPU-only and float16 is appropriate.

```python
def _load_cross_encoder(self) -> None:
    from sentence_transformers import CrossEncoder
    import torch

    device = self._resolve_device()

    # Only GPU-exclusive models benefit from float16.
    # CPU-default models (MiniLM) use float32 to avoid inference slowdown
    # and known dtype mismatch bugs in the CrossEncoder path.
    model_kwargs = {}
    if device == "cuda" and not self._config.cpu_feasible:
        model_kwargs["torch_dtype"] = torch.float16

    self._model = CrossEncoder(
        self._model_name,
        max_length=self._config.max_length,
        device=device,
        model_kwargs=model_kwargs if model_kwargs else None,
    )
```

### Part C — Flash Attention 2 (Optional, Deferred)

`attn_implementation="flash_attention_2"` gives meaningful throughput improvement for
Qwen3-Embedding and Qwen3-Reranker models. The official model cards recommend it.
However it requires the `flash-attn` package which:
- Must be installed separately (not in the base `pyproject.toml`)
- Has its own CUDA version requirements
- Is not available on CPU or MPS

This is worth adding but requires a capability check:

```python
# Example guard pattern (do not add yet — verify flash-attn is in dependencies first)
try:
    import flash_attn  # noqa: F401
    _model_kwargs["attn_implementation"] = "flash_attention_2"
except ImportError:
    pass  # Proceed without FA2
```

**Decision: defer Flash Attention 2 until a separate PR** that adds `flash-attn` as
an optional dependency for the GPU install tiers. Do not block the float16 dtype fix
on this.

### Update `model_catalog.py` comment accuracy

The `unsloth/Qwen3-Embedding-4B` description currently says:
> "The unsloth variant loads with flash_attention_2 + float16 on CUDA"

This is aspirational documentation — after Task 7 Part A, float16 will be accurate.
Flash attention remains deferred. Update the description to reflect actual behavior:

```python
description="Unsloth-optimised Qwen3-Embedding-4B — loaded in float16 on CUDA (~8 GB VRAM), flash_attn optional.",
```

### Test additions

1. Mock `SentenceTransformer` constructor in `tests/unit/` and assert that on a
   simulated CUDA device, `model_kwargs={"torch_dtype": torch.float16}` is passed.
2. Assert that on CPU, `model_kwargs` is `None` (or absent).
3. Assert `_load_cross_encoder` passes `torch_dtype=torch.float16` for
   `BAAI/bge-reranker-v2-m3` (non-cpu-feasible) and does NOT pass it for
   `ms-marco-MiniLM-L-6-v2` (cpu-feasible).

---

## Implementation Order

| # | Task | Impact | Risk | Effort |
|---|------|--------|------|--------|
| 7A | Float16 for SentenceTransformer (CUDA) | **Critical** — fixes OOM on 4B/8B | Low (CUDA-only guard) | ~20 lines + 2 tests |
| 7A | SFR trust_remote_code fix | High — model unusable without it | Low | ~5 lines + catalog field |
| 1 | `prefilter=True` for file_pattern | High — fixes confirmed bug | Low | 2-line change + 1 test |
| 6 | Deduplication | Medium — prevents redundant results | Low | ~10 lines + 1 test |
| 7B | Float16 for BGE CrossEncoder reranker | Medium — GPU memory saving | Low | ~10 lines + 1 test |
| 2 | Surface `vector_score` in output | Medium — diagnostic transparency | Low | ~15 lines + 2 tests |
| 5 | Tool description (score hint + chunk_type tip) | Low — directional guidance only | None | 1 line |
| 3 | Min reranker score threshold | Low-medium — opt-in pruning | Low | ~20 lines + 4 tests |
| 4 | Smart GPU memory management | Low-medium — VRAM hygiene | Low-medium | ~40 lines |
| 7C | Flash Attention 2 | Low-medium — throughput | Medium (new dep) | Separate PR |

**PR grouping:**
- **PR 1** (critical fixes): Tasks 7A + 7B + 1 + 6
- **PR 2** (transparency + docs): Tasks 2 + 5
- **PR 3** (opt-in features): Tasks 3 + 4
- **PR 4** (Flash Attention): Task 7C — after `flash-attn` dependency is validated

---

## Out of Scope / Deferred

- **Score cliff in vocabulary-mismatch cases (Finding 4)**: The current BM25+vector
  RRF hybrid already rescues most vocabulary-mismatch results via the vector branch.
  The residual issue (ranks 3–4 scoring 0.04 when BM25 contribution is zero) is a
  fundamental limitation — fixing it would require SPLADE or query expansion, deferred
  per the "not included" rationale at the top of this document.

- **Mild penalty for property/config_entry chunks on behavioral queries (Finding 7)**:
  Would require query intent classification. Existing `chunk_type` filter is the
  correct user-controlled solution. Documented clearly in Task 5 rather than
  auto-penalizing.

- **Flash Attention 2 (Task 7C)**: Deferred to its own PR pending `flash-attn`
  dependency validation for all GPU install tiers.
