# AGENT Context Local — MCP Code Search Evaluation

**Date:** 2026-03-13
**Codebase:** `rsprox` (RSProx OSRS proxy, Kotlin/Gradle multi-project)
**Tool version:** `agent-context-local` v0.9.x (beta)
**Evaluator:** Claude Sonnet 4.6 via Claude Code

---

## 1. Test Environment

| Component | Spec |
|-----------|------|
| GPU | NVIDIA RTX 5080 (16 GB VRAM) |
| CPU | AMD Ryzen 7 9800X3D |
| RAM | 64 GB DDR5 |
| Storage | NVMe SSD |
| OS | Windows 11 Pro |
| Embedding model | `Qwen/Qwen3-Embedding-0.6B` (GPU auto-detected, 1024-d) |
| Reranker | `Qwen3-Reranker-0.6B` (available, not enabled during tests) |
| Device | `cuda:0` |

The tool correctly auto-detected the RTX 5080 and upgraded from the default `mxbai-embed-xsmall-v1`
(384-d, CPU) to `Qwen3-Embedding-0.6B` (1024-d, GPU). This is a meaningful quality upgrade.

---

## 2. Index Build Performance

| Metric | Value |
|--------|-------|
| Files indexed | 4,070 (of 4,155 total; 62 ignored by .gitignore/hardcoded) |
| Chunks indexed | 21,942 |
| Indexing time | **~404 seconds (~6.7 minutes)** |
| Index size on disk | 114.79 MB |
| Chunk throughput | ~54 chunks/sec |
| Graph symbols | 21,464 |
| Graph edges | **1,146,246** (1.1M!) |
| Edge breakdown | calls: 1,036,127 · contains: 16,098 · inherits: 94,021 |
| Sync status | synced |

**Assessment:** 6.7 minutes for a ~4K file Kotlin multi-module project is very fast on GPU hardware.
The graph edge count (1.1M) reflects the highly cross-referenced protocol decoder hierarchy in this
codebase. Cold-start is a one-time cost; subsequent runs are incremental.

**GPU memory observed during indexing:**
- Idle (model loaded, not querying): ~7.1 GB total / 6.9 GB dedicated, ~6% utilization
- Embedding spikes: peaked at ~12 GB GPU memory at highest spike
- GPU utilization remained low overall — the bottleneck is I/O + CPU tokenization, not GPU compute
- This confirms the 0.6B model is extremely lightweight on a 16 GB card; the Qwen3-4B model
  (`qwen-embed-4b`, ~10 GB VRAM) would fit comfortably and would deliver a major quality jump

**Chunk type breakdown:**
- `property`: 9,388 — largest category, driven by data model classes
- `method`: 6,933
- `class`: 3,938
- `config_section`: 397 — YAML/TOML structured files parsed correctly
- `enum`: 119, `interface`: 86

---

## 3. Test Battery Results

### T1 — Architecture Discovery: Main Entry Point

**Query:** `"proxy launcher main entry point startup"` (chunk_type=function)

| Rank | File | Score | Vector | Assessment |
|------|------|-------|--------|------------|
| 1 | `installer/liblauncher/elevation.cpp` | 0.60 | 0.48 | C++ JNI elevation launcher — relevant but secondary |
| 2 | `installer/native/src/win32/packr_win32.cpp` | 0.60 | 0.55 | Native Windows entry point — relevant |
| 3 | `gui/proxy-tool/.../ProxyToolGui.kt:main` | 0.59 | 0.58 | **Primary Kotlin entry point** |

**Verdict:** ⚠️ Partial pass. The primary Kotlin `main()` was found (rank 3) but ranked behind native
C++ launchers. The query was vague — more specific queries ("ProxyToolGui main function") reliably
surface the Kotlin entry point first. Score range (0.41–0.60) correctly signals moderate confidence.

---

### T2 — Domain-Specific: RSA Key Decryption

**Query:** `"RSA key decryption login packet"`

| Rank | File | Score | Vector | Assessment |
|------|------|-------|--------|------------|
| 1 | `proxy/.../RsaKeyProvider.kt:readOrGenerateRsaKey` | **0.91** | 0.55 | Primary RSA key lifecycle ✓ |
| 2 | `proxy/.../ClientLoginHandler.kt:invalidRsa` | 0.87 | 0.62 | RSA failure handler in login path ✓ |
| 3 | `transcriber/.../SessionTracker.kt:onServerPacket` | 0.78 | 0.55 | Tangentially related |
| 4 | `proxy/.../LoginServerProtId.kt:INVALID_LOGIN_PACKET` | 0.48 | 0.63 | Login protocol constants ✓ |

**Verdict:** ✅ Excellent. Top 2 results are exactly the right places. Score 0.91 signals high
confidence correctly. Graph relationships on result #1 show the full call chain:
`ProxyService.loadRsa` → `readOrGenerateRsaKey` → `Rsa.readPrivateKey` — giving an agent the full
context from a single query result.

**Token insight:** This one search result returned the complete RSA subsystem context (key loading,
validation, generation, login failure handling) without reading any files. A grep/file-browsing
approach would have required opening 4–6 files.

---

### T3 — Protocol Versioning: Packet Decoder Classes

**Query:** `"incoming game packet decoder handler"` (chunk_type=class)

| Rank | File | Score | Assessment |
|------|------|-------|------------|
| 1–5 | `MessageGameDecoder` (osrs-225, 229, 231, 234, 223) | 0.99 | All identical, different versions |

**Verdict:** ⚠️ Critical pattern identified: **multi-version flooding**. This codebase maintains
protocol decoders across 14+ OSRS revision submodules (osrs-223 through osrs-236+). Because each
decoder is nearly byte-for-byte identical across versions, all 14 versions of any given decoder
score identically and flood the top-k results.

**Impact:** For a k=5 query, an agent may receive 5 results that are semantically the same file
from different protocol versions. Useful results get buried.

**Recommended mitigation:** Use `file_pattern="protocol/osrs-233/**/*.kt"` to pin to the revision
relevant to the EchosReforged fork, or `max_results_per_file=1` (not available — but filtering by
version pattern is the correct strategy).

---

### T4 — Cross-Concept: XTEA Keys

**Query:** `"XTEA cipher decryption game session keys"`

| Rank | File | Score | Vector | Assessment |
|------|------|-------|--------|------------|
| 1–5 | `RebuildWorldEntityV3Decoder` (multiple versions) | 0.99 | 0.51 | Map rebuild packet decoder |

**Verdict:** ✅ Semantically correct despite looking surprising. In OSRS protocol, XTEA keys are
transmitted in the `RebuildNormal`/`RebuildWorldEntity` server packets to decrypt map regions.
Finding `RebuildWorldEntityV3Decoder` for an XTEA query is accurate domain knowledge. The RRF
fusion elevated a BM25 keyword match (likely "keys") combined with moderate vector similarity to
0.99. This demonstrates hybrid search surfacing domain-specific context that pure vector or pure
keyword search might miss. Multi-version flooding is again present.

---

### T5 — Core Orchestrator Class

**Query:** `"ProxyService session management client server bridge"` (chunk_type=class)

| Rank | File | Score | Assessment |
|------|------|-------|------------|
| 1 | `proxy/.../ProxyService.kt` (lines 85–1116) | 0.73 | ✓ The 1,031-line main orchestrator |
| 2 | `proxy/.../ProxyConnectionContainer.kt` | 0.17 | Relevant but low rank |
| 3–5 | `LogoutDecoder` variants | 0.06 | Unrelated — version flooding |

**Verdict:** ✅ Passed for result #1. The main `ProxyService` class was correctly identified.
The sharp drop from 0.73 to 0.17 and 0.06 correctly communicates that only the first result is
truly relevant. Score cliff detection works.

---

### T6 — Complex Multi-Concept: Transcription Pipeline

**Query:** `"transcriber binary blob replay file format write read"`

| Rank | File | Score | Assessment |
|------|------|-------|------------|
| 1 | `proxy/.../TranscribeCommand.kt:fileTranscribe` | **1.0** | Full CLI transcription pipeline ✓ |
| 2 | `proxy/.../BinaryToStringCommand.kt:simpleTranscribe` | 0.99 | Simpler variant ✓ |
| 3 | `README.md` section "Transcribing" | 0.68 | Documentation surfaced alongside code |
| 4 | `proxy/.../DecodingSession.kt` | 0.33 | Underlying decode engine ✓ |
| 5 | `proxy/.../BinaryBlob.kt:decode` | 0.28 | Binary format reader ✓ |

**Verdict:** ✅ Excellent. Score 1.0 on the first result. Critically, **result #3 surfaced the
README documentation section** alongside code — this is a major UX advantage. An agent can get
oriented on what a feature does (README) and where it lives (code) from a single query. The graph
relationships on result #4 also expose all callers of `DecodingSession`, mapping the full pipeline.

---

### T7 — File-Pattern Filtered: Netty Bootstrap

**Query:** `"Netty channel pipeline bootstrap server bind"` (file_pattern=`proxy/**/*.kt`)

| Rank | File | Score | Assessment |
|------|------|-------|------------|
| 1 | `proxy/.../BootstrapFactory.kt:createClientBootstrap` | 0.65 | ✓ |
| 2 | `proxy/.../ServerConnectionInitializer.kt` | 0.41 | ✓ |
| 3 | `ServerConnectionInitializer:initChannel` | 0.23 | ✓ |
| 4 | `BinaryBlob.kt:serverChannel` property | 0.12 | Tangential |
| 5 | `ServerRelayHandler.kt` | 0.07 | ✓ but low score |

**Verdict:** ✅ File pattern filtering works correctly — all results are within `proxy/`. The
`BootstrapFactory` is correctly ranked #1. Score range (0.07–0.65) accurately shows diminishing
relevance. The graph on `ServerConnectionInitializer` shows it is called by `createClientBootstrap`,
building the correct mental model.

---

### T8 — Cross-Protocol Domain: Inventory Updates

**Query:** `"widget inventory item interaction client packet"` (file_pattern=`protocol/**/*.kt`, chunk_type=class)

| Rank | Files | Score | Assessment |
|------|-------|-------|------------|
| 1–5 | `UpdateInvFullDecoder` (osrs-228, 225, 232, 226, 231) | 0.85 | Correct decoder type, version flooding |

**Verdict:** ✅ Semantically correct. The query for "widget inventory item interaction" correctly
mapped to `UpdateInvFull` (the server packet that fully refreshes an inventory widget). Multi-version
flooding again consumes all 5 results. The `max_results_per_file` parameter is strongly recommended
for this codebase but is not per-filename — it's per `file_path`. Since each version IS a different
file, `max_results_per_file` doesn't help here. This is a structural limitation for versioned codebases.

---

### T9 — Score Calibration: Nonsense Query

**Query:** `"spaghetti noodle algorithm database schema migration"`

| Rank | File | Score | Vector |
|------|------|-------|--------|
| 1 | `IndexerTranscriber.kt:ifMoveSub` | **0.01** | 0.39 |
| 2–5 | Various `NpcInfoClient.kt:Npc` variants | **0.00** | 0.38 |

**Verdict:** ✅ Excellent calibration. The tool correctly returns scores of 0.0–0.01 for a
completely nonsensical query. There is no false-positive inflation. An agent can trust that
scores below ~0.15 mean "no real match found." The threshold for actionable results is around
≥0.40 (vector) / ≥0.50 (RRF combined).

---

### T10 — Structural Similarity: RSA Key Methods

**Reference chunk:** `proxy/.../Rsa.kt:readPublicKey`

| Rank | File | Similarity | Assessment |
|------|------|------------|------------|
| 1 | `Rsa.kt:readPrivateKey` | **0.926** | Structural twin ✓ |
| 2 | `Rsa.kt:readPublicKey(path)` | 0.869 | Overload variant ✓ |
| 3 | `Rsa.kt:readPrivateKey(path)` | 0.806 | Path-based overload ✓ |
| 4 | `RsaKeyProvider.kt:readOrGenerateRsaKey` | 0.761 | High-level caller ✓ |
| 5 | `Rsa.kt:readSinglePemObject` | 0.740 | Shared helper ✓ |

**Verdict:** ✅ Outstanding. All 5 results are precisely correct and represent the complete RSA
subsystem in order of structural similarity. Scores ≥0.80 match the documented "same pattern/interface"
threshold. This tool is ideal for "show me all places doing similar I/O pattern" refactoring work.

---

### T11 — Configuration Discovery: Proxy Targets

**Query:** `"proxy target configuration jav_config revision modulus port"`

| Rank | File | Score | Assessment |
|------|------|-------|------------|
| 1 | `ProxyService.kt:loadProxyTargetConfigs` | **1.0** | Config loading entry point ✓ |
| 2 | `ProxyService.kt:mapToProxyTargetConfig` | 0.99 | YAML→domain model mapping ✓ |
| 3 | `ProxyService.kt:currentProxyTarget` property | 1.0 | Config property ✓ |
| 4 | `docs/examples/proxy-targets.sample.yaml` | 0.99 | Sample config file ✓ |
| 5 | `README.md` section "Setting Up Custom Targets" | 0.99 | Documentation ✓ |

**Verdict:** ✅ Outstanding. Scores of 1.0 and 0.99 across the board. The tool surfaced:
code logic + data model + sample config + README section all in one query. This is the ideal
result for a developer asking "how does proxy target configuration work?"

---

### T12 — Authentication Flow: Jagex Account OAuth

**Query:** `"Jagex account authentication login token OAuth"` (file_pattern=`proxy/**/*.kt`)

| Rank | File | Score | Assessment |
|------|------|-------|------------|
| 1 | `DefaultJagexAccountStore.kt:AUTH_GAME_SESSION_BASE` URL | 0.99 | Auth endpoint constant ✓ |
| 2 | `ProxyService.kt:jagexAccountStore` property | 0.79 | Account store dependency ✓ |
| 3 | `DefaultJagexAccountStore.kt:refreshSessionId` | 0.78 | Token refresh method ✓ |
| 4 | `DefaultJagexAccountStore.kt` companion object | 0.76 | Constants block ✓ |
| 5 | `RSProx.kt:JAGEX_ACCOUNTS_FILE` | 0.42 | Accounts file path ✓ |

**Verdict:** ✅ Excellent. All 5 results are directly relevant to Jagex account auth handling.
The URL constant `https://auth.jagex.com/game-session/v1` at score 0.99 gives an agent immediate
orientation on where the external dependency is.

---

## 4. Graph Context Tool: Critical Finding

**Test:** `get_graph_context(chunk_id="proxy/.../RsaKeyProvider.kt:readOrGenerateRsaKey", max_depth=2)`

**Result:** The tool **returned 63,700 characters of output**, exceeding Claude Code's inline limit
and requiring file-based retrieval.

**Root cause:** This codebase has **1,146,246 graph edges**, predominantly `calls` relationships.
At `max_depth=2`, the traversal explodes combinatorially — a node with 10 outgoing calls, each
having 10 calls, generates 110+ edges at depth 2. In a highly interconnected Kotlin codebase this
cascades rapidly.

**Practical guidance for agents using this codebase:**
- Use `max_depth=1` to stay manageable: `get_graph_context(chunk_id=..., max_depth=1)`
- Reserve `get_graph_context` for architecture-level classes only (prefer `search_code` which
  already includes lightweight graph hints)
- The graph hints included in `search_code` results (relationships field) are often sufficient

**This is the most significant usability issue found in this evaluation.**

### Recommended Fix for the Graph Overflow Issue

The root problem is that `get_graph_context` returns the **full raw edge list** at each depth
level with no server-side pruning. At depth=2 on a 1.1M-edge graph, the result can include
thousands of edges even for a moderately connected node.

**Best resolution — server-side result capping with relevance pruning:**

The ideal fix would be for the tool itself to implement a bounded traversal that:
1. Caps total edges returned (e.g., `max_edges=50` parameter, default 30)
2. Prioritizes edge types by signal value: `contains` > `inherits` > `calls`
   (structural containment is almost always more useful than call graph noise)
3. Deduplicates versioned paths — if 10 `inherits` edges point to structurally identical
   files in `protocol/osrs-223` through `protocol/osrs-233`, collapse them to one representative
   with a `(+9 similar)` annotation

Until that is implemented, the agent-side workaround is: **always use `max_depth=1`** and rely
on the lightweight graph hints already embedded in `search_code` results (the `relationships`
field is pre-bounded and is sufficient for most navigation tasks).

---

## 5. Token Efficiency Analysis

### Baseline: Traditional Approach (grep + file reads)

To answer "How does RSA key loading work in RSProx?", a traditional approach would require:
1. `grep -r "rsa\|RSA" proxy/src/ --include="*.kt"` → scan results (~50+ matches)
2. Read `RsaKeyProvider.kt` (~25 lines)
3. Read `Rsa.kt` (~311 lines, to understand key methods)
4. Read `ClientLoginHandler.kt` (~441 lines, to understand error handling)
5. Maybe read `ProxyService.kt:loadRsa` (1116 lines total)

**Estimated tokens consumed:** ~5,000–8,000 tokens (reading full files)

### With `search_code`

Query: `"RSA key decryption login packet"`

**Result:** 5 chunks returned, each with:
- File path + line range
- 1-line snippet showing exact method signature
- Graph relationships showing call chain

**Estimated tokens:** ~2,000–3,000 tokens (compact result set)

**Outcome:** The agent gets the key files, line ranges, and call chain without reading any files.
If a specific method body is needed, `Read` with offset/limit is targeted rather than reading the
full file. Token savings: **50–75% on orientation queries.**

For a complex codebase like rsprox (1,031-line `ProxyService.kt`), this is substantial.

### Where the savings are smallest

For highly version-duplicated queries (T3, T4, T8), the agent receives 5 near-identical results
pointing to different protocol versions. The useful information density per result is low. Here the
tool provides less value — the agent must add `file_pattern` filtering to recover value.

---

## 6. Codebase-Specific Patterns & Findings

### 6.1 The Multi-Version Protocol Problem

RSProx maintains packet decoders for **14+ OSRS revisions** (osrs-223 through osrs-236+) in
parallel module trees. The structural pattern is:
```
protocol/osrs-{N}/src/main/kotlin/net/rsprox/protocol/v{N}/game/
    outgoing/decoder/codec/{category}/{PacketName}Decoder.kt
    incoming/decoder/codec/{category}/{PacketName}Decoder.kt
```

Each version's decoder is nearly identical to adjacent versions. This creates a "false diversity"
in search results — every query for a specific decoder type returns 14 near-identical files.

**Recommended workaround for this project:** Always specify `file_pattern="protocol/osrs-233/**"`
when doing protocol-level work for EchosReforged (revision 233).

### 6.2 Inheritance Graph as Version Tracking

The graph `inherits` edges (94,021 total) encode the version evolution chain. When a decoder in
osrs-223 inherits from osrs-224, it means the v224 decoder copied from v223. The graph context
tool could theoretically trace the evolution of a decoder across versions via inheritance — but
the token explosion at depth=2 makes this impractical.

### 6.3 README + Code Co-surfacing

Multiple queries (T6, T11) retrieved README sections alongside code at high scores. This is
genuinely useful — an agent can get the "what is this" (documentation) and "where is it" (code)
from a single query. Most tools only search code.

### 6.4 Score Interpretation Guide (this codebase)

| Combined Score | Interpretation |
|----------------|----------------|
| ≥ 0.90 | Near-certain match. Trust immediately. |
| 0.70–0.89 | Strong match. One of the right places. |
| 0.50–0.69 | Moderate. Worth reading but may need refinement. |
| 0.20–0.49 | Weak. Likely tangential. |
| < 0.20 | Poor match. Discard. |

The vector_score field is informative separately:
- vector_score ≥ 0.60 = semantically on-topic
- vector_score 0.50–0.59 = keyword overlap driving the result

---

## 7. Verdict

### Overall Rating: **8.5 / 10**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Index quality | 9/10 | Correct structure, fast GPU indexing, synced |
| Semantic accuracy | 9/10 | Most queries return correct results; cross-concept queries (XTEA) work surprisingly well |
| Score calibration | 10/10 | Nonsense returns 0.0; high confidence correctly shown at ≥0.87 |
| Token efficiency | 8/10 | 50–75% savings on orientation queries; less effective for versioned code |
| Graph context | 5/10 | Critical overflow issue at depth=2; depth=1 is safe |
| Similarity search | 10/10 | Structural twins found with 0.92+ scores |
| File pattern filtering | 9/10 | Works correctly; essential for this versioned codebase |
| Multi-version handling | 4/10 | Version flooding is a real problem for protocol decoder queries |
| README/doc surfacing | 9/10 | Excellent — surfaces docs alongside code |
| Agent workflow fit | 8/10 | Tool calls are fast; graph overflow needs documented workaround |

### Strengths

1. **Semantic search is genuinely useful.** Domain-specific queries like "RSA key decryption login
   packet" immediately surface the exact subsystem with relationship context.
2. **Score calibration is honest.** The 0.0 nonsense score means agents can threshold-filter
   results without hallucinating relevance.
3. **Hybrid BM25 + vector fusion pays off.** The XTEA query found the correct OSRS-domain context
   because keyword ("keys") combined with vector similarity found the right decoder.
4. **Incremental indexing** means agents can ask to re-index after edits without paying the full
   6.7-minute cost — only changed files re-process.
5. **find_similar_code is excellent** for finding duplicate patterns, refactoring targets, and
   understanding API shapes.

### Weaknesses / Honest Concerns

1. **Multi-version flooding.** In versioned codebases, k=5 results often means 5 copies of the
   same decoder from different protocol versions. Agents must apply file_pattern discipline.
2. **get_graph_context overflows** on highly connected nodes at depth ≥ 2. This makes one of the
   most interesting features (structural traversal) practically unusable without care.
3. **ProxyToolGui.kt ranked #3** behind C++ launchers for the main entry point query. Native code
   in the same repo competes with Kotlin code for "launcher" queries.
4. **graph relationship noise in results.** Each result includes 10 graph relationships, many of
   which point to version-duplicated methods (e.g., `inherits` pointing to 10 identical decoder
   versions). This adds token cost without signal.

### Recommendation for EchosReforged Use

Add to `CLAUDE.md`:
```markdown
## Code Search

This project has a local semantic code index. Use `search_code` before browsing files.
For protocol work: **always add `file_pattern="protocol/osrs-233/**"` to filter to revision 233**.
Use `max_depth=1` for `get_graph_context` to avoid token overflow.
```

---

*Generated by Claude Sonnet 4.6 via structured test battery on 2026-03-13.*
