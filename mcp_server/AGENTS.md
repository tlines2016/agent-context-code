# MCP Server Best Practices (Mar 2026)

Last updated: 2026-03-11  
Scope: `mcp_server/` in this repository.

## Purpose

This document is a guardrail for future agents and maintainers so updates to MCP tool strings remain:

- clear for model tool selection and parameterization,
- compact enough to avoid context bloat,
- compatible across MCP clients.

Use this before editing `mcp_server/strings.yaml`, tool schemas, or server prompt/help text.

## Current server context

Relevant files:

- `mcp_server/strings.yaml`
- `mcp_server/code_search_mcp.py`
- `mcp_server/code_search_server.py`
- `mcp_server/server.py`

Current tools are appropriately domain-scoped (code search/indexing):

- `search_code`
- `index_directory`
- `find_similar_code`
- `get_index_status`
- `list_projects`
- `switch_project`
- `index_test_project`
- `clear_index`
- `get_graph_context`

## 2026 Best Practices (evidence-backed)

### A. Tool metadata quality (highest impact)

1. **Descriptions should be operational, not marketing**  
   Include: what the tool does, when to use it, when not to use it, and one short example.

2. **Disambiguate neighboring tools**  
   Explicitly separate overlapping responsibilities (`search_code` vs `find_similar_code`, and `search_code` vs `get_graph_context`).

3. **Parameter intent must be explicit**  
   For each non-trivial argument, explain accepted format/range and common mistakes.

4. **Keep runtime payload concise even if descriptions are richer**  
   Rich metadata helps tool choice; concise result payloads control token cost.

### B. Protocol and compatibility

1. **Prefer strict `inputSchema` and machine-readable outputs (`outputSchema` + `structuredContent`)**  
   Keep text fallback for older clients when needed.

2. **Use tool-execution errors for recoverable validation issues**  
   Return short actionable errors (what failed + direct fix), avoid opaque errors.

3. **Avoid over-complex schema constructs if client compatibility is uncertain**  
   Inlining can be more robust than deep `$ref/$defs` chains in mixed client ecosystems.

### C. Cost and reliability controls

1. **Budget context intentionally**  
   Keep help text short; move deep guidance into durable docs (this file + plan doc), not every request prompt.

2. **Include bounded outputs and explicit truncation signals**  
   Use limits and flags (for example `has_more`) where responses can grow.

3. **Design for agent recovery**  
   Error responses should enable a deterministic next action (`index_directory(...)`, reduce `k`, correct `project_path`, etc.).

## Practical anti-patterns to avoid

- Large multi-paragraph descriptions that repeat the same idea.
- Tool descriptions that omit "when not to use this tool".
- Ambiguous parameter names without format guidance.
- Help prompts that duplicate full docs and inflate every run.
- Unbounded tool responses (large snippets/lists) without truncation behavior.

## Recommended string pattern for each tool

Use this shape in `strings.yaml`:

1. **One-line purpose** (what it does)  
2. **Use when** (1 bullet)  
3. **Do not use when** (1 bullet)  
4. **Key args** (only args agents commonly misuse)  
5. **Minimal example** (one call)  
6. **Optional advanced example** (only if it changes behavior meaningfully)

## Suggested targeted improvements for this repository

1. **`search_code`**  
   - Keep as primary entry point.  
   - Clarify decision boundary with `find_similar_code` and `get_graph_context`.  
   - Keep cross-project usage example (high value, low cost).

2. **`find_similar_code`**  
   - Emphasize precondition: needs `chunk_id` from `search_code`.  
   - Add brief "not for initial discovery" wording.

3. **`get_graph_context`**  
   - Clarify that this is deep structural traversal and optional after search.  
   - Keep `max_depth` guidance tight (small integer recommendation).

4. **`index_directory` / `switch_project` / `list_projects`**  
   - Preserve multi-project flow but reduce repeated narrative in help text.  
   - Use one canonical workflow block in `help`.

5. **`clear_index`**  
   - Keep explicit warning language because it is destructive to local index state.

## Lightweight evaluation protocol (before/after string edits)

Run an A/B eval where only strings change:

1. Build a 40-80 prompt set:
   - realistic queries,
   - edge cases,
   - distractors (ambiguous phrasing).
2. Compare baseline vs candidate strings (same model and settings).
3. Track:
   - tool selection accuracy,
   - argument correctness rate,
   - task success rate,
   - tool error rate,
   - tokens per successful task.
4. Accept changes only when:
   - success/argument metrics improve,
   - token cost does not materially regress.

## Release checklist for future agents

- [ ] Tool descriptions are concise, disambiguated, and operational.
- [ ] Help text does not duplicate long-form docs.
- [ ] Destructive tools clearly state impact.
- [ ] Validation errors are actionable and short.
- [ ] Cross-project flows are documented once, not repeated in every tool.
- [ ] Any schema/output changes preserve client compatibility.
- [ ] A/B eval run captured metrics before merge.

## Sources used (March 2026 research snapshot)

Official / spec:

- Model Context Protocol spec (tools/schema/changelog):  
  `https://modelcontextprotocol.io/specification/2025-11-25/server/tools.md`  
  `https://modelcontextprotocol.io/specification/2025-11-25/schema.md`  
  `https://modelcontextprotocol.io/specification/2025-11-25/changelog.md`
- SEP-1303 (tool execution errors):  
  `https://modelcontextprotocol.io/seps/1303-input-validation-errors-as-tool-execution-errors.md`
- SEP-986 (tool naming guidance):  
  `https://modelcontextprotocol.io/seps/986-specify-format-for-tool-names.md`
- Anthropic tool-use docs:  
  `https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use`
- Anthropic engineering guidance (tool writing):  
  `https://www.anthropic.com/engineering/writing-tools-for-agents`

Community + benchmarking signal:

- MCP-Atlas paper / HF summary:  
  `https://arxiv.org/html/2602.00933v1`  
  `https://huggingface.co/papers/2602.00933`
- MCP tool description quality research (2026):  
  `https://arxiv.org/html/2602.14878v2`
- BFCL benchmark resources:  
  `http://gorilla.cs.berkeley.edu/leaderboard.html`  
  `https://proceedings.mlr.press/v267/patil25a.html`

Operational issue references (compat and failure modes):

- Numeric-string argument mismatch example:  
  `https://github.com/github/github-mcp-server/issues/2044`
- `$ref/$defs` interoperability issue example:  
  `https://github.com/github/copilot-cli/issues/1876`
- LangChain MCP timeout/tool invocation behavior:  
  `https://github.com/langchain-ai/langchainjs/issues/8279`  
  `https://github.com/langchain-ai/langchainjs/pull/8536`
- Structured output adapter gap example:  
  `https://github.com/langchain-ai/langchain-mcp-adapters/issues/283`
