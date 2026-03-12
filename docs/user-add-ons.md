# User Add-Ons — Research Findings & Action Plan

---

## Implementation Session Guide

This document is designed to be handed to agents session-by-session. The work is split into four sessions based on which areas of the codebase are touched, with dependency ordering noted so parallel sessions don't create merge conflicts.

### Session Map

```
Session A (Backend: Concurrency)     Session B (Chunking: Tier 1 + Fixes)
  Item 1 — full scope                  Item 2 Tier 1 — Bash, PowerShell, HTML, CSS
  ├─ incremental_indexer.py             Item 3 — Java records, Go generics,
  ├─ code_search_server.py                       TOML accuracy, JSX detection
  ├─ common_utils.py                   ├─ chunking/languages/*.py (new + fixes)
  └─ pyproject.toml (filelock)         ├─ chunking/available_languages.py
                                       ├─ chunking/languages/__init__.py
  Can run in PARALLEL with B           ├─ chunking/structured_data_chunker.py
                                       ├─ pyproject.toml (new grammars)
         │                             └─ tests/
         │
         ▼                             Can run in PARALLEL with A
Session C (Search Improvements)                  │
  Item 4 — full scope                            ▼
  ├─ search/searcher.py              Session D (Chunking: Tier 2 + 3)
  ├─ search/indexer.py                 Item 2 Tier 2 — Angular, Ruby, PHP,
  ├─ mcp_server/code_search_server.py            Swift, SQL, Vue
  └─ README.md                         Item 2 Tier 3 — Terraform/HCL, Scala,
                                                 Dart, Lua, Elixir, etc.
  Run AFTER Session A                  ├─ Same file pattern as Session B
  (both touch code_search_server.py)   └─ Follows patterns established in B

                                       Run AFTER Session B
                                       (same directory, follows established patterns)
```

### Session Details

| Session | Scope | Sections to Reference | Can Parallelize With | Run After |
|---------|-------|-----------------------|---------------------|-----------|
| **A** | Concurrency safety: file locks, global embedding semaphore, `filelock` dependency | Item 1 (all phases) | Session B | — (start anytime) |
| **B** | Tier 1 languages (Bash, PowerShell, HTML, CSS) + chunker accuracy fixes (Java records/sealed, Go generics, TOML line accuracy, JSX detection) | Item 2 (Tier 1 only) + Item 3 (all priorities) | Session A | — (start anytime) |
| **C** | Search improvements: query preprocessing, refine_factor config, BM25 research, document code-specific model option | Item 4 (all priorities) | Session D | Session A |
| **D** | Tier 2 + 3 languages: Angular, Ruby, PHP, Swift, SQL, Vue, Terraform/HCL, Scala, Dart, Lua, Elixir, Haskell, Protobuf | Item 2 (Tiers 2 + 3 only) | Session C | Session B |

### Notes for Agents

- **Session B is the largest** — ~4 new language chunkers + 4 accuracy fixes across existing chunkers. All work is in `chunking/` and `tests/`. Each new language follows the same pattern: add dependency to `pyproject.toml`, create `chunking/languages/<lang>_chunker.py`, register in `__init__.py` and `available_languages.py`, add test data.
- **Session D is repetitive but high volume** — up to ~10 new languages, all following the exact patterns established in Session B. The agent should reference Session B's completed work as templates.
- **pyproject.toml conflict note** — Sessions A and B both add dependencies to `pyproject.toml` (A adds `filelock`, B adds tree-sitter grammars). These are in different sections of the file and unlikely to conflict, but if running truly in parallel, the agent should be aware.
- Each section below contains research findings, specific file paths, line numbers, and concrete action items. The agent does not need to re-investigate — go straight to implementation.

---

## 1. Embedding Model & Indexing Safety (Concurrency Protection)

### Original Concern

Multiple AI agents could simultaneously trigger indexing on separate workspaces, overwhelming local resources. Initial indexing is resource-intensive; we need safety so the package doesn't freeze a user's PC. Incremental indexing (lightweight) should not be blocked.

### Research Findings

**Current State: No concurrency protection exists.**

- No file locks, mutexes, semaphores, or "busy" flags anywhere in the codebase.
- The MCP server (`mcp_server/server.py`) is a single-threaded asyncio event loop per process. Claude Code spawns **one MCP server subprocess per session**, so two Claude Code sessions = two separate MCP server processes, each with its own embedder loaded into memory.
- The embedder is lazy-loaded once via `@lru_cache(maxsize=1)` in `mcp_server/code_search_server.py:147-159` and reused for all operations within that process.
- LanceDB (vector store) is serverless/filesystem-based — concurrent reads are safe, but **concurrent writes to the same project index from two processes will corrupt the index**.
- SQLite graph DB uses WAL mode (`graph/code_graph.py:82`) — concurrent reads safe, writes serialized per connection, but two processes writing simultaneously is still dangerous.
- The Merkle snapshot consistency barrier (only advances when both vector + graph succeed) is good, but doesn't prevent two processes from racing.

**Resource Profile:**

| Operation | CPU | RAM | Disk I/O | Time (typical) |
|-----------|-----|-----|----------|----------------|
| **Initial index** (large repo, 10K files) | Heavy (chunking + embedding) | 1–5 GB | Write burst | 5–30 min |
| **Incremental index** (5 files changed) | Minimal | 100–500 MB | Small write | < 5 sec |
| **Search query** | Low (embed query + ANN) | ~200 MB | Read | < 1 sec |

**Risk Scenarios:**
1. **Two agents index the same workspace simultaneously** → index corruption (HIGH risk)
2. **Two agents index different workspaces simultaneously** → both embedders in memory, 2x RAM/VRAM usage (MEDIUM risk on low-memory machines)
3. **Agent searches while another indexes same workspace** → stale/partial results (LOW risk, self-healing on next incremental)
4. **Multiple rapid search queries** → single-threaded MCP handles sequentially, no risk

### vLLM Investigation — Verdict: NOT Appropriate

**vLLM is designed for serving generative large language models (text generation), not embedding models.** Key findings:

- vLLM's own documentation states that pooling/embedding model support "is not guaranteed to provide any performance improvements over using Hugging Face Transformers or Sentence Transformers directly."
- There are active compatibility bugs — embedding outputs differ between vLLM and Sentence Transformers for several models (GitHub issues #16892, #17493, #26945).
- Our default embedding model (`mxbai-embed-xsmall-v1`, 22.7M params) is tiny — vLLM's optimizations (PagedAttention, continuous batching, tensor parallelism) are designed for billion-parameter generative models and provide no benefit here.
- vLLM would add a heavy dependency (CUDA toolkit, ~2GB install), require a running server process, and introduce network latency — all for zero performance gain on a 22.7M parameter embedding model.
- Even for GPU models (Qwen3-Embedding-0.6B/4B), Sentence Transformers' `.encode()` with batching is already optimal for embedding workloads.

**Our current setup (Sentence Transformers with `@lru_cache` singleton) is the correct architecture for this use case.** The issue is not inference speed — it's concurrency safety.

### Action Plan

**Phase 1: Project-Level File Lock for Initial Indexing** (Priority: HIGH)

Add a cross-platform file lock using the `filelock` library (pure Python, no native deps, works on Windows/macOS/Linux):

- **Where**: `search/incremental_indexer.py` — wrap `_full_index()` with a file lock on the project storage directory (e.g., `~/.agent_code_search/projects/{project_hash}/.indexing.lock`).
- **Behavior**: If another process holds the lock, return immediately with a message: `"Indexing is already in progress for this workspace. Please try again later."`
- **Scope**: Only lock on **initial (full) indexing**. Incremental indexing is fast enough that brief serialization is acceptable — use a non-blocking try-lock with a short timeout (e.g., 5 seconds).
- **Dependency**: Add `filelock>=3.13` to `pyproject.toml` (zero transitive deps, widely used).

**Phase 2: Global Embedding Semaphore** (Priority: MEDIUM)

Prevent multiple simultaneous heavy embedding operations across different projects:

- **Where**: `mcp_server/code_search_server.py` — add a system-wide lock file (e.g., `~/.agent_code_search/.embedding.lock`) that limits concurrent initial indexing to one project at a time across all MCP server instances.
- **Behavior**: Second process attempting initial index gets: `"The embedding model is currently in use indexing another workspace. Please try again later."`
- **Search is never blocked** — only initial indexing contends for this lock.

**Phase 3: Resource-Aware Batch Sizing** (Priority: LOW, nice-to-have)

Currently `batch_size=32` is hardcoded in `embeddings/embedder.py:261`. Could be made adaptive:
- Detect available system RAM / GPU VRAM
- Scale batch size accordingly (e.g., 16 for 4GB RAM, 64 for 32GB+)
- Not critical since the default model is tiny, but helpful for GPU models.

**Files to Modify:**
- `search/incremental_indexer.py` — add file lock around `_full_index()` and `incremental_index()`
- `mcp_server/code_search_server.py` — add global embedding semaphore
- `pyproject.toml` — add `filelock>=3.13` dependency
- `common_utils.py` — helper to get lock file paths

---

## 2. Language Support Expansion

### Original Concern

Ensure we cover the popular coding languages beyond our current set.

### Research Findings

**Currently Supported (13 programming languages + 3 structured data + Markdown):**

| Language | Tree-Sitter Package | Extensions | Status |
|----------|-------------------|------------|--------|
| Python | `tree-sitter-python>=0.23.6` | `.py` | Full support |
| JavaScript | `tree-sitter-javascript>=0.25.0` | `.js` | Full support |
| JSX | `tree-sitter-javascript>=0.25.0` | `.jsx` | Full support |
| TypeScript | `tree-sitter-typescript>=0.23.2` | `.ts` | Full support |
| TSX | `tree-sitter-typescript>=0.23.2` | `.tsx` | Full support |
| Go | `tree-sitter-go>=0.25.0` | `.go` | Full support |
| Rust | `tree-sitter-rust>=0.24.0` | `.rs` | Full support |
| Java | `tree-sitter-java>=0.23.5` | `.java` | Full support |
| Kotlin | `tree-sitter-kotlin>=1.1.0` | `.kt`, `.kts` | Full support (excellent) |
| C | `tree-sitter-c>=0.24.1` | `.c` | Full support |
| C++ | `tree-sitter-cpp>=0.23.4` | `.cpp`, `.cc`, `.cxx`, `.c++` | Full support |
| C# | `tree-sitter-c-sharp>=0.23.1` | `.cs` | Full support |
| Svelte | `tree-sitter-svelte>=1.0.2` | `.svelte` | Full support |
| Markdown | `tree-sitter-markdown>=0.3.2` | `.md` | Full support (header-based sections, preamble, heading levels) |
| JSON | Python `json` stdlib | `.json` | Stdlib parser (no tree-sitter) |
| YAML | `PyYAML>=6.0` | `.yaml`, `.yml` | Stdlib parser (no tree-sitter) |
| TOML | Python `tomllib` (3.11+) | `.toml` | Stdlib parser (no tree-sitter) |

**Unsupported files are silently skipped** — no fallback chunking. `TreeSitterChunker.get_chunker()` returns `None` and the file is excluded from the index entirely.

**Gap Analysis — Missing Popular Languages:**

| Language | Popularity | PyPI Package Available | Effort | Priority |
|----------|-----------|----------------------|--------|----------|
| **PowerShell** | High (Windows/DevOps) | No standalone PyPI pkg — available via `tree-sitter-language-pack` or build from [PowerShell/tree-sitter-PowerShell](https://github.com/PowerShell/tree-sitter-PowerShell) | Medium | **High** |
| **Shell/Bash** | High (DevOps, scripts) | `tree-sitter-bash` ✅ | Low | **High** |
| **HTML** | Very High (web) | `tree-sitter-html` ✅ | Low | **High** |
| **CSS** | Very High (web) | `tree-sitter-css` ✅ | Low | **High** |
| **Angular** | High (web framework) | No standalone PyPI pkg — grammar at [dlvandenberg/tree-sitter-angular](https://github.com/dlvandenberg/tree-sitter-angular). Note: Angular component logic is TypeScript (already supported); templates are HTML (covered by adding HTML support) | Medium | Medium |
| **Ruby** | High (Rails ecosystem) | `tree-sitter-ruby` ✅ | Low — follow existing chunker pattern | Medium |
| **PHP** | High (WordPress, Laravel) | `tree-sitter-php` ✅ | Low | Medium |
| **Swift** | High (iOS/macOS) | `tree-sitter-swift` ✅ | Low | Medium |
| **SQL** | High (data/backend) | `tree-sitter-sql` ✅ | Low | Medium |
| **Vue** | High (web framework) | `tree-sitter-vue` ✅ | Medium (multi-language like Svelte) | Medium |
| **Terraform/HCL** | Medium (IaC) | `tree-sitter-hcl` ✅ (covers both `.tf` and `.hcl` — one grammar) | Low | Low |
| **Scala** | Medium (JVM, Spark) | `tree-sitter-scala` ✅ | Low | Low |
| **Dart** | Medium (Flutter) | `tree-sitter-dart` ✅ | Low | Low |
| **Lua** | Medium (game dev) | `tree-sitter-lua` ✅ | Low | Low |
| **Elixir** | Medium (Erlang VM) | `tree-sitter-elixir` ✅ | Low | Low |
| **Haskell** | Low-Medium | `tree-sitter-haskell` ✅ | Low | Low |
| **Protobuf** | Medium (gRPC) | `tree-sitter-protobuf` ✅ | Low | Low |
| **Dockerfile** | Medium (containers) | N/A (simple format) | Could use structured data approach | Low |

**Architecture Note:** Adding a new language follows a consistent pattern:
1. Add `tree-sitter-<lang>` to `pyproject.toml`
2. Create `chunking/languages/<lang>_chunker.py` (define splittable node types + metadata extraction)
3. Register in `chunking/languages/__init__.py` (LANGUAGE_MAP)
4. Register in `chunking/available_languages.py`
5. Add test data in `tests/test_data/multi_language/`

Each new language is roughly ~50-150 lines of code following the existing pattern.

### Action Plan

**Tier 1 — Add First (High Impact, common in nearly all projects):**
- **Shell/Bash** (`.sh`, `.bash`, `.zsh`) — every project has scripts
- **PowerShell** (`.ps1`, `.psm1`, `.psd1`) — Windows automation/DevOps. No standalone PyPI package exists yet, but the official grammar is at [PowerShell/tree-sitter-PowerShell](https://github.com/PowerShell/tree-sitter-PowerShell). Options: (a) build from source and vendor the `.so`/`.dll`, (b) use `tree-sitter-language-pack` which bundles it, or (c) wait for a dedicated PyPI release. Given this project already has PowerShell install scripts (`scripts/install.ps1`, `scripts/uninstall.ps1`), PowerShell support is directly relevant to our own users.
- **HTML** (`.html`, `.htm`) — web development staple
- **CSS** (`.css`, `.scss`, `.less`) — companion to HTML

**Tier 2 — Add Next (Popular backend/mobile/framework languages):**
- **Angular** — Angular component logic is TypeScript (`.ts`, already supported). Angular templates use HTML with Angular-specific syntax (control flow, directives). Adding HTML support (Tier 1) covers most Angular template parsing. A dedicated Angular grammar exists at [dlvandenberg/tree-sitter-angular](https://github.com/dlvandenberg/tree-sitter-angular) (extends tree-sitter-html for Angular control flow syntax) but has no PyPI package. **Practical approach:** HTML support covers ~80% of Angular templates; the Angular-specific grammar is a stretch goal if demand warrants it.
- **Ruby** (`.rb`) — Rails ecosystem
- **PHP** (`.php`) — WordPress/Laravel ecosystem
- **Swift** (`.swift`) — iOS/macOS development
- **SQL** (`.sql`) — database queries
- **Vue** (`.vue`) — popular web framework (similar approach to Svelte chunker)

**Tier 3 — Add Later (Infrastructure & Niche):**
- **Terraform/HCL** (`.tf`, `.tfvars`, `.hcl`) — Infrastructure as Code. Uses `tree-sitter-hcl` which covers both HCL (the language) and Terraform (which uses HCL as its config format) — one grammar handles both. Note: Go is already supported for users building Terraform providers/modules in Go; this adds support for the `.tf` config files themselves. Relevant for HashiCorp ecosystem tools (Terraform, Vault, Waypoint, Nomad, Packer).
- Scala, Dart, Lua, Elixir, Haskell, Protobuf

### Performance Impact of Adding Languages — Validated: Zero Degradation

Investigation of the file discovery and chunking pipeline confirms that adding new languages has **no measurable performance impact** on indexing or search:

**How file discovery works (two-pass design):**
1. **Pass 1 — File walk:** `MerkleDAG.build()` (`merkle/merkle_dag.py:203`) recursively walks the directory tree once, respecting `.gitignore`/`.cursorignore` rules. This produces a list of all non-ignored files.
2. **Pass 2 — Extension filter:** `MultiLanguageChunker.is_supported()` (`chunking/multi_language_chunker.py:167`) checks each file's extension against `SUPPORTED_EXTENSIONS`, which is a **Python `set`** built at init time (`line 20`). Set membership is O(1).

**Why adding languages costs nothing:**
- `SUPPORTED_EXTENSIONS` is a `set` — adding 20 more extensions to a set doesn't change lookup time (still O(1) hash lookup).
- `LANGUAGE_MAP` is a `dict` — extension-to-chunker lookup is O(1) regardless of dict size.
- **Tree-sitter grammars load eagerly** at module import (`available_languages.py:12-95`) via try/except — but only if the pip package is installed. Uninstalled grammars are skipped with a debug log and zero overhead.
- **Chunker instances are lazy** — created on first use per extension (`tree_sitter.py:40-43`), stored in a dict cache. A language that's registered but never encountered in the codebase has zero runtime cost.
- The file walk itself (`path.iterdir()`) is the same regardless of how many extensions we support — we walk once, filter inline.

**Bottom line:** Whether we support 17 or 40 file types, the indexing pipeline's performance profile is identical. The only cost is the one-time grammar import at startup (~milliseconds per grammar), and that only applies to grammars that are actually pip-installed.

**Files to Modify (per language):**
- `pyproject.toml` — add tree-sitter grammar dependency
- `chunking/languages/<lang>_chunker.py` — new file (splittable types + metadata)
- `chunking/languages/__init__.py` — register in LANGUAGE_MAP
- `chunking/available_languages.py` — register language binding
- `tests/test_data/multi_language/` — add test files

---

## 3. Tree-Sitter Setup Accuracy & Structured Data Parsing

### Original Concern

Validate that TOML, JSON, YAML, Kotlin, and Java parsing is correct and handles different JDK versions.

### Research Findings

#### TOML, JSON, YAML — NOT Using Tree-Sitter (This Is the Key Finding)

**None of these formats use tree-sitter grammars.** They all use Python stdlib parsers with regex-based line number estimation:

| Format | Parser Used | Line Number Method | Accuracy |
|--------|-----------|-------------------|----------|
| **TOML** | `tomllib` (Python 3.11+ builtin) | Regex: `[table]` and `[[array]]` patterns | Approximate — off by several lines for nested structures |
| **JSON** | `json` (Python builtin) | Regex: `"key"\s*:` pattern matching | Approximate — degrades with deep nesting |
| **YAML** | `PyYAML` (`yaml.safe_load_all()`) | Regex: lines starting with `-` or containing `:` | Approximate — edge cases with flow syntax, anchors |

**The Problem:** Line number estimation uses a "first occurrence" line index built from regex. For complex nested files (e.g., a large `pyproject.toml` with deeply nested dependency tables), the `start_line`/`end_line` on chunks can be off by multiple lines. This means when Claude Code shows a search result from a TOML/JSON/YAML file, the line reference may not point to the exact right location.

**Tree-sitter alternatives exist and are available on PyPI:**
- `tree-sitter-toml` v0.7.0 (Dec 2024) — wheels for Windows/macOS/Linux, CPython 3.9+
- `tree-sitter-json` v0.24.8 — wheels for all platforms
- `tree-sitter-yaml` — available on PyPI

**However, the benefit may be marginal:** Tree-sitter would give exact line numbers and proper AST awareness, but the actual _chunking_ logic for config files (grouping by top-level sections/keys) would remain largely the same. The main improvement is line number precision.

**Recommendation:** The current stdlib approach is functional and fast. Switching to tree-sitter for these formats is a nice-to-have for line accuracy but not critical. If we do switch, prioritize TOML (most likely to have complex nested structures in code projects like `pyproject.toml`, `Cargo.toml`).

#### Kotlin — Excellent (No Issues Found)

The Kotlin chunker (`chunking/languages/kotlin_chunker.py`) is the **most feature-rich** chunker in the codebase:

- **Modern features covered:** Data classes, sealed classes, companion objects, extension functions, suspend/coroutines (`is_async` tag), init blocks, property declarations, secondary constructors
- **KDoc extraction:** Properly extracts documentation from preceding named siblings
- **Modifier parsing:** Handles annotations, class modifiers, function modifiers, visibility modifiers, inheritance modifiers, property modifiers — all mapped to metadata
- **Extension functions:** Detected with receiver type extracted
- **Generics:** `type_parameters` node detection

**Verdict: Kotlin parsing is solid. No changes needed.**

#### Java — Gaps with Modern Features (Java 17+)

The Java chunker (`chunking/languages/java_chunker.py`) handles traditional Java well but has gaps:

**Splittable node types:**
```
method_declaration, constructor_declaration, class_declaration,
interface_declaration, enum_declaration, annotation_type_declaration
```

**What's Missing:**
| Feature | Java Version | Issue |
|---------|-------------|-------|
| **Records** (`record Point(int x, int y)`) | Java 16+ | `record_declaration` NOT in splittable types — records are silently skipped |
| **Sealed classes** (`sealed class Shape`) | Java 17+ | `sealed` modifier NOT detected in metadata |
| **Pattern matching** (`instanceof Pattern p`) | Java 16+ | Not captured (metadata only, not critical) |
| **Text blocks** (`"""..."""`) | Java 15+ | Not captured (metadata only, not critical) |

**JDK Version Handling:** Tree-sitter grammars are **version-agnostic** — they parse syntax, not semantics. `tree-sitter-java` v0.23.5 can parse both JDK 11 and JDK 21+ syntax in the same grammar. The issue is that our chunker doesn't _recognize_ newer node types like `record_declaration`. **Both your JDK 11 client code and JDK 21+ Kotlin server code will parse fine for traditional constructs** — the gap is only that Java records and sealed classes won't appear as separate indexed chunks.

#### Go — Generics Metadata Gap

The Go chunker handles standard Go well but **doesn't extract generics metadata** (Go 1.18+, released 2022). A generic function like `func Min[T constraints.Ordered](a, b T) T` will be chunked correctly as a function, but the type parameters won't appear in metadata. This is a metadata enrichment gap, not a parsing failure.

#### C++ — Good, Concepts Supported

The C++ chunker includes `concept_definition` (C++20) as a splittable type — modern C++ is well-handled. Notable gap: lambda expressions are not separately chunked (they appear as part of their enclosing function's chunk).

#### JSX Component Detection — Fragile

The JSX chunker uses a string-based heuristic to detect React components (checks if function body contains `<` and `jsx` or `return`). This can produce false positives (any function with a `<` comparison) or false negatives. Not critical for indexing but metadata accuracy is weak.

### Action Plan

**Priority 1: Fix Java Record Support** (HIGH — your codebase uses Java 21+)

- Add `record_declaration` to `_get_splittable_node_types()` in `chunking/languages/java_chunker.py`
- Add `sealed` to modifier detection in `extract_metadata()`
- Verify with a test file containing Java 17+ features
- **Effort:** ~15 lines of code changes

**Priority 2: Add Go Generics Metadata** (MEDIUM)

- Extract `type_parameter_list` from function/type declarations in `chunking/languages/go_chunker.py`
- Add `generic_params` to metadata
- **Effort:** ~10 lines

**Priority 3: Improve TOML Line Accuracy** (LOW — nice-to-have)

Two options:
- **Option A (minimal):** Improve the regex line estimation in `structured_data_chunker.py` — add patterns for nested TOML tables, inline tables, multi-line strings
- **Option B (thorough):** Add `tree-sitter-toml` dependency and create a proper tree-sitter TOML chunker. Gives exact line numbers and proper AST. More work (~100 lines + new dependency) but definitive fix.

**Priority 4: Improve JSX Component Detection** (LOW)

- Replace string heuristic with AST check: look for `jsx_element` or `jsx_self_closing_element` nodes in the function body's parse tree rather than string matching.

**Files to Modify:**
- `chunking/languages/java_chunker.py` — add record_declaration, sealed modifier
- `chunking/languages/go_chunker.py` — add generics metadata extraction
- `chunking/structured_data_chunker.py` — improve line estimation or add tree-sitter option
- `tests/test_data/multi_language/Calculator.java` — add Java 17+ test cases
- `tests/test_data/multi_language/calculator.go` — add generic function test cases

---

## 4. Reranker & Hybrid Search Validation

### Original Concern

Validate that our reranker setup and hybrid search follow best practices for code search, and identify any adjustments to improve accuracy for coding-focused use.

### Research Findings

#### Hybrid Search — Well Aligned with Industry Best Practice

**Implementation:** Reciprocal Rank Fusion (RRF) combining BM25 keyword matching (via Tantivy FTS on the `text` column) with vector cosine similarity. This is the same approach used by Elasticsearch, Weaviate, and other production search systems.

**End-to-End Search Flow:**
```
Query → strip whitespace → intent detection → embed query
  → hybrid search (BM25 + vector RRF) or vector-only fallback
  → optional reranking (50 candidates → top k)
  → heuristic re-ranking (type boosts, name matching, path relevance)
  → per-file diversity cap → truncate to k → return results
```

**Key Parameters (current values):**

| Parameter | Value | Location | Assessment |
|-----------|-------|----------|------------|
| Default `k` | 5 | `searcher.py:83` | Reasonable for LLM context windows |
| Max `k` | 100 | `code_search_server.py:336` | Appropriate ceiling |
| `refine_factor` | 5 | `searcher.py:434` | Good — recomputes exact distances on 5x candidates post-ANN |
| `fetch_k` multiplier (filtered) | 10x | `indexer.py:389` | Correct — compensates for WHERE clause filtering ANN candidates |
| Reranker `recall_k` | 50 | `code_search_server.py:285` | Good — broad first pass for reranker diversity |
| Cosine metric | Yes | `indexer.py:356` | Correct for L2-normalized embeddings |

**Documented ~48% retrieval improvement** over vector-only search — this aligns with published RAG benchmarks.

#### Reranker — Solid Two-Stage Pipeline

**Architecture:**
1. **Stage 1:** Hybrid search fetches `recall_k=50` candidates
2. **Stage 2:** CrossEncoder reranks all 50, returns top `k`
3. **Stage 3:** Heuristic boosts dampened by 0.5x when reranker active (so reranker's semantic precision takes priority, heuristics become tiebreakers only)

**Default reranker** (`cross-encoder/ms-marco-MiniLM-L-6-v2`):
- 22.7M params, CPU-friendly, NDCG@10 of 74.30
- Trained on MS MARCO passage retrieval — general purpose, not code-specific
- Scores normalized via sigmoid to [0, 1] range

**GPU reranker** (`Qwen/Qwen3-Reranker-0.6B`):
- Auto-enabled when GPU detected
- MTEB-Code score of 73.42 — has some code awareness
- Uses yes/no token classification via causal LM logits

**Graceful fallback:** If reranker fails, search continues with hybrid results only.

#### Post-Ranking Heuristics — Thoughtful & Code-Aware

The heuristic layer (`searcher.py:255-339`) applies intelligent scoring:

| Heuristic | Boost | Purpose |
|-----------|-------|---------|
| **Chunk type matching** | 1.05x–1.3x | Boosts classes when "class" in query, functions for general queries |
| **Name matching** (exact) | 1.4x | Direct entity lookup (e.g., "UserAuthService") |
| **Name matching** (token overlap) | 1.1x–1.3x | Handles partial matches, CamelCase/snake_case splitting |
| **Path relevance** | +5% per token | File path tokens matching query tokens |
| **Intent tags** | +10% per tag | Detected patterns: error_handling, auth, testing, database, API |
| **Docstring present** | 1.02x–1.05x | Slight preference for documented code |
| **Complexity penalty** | 0.98x | Slight penalty for chunks >1000 chars |

**CamelCase/snake_case handling** is done in the ranking phase (path relevance + name matching) but **NOT in query preprocessing** — this is a gap.

#### What's Working Well

1. **RRF fusion** — industry standard, proven effective
2. **Two-stage retrieval** — broad recall (50) → precise reranking → heuristic polish
3. **AST-aware chunking** — chunks respect code boundaries (functions, classes, methods)
4. **Parent context in embeddings** — methods get class context prefix (`# In Calculator:`)
5. **Smart content truncation** — 6000 char max with head/tail preservation
6. **Heuristic dampening when reranked** — prevents overriding semantic precision
7. **Per-file diversity cap** — pushes excess to end rather than removing, maximizing breadth

#### Gaps & Potential Improvements

**Gap 1: No Code-Specific Query Preprocessing** (Impact: MEDIUM)
- Current: Query is only `.strip()`'d before embedding (`searcher.py:169-176`)
- Missing: CamelCase/snake_case splitting is done in ranking but NOT before embedding
- Example: Query `"getUserById"` would embed as one token. If we also searched for `"get user by id"` the BM25 component could find more matches.
- **Recommendation:** Add optional query expansion: split CamelCase/snake_case tokens and include both original + split form in the BM25 query. Keep the original for vector embedding (models handle concatenated terms fine).

**Gap 2: General-Purpose Embedding Model** (Impact: LOW-MEDIUM)
- Default `mxbai-embed-xsmall-v1` is a general-purpose text embedding model, not code-specific
- The model catalog already includes `Salesforce/SFR-Embedding-Code-400M_R` (`model_catalog.py:122-127`) — a code-focused 400M model
- **Tradeoff:** The general model is tiny (22.7M) and fast on CPU. The code-specific model is 18x larger (400M) and slower. For most users on CPU, the speed tradeoff isn't worth it.
- **Recommendation:** No change to defaults. The general model + BM25 hybrid search compensates well. Users who want higher precision on code can already switch via `config model sfr-code-400m`. Document this option more prominently.

**Gap 3: BM25 Parameters Not Code-Tuned** (Impact: LOW)
- BM25 uses LanceDB/Tantivy defaults (standard TF-IDF weighting)
- Code has different term distributions than natural language (keywords like `def`, `class`, `return` are extremely frequent)
- **Recommendation:** Investigate if Tantivy exposes BM25 `k1`/`b` parameter tuning. If so, a slight reduction in `k1` (term frequency saturation) could reduce the weight of common code keywords. This is a research task — may not be possible through LanceDB's FTS API.

**Gap 4: No Parent-Child Context Expansion** (Impact: MEDIUM, already planned)
- Currently each chunk is retrieved independently
- Ideally: embed at function/method level for precision, but return the enclosing class/module for LLM context
- The chunker already produces the right granularity — the missing piece is linkage at index time + context expansion at search time
- **Noted in codebase comments** (`indexer.py:367-374`) as a future improvement

**Gap 5: refine_factor Could Be Configurable** (Impact: LOW)
- Fixed at 5 — reasonable for most index sizes
- For very large indices (100K+ chunks), a higher refine_factor (e.g., 10) would improve recall at the cost of latency
- **Recommendation:** Make configurable via `install_config.json` but keep default at 5.

### Action Plan

**Priority 1: Code-Aware Query Preprocessing** (MEDIUM effort, MEDIUM impact)

- Add CamelCase/snake_case splitting to the query before BM25 search
- Keep the original query for vector embedding (embedding models handle compound terms)
- Expand the BM25 query with split tokens: `"getUserById"` → BM25 searches for `"getUserById" OR "get" OR "User" OR "By" OR "Id"`
- **Where:** `search/searcher.py` — new `_preprocess_query()` step before `_hybrid_search()`

**Priority 2: Document Code-Specific Model Option** (LOW effort, LOW-MEDIUM impact)

- Add a note in README.md and CLI help about switching to `sfr-code-400m` for code-focused projects
- Current: `python scripts/cli.py config model sfr-code-400m`
- Already supported, just not prominently documented

**Priority 3: Investigate BM25 Parameter Tuning** (Research only)

- Check if LanceDB/Tantivy expose `k1`/`b` BM25 parameters
- If available, test with code-heavy queries to see if tuning reduces noise from common keywords
- **Not actionable until we confirm API support**

**Priority 4: Make refine_factor Configurable** (LOW effort, LOW impact)

- Add `refine_factor` to `install_config.json` search config
- Default: 5 (current value)
- **Where:** `search/indexer.py` and `mcp_server/code_search_server.py`

**Files to Modify:**
- `search/searcher.py` — add `_preprocess_query()` with CamelCase/snake_case splitting
- `search/indexer.py` — make refine_factor configurable
- `mcp_server/code_search_server.py` — pass refine_factor from config
- `README.md` — document code-specific model option

---

## Session A — Completed: Concurrency Safety

**Status:** Done (revision-1.5 branch)
**Date:** 2026-03-12

### What Was Implemented

Phase 1 (Project-Level File Lock) and Phase 2 (Global Embedding Semaphore) from Item 1 are fully implemented. Phase 3 (Resource-Aware Batch Sizing) was deferred as planned — the default 22.7M-param model makes `batch_size=32` fine.

### Files Modified

| File | Change |
|------|--------|
| `pyproject.toml` | Added `filelock>=3.13` dependency (pure Python, zero transitive deps) |
| `common_utils.py` | Added `get_project_lock_path(project_path)` and `get_embedding_lock_path()` — derives the same `{name}_{hash}` key as `CodeSearchServer._project_storage_key()` |
| `search/incremental_indexer.py` | Project-level `FileLock` wrapping `incremental_index()`. `lock_contention: bool` field on `IncrementalIndexResult`. `lock_timeout` param threaded through `auto_reindex_if_needed()`. Class constants: `_FULL_INDEX_LOCK_TIMEOUT = 0`, `_INCREMENTAL_LOCK_TIMEOUT = 5` |
| `mcp_server/code_search_server.py` | Global embedding semaphore (`FileLock` on `.embedding.lock`) in `index_directory()` for full indexes only. `lock_timeout=0` passed in `search_code()` auto-reindex path so searches are never blocked |
| `tests/unit/test_concurrency_locks.py` | 19 tests covering lock path derivation, timeout selection, contention behavior, lock release safety, search non-blocking, and global embedding lock |

### Lock Behavior

| Scenario | Lock | Timeout | Result |
|----------|------|---------|--------|
| Full index, same project contention | Project | 0s | Return immediately, `lock_contention: true` |
| Incremental index, same project contention | Project | 5s | Wait briefly, then `lock_contention: true` |
| Full index on different project | Global embedding | 0s | Return immediately with message |
| Search while project is indexing | Project (via search path) | 0s | Search proceeds with existing index |

### Key Design Decisions

- **Lock ordering:** Global embedding (outer) → project (inner) — prevents deadlocks
- **Crash safety:** All locks released in `finally` blocks
- **TOCTOU prevention:** Snapshot state re-evaluated inside the lock after acquisition
- **Non-invasive:** `lock_contention` only appears in JSON response when `true`; omitted otherwise

### Test Results

- 19/19 concurrency lock tests pass
- 484/484 full suite tests pass (0 regressions)

---

## Session B — Completed: Tier 1 Languages + Chunker Accuracy Fixes

**Status:** Done (revision-1.5 branch)
**Date:** 2026-03-12

### What Was Implemented

**Tier 1 Languages Added:**
- **Bash/Shell** (`.sh`, `.bash`, `.zsh`) — chunks `function_definition` nodes
- **HTML** (`.html`, `.htm`) — chunks by structural elements (`script`, `style`, `head`, `body`, `main`, `nav`, `header`, `footer`, `section`, `article`, `aside`, `form`, `template`); handles `script_element`/`style_element` distinct node types
- **CSS** (`.css`) — chunks `rule_set`, `media_statement`, `keyframes_statement`, `import_statement`, `supports_statement`, `charset_statement`

**Note:** PowerShell (`tree-sitter-powershell`) is not available on PyPI. Deferred until a standalone package is published.

**Chunker Accuracy Fixes:**
- **Java records/sealed classes** — added `record_declaration` to splittable types, `sealed`/`non-sealed` modifier detection
- **Go generics metadata** — extracts `type_parameter_list` from function/type declarations, adds `has_generics` and `generic_params` metadata
- **TOML line accuracy** — added comment skipping, dotted key handling, quote stripping for table names
- **JSX component detection** — replaced string-based heuristic with AST-based `_has_jsx_children()` method that walks subtree for `jsx_element`/`jsx_self_closing_element` nodes

**Base chunker improvement:** Added `child_count == 0` guard to `should_chunk_node()` to filter keyword tokens that share type names with declaration nodes (affects Ruby `class`/`module`, Haskell `class`).

### Files Modified

| File | Change |
|------|--------|
| `chunking/languages/bash_chunker.py` | New — Bash/Shell chunker |
| `chunking/languages/html_chunker.py` | New — HTML structural element chunker |
| `chunking/languages/css_chunker.py` | New — CSS rule/at-rule chunker |
| `chunking/languages/java_chunker.py` | Added `record_declaration`, `sealed`/`non-sealed` modifiers |
| `chunking/languages/go_chunker.py` | Added Go 1.18+ generics metadata extraction |
| `chunking/languages/jsx_chunker.py` | AST-based JSX detection replacing string heuristic |
| `chunking/structured_data_chunker.py` | TOML line accuracy improvements |
| `chunking/base_chunker.py` | `child_count == 0` keyword token guard |
| `chunking/available_languages.py` | Registered bash, html, css |
| `chunking/languages/__init__.py` | LANGUAGE_MAP entries for new extensions |
| `chunking/multi_language_chunker.py` | chunk_type_map entries for new node types |
| `pyproject.toml` | Added `tree-sitter-bash`, `tree-sitter-html`, `tree-sitter-css` |

### Test Results

- 484/484 full suite tests pass (0 regressions)

---

## Session D — Completed: Tier 2 + Tier 3 Languages

**Status:** Done (revision-1.5 branch)
**Date:** 2026-03-12

### What Was Implemented

**Tier 2 Languages Added:**
- **Ruby** (`.rb`) — chunks `method`, `singleton_method`, `class`, `module`; extracts `constant` for class/module names
- **PHP** (`.php`) — chunks functions, classes, methods, interfaces, traits, enums, namespaces; uses `language_php()` binding
- **Swift** (`.swift`) — handles `class_declaration` for class/struct/enum/extension, `protocol_declaration`, `init_declaration`, `function_declaration`, `property_declaration`
- **SQL** (`.sql`) — chunks `create_table`, `create_view`, `create_index` (note: `create_function`, `create_type`, `create_trigger` are dead entries due to tree-sitter-sql grammar limitations)

**Note:** Angular and Vue chunkers deferred — no standalone PyPI packages available. HTML support (from Session B) covers ~80% of Angular template parsing. Vue would require a multi-language approach similar to Svelte.

**Tier 3 Languages Added:**
- **Terraform/HCL** (`.tf`, `.tfvars`, `.hcl`) — chunks `block` nodes, extracts block type and labels
- **Scala** (`.scala`, `.sc`) — chunks classes, objects, traits, functions, vals, vars, type definitions; handles case/sealed classes, `type_identifier` for type aliases
- **Lua** (`.lua`) — chunks `function_declaration`; handles `method_index_expression` for `Obj:method()` syntax
- **Elixir** (`.ex`, `.exs`) — custom `should_chunk_node()` and `chunk_code()` because Elixir uses `call` nodes for all definitions (`defmodule`, `def`, `defp`, `defmacro`, `defprotocol`, `defimpl`)
- **Haskell** (`.hs`) — chunks `function`, `signature`, `data_type`, `class`, `instance`, `type_synomym` (grammar typo is intentional — matches tree-sitter-haskell), `newtype`

**Note:** Dart (`tree-sitter-dart`), Protobuf (`tree-sitter-protobuf`) are not available on PyPI. Deferred until standalone packages are published.

### Files Created

| File | Language |
|------|----------|
| `chunking/languages/ruby_chunker.py` | Ruby |
| `chunking/languages/php_chunker.py` | PHP |
| `chunking/languages/swift_chunker.py` | Swift |
| `chunking/languages/sql_chunker.py` | SQL |
| `chunking/languages/hcl_chunker.py` | Terraform/HCL |
| `chunking/languages/scala_chunker.py` | Scala |
| `chunking/languages/lua_chunker.py` | Lua |
| `chunking/languages/elixir_chunker.py` | Elixir |
| `chunking/languages/haskell_chunker.py` | Haskell |

### Test Data Added

12 new test data files in `tests/test_data/multi_language/`: `example.sh`, `example.html`, `example.css`, `calculator.rb`, `Calculator.php`, `Calculator.swift`, `example.sql`, `main.tf`, `Calculator.scala`, `calculator.lua`, `calculator.ex`, `Calculator.hs`

### Registration Files Updated

- `chunking/available_languages.py` — all 12 new languages registered
- `chunking/languages/__init__.py` — all new LANGUAGE_MAP entries
- `chunking/multi_language_chunker.py` — chunk_type_map + declaration_kind entries for all new node types
- `chunking/base_chunker.py` — `_CONTAINER_NODE_TYPES` expanded with Ruby, PHP, Swift, Scala, Haskell containers
- `pyproject.toml` — 9 new tree-sitter dependencies (ruby, php, swift, sql, hcl, scala, lua, elixir, haskell)

### Known Limitations

- **PowerShell, Dart, Vue, Protobuf** — no standalone PyPI packages for their tree-sitter grammars. Graceful degradation: `available_languages.py` uses try/except imports, so missing grammars are silently skipped.
- **SQL** — `create_function`, `create_type`, `create_trigger` are registered but tree-sitter-sql doesn't parse them into structured nodes (they produce `ERROR` nodes). Only `create_table`, `create_view`, `create_index` are effectively chunked.

### Test Results

- 484/484 full suite tests pass (0 regressions)

---

## Summary — Prioritized Action Items

### Critical / Do First
1. ~~**Add project-level file lock for indexing** — prevents index corruption from concurrent agents (Item 1)~~ **DONE (Session A)**
2. ~~**Fix Java record/sealed class support** — your codebase uses JDK 21+ (Item 3)~~ **DONE (Session B)**

### Important / Do Next
3. ~~**Add Tier 1 languages** — Shell/Bash, HTML, CSS (Item 2)~~ **DONE (Session B)** (PowerShell deferred — no PyPI package)
4. **Add code-aware query preprocessing** — CamelCase/snake_case splitting for BM25 (Item 4)
5. ~~**Add global embedding semaphore** — resource protection across MCP instances (Item 1)~~ **DONE (Session A)**

### Nice-to-Have / Do Later
6. ~~**Add Tier 2 languages** — Ruby, PHP, Swift, SQL (Item 2)~~ **DONE (Session D)** (Angular/Vue deferred — no PyPI packages)
7. ~~**Add Go generics metadata** (Item 3)~~ **DONE (Session B)**
8. ~~**Improve TOML line accuracy** — better regex with comment skipping, dotted keys, quote stripping (Item 3)~~ **DONE (Session B)**
9. **Make refine_factor configurable** (Item 4)
10. **Investigate BM25 parameter tuning** — research task (Item 4)
11. **Resource-aware batch sizing** for embeddings (Item 1)
12. ~~**Add Tier 3 languages** — Terraform/HCL, Scala, Lua, Elixir, Haskell (Item 2)~~ **DONE (Session D)** (Dart/Protobuf deferred — no PyPI packages)
