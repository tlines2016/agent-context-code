# Pre-PyPI Readiness Review

## Scope and validation performed

This review focused on PyPI/distribution readiness, cross-platform setup behavior, MCP usability, runtime reliability, and likely clean-machine failure modes.

Validation completed:

- `uv build` succeeded for both sdist and wheel.
- Baseline test suite passed: `448 passed, 10 skipped`.
- Console entrypoint targets resolved in the current environment.
- Additional manual review covered `pyproject.toml`, `README.md`, `scripts/`, `common_utils.py`, `mcp_server/`, `search/`, `chunking/`, `embeddings/`, `merkle/`, and the packaged source manifest.

Overall assessment:

- **Core functionality looks solid.**
- **The release is not fully PyPI-ready yet** because packaging, docs, installer flows, and distribution validation are still biased toward “run from a cloned repo on the author’s machine” instead of “install cleanly and behave predictably everywhere”.

---

## What already looks good

- `pyproject.toml` is present and builds successfully.
- The main package layout is discoverable by setuptools.
- `mcp_server/strings.yaml` is currently included in build artifacts.
- The project has meaningful automated coverage across chunking, indexing, search, MCP, and prerequisites.
- Storage is intentionally kept outside user workspaces, which is the right default for an MCP-oriented local indexer.

---

## Release blockers / high-priority issues

### 1. The public install story is still source-checkout-oriented, not PyPI-oriented

**Why this matters**

Users installing from PyPI will expect installed commands such as `agent-context-local` and `agent-context-local-mcp`, but the docs and CLI help still primarily teach “clone a repo, then run `uv run --directory ... python ...`”.

**Evidence**

- `README.md:225-245` registers the MCP server via `uv run --directory ... python mcp_server/server.py`
- `README.md:263-268`, `README.md:501-537`, `README.md:618-695` repeatedly instruct users to run `python scripts/cli.py ...`
- `scripts\cli.py:7`, `scripts\cli.py:237-260`, `scripts\cli.py:588-609`, `scripts\cli.py:728-729`, `scripts\cli.py:931`, `scripts\cli.py:1040` present source-tree commands as the primary UX

**Risk**

- PyPI users may install the package and then never use the installed entrypoints.
- Documentation will create two parallel installation modes with different operational behavior.
- Support burden goes up because “pip-installed” and “cloned-and-run” users follow different workflows.

**Recommended fix**

- Make installed commands first-class in docs and CLI output.
- Add a PyPI path such as:
  - `pipx install agent-context-local`
  - `agent-context-local --help`
  - `agent-context-local-mcp --version`
- Keep the `uv run --directory ...` flow explicitly labeled as **development/source install**.

---

### 2. Several runtime/CLI modules still mutate `sys.path` at import time

**Why this matters**

This is a common pre-packaging convenience, but it is fragile once the project becomes an installed distribution. It also makes import behavior dependent on directory layout.

**Evidence**

- `mcp_server\server.py:5-6`
- `mcp_server\code_search_server.py:19-20`
- `scripts\cli.py:38-39`
- `scripts\download_model_standalone.py:23`
- `scripts\download_reranker_standalone.py:25`
- `scripts\index_codebase.py:10-11`

**Risk**

- Harder-to-debug import shadowing issues in installed environments.
- More brittle behavior if package structure changes later.
- Makes the package feel “repo-relative” instead of truly installable.

**Recommended fix**

- Remove the `sys.path.insert(...)` shims from distributable runtime modules.
- Verify that absolute imports work in an isolated installed environment.
- Keep any path shims, if needed at all, only in tests or explicitly dev-only launchers.

---

### 3. Installer flows still have cross-platform robustness and safety issues

#### 3a. `install.sh` does not reliably make freshly installed `uv` available in the same shell

**Evidence**

- `scripts\install.sh:50-57`

The script installs `uv` and immediately checks `command -v uv`, but unlike the PowerShell version it does not patch `PATH` in-process. On a fresh macOS/Linux machine, Astral’s installer commonly updates shell profile files for future shells rather than the current non-interactive shell.

**Risk**

- “uv installation failed or not found in PATH” on clean machines even though the install itself succeeded.

**Recommended fix**

- After installing `uv`, explicitly probe common install locations and prepend them to `PATH` for the current process before failing.

#### 3b. `install.sh` does not handle an existing non-git, non-empty target directory cleanly

**Evidence**

- `scripts\install.sh:64-66`
- `scripts\install.sh:110-112`

If `PROJECT_DIR` exists, is non-empty, and does not contain `.git`, the script falls into the clone path and `git clone ... "$PROJECT_DIR"` can fail.

**Risk**

- Partial installs or confusing clone failures on machines with leftover directories.

**Recommended fix**

- Detect “exists + non-empty + not our repo” explicitly and prompt, abort, or require a force flag.

#### 3c. `install.ps1` promises non-interactive friendliness but still blocks on `Read-Host`

**Evidence**

- Comment says non-interactive default should stash: `scripts\install.ps1:49-53`
- Actual prompt path: `scripts\install.ps1:65-95`

Unlike the shell installer, the PowerShell installer does not appear to detect a non-interactive session before calling `Read-Host`.

**Risk**

- Hanging or failing unattended installs in CI/automation.

**Recommended fix**

- Mirror the shell script behavior: detect non-interactive mode and pick a safe default instead of prompting.

#### 3d. `install.ps1` can delete an existing directory without validating ownership/signature

**Evidence**

- `scripts\install.ps1:109-118`

On the fresh-install branch, any existing `ProjectDir` is recursively deleted before clone.

**Risk**

- Data loss if a user overrides `-ProjectDir` to a path that already contains unrelated files.

**Recommended fix**

- Reuse the same sort of signature/path-safety checks used in the uninstall scripts before deleting anything.
- If the directory is not clearly an AGENT Context Local install, abort with instructions instead of deleting it.

---

### 4. MCP server logging is too verbose by default for a packaged stdio tool

**Evidence**

- `mcp_server\server.py:13-19`

The server globally configures DEBUG logging for itself, `mcp`, and `fastmcp`.

**Risk**

- Noisy stderr in normal usage.
- More difficult diagnostics because everything is DEBUG all the time.
- Potential performance and UX degradation for long-lived MCP sessions.

**Recommended fix**

- Default to `INFO` or `WARNING`.
- Add an opt-in environment variable or CLI flag for verbose logging.

---

### 5. Snapshot and metadata corruption handling is still too opaque

**Evidence**

- `merkle\snapshot_manager.py:112-124`
- `merkle\snapshot_manager.py:140-145`

Snapshot and metadata load failures use `print(...)` and broad exception handling, then silently fall back to `None`.

**Risk**

- Corrupt state becomes “invisible”.
- Users may get unnecessary full reindexes with little explanation.
- Harder support/debugging on other machines.

**Recommended fix**

- Replace `print(...)` with structured logging.
- Distinguish missing-file, parse-error, and schema/version-mismatch cases.
- Consider quarantining corrupt files and surfacing a clear remediation message.

---

## Medium-priority issues

### 6. The released source distribution does not include the full validation surface

**Evidence**

- `agent_context_local.egg-info\SOURCES.txt:63-64` includes only:
  - `tests/test_lancedb_schema.py`
  - `tests/test_unsloth_embedder.py`
- The sdist manifest does **not** include the broader `tests\unit\...` and `tests\integration\...` suites.
- Operational scripts like `scripts\install.sh`, `scripts\install.ps1`, `scripts\uninstall.sh`, `scripts\uninstall.ps1`, `scripts\prereqs.sh`, and `scripts\prereqs.ps1` are also absent from the sdist manifest.

**Risk**

- The PyPI source artifact is not a faithful reproduction of the repo’s test/ops surface.
- Downstream packagers and users cannot validate the full package from the sdist alone.

**Recommended fix**

- Decide intentionally whether sdists should include:
  - the full test suite
  - setup/uninstall helper scripts
- If yes, add the necessary manifest configuration.
- If no, document that the GitHub repo is the full source-of-truth for contributor workflows.

---

### 7. There are no automated clean-environment packaging tests

**Evidence**

- Existing coverage includes prerequisites tests:
  - `tests\unit\test_prereqs_sh.py`
  - `tests\unit\test_prereqs_ps1.py`
- I did **not** find equivalent tests for:
  - wheel install into a fresh venv
  - installed console-script execution
  - MCP startup from an installed wheel
  - install/uninstall script behavior

**Risk**

- “Build succeeds” but clean-machine install still breaks.
- Regressions in entrypoints or package-data delivery can slip through.

**Recommended fix**

- Add integration tests that:
  - create a fresh venv
  - install the built wheel or editable package
  - run `agent-context-local --version`
  - run `agent-context-local-mcp --version`
  - instantiate `CodeSearchMCP` to verify `strings.yaml` loading

---

### 8. Startup is somewhat brittle around `strings.yaml` and tool registration

**Evidence**

- `mcp_server\code_search_mcp.py:25-34` loads `strings.yaml` directly via filesystem path with no friendly fallback
- `mcp_server\code_search_mcp.py:40-42` assumes every tool name in YAML maps directly to a server method

**Risk**

- A malformed or missing YAML file can crash startup.
- A rename drift between YAML and server methods becomes a hard failure.

**Recommended fix**

- Load package data more defensively, preferably with `importlib.resources`.
- Validate the YAML schema.
- Fail with a clearer startup error, or skip unknown tools with logging.

---

### 9. There are a few avoidable performance hot spots

#### 9a. Directory chunking traverses the tree once per extension

**Evidence**

- `chunking\multi_language_chunker.py:341-354`

`chunk_directory()` loops over every supported extension and runs `rglob()` for each one.

**Risk**

- Extra filesystem work on large repos.
- Slower first-index experience, especially on Windows and networked filesystems.

**Recommended fix**

- Walk the tree once, filter by suffix in-process, and skip ignored directories during traversal.

#### 9b. Stats fallback can still materialize the full Lance table, including vectors

**Evidence**

- `search\indexer.py:739-747`

The preferred projection path is good, but the fallback does a full `to_pandas()` scan.

**Risk**

- Large memory spikes on big indexes.

**Recommended fix**

- Keep the projection-first approach, but consider a lighter fallback or incremental stats persistence so full scans are rare.

#### 9c. FTS is rebuilt after every optimize cycle

**Evidence**

- `search\indexer.py:551-580`

**Risk**

- Expensive maintenance on large indexes, especially during incremental updates.

**Recommended fix**

- Rebuild FTS only when content changed, and consider separating “fast incremental maintenance” from “full optimize”.

---

### 10. Packaging/metadata polish is not finished yet

#### 10a. `Typing :: Typed` is declared without a `py.typed` marker

**Evidence**

- `pyproject.toml:95`
- No `py.typed` marker is present in the package tree

**Risk**

- Type-checking tools may not treat the distribution as a typed package correctly.

**Recommended fix**

- Add `py.typed` and include it in package data.

#### 10b. Naming is still mixed between `agent-context-local` and `agent-context-code`

**Evidence**

- Package name: `pyproject.toml:6`
- Server version/help strings use `agent-context-code`: `mcp_server\server.py:45`, `scripts\index_codebase.py:46`, multiple CLI/help strings

**Risk**

- Confusing branding/version output on PyPI.

**Recommended fix**

- Standardize the user-facing product/package naming before release and keep compatibility notes explicit where needed.

---

## Suggested pre-release checklist

### Must do before PyPI

1. Make PyPI-installed commands the primary documented workflow.
2. Remove runtime `sys.path` bootstrapping from distributable modules.
3. Harden `install.sh` and `install.ps1` for clean-machine and non-interactive scenarios.
4. Reduce MCP default logging verbosity.
5. Improve snapshot/metadata corruption reporting.
6. Add at least one clean-venv install + entrypoint smoke test.

### Strongly recommended

1. Decide whether sdists should contain the full test and script surface.
2. Harden `strings.yaml` loading and tool registration validation.
3. Optimize `chunk_directory()` to walk the tree once.
4. Add `py.typed`.
5. Standardize naming across package, docs, and CLI output.

---

## Bottom line

The codebase is **substantially closer to release-ready than “beta prototype” status**: the package builds, the tests pass, and the core architecture is coherent.

The remaining work is mostly about **distribution hardening**:

- making the PyPI workflow first-class
- removing “repo-relative” assumptions
- hardening installers
- validating clean-machine behavior

Once those pieces are addressed, this should be in much better shape for a reliable PyPI release and cross-platform MCP usage.
