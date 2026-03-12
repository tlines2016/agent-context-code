# Issue: Silent Skipping of Large Files During Indexing

**Priority:** Medium-High
**Component:** `search/indexer.py` (or wherever `max_structured_file_bytes` is enforced)
**Discovered via:** Victrix-Server performance test (2026-03-12)

---

## Summary

When `index_directory` is called, files exceeding `max_structured_file_bytes` (default: 5,000,000 bytes) are silently skipped with no warning to the user. The index appears to succeed normally, but searches against that content return no results — with no indication that the data was never indexed.

---

## Reproduction

Index a project containing large structured data files:

```bash
python -m scripts.cli index /path/to/project
# Output: "Indexed 972 files, 24131 chunks" — no mention of skipped files
```

Then search for content that only exists in the skipped file:

```python
search_code("NPC drop tables loot")  # → 0 results, no explanation
```

The user has no way to know whether 0 results means "not found" or "never indexed."

---

## Impact

### For the current project (Victrix-Server)
The 5 MB limit was set intentionally because the wiki pipeline produces very large TOML exports unsuitable for semantic chunking. But the silence is still confusing during debugging.

### For general PyPI users
Most source code files never approach 5 MB, so the limit is invisible for pure-code projects. However, any project with generated data exports, lock files, or large config dumps will hit this silently:

| File type | Can exceed 5 MB? | Examples |
|-----------|-----------------|---------|
| Generated TOML/JSON data | Yes, easily | ETL pipeline outputs, fixtures |
| `package-lock.json` | Yes (~800 KB–8 MB) | Node.js projects |
| `*.sql` dump files | Yes | DB migration test fixtures |
| Large YAML configs | Occasionally | Kubernetes manifests |
| Source `.kt` / `.py` | Almost never | Pathological cases only |

The distinction matters: **a 6 MB source file is almost certainly a mistake; a 6 MB TOML export is completely normal.**

---

## Proposed Fix

### 1. Warn on skip (minimum viable fix)

At the end of indexing, log a summary of skipped files:

```python
# In indexer.py, after processing all files
if skipped_files:
    logger.warning(
        f"Skipped {len(skipped_files)} file(s) exceeding size limit "
        f"({max_structured_file_bytes / 1_000_000:.1f} MB):"
    )
    for path, size in sorted(skipped_files, key=lambda x: x[1], reverse=True):
        logger.warning(f"  {size / 1_000_000:.1f} MB  {path}")
    logger.warning(
        "To index these files, raise max_structured_file_bytes in your config "
        "or pass --max-file-bytes to the CLI."
    )
```

This should also surface in the MCP `index_directory` return value — add a `skipped_files: list[{path, size_bytes, reason}]` field to the response JSON.

### 2. Expose the limit as a user-configurable parameter (quality-of-life fix)

`index_directory` already accepts `file_patterns`. Add:

```python
def index_directory(
    directory_path: str,
    project_name: str | None = None,
    file_patterns: list[str] | None = None,
    incremental: bool = True,
    max_file_bytes: int | None = None,   # ← new: override the global default
) -> IndexResult:
    ...
```

CLI equivalent:
```bash
python -m scripts.cli index /path/to/project --max-file-bytes 20000000
```

### 3. Split limits by file category (ideal fix)

The 5 MB limit is appropriate for source code but too restrictive for structured data files. Consider separate thresholds:

```toml
# config example
[indexing]
max_code_file_bytes = 5_000_000       # .kt, .py, .ts, .go, etc.
max_structured_file_bytes = 50_000_000 # .toml, .yaml, .json, .csv, etc.
```

Or a simpler `per_extension` map:

```python
MAX_FILE_BYTES_BY_EXTENSION = {
    "default": 5_000_000,
    ".toml": 20_000_000,
    ".json": 10_000_000,
    ".yaml": 10_000_000,
    ".yml":  10_000_000,
}
```

Note: raising the limit for structured files requires the structured data chunker to handle very large files gracefully (streaming parse, not full in-memory load).

---

## Additional Context

From the Victrix-Server test, these files were silently excluded:

| File | Size | Why it matters |
|------|------|----------------|
| `drop_tables.toml` | 14.2 MB | Primary NPC loot data — most-queried game content |
| `npc_spawns.toml` | 4.9 MB | NPC spawn locations |
| `items.toml` | 2.2 MB | Item definitions |
| `npc_combat.toml` | 2.2 MB | NPC combat stats |
| `shops.toml` | 613 KB | Shop data |

These are all outputs of the wiki ETL pipeline — exactly the kind of content a developer would want to search semantically.

---

## Related

- `docs/victrix-server-perf-test.md` — full performance test report where this was discovered
- `indexing_config.max_structured_file_bytes` in `get_index_status` response
