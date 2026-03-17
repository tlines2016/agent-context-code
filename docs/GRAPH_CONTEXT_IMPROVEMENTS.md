# Graph Context Improvements — Implementation Plan

**Author:** Claude Sonnet 4.6
**Implementer:** Claude Opus 4.6
**Branch:** `revision-1.9`
**Source:** Structured evaluation of `get_graph_context` on the `rsprox` codebase
(4,070 files · 21,942 chunks · **1,146,246 graph edges** — evaluation at `docs/MCP_EVALUATION.md`)

---

## Context & Motivation

The evaluation exposed a critical usability failure in `get_graph_context`: calling it with `max_depth=2` on a highly-connected node returned **63,700 characters** of raw output, exceeding Claude Code's inline context limit. The tool became practically unusable without the manual workaround of always using `max_depth=1`.

Root causes:
1. `get_connected_subgraph()` performs unbounded BFS, returning all edges in the traversal boundary with no cap, no priority, no transparency about what was returned.
2. `resolve_call_edges()` builds call edges using a Cartesian product: if a called function name matches N symbols (common in versioned codebases), N edges are created per call site. On rsprox, this generated 1.036M `calls` edges out of 1.146M total — the vast majority noise.
3. The lightweight `relationships` hints in `search_code` results are returned in arbitrary database order, leading agents to see low-value `calls` hints before high-value structural `contains`/`inherits` hints.

**Goal:** Fix graph context overflow with intelligent, graceful truncation that is transparent to the consuming agent. Reduce call edge noise at index time. Sort relationship hints by usefulness.

---

## Fix 1 — Bounded `get_graph_context` with Transparent Truncation (CRITICAL)

### Design Principles

- Server-side edge cap, not just depth control. `max_depth` alone doesn't protect against dense graphs.
- Prioritize by signal value: `contains` (structural containment) → `inherits` (type hierarchy) → `calls` (call graph). When truncating, keep the most structurally useful edges first.
- Be transparent: if a response was truncated, say so explicitly in machine-readable fields + a human-readable `truncation_note` so the consuming agent knows what to do next.
- Expose focused filtering via `edge_type` parameter so agents can request only the structural relationship type they care about.

### New Tool Parameters

| Parameter | Type | Default | Valid Range | Description |
|-----------|------|---------|-------------|-------------|
| `max_edges` | int | 50 | 1–200 | Hard cap on edges returned after priority sort |
| `edge_type` | str \| None | None | `"contains"`, `"inherits"`, `"calls"`, `"imports"`, `None` | Filter traversal to one edge type |

### Implementation

#### A. `graph/code_graph.py`

**1. Add module-level priority constant** near the existing `EDGE_*` constants (around line 54):

```python
# Display / truncation priority for graph edges.
# Lower number = kept first when max_edges is exceeded.
# contains: class→method containment — highest structural signal
# inherits: type hierarchy — useful for architecture mapping
# calls:    call-graph edges — highest cardinality, most noise
EDGE_PRIORITY: Dict[str, int] = {
    EDGE_CONTAINS: 0,
    EDGE_INHERITS: 1,
    EDGE_IMPORTS:  1,
    EDGE_CALLS:    2,
}
```

**2. Update `get_connected_subgraph()` signature (line 314):**

```python
def get_connected_subgraph(
    self,
    chunk_id: str,
    max_depth: int = 2,
    max_edges: int = 50,
    edge_type_filter: Optional[str] = None,
) -> Dict[str, Any]:
```

**3. Replace the BFS body (lines 340–363) with depth-aware BFS:**

The current BFS uses a flat `all_edges: List[Dict]`. Replace with `all_edges: List[Tuple[Dict, int]]` where the second element is the hop-distance at which the edge was discovered. This enables priority sort by `(edge_type_priority, hop_depth)`.

```python
visited_ids: set = set()
frontier = {chunk_id}
all_edges: List[Tuple[Dict[str, Any], int]] = []  # (edge_dict, hop_depth)

for current_hop in range(traversal_depth + 1):
    if not frontier:
        break
    next_frontier: set = set()
    for cid in frontier:
        if cid in visited_ids:
            continue
        visited_ids.add(cid)
        # Pass edge_type_filter — get_relationships already supports it
        rels = self.get_relationships(cid, direction="both", edge_type=edge_type_filter)
        for edge in rels:
            all_edges.append((edge, current_hop))
            neighbour = (
                edge["target_chunk_id"]
                if edge["source_chunk_id"] == cid
                else edge["source_chunk_id"]
            )
            if neighbour not in visited_ids:
                next_frontier.add(neighbour)
    frontier = next_frontier
```

**4. Replace post-BFS deduplication and return (lines 365–384) with prioritized truncation:**

```python
# Resolve all visited symbols first (needed for boundary check below).
# We will re-filter symbols after edge truncation.
visited_set = visited_ids  # already fully built by BFS above

# Deduplicate edges, enforcing boundary consistency.
seen_keys: set = set()
unique_edges_with_depth: List[Tuple[Dict[str, Any], int]] = []
for e, depth in all_edges:
    if (
        e["source_chunk_id"] not in visited_set
        or e["target_chunk_id"] not in visited_set
    ):
        continue
    key = (e["source_chunk_id"], e["target_chunk_id"], e["edge_type"])
    if key not in seen_keys:
        seen_keys.add(key)
        unique_edges_with_depth.append((e, depth))

# Sort by (structural priority, hop depth) — most useful edges first.
unique_edges_with_depth.sort(
    key=lambda ed: (EDGE_PRIORITY.get(ed[0]["edge_type"], 99), ed[1])
)

total_edges_found = len(unique_edges_with_depth)
truncated = total_edges_found > max_edges

kept_with_depth = unique_edges_with_depth[:max_edges]
omitted_with_depth = unique_edges_with_depth[max_edges:]

kept_edges = [e for e, _ in kept_with_depth]

# Count omitted edges by type for transparency metadata.
omitted_by_type: Dict[str, int] = {}
for e, _ in omitted_with_depth:
    t = e["edge_type"]
    omitted_by_type[t] = omitted_by_type.get(t, 0) + 1

# Resolve only the symbols that appear in the kept edge set + seed node.
# This keeps the symbols list consistent with the edge list.
referenced_ids: set = {chunk_id}  # seed always included
for edge in kept_edges:
    referenced_ids.add(edge["source_chunk_id"])
    referenced_ids.add(edge["target_chunk_id"])
symbols = self._resolve_symbols(list(referenced_ids))

return {
    "symbols": symbols,
    "edges": kept_edges,
    "total_edges_found": total_edges_found,
    "truncated": truncated,
    "omitted_by_type": omitted_by_type,
}
```

**5. Update the docstring** to describe new parameters and return fields.

---

#### B. `mcp_server/code_search_server.py`

**1. Update `get_graph_context()` signature (line 1408):**

```python
def get_graph_context(
    self,
    chunk_id: str,
    max_depth: int = 2,
    max_edges: int = 50,
    edge_type: Optional[str] = None,
    project_path: str = None,
) -> str:
```

**2. Add parameter validation** after the existing `max_depth` validation block (after line 1448):

```python
# Validate and clamp max_edges.
try:
    max_edges = max(1, min(200, int(max_edges)))
except (TypeError, ValueError):
    max_edges = 50

# Validate edge_type filter.
_VALID_EDGE_TYPES = {"contains", "inherits", "calls", "imports"}
if edge_type is not None and edge_type not in _VALID_EDGE_TYPES:
    return json.dumps({
        "error": f"Invalid edge_type '{edge_type}'.",
        "valid_values": sorted(_VALID_EDGE_TYPES),
        "suggestion": "Use one of the listed valid values, or omit edge_type to return all types."
    })
```

**3. Update the traversal call (line 1494):**

```python
subgraph = graph.get_connected_subgraph(
    chunk_id,
    max_depth=max_depth,
    max_edges=max_edges,
    edge_type_filter=edge_type,
)
```

**4. Update the response block (lines 1499–1507)** to include truncation metadata and human-readable guidance:

```python
response: Dict[str, Any] = {
    "chunk_id": chunk_id,
    "found": True,
    "max_depth": max_depth,
    "max_edges": max_edges,
    "symbols": subgraph["symbols"],
    "edges": subgraph["edges"],
    "symbol_count": len(subgraph["symbols"]),
    "edge_count": len(subgraph["edges"]),
    "total_edges_found": subgraph["total_edges_found"],
    "truncated": subgraph["truncated"],
}

if subgraph["truncated"]:
    omitted = subgraph["omitted_by_type"]
    omitted_parts = ", ".join(
        f"{t}: {n}"
        for t, n in sorted(omitted.items(), key=lambda kv: -kv[1])
    )
    response["truncation_note"] = (
        f"Response capped at {max_edges} of {subgraph['total_edges_found']} edges "
        f"(priority order: contains > inherits > calls). "
        f"Omitted — {omitted_parts}. "
        f"To narrow: set edge_type='contains' for structure, "
        f"or reduce max_depth to 1."
    )

return json.dumps(response, indent=2)
```

**5. Update the Python docstring** for `get_graph_context()` to document `max_edges` and `edge_type` parameters.

---

#### C. `mcp_server/strings.yaml`

Replace the `get_graph_context` entry (lines 27–36) with:

```yaml
  get_graph_context: |
    Deep structural traversal around a code chunk. Returns containment (class→method), inheritance (child→parent), and call (caller→callee) relationships within max_depth hops.
    USE WHEN: You have a chunk_id from search_code and need the structural neighborhood — parent class, sibling methods, inheritance chain, callers/callees. Use AFTER search_code, not instead of it.
    DO NOT USE WHEN: You want to find code by meaning — use search_code (which already embeds lightweight graph hints in every result via the relationships field).
    Key args:
      chunk_id (required): identifier from a search_code result.
      max_depth: traversal hops (default 2). On large or densely-connected codebases, prefer max_depth=1 to avoid edge flooding.
      max_edges: hard cap on edges returned (default 50, max 200). Edges are prioritized: contains > inherits > calls. Raise only if you need more call-graph depth.
      edge_type: restrict traversal to one type — "contains" (class structure), "inherits" (type hierarchy), "calls" (call graph). Omit for all types.
      project_path: query a different project's graph without switching context.
    Truncation: when truncated=true in the response, read truncation_note — it lists what was omitted by type and suggests how to refine. This means the edge list is intentionally bounded, not an error.
    Best practice: start with max_depth=1. Use edge_type="contains" to map a class's methods, edge_type="inherits" to trace a type hierarchy, or omit for a mixed overview.
    Returns found=true with symbols/edges, or found=false with miss_reason when chunk is absent from the graph.
    Example: get_graph_context(chunk_id="src/auth.py::AuthService::0", max_depth=1, edge_type="contains")
```

---

## Fix 2 — Call Edge Noise Reduction at Index Time

### Design

Add a module-level `MAX_CALLEE_AMBIGUITY` constant in `graph/code_graph.py`. In `resolve_call_edges()`, skip creating edges when a called function name matches more symbols than this threshold. Names matching many symbols are generic utility names or version-duplicated symbols where the call relationship is noise, not signal.

**Conservative default:** `MAX_CALLEE_AMBIGUITY = 8`

This catches versioned-codebase cases (14 versions → 14 matches > 8 → skip) while preserving genuine overloading (2–4 matches → create edges normally).

**Important:** This change affects indexing only. Existing indexes continue to work as before. Users on versioned codebases who want reduced edge counts should run `clear_index` and re-index after updating.

### Implementation

#### `graph/code_graph.py`

**1. Add module-level constant** near the other `EDGE_*` constants (around line 54):

```python
# If a called function name resolves to more than this many symbols, skip
# creating call edges for it. Names matching many symbols are typically generic
# utilities or versioned duplicates where the edge would be noise.
MAX_CALLEE_AMBIGUITY: int = 8
```

**2. Add the ambiguity check in `resolve_call_edges()` (line 536–544):**

The inner loop currently:
```python
for called_name in called_names:
    callee_ids = name_to_ids.get(called_name, [])
    for callee_id in callee_ids:
        if callee_id == caller_id:
            continue  # skip self-calls
        self.add_edge(...)
```

Add the skip before the inner loop:
```python
for called_name in called_names:
    callee_ids = name_to_ids.get(called_name, [])
    # Skip if name maps to too many symbols — likely a generic utility or
    # a versioned-codebase duplicate. These edges are noise, not signal.
    if len(callee_ids) > MAX_CALLEE_AMBIGUITY:
        continue
    for callee_id in callee_ids:
        if callee_id == caller_id:
            continue  # skip self-calls
        self.add_edge(
            source_chunk_id=caller_id,
            target_chunk_id=callee_id,
            edge_type=EDGE_CALLS,
        )
```

**3. Update the log message** at line 550 to include a note about ambiguous names skipped (optional but useful for diagnosis):

```python
logger.info(
    "resolve_call_edges: inserted %d CALLS edges (MAX_CALLEE_AMBIGUITY=%d)",
    new_edges,
    MAX_CALLEE_AMBIGUITY,
)
```

---

## Fix 3 — Sort `search_code` Relationship Hints by Signal Priority

### Design

`_enrich_results_with_graph()` currently slices the first 10 raw relationships in database-return order. Sort by edge type priority before slicing so the most structurally useful hints always appear within the 10-hint cap.

### Implementation

#### `mcp_server/code_search_server.py` — `_enrich_results_with_graph()` (line 765)

Add a sort before the slice. Replace:
```python
item['relationships'] = [
    {
        'type': r['edge_type'],
        'target': r['target_chunk_id'] if r['source_chunk_id'] == chunk_id else r['source_chunk_id'],
        'direction': 'outgoing' if r['source_chunk_id'] == chunk_id else 'incoming',
    }
    for r in rels[:max_relationships]
]
```

With:
```python
# Sort by structural signal: contains > inherits/imports > calls
_HINT_PRIORITY = {"contains": 0, "inherits": 1, "imports": 1, "calls": 2}
sorted_rels = sorted(rels, key=lambda r: _HINT_PRIORITY.get(r["edge_type"], 99))
item['relationships'] = [
    {
        'type': r['edge_type'],
        'target': r['target_chunk_id'] if r['source_chunk_id'] == chunk_id else r['source_chunk_id'],
        'direction': 'outgoing' if r['source_chunk_id'] == chunk_id else 'incoming',
    }
    for r in sorted_rels[:max_relationships]
]
```

This is a two-line change with no schema impact.

---

## Issues NOT Fixed (Honest Assessment)

### Multi-version result flooding (eval score: 4/10)

When a codebase has 14+ near-identical files (versioned protocol decoders), all versions score identically and flood `k=5` results. A `max_results_per_basename` grouping parameter was considered but rejected: file basename collisions occur in normal codebases too (e.g., `utils.py` in separate packages). The risk of false collisions outweighs the benefit for a niche versioned-codebase pattern. **Mitigation: `file_pattern` filtering, which already works at 9/10.**

### Native-vs-target-language ranking bias

In T1 of the evaluation, C++ launcher files ranked above the primary Kotlin `main()`. Language-aware scoring weights are subjective, non-generalizable, and would require per-project configuration. The Kotlin entry point's score (0.59) is not poor — it narrowly lost to two native launchers on a vague query. **Mitigation: more specific queries.**

---

## Files to Modify

| File | Change |
|------|--------|
| `graph/code_graph.py` | Add `EDGE_PRIORITY` dict + `MAX_CALLEE_AMBIGUITY` constant; update `get_connected_subgraph()` with depth-aware BFS + prioritized truncation + new return fields; add ambiguity guard in `resolve_call_edges()` |
| `mcp_server/code_search_server.py` | Add `max_edges` + `edge_type` params to `get_graph_context()`; validation; pass-through to graph; updated response with truncation fields; sort rels in `_enrich_results_with_graph()` |
| `mcp_server/strings.yaml` | Replace `get_graph_context` description with updated version documenting new params and truncation behavior |

---

## Tests to Add

All new tests go in `tests/unit/test_code_graph.py`. Follow the existing `@pytest.fixture def graph(tmp_path)` pattern.

### Fix 1 Tests

**`test_get_connected_subgraph_respects_max_edges`**
- Build a graph: seed node + 20 nodes connected to seed via `calls` edges
- Call `get_connected_subgraph(seed, max_depth=1, max_edges=5)`
- Assert `len(result["edges"]) == 5`
- Assert `result["truncated"] is True`
- Assert `result["total_edges_found"] == 20`

**`test_get_connected_subgraph_priority_order_when_truncating`**
- Build: seed → 5 `calls` edges + 2 `contains` edges (all at depth 1)
- Call with `max_edges=3`
- Assert: all 2 `contains` edges are in `result["edges"]`, and 1 `calls` edge (since `contains` priority=0 is kept before `calls` priority=2)
- Assert `result["omitted_by_type"]["calls"] == 4`

**`test_get_connected_subgraph_no_truncation_when_under_limit`**
- Build: seed → 5 `calls` edges
- Call with `max_edges=50`
- Assert `result["truncated"] is False`
- Assert `"omitted_by_type"` is empty or absent
- Assert `result["total_edges_found"] == 5`

**`test_get_connected_subgraph_edge_type_filter`**
- Build: seed → 3 `calls` + 2 `contains` edges
- Call with `edge_type_filter="contains"`
- Assert all edges in result have `edge_type == "contains"`
- Assert `len(result["edges"]) == 2`

**`test_get_connected_subgraph_symbols_consistent_with_edges`**
- After truncation, assert every `chunk_id` in `result["symbols"]` appears in at least one edge OR equals the seed `chunk_id`
- Assert no orphaned symbols (symbols with no edge referencing them, except seed)

### Fix 2 Tests

**`test_resolve_call_edges_skips_ambiguous_names`**
- Create `MAX_CALLEE_AMBIGUITY + 1` symbols all named `"helper"`
- Create one caller symbol with `metadata_json=json.dumps({"calls": ["helper"]})`
- Call `resolve_call_edges()`
- Assert zero `calls` edges exist in the graph

**`test_resolve_call_edges_allows_non_ambiguous_names`**
- Create 3 symbols named `"helper"` (3 < `MAX_CALLEE_AMBIGUITY`)
- Create one caller with `metadata_json=json.dumps({"calls": ["helper"]})`
- Call `resolve_call_edges()`
- Assert 3 `calls` edges were created

**`test_resolve_call_edges_mixed_ambiguity`**
- Create 10 symbols named `"generic"` + 2 symbols named `"specific"`
- Create one caller that calls both `"generic"` and `"specific"`
- Assert: 0 edges for `"generic"` (ambiguous), 2 edges for `"specific"` (not ambiguous)

### Existing Test Updates

Any test in `test_code_graph.py` that calls `get_connected_subgraph()` and asserts on the return shape will need updating to handle the new return keys (`total_edges_found`, `truncated`, `omitted_by_type`). Update assertions without removing the core behavior checks.

---

## Implementation Order

1. **`graph/code_graph.py`** — Add constants (`EDGE_PRIORITY`, `MAX_CALLEE_AMBIGUITY`)
2. **`graph/code_graph.py`** — Update `get_connected_subgraph()` (BFS + truncation logic)
3. **`graph/code_graph.py`** — Add ambiguity guard in `resolve_call_edges()`
4. Run `uv run python -m pytest tests/unit/test_code_graph.py -v` — fix any regressions from return shape changes
5. **`mcp_server/code_search_server.py`** — Update `get_graph_context()` (new params + response)
6. **`mcp_server/code_search_server.py`** — Sort rels in `_enrich_results_with_graph()`
7. Run `uv run python -m pytest tests/unit/ -v`
8. **`mcp_server/strings.yaml`** — Replace `get_graph_context` description
9. Write new unit tests (see above)
10. Run `uv run python tests/run_tests.py` — full suite

---

## Verification (End-to-End)

After implementation, verify using the MCP tools directly in a Claude Code session with an indexed project:

```
# 1. Confirm truncation works with default max_edges=50
get_graph_context(chunk_id="<highly-connected-chunk>", max_depth=2)
# ✓ Expect: edge_count <= 50, truncated=true on dense graphs, truncation_note present

# 2. Confirm edge_type filter narrows results
get_graph_context(chunk_id="<a-class-chunk>", max_depth=2, edge_type="contains")
# ✓ Expect: all edges have type "contains", truncated=false for most classes

# 3. Confirm no truncation on small graphs
get_graph_context(chunk_id="<a-leaf-function>", max_depth=1, max_edges=50)
# ✓ Expect: truncated=false, total_edges_found == edge_count

# 4. Confirm max_edges raise allows more data
get_graph_context(chunk_id="<highly-connected-chunk>", max_depth=2, max_edges=150)
# ✓ Expect: edge_count > 50 (more data now accessible)

# 5. Confirm priority ordering: on a chunk with contains + calls edges,
#    the contains edges should appear first in the edges array
```

---

*Plan authored 2026-03-17. Implement in order above. Run tests after each logical step per CLAUDE.md working rules.*
