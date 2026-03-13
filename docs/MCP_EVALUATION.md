# AGENT Context Local — MCP Server Evaluation Report

**Date:** 2026-03-12
**Test Codebase:** Victrix-Server (Kotlin game server, `C:\Users\tline\EchosReforged\Main\Victrix-Server`)
**Branch:** revision-1.1
**Evaluator:** Claude Code (claude-sonnet-4-6)
**Target audience:** Developers and AI agents working on the MCP server's source code

---

> **Purpose of this document**
>
> This is an engineering feedback report for contributors to
> [tlines2016/agent-context-code](https://github.com/tlines2016/agent-context-code).
> It documents observed behavior — correct, incorrect, or surprising — from a full
> integration test run against a real production-sized Kotlin codebase. Each finding
> is written as actionable signal for the server's developers: what works well and
> should be preserved, and where the implementation has gaps worth investigating.

---

## 1. Test Environment

### Hardware

| Component | Spec |
|-----------|------|
| CPU | AMD Ryzen 9 9800X3D |
| RAM | 64 GB DDR5 |
| GPU | NVIDIA RTX 5080 (16 GB VRAM) |
| Storage | NVMe SSD |

### Model Configuration

This test ran on the **GPU starter** tier (auto-detected by the installer):

| Role | Model | Dimension | Device |
|------|-------|-----------|--------|
| Embedding | `Qwen/Qwen3-Embedding-0.6B` | 1024-d | cuda:0 |
| Reranker | `Qwen/Qwen3-Reranker-0.6B` | cross-encoder | cuda:0 |

Both models are kept resident on GPU throughout the session (dual-load). This is one of
several supported configurations. The **default CPU install** uses
`mxbai-embed-xsmall-v1` (22.7M params, 384-d, ~200 MB RAM) with no reranker — a very
different performance and memory profile. See the README configuration table for the
full tier list (`Default` → `GPU starter` → `GPU mid-tier` → `GPU high-end`).

### Observed GPU Memory Usage

- **Total system memory reported by GPU monitor during testing:** ~30.7 GB / 46.8 GB
- The 46.8 GB figure represents combined GPU VRAM (16 GB) + system RAM available to
  the GPU (RTX 5080 with resizable BAR / CUDA unified addressing).
- **Important context:** The test machine was running several other memory-heavy
  applications concurrently — Docker Desktop, multiple Cursor instances, and Firefox.
  These applications contribute meaningfully to the 30.7 GB figure. The number should
  not be interpreted as the MCP server's isolated footprint.
- That said, the GPU VRAM portion of that usage is largely attributable to the two
  resident models (`Qwen3-Embedding-0.6B` + `Qwen3-Reranker-0.6B` on `cuda:0`).
  The Qwen 0.6B pair holds both models in VRAM continuously for the duration of the
  session. GPU VRAM does not fluctuate between queries — the models stay loaded.
- Developers benchmarking GPU memory impact should test in an isolated environment
  to separate model footprint from ambient application load.
- No OOM errors were observed. Search query latency was <2 s per call.

---

## 2. Indexing Run

### Results

| Metric | Value |
|--------|-------|
| Wall-clock duration | **6 min 55 s** |
| Tool-reported time | 415.4 s |
| Files scanned | 780 |
| Files indexed (supported) | 732 |
| Chunks created | 16,818 |
| Graph symbols | 16,656 |
| Graph edges | 9,301 |
| Index size on disk | 81.58 MB |
| Files ignored | 33 (20 hardcoded, 13 gitignore) |
| Files skipped | **1** — `item-data.json` (2.3 MB, exceeds 100k line limit) |

The single skipped file is a raw cache dump — expected and correct. The `.gitignore`
and hardcoded ignore rules applied cleanly with no surprises.

### Chunk Composition

```
property        6,809  (40.5%)  — game-api/cfg/ constants layer
config_section  4,595  (27.3%)  — TOML/YAML/JSON structured data
config_entry    1,268   (7.5%)
method          2,158  (12.8%)
class             621   (3.7%)
function          521   (3.1%)
enum               78   (0.5%)
object            250   (1.5%)
```

The dominant `property` share (40.5%) is specific to this codebase's large constants
layer (`game-api/cfg/`). This has relevance to search result quality — see §4 Finding #4.

---

## 3. Test Suite

Twelve tests across all three search tools were run against simulated real agent tasks.
Test categories:

| Category | Tests | Purpose |
|----------|-------|---------|
| Happy path | 3, 7, 10, 11, 12 | Named concepts that clearly exist in the codebase |
| Cross-layer | 4, 8, 9, 13* | Concepts that span engine/content/API modules |
| Absent concept | 1, 5, 6 | RSMod-era APIs that don't exist in Victrix-Server |
| Adversarial filter | 2 | Module-scoped query using `file_pattern` glob |

*Tests 13+ were run as bonus queries (login event, attribute keys).

---

## 4. Findings

Each finding below is written for the server's developers: what was observed, what the
root cause likely is, and what impact it has on agent behavior.

---

### Finding 1 — BUG: `file_pattern` with `**` glob does not filter correctly

**Observed in:** Test 2 (logging pattern in `game-plugins`)
**Severity:** Medium — misleads agents working in multi-module repos

**Reproduction:**
```python
search_code(
    query="logging in game plugins KotlinLogging logger",
    file_pattern="game-plugins/**/*.kt",
    k=5
)
```

**Expected:** Results restricted to files under `game-plugins/`
**Actual:** All top-5 results were from `game-server/` (different module), with scores of 0.96

The results returned were companion objects from:
- `game-server/.../ItemMetadataService.kt`
- `game-server/.../DefinitionSet.kt`
- `game-server/.../MessageHandler.kt`

None of these are under `game-plugins/`. The filter either did not apply, or the `**`
wildcard glob is being evaluated differently than expected (possibly matching any path
containing the string `game-plugins` at any depth, rather than paths starting with it).

**Agent impact:** An agent asking "what logging pattern is used in game-plugins?" gets
confident (0.96) answers from a completely different module. It would write code using
the wrong logging import without knowing it made a mistake.

**Suggested investigation:** Check how `file_pattern` is applied in the LanceDB query
path. Specifically, verify that `game-plugins/**/*.kt` is anchored to the project root
and not a substring match. A flat pattern `game-plugins/*.kt` or `*.kt` with a
`max_results_per_file` cap may work around this in the interim.

---

### Finding 2 — BEHAVIOR: High-confidence false positives when concept is absent

**Observed in:** Tests 2 and 5
**Severity:** Low-medium — affects agent trust calibration

**Detail:**

In Test 5, searching for a TOML parser class that does not exist in the codebase:
```python
search_code("TOML parser wiki data drops items npcs")
```
Returned `NpcServerCodec.createData()` at **score 0.96** — a cache codec with no
TOML parsing and no wiki data connection. The actual TOML-adjacent result
(`GameValProvider.processGameValToml()`) appeared at rank 3 with a much more honest
score of 0.55.

The pattern: when BM25 finds a strong keyword hit in a result (e.g. "NPC" + "data")
that the vector model doesn't rank highly, RRF fusion can still push it to rank 1 with
an inflated combined score. The reranker then gives it a high score because the
query contains terms that appear in the code, even if the semantic match is poor.

**Agent impact:** A new agent working on the codebase sees a confident result and
reads `NpcServerCodec.createData()` expecting a TOML parser. It wastes a read and
potentially writes a wrong code reference.

**Suggested investigation:**
- Does the reranker have a minimum relevance threshold that truncates results below
  a certain cross-encoder score? If not, adding one (e.g., drop results below 0.3
  reranker score) would reduce confident false positives.
- Alternatively, consider exposing the raw reranker score in the result object
  alongside the combined RRF score, so the distinction between "keyword hit" and
  "semantic match" is visible to callers.

**Positive note:** The score cliff behavior is correct and useful. When a concept is
absent, scores cluster at ~0.55 uniformly. When it exists, one result pulls away to
0.90+. Agents can read this distribution. Preserving this signal while reducing false
positives at the top is the goal.

---

### Finding 3 — GOOD: Score calibration is reliable across modalities

**Observed in:** Tests 3, 7, 10, 11, 12
**Severity:** N/A — this is working correctly, document to preserve

The score distribution across tests showed strong calibration:

| Score range | Observed reliability | Examples |
|-------------|----------------------|---------|
| ≥ 0.90 | Near-perfect — chunk is the correct answer | `dealHit` (1.00), `isQuestCompleted` (1.00), `getCurrentHp` (0.98) |
| 0.60–0.89 | Useful — correct module/file, may need one hop | `World.shops` (0.91), `BobPlugin.storeItems` (0.72) |
| 0.40–0.60 | Related concept — read to verify | `GameValProvider.processGameValToml` (0.55) |
| < 0.40 | Noise — treat as loose hints | `LootTable` class (0.03) — see Finding 4 |
| Uniform cluster ~0.55 | Concept likely absent — signal is the uniformity | ResistanceState tests |

This calibration is a significant quality feature. Agents that learn to read score
distributions get reliable guidance without additional tool calls.

**Recommendation:** Preserve RRF + reranker combination behavior that produces this
pattern. Do not normalize scores to a flat [0,1] band — the raw spread is informative.

---

### Finding 4 — BEHAVIOR: Vocabulary mismatch causes sharp score cliff within correct results

**Observed in:** Test 8 (loot table)
**Severity:** Low — correct results present but buried

**Detail:**

Query: `drop table loot NPC drops item reward`

| Rank | Result | Score |
|------|--------|-------|
| 1 | `WeightedTableBuilder` (LootTableDsl.kt) | 0.68 |
| 2 | `addToTable()` | 0.64 |
| 3 | `LootTableBuilder.roll()` | 0.04 ← sharp cliff |
| 4 | `LootTable` class | 0.03 |

The DSL builder class is named `WeightedTableBuilder` and stored in `LootTableDsl.kt`.
The codebase uses none of the query's vocabulary ("drop", "NPC drops", "reward"). BM25
gets no keyword hits for ranks 3-4 despite `LootTableBuilder.roll()` being the actual
execution-time function.

The real `LootTableBuilder.roll()` is the function that executes a roll and returns
ground items — arguably the most important function for the task — but it scores 0.04
because its name and code don't overlap with the query terms.

**Agent impact:** With default `k=5`, ranks 3-4 are always returned. But if an agent
stops reading at the score cliff (0.64 → 0.04), it misses the roll logic. A score of
0.04 on a correct result is a calibration issue — it's not "noise", it's a relevant
function that has zero BM25 overlap with the query.

**Suggested investigation:**
- Is there a floor score below which results are excluded before returning? If so, 0.04
  may be getting filtered in some configurations. Verify that very-low-score results are
  still returned when they are structurally related (same file as a higher-ranked result).
- `max_results_per_file` capping may mitigate this when both `LootTableDsl.kt` and
  `LootTableBuilder.kt` results are relevant — but it wouldn't help here since they're
  different files.

---

### Finding 5 — GOOD: `find_similar_code` correctly surfaces sibling implementations

**Observed in:** Test 11
**Severity:** N/A — working correctly

Using the chunk ID from a `search_code` result for `dealHit`:
```python
find_similar_code("game-plugins/.../PawnExt.kt:67-107:function:dealHit", k=6)
```

Returned (in order): the other `dealHit` overload (0.908), the lower-level `Pawn.hit()`
primitive (0.859), `PawnHit` data class (0.803), two `getMaxHit` implementations (0.786,
0.779), and `getClientHitDelay()` (0.777). All six are genuinely related to combat hit
dispatch.

This tool correctly navigates the embedding space to find alternative implementations,
related primitives, and supporting types — behavior that is hard to get from Grep.
The cross-file jump from `game-plugins/PawnExt.kt` to `game-api/PawnExt.kt` (the
lower-level `hit()`) is especially valuable and demonstrates the embedding space
correctly understands semantic relationship across module boundaries.

---

### Finding 6 — GOOD: `get_graph_context` returns complete, accurate class maps

**Observed in:** Test 12
**Severity:** N/A — working correctly

```python
get_graph_context("content/.../Quest.kt:19-169:class:Quest", max_depth=2)
```

Returned all 10 child symbols (methods + properties) with correct line ranges and
`contains` edges. A subsequent login event query showed `inherits` edges correctly
linking `content/LoginEvent` back to `game-server/LoginEvent`, demonstrating that
cross-file inheritance is tracked accurately in the graph.

The graph is particularly valuable for:
- Planning edits before reading a full file (inventory the method list first)
- Understanding engine → content inheritance chains
- Finding all methods to update when changing an interface contract

No issues observed. The bounded `max_depth` parameter correctly limits the traversal.

---

### Finding 7 — BEHAVIOR: Config-heavy index creates noise for logic searches

**Observed in:** Baseline observation from chunk composition
**Severity:** Low — workaround exists

40.5% of this codebase's chunks are `property` type, mostly from `game-api/cfg/` — a
large constants file. When an agent searches for logic (methods, functions), these
property chunks can occupy result slots, especially for queries that contain terms
present in constant names.

Example: searching for bank deposit logic returns `BANK_KEY = ContainerKey(...)` as
the top result — a useful hint, but not the operation logic the agent asked for.

**Current workaround:** `chunk_type="method"` or `chunk_type="function"` filter
effectively eliminates this noise. This filter works correctly and should be documented
prominently in agent guidance.

**Possible improvement:** When a query contains behavioral verbs ("how do I", "deposit",
"calculate", "spawn"), auto-applying a mild relevance penalty to `property` and
`config_entry` chunks in ranking could improve results without requiring agents to know
about chunk types.

---

### Finding 8 — NOTE: Absent-concept behavior is correct

**Observed in:** Tests 1, 5, 6
**Severity:** N/A — by design, documenting expected behavior

Three tests searched for RSMod-era concepts that don't exist in Victrix-Server
(`everyNthAttack`, `GeneratedWikiDataTomlParser`, `ResistanceState`). In each case:

- The tool returned the nearest conceptual analog with a score of ~0.55–0.86
- No fabricated chunk IDs or hallucinated file paths were returned
- All returned chunks are real, readable code — just not the requested concept

This is correct behavior. The tool does not signal "not found" — it returns the
best available match. Agents must interpret score distribution to infer absence.

**Documentation note:** The server's tool description could note that a uniform
cluster of ~0.55 results is a meaningful signal that the concept may not exist,
and that confirming absence requires a targeted Grep.

---

## 5. Test-by-Test Summary

| # | Tool | Query concept | Verdict | Score |
|---|------|---------------|---------|-------|
| 1 | `search_code` | `everyNthAttack` (absent) | Correct near-miss | 3/5 |
| 2 | `search_code` | Logging pattern + `file_pattern` glob | **BUG** — wrong module | 1/5 |
| 3 | `search_code` | NPC hitpoints accessors | Excellent | 5/5 |
| 4 | `search_code` | Shop storage + content examples | Good | 4/5 |
| 5 | `search_code` | Wiki TOML parser (absent) | False positive at rank 1 | 2/5 |
| 6 | `search_code` | `ResistanceState` (absent) | Correct near-miss | 3/5 |
| 7 | `search_code` | `dealHit` overloads | Excellent | 5/5 |
| 8 | `search_code` | Loot table roll logic | Score cliff buries correct result | 3/5 |
| 9 | `search_code` | Bank deposit/withdraw | Structural result, not behavioral | 3/5 |
| 10 | `search_code` | Quest completion state | Excellent | 5/5 |
| 11 | `find_similar_code` | Similar combat hit functions | Excellent | 5/5 |
| 12 | `get_graph_context` | Quest class map | Excellent | 5/5 |
| **Avg** | | | | **3.67 / 5** |

---

## 6. Token Efficiency

The core question: does the tool save context tokens and produce more accurate agent
edits compared to raw file exploration?

### Baseline (no code search)

To find both `dealHit` overloads without the tool:
1. `Glob("**/*.kt")` → scan hundreds of files for "combat" in path
2. Read `PawnExt.kt` fully (~107 lines + imports)
3. Potentially read 2–3 adjacent combat files to understand context
- **Cost:** ~800–2,000 tokens, 3–5 tool calls

### With code-search

1. `search_code(...)` → exact file + line range (55–65, 67–107)
2. `Read(file, offset=55, limit=53)` — only the relevant lines
- **Cost:** ~150–350 tokens, 2 tool calls

### Estimated savings by task type

| Task type | Savings factor | Notes |
|-----------|---------------|-------|
| Named method/function | **8–50×** | `getCurrentHp`, `dealHit` — pinpoint |
| Class API inventory | **4–8×** | `get_graph_context` eliminates full-file read |
| Cross-layer architecture | **3–6×** | Graph enrichment surfaces inheritance |
| Behavioral/operational | **1.5–3×** | Still better than blind search, but needs follow-up |
| Absent concept | **~1×** | No savings; Grep still required for confirmation |

For well-matched queries the tool is clearly worth the indexing cost. The 6m 55s
full re-index amortizes quickly — incremental runs on file changes are near-instant
(Merkle DAG tracks only modified files).

---

## 7. Summary for Developers

### Confirmed working well — preserve
- Score calibration (0.0–1.0 spread is meaningful, not normalized)
- `find_similar_code` cross-module similarity traversal
- `get_graph_context` containment + inheritance edge accuracy
- BM25 + vector RRF producing diverse result sets
- Incremental indexing (Merkle DAG)
- `.gitignore` + hardcoded ignore rule application
- `max_file_bytes` / `max_file_lines` skip logic with reporting

### Issues to investigate
1. **`file_pattern` `**` glob not filtering by module** (Finding 1) — confirmed bug
2. **High reranker scores on poor semantic matches** (Finding 2) — consider minimum threshold
3. **Score cliff buries correct results in vocab-mismatch cases** (Finding 4) — check
   whether a BM25-0 result with a semantically valid embedding can be rescued

### Potential improvements
4. **Surface raw reranker score** alongside combined RRF score in result objects — gives
   agents and developers visibility into whether the rank is keyword-driven or semantic
5. **Consider mild penalty for `property`/`config_entry` chunks on behavioral queries** —
   would reduce noise in codebases with large constants layers without breaking existing behavior
6. **Tool description: document the absent-concept signal** — "uniform ~0.55 cluster = confirm
   absence with Grep" is useful agent guidance that could live in the tool docstring

---

## 8. Memory Management Recommendations

### Per-codebase MCP activation (user guidance)

Users should **enable this MCP server only for the codebase they are actively working
on** and disable it when switching projects or when the tool is not needed. This is
particularly important for developers multitasking across several codebases
simultaneously.

The reason is model residency: once the embedding and reranker models are loaded into
GPU VRAM or system RAM, they stay there for the entire MCP server session. Running two
or three separate instances of the server — each loading its own model copy — would
multiply that footprint proportionally. On GPU configurations this means VRAM fills up
fast; on CPU configurations RAM pressure builds to the point where the OS starts
paging, which makes everything slow.

Practical steps for users:
- In Claude Code, MCP servers can be toggled per-session with `/mcp` — users should
  get in the habit of disabling `code-search` when switching to a different repo.
- For clients that load MCP servers globally (e.g. Cursor workspace config), scope
  the server to workspace-level config rather than user-level config so it only
  activates when that workspace is open.
- Users running multiple AI coding assistant windows (e.g. two Cursor instances on
  two codebases) should be explicitly warned that each window will spin up its own
  model instance unless the MCP server is globally shared.

**This is worth surfacing prominently in the README's "System Requirements" section**
as a practical usage note, not just a technical footnote.

---

### Future investigation: memory savings for idle sessions

The server currently keeps models resident in GPU/CPU memory for the full duration of
the session regardless of activity. For users who leave the MCP server running across
long stretches of non-coding time (overnight, across meetings, etc.), this is wasteful.
Two directions are worth investigating:

#### Option A — Idle offload within the existing PyTorch setup

Without changing inference backends, several standard PyTorch techniques could reduce
idle memory pressure:

- **Move models to CPU on idle, back to GPU on demand.** After N minutes of no
  `search_code` calls, call `model.to("cpu")` and `torch.cuda.empty_cache()`. On the
  next query, move back to `cuda` before inference. The latency penalty is a one-time
  ~1–3 s reload per query after a cold-idle period, which is acceptable for
  interactive use.

- **`torch.cuda.empty_cache()` after each query.** PyTorch retains the CUDA allocator
  cache even after tensors are freed, which keeps VRAM fragmented and unavailable to
  other processes. Calling `empty_cache()` after each search response releases this
  back to the OS without unloading the model. Low-cost, immediate win.

- **Half-precision loading (`torch.float16` or `bfloat16`).** If models are currently
  loaded in `float32`, switching to `float16` roughly halves model VRAM footprint with
  negligible quality impact for embedding and reranking tasks. Check current dtype in
  the model loading code and add `torch_dtype=torch.float16` to the
  `from_pretrained()` call if not already set.

- **Configurable idle timeout.** Expose a config option (e.g.
  `CODE_SEARCH_IDLE_OFFLOAD_MINUTES=30`) that triggers the CPU offload. Users on
  memory-constrained systems set it low; users on high-RAM workstations leave it
  disabled.

#### Option B — vLLM as inference backend (longer-term investigation)

vLLM is primarily designed for LLM generation throughput, but it includes optimized
memory management features that could be relevant:

- **PagedAttention** — vLLM's KV-cache paging mechanism is specific to generative
  inference and would not apply to embedding models (which don't autoregressively
  generate tokens). This is likely **not beneficial** for the embedding model use case.

- **For the reranker specifically** — the Qwen3-Reranker models are causal LMs
  (generative architecture used in cross-encoder scoring mode). vLLM *can* serve
  these, and its memory pooling and continuous batching could help if many reranking
  requests are queued. However, vLLM's startup cost and daemon model make it a heavier
  dependency than the current `transformers` + PyTorch stack.

- **Practical assessment:** vLLM is most compelling if the server evolves toward
  handling concurrent requests from multiple agents or multiple codebases sharing one
  model server process. For the current single-user, single-session design, the
  PyTorch idle offload approach (Option A) is lower complexity and more immediately
  useful. vLLM is worth revisiting if the server ever adds a shared/daemon mode.

**Recommended priority order:**
1. `torch.cuda.empty_cache()` after each response — zero risk, immediate benefit
2. `float16` model loading — halves VRAM, minimal quality impact
3. Idle CPU offload with configurable timeout — high user value, moderate implementation effort
4. vLLM backend investigation — defer until concurrent/shared-server use case is validated
