# Feature: Respect `.gitignore` and `.cursorignore` During Indexing

**Priority:** Medium
**Component:** `search/indexer.py`, file discovery logic
**Discovered via:** Victrix-Server performance test (2026-03-12)

---

## Summary

When indexing a project, the indexer should automatically read and respect `.gitignore` (and optionally `.cursorignore`) in the project root, skipping files and directories that the developer has already declared irrelevant. This prevents build artifacts, generated outputs, secrets, and IDE metadata from polluting the index — without requiring the user to manually configure exclusion patterns.

---

## Motivation

Currently, indexing `Victrix-Server` picked up files from:

- `content/build/` — Gradle build output (compiled classes, processed resources)
- `content/bin/` — IntelliJ build output
- `http-api/node_modules/` — Node.js dependencies (if present)
- `.idea/` — IntelliJ IDE metadata
- `.cursor/` — Cursor IDE metadata

All of these are already listed in `.gitignore` for good reason: they're either auto-generated, extremely large, or not meaningful to a developer searching for code. Indexing them wastes storage, inflates chunk counts, and adds noise to search results.

For example, in the Victrix-Server index:
- `content/build/resources/main/wiki-data/drops/drop_tables.toml` (14.2 MB) is a *build copy* of a source TOML — the canonical source is `content/src/main/resources/`. Both end up indexed, producing duplicate results.
- Several TOML files appear twice — once from `src/` and once from `bin/` or `build/` — because both trees are indexed.

A `.gitignore`-aware indexer would naturally solve these duplicates without any user configuration.

---

## Proposed Behavior

### `.gitignore` support

At index time, walk the project directory and apply `.gitignore` rules the same way Git does:

- Read `.gitignore` from the project root
- Read nested `.gitignore` files in subdirectories (Git supports these)
- Skip any file or directory that matches a gitignore pattern
- This should be **on by default** — virtually every real project has a `.gitignore` and virtually no developer wants to index their `node_modules/` or `build/`

```python
# Proposed index_directory signature addition
def index_directory(
    directory_path: str,
    project_name: str | None = None,
    file_patterns: list[str] | None = None,
    incremental: bool = True,
    respect_gitignore: bool = True,    # ← default True
    respect_cursorignore: bool = True, # ← default True
) -> IndexResult:
    ...
```

### `.cursorignore` support

Cursor IDE uses `.cursorignore` (same syntax as `.gitignore`) to tell the AI assistant which files to exclude from context. Since this tool is an MCP server used alongside AI coding tools, respecting `.cursorignore` is a natural fit — if the user has told Cursor to ignore something, they likely want the code search tool to ignore it too.

`.cursorignore` should be **opt-in or at least surfaced** rather than silently applied, since some users may want different exclusion sets for search vs. Cursor context.

### Suggested precedence order

1. Explicit `file_patterns` passed to `index_directory` (highest priority — user override)
2. `.cursorignore` (if `respect_cursorignore=True`)
3. `.gitignore` (if `respect_gitignore=True`)
4. Built-in hardcoded exclusions (e.g., `.git/` directory itself)

---

## Implementation Notes

- The [`pathspec`](https://pypi.org/project/pathspec/) library implements `.gitignore`-style glob matching and is already commonly used for this purpose. It handles edge cases like negation patterns (`!important-file`), directory-only patterns (`build/`), and nested ignore files.
- Nested `.gitignore` files (e.g., a module-level `.gitignore` inside `content/`) should be applied relative to their location, matching Git's actual behavior.
- The `index_directory` result should report how many files were skipped due to ignore rules (separate from the size-limit skips) so the user can verify the exclusions are working as intended.

---

## Expected Impact on Victrix-Server Index

With `.gitignore` support enabled, the following directories would be excluded automatically:

| Path | Reason |
|------|--------|
| `content/build/` | Gradle build output |
| `content/bin/` | IntelliJ compiled output |
| `*/node_modules/` | Node.js dependencies |
| `.idea/` | IntelliJ metadata |
| `.gradle/` | Gradle cache |

Estimated effect: removes duplicate TOML/resource files, reduces noise from build artifacts, and likely drops total indexed file count from 972 to ~600–700 (actual source files only).

---

## Related

- `docs/issue-silent-large-file-skip.md` — related issue about skipped files and surfacing exclusion reasons
- `docs/victrix-server-perf-test.md` — performance test where duplicate build-dir files were observed
