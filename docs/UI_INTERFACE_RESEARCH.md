# UI Interface Research Report: Agent Context Local

**Date:** March 2026  
**Package:** `agent-context-local` (PyPI)  
**Scope:** Feasibility analysis and high-level design plan for adding a UI interface—covering a standalone local web dashboard and a VSCode extension—for querying embeddings, inspecting index health, and managing settings.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Architecture Overview](#2-current-architecture-overview)
3. [Is a UI Feasible for a PyPI Package?](#3-is-a-ui-feasible-for-a-pypi-package)
4. [Approach A — Local Web Dashboard (Primary Recommendation)](#4-approach-a--local-web-dashboard-primary-recommendation)
5. [Approach B — VSCode Extension](#5-approach-b--vscode-extension)
6. [Approach C — Hybrid (Ultimate Goal)](#6-approach-c--hybrid-ultimate-goal)
7. [Recommended Technology Stack](#7-recommended-technology-stack)
8. [Feature Breakdown](#8-feature-breakdown)
9. [Code Snippet Display — How Chunks Would Surface](#9-code-snippet-display--how-chunks-would-surface)
10. [High-Level Implementation Plan](#10-high-level-implementation-plan)
11. [Community Research: LocalLLM & RAG Ecosystem](#11-community-research-locallm--rag-ecosystem)
12. [Risks and Honest Trade-offs](#12-risks-and-honest-trade-offs)
13. [Conclusion and Recommendation](#13-conclusion-and-recommendation)

---

## 1. Executive Summary

**A UI interface is fully feasible for this PyPI package.** The established precedent across the Python ecosystem (Jupyter, MLflow, Gradio, Streamlit, Optuna Dashboard, PrivateGPT, Open WebUI) demonstrates a proven pattern: bundle a compiled frontend as static assets inside the package, serve them from a locally-launched web server, and open the browser automatically. No external hosting, no cloud dependency, no API keys—perfectly aligned with the project's "100% local" philosophy.

A **VSCode extension** is a compelling secondary surface that complements (not replaces) the web dashboard. It can talk to the same local server and present results inline within the editor context where the developer is already working.

**Recommended path:**  
1. Phase 1 — Local web dashboard served by a FastAPI REST layer (new `ui_server/` module).  
2. Phase 2 — VSCode extension as a thin Webview client over the same REST API.

Both phases are independently shippable and the REST API produced in Phase 1 is the shared foundation.

---

## 2. Current Architecture Overview

Understanding the existing system is the starting point for where a UI layer plugs in.

```
┌─────────────────────────────────────────────────────────┐
│  MCP Server (mcp_server/)                               │
│   FastMCP → CodeSearchMCP → CodeSearchServer            │
└──────────────────────┬──────────────────────────────────┘
                       │  Python API calls
     ┌─────────────────┼─────────────────────────────┐
     │                 │                             │
     ▼                 ▼                             ▼
LanceDB (vector)   SQLite graph           install_config.json
search/indexer.py  graph/code_graph.py    ~/.agent_code_search/
search/searcher.py
     │
     ▼
SentenceTransformers / Qwen3 embedding
embeddings/embedder.py
```

Key surfaces the UI needs to interact with:

| Operation | Existing Python class | MCP tool name |
|---|---|---|
| Keyword/semantic search | `IntelligentSearcher.search()` | `search_code` |
| Index a directory | `CodeIndexManager` | `index_directory` |
| Index health & stats | `CodeIndexManager.get_stats()` | `get_index_status` |
| List projects | `CodeSearchServer.list_projects()` | `list_projects` |
| Switch active project | `CodeSearchServer.switch_project()` | `switch_project` |
| Clear index | `CodeSearchServer.clear_index()` | `clear_index` |
| Settings read/write | `common_utils.load/save_local_install_config()` | (no MCP tool today) |
| Graph context | `CodeGraph` | `get_graph_context` |

All of these are already Python-callable, meaning a REST API adapter layer is thin and straightforward.

---

## 3. Is a UI Feasible for a PyPI Package?

### Honest Assessment

**Yes—with a well-known pattern.** Concerns that sometimes arise, and why they don't apply here:

| Concern | Reality |
|---|---|
| "Frontend assets can't ship in a wheel" | False. Compiled static assets (HTML/JS/CSS) are plain files. `MANIFEST.in` + `package_data` in `pyproject.toml` handles this. Wheels include arbitrary data files. |
| "Browser UIs require a server process" | That's fine. The existing `agent-context-local-mcp` entry point already launches a long-running process. A new `agent-context-local-ui` entry point follows the same model. |
| "PyPI size limits" | PyPI allows packages up to 60 MB. A production-built React bundle with code-splitting is typically 500 KB–2 MB compressed—well within budget. |
| "Dependency conflicts" | FastAPI and uvicorn add ~8 MB of dependencies. They are already indirectly present (fastmcp pulls them). Making them explicit is low-risk. |
| "Cross-platform" | Python's stdlib `webbrowser` module opens the default browser on macOS, Windows, and Linux without any extra dependencies. |

### Precedent in the Python Ecosystem

Tools that follow this exact pattern successfully:

- **MLflow** — `mlflow ui` opens a React dashboard served by Flask. Ships as a single PyPI package.
- **Jupyter Lab** — Entire Node.js-compiled frontend packed into a Python wheel.
- **Gradio** — Ships compiled Svelte UI + FastAPI server in `gradio` PyPI package.
- **Optuna Dashboard** — React frontend bundled into `optuna-dashboard` wheel.
- **PrivateGPT** — Local RAG project that ships a React UI alongside its Python backend.
- **Open WebUI** — Demonstrates that rich chat + RAG UIs can run fully locally (though it targets Docker, the architecture lessons transfer).
- **Chroma** — Embedded vector DB (similar niche to LanceDB used here) that ships an optional dashboard.

### Pip-installed vs. `uv tool install`

This package uses `uv tool install agent-context-local`. That installs into an isolated virtual environment and exposes entry-point scripts. A `agent-context-local-ui` entry point works identically to `agent-context-local-mcp`—`uv tool install` wires it up automatically. No special handling required.

---

## 4. Approach A — Local Web Dashboard (Primary Recommendation)

### Architecture

```
User runs: agent-context-local-ui
                    │
                    ▼
         ┌──────────────────────┐
         │  ui_server/server.py │  (new entry point)
         │  FastAPI app          │
         │  uvicorn on :7432    │
         └──────────┬───────────┘
                    │  REST API  /api/v1/...
         ┌──────────┴───────────┐
         │  Existing Python     │
         │  business logic      │
         │  (CodeSearchServer,  │
         │   IntelligentSearcher│
         │   etc.)              │
         └──────────────────────┘
                    │
         ┌──────────┴───────────┐
         │  Static files        │
         │  ui_server/static/   │ ← compiled React bundle
         │  (shipped in wheel)  │
         └──────────────────────┘
```

- FastAPI mounts compiled static files at `/` and all `/api/v1/*` routes return JSON.
- On startup, the server opens `http://localhost:7432` in the system browser automatically.
- The port is configurable via `CODE_SEARCH_UI_PORT` environment variable.
- The REST API re-uses the existing `CodeSearchServer` instance—no duplicated logic.

### Why FastAPI Over Flask / Starlette / Django

FastAPI is already an indirect dependency via `fastmcp`. It provides:
- Async-native (consistent with MCP server design)
- Auto-generated OpenAPI docs at `/docs` (bonus: agents/scripts can use the REST API too)
- `StaticFiles` middleware for single-page app serving
- Pydantic models already used throughout the project

---

## 5. Approach B — VSCode Extension

### Is It Possible?

**Yes, and it adds genuine developer-experience value.** A VSCode extension complements the web dashboard without replacing it. The extension acts as a thin Webview client that talks to the same FastAPI server started by `agent-context-local-ui`.

### Architecture

```
VSCode Extension (TypeScript)
        │
        │  postMessage / fetch
        ▼
Webview Panel (HTML/React embedded in VSCode)
        │
        │  HTTP fetch to localhost:7432
        ▼
FastAPI server (same one as the web dashboard)
```

The extension can also:
- Register a VSCode command: `Agent Context: Search Code` (palette shortcut)
- Open a sidebar panel with search + results
- Jump to file/line when a result is clicked (VSCode's `vscode.open` API)
- Show a CodeLens decoration above indexed functions ("indexed · similarity 0.93")

### Distribution

VSCode extensions are distributed via the **Visual Studio Marketplace** (free, separate from PyPI). They can be developed in any language but TypeScript is the standard. The extension package (`agent-context-local.vsix`) would be published on the Marketplace and optionally bundled in the GitHub repo.

This is a separate distribution artifact from the PyPI wheel. The extension's only runtime dependency on the Python package is that the FastAPI server is running—which the extension can detect, and if not found, display a "Start UI server" button with the right CLI command.

---

## 6. Approach C — Hybrid (Ultimate Goal)

The two approaches complement each other:

| Feature | Web Dashboard | VSCode Extension |
|---|---|---|
| Standalone use (no VSCode) | ✅ | ❌ |
| Works in browser | ✅ | ❌ (Webview is browser-like but sandboxed) |
| Jump to file in editor | Requires OS file open | ✅ Native |
| Settings management | ✅ Full | ✅ Subset |
| Index health dashboard | ✅ Full charts | ✅ Status panel |
| Keyboard shortcut in editor | ❌ | ✅ |
| CodeLens decorations | ❌ | ✅ |
| Ships in PyPI wheel | ✅ | ❌ (Marketplace) |

**Phase 1** ships the web dashboard (most value, single artifact, broadest reach).  
**Phase 2** ships the VSCode extension reusing the Phase 1 REST API.

---

## 7. Recommended Technology Stack

### 7.1 Backend (REST API Layer) — Python

| Technology | Recommendation | Reason |
|---|---|---|
| **FastAPI** | ✅ Primary | Already indirect dep; async-native; auto docs; `StaticFiles` support |
| **uvicorn** | ✅ | ASGI server; already pulled by fastmcp; single-threaded fine for local use |
| **Pydantic v2** | ✅ | Already a project dep; define request/response models with zero overhead |

New REST endpoints needed (thin wrappers over existing Python API):
```
GET  /api/v1/health
GET  /api/v1/projects
POST /api/v1/projects/switch
POST /api/v1/search
GET  /api/v1/index/status
POST /api/v1/index/run
DELETE /api/v1/index/clear
GET  /api/v1/settings
PUT  /api/v1/settings
GET  /api/v1/models
```

### 7.2 Frontend — JavaScript/TypeScript

#### Framework

| Option | Stars | Bundle size | Assessment |
|---|---|---|---|
| **React 19 + Vite** | 230k+ | ~40 KB gzip (core) | ✅ Best ecosystem; Vite is the fastest dev toolchain |
| Svelte 5 | 82k | ~10 KB gzip (core) | ✅ Smaller bundle; less ecosystem for rich code UIs |
| Vue 3 + Vite | 207k | ~35 KB gzip (core) | Good; but React has better TypeScript tooling |
| Vanilla JS | — | 0 KB | Not maintainable at this scale |

**Recommendation: React 19 + Vite + TypeScript.** The ecosystem advantage matters for the rich components needed here (Monaco Editor, data tables, charts).

#### Component Library

| Option | Style | Assessment |
|---|---|---|
| **shadcn/ui** | Radix UI + Tailwind | ✅ Best choice. Modern, professional, unstyled base components that are fully owned (copy into project, not a runtime dep). Used by Vercel, Linear, etc. |
| Radix UI | Headless | Good but requires more styling work |
| Mantine | Full-featured | Good but opinionated; heavier |
| Ant Design | Enterprise | Dated aesthetic; heavy bundle |
| Material UI | Material Design | Not "clean/modern" enough; heavy |

**Recommendation: shadcn/ui + Tailwind CSS v4.** The shadcn philosophy (code ownership, no runtime component library dep) keeps bundle size small and makes the UI fully customizable.

#### Code Display

This is the most important decision for showing query results as code snippets.

| Option | Size | Assessment |
|---|---|---|
| **Monaco Editor** | ~4 MB | ✅ Identical to VSCode. Full syntax highlighting for all languages. Read-only mode is trivial. Best option for "feels like VSCode in the browser". |
| **CodeMirror 6** | ~400 KB | ✅ Lighter alternative. Language-specific packages load lazily. Better if bundle size is a concern. |
| **Shiki** | ~2 MB (langs) | ✅ Server-side or build-time highlight. Uses the same TextMate grammars as VSCode. Best for static display. |
| Prism.js | ~150 KB | Adequate. Fewer languages; less accurate. |
| highlight.js | ~300 KB | Adequate. No line number support built-in. |

**Recommendation: Shiki for code snippet display in search results** (renders highlighted HTML server-side, zero browser JS for display), plus **Monaco Editor for an optional "view full file" drawer** when the user wants to expand a result. This gives VSCode-quality display with optimal performance.

#### Charts (for index health dashboard)

| Option | Assessment |
|---|---|
| **Recharts** | ✅ React-native, composable, small. Good for simple bar/line/pie charts. |
| Chart.js + react-chartjs-2 | Good; imperative API is slightly less ergonomic in React |
| Visx (Airbnb) | Powerful but lower-level |

#### State Management

**Zustand** — lightweight, no boilerplate, works seamlessly with React 19 + TanStack Query. No Redux needed at this scale.

**TanStack Query (React Query)** for all server state (API calls, caching, background refetch). Standard choice for React + REST API.

### 7.3 Build Toolchain

```
Vite 6 + TypeScript 5
  → Output: ui_server/static/ (dist/)
  → Tree-shaken, code-split, gzip ~1-2 MB total
  → Source maps excluded from wheel (dev only)
```

The build is a one-time step during package release; the compiled output is committed to the repo and included in the wheel via `package_data`.

### 7.4 VSCode Extension (Phase 2)

| Technology | Use |
|---|---|
| **TypeScript 5** | Extension logic |
| **vscode-webview-ui-toolkit** | Microsoft's official toolkit for Webview UIs (uses Fluent UI) |
| **@vscode/webview-ui-toolkit** | Provides VSCode-themed buttons, text fields, badges |
| **esbuild** (via vsce) | Bundle extension for Marketplace |

The Webview inside VSCode can reuse the same React components from the web dashboard by targeting the webview context in the Vite build. This avoids duplicated UI code.

---

## 8. Feature Breakdown

### 8.1 Code Search Interface (Core Feature)

The primary reason users would open this UI: run natural language queries and see code chunks returned with full syntax highlighting.

**Search panel:**
- Large text input with placeholder "Search your codebase semantically…"
- Project selector dropdown (populated from `list_projects`)
- Filters: language, chunk type (function/class/method), file pattern glob
- `k` (results count) slider (1–20, default 5)
- "Search" button + keyboard shortcut (Ctrl+Enter / Cmd+Enter)

**Results panel:**
- Each result is a card showing:
  - **File path** (relative, clickable to open in OS file manager or copy)
  - **Symbol name** and **type** (e.g. `authenticate_user` · function)
  - **Similarity score** as a visual badge (color-coded: green ≥0.80, yellow 0.40–0.79, red <0.40)
  - **Line range** (e.g. lines 42–67)
  - **Code snippet** — the full chunk content with Shiki syntax highlighting, proper line numbers
  - **Docstring** (if present) shown below the snippet
  - **Tags** (intent tags from the searcher)
  - Expandable "Graph context" section showing `contains`, `calls`, `inherits` relationships

**Copy-to-clipboard button** on each result card: copies the code snippet in a format ready to paste into an AI chat window (includes file path comment header, line numbers, full content).

**"Export as Markdown"** button: formats all results as a Markdown code fence block with metadata headers — the exact format a user would want to paste as context into Claude, GPT-4, or any AI assistant.

### 8.2 Index Health Dashboard

A real-time status page for the active project's index.

**Status overview (header):**
- Project name and path
- Sync status badge (✅ Synced / ⚠️ Stale / ❌ Degraded)
- Total chunks indexed
- Storage size (vector + graph)
- Last indexed timestamp

**Metrics cards:**
- Chunks by language (bar chart via Recharts)
- Chunks by type (function / class / method / module — pie chart)
- Files indexed vs. files skipped
- Average embedding dimension

**Re-index button** — triggers `index_directory` with `incremental=True` (or Full Re-index toggle)

**Activity log** — last 10 indexing events with timestamps (stored in `stats.json`)

### 8.3 Settings Management

A form-based UI to edit `install_config.json` without touching the filesystem manually.

**Model settings:**
- Dropdown to select embedding model from the catalog (`embeddings/model_catalog.py`)
- Current model displayed with download status indicator
- "Download model" button that streams progress
- HuggingFace token input (masked, for gated models like `google/embeddinggemma-300m`)

**Idle management:**
- `idle_offload_minutes` slider (0 = disable, 5–60 range) — warm offload to CPU
- `idle_unload_minutes` slider (0 = disable, 10–120 range) — cold unload from RAM

**Reranker settings:**
- Toggle to enable/disable reranker
- Reranker model selection (from `reranker_catalog.py`)
- `reranker_recall_k` input (candidates fetched before reranking)
- `min_reranker_score` threshold slider

**Storage:**
- Current storage path display
- `CODE_SEARCH_STORAGE` override with live path validation
- "Open storage folder" button

All settings changes write through `save_local_install_config()` / `save_reranker_config()` — the same functions used by the CLI today.

### 8.4 Projects Manager

A table/list view of all indexed projects.

- Project name, path, chunk count, last indexed
- "Set active" button
- "Re-index" button per project
- "Delete index" button (with confirmation dialog) per project
- "Add new project" → path input → triggers `index_directory`

---

## 9. Code Snippet Display — How Chunks Would Surface

This is worth detailing because it's the highest-value feature for users who want to provide context to an AI agent.

### What the Searcher Already Returns

`IntelligentSearcher.search()` returns `SearchResult` objects with:

```python
@dataclass
class SearchResult:
    chunk_id: str          # e.g. "src/auth.py::authenticate_user::0"
    similarity_score: float
    content_preview: str   # The actual code text of the chunk
    file_path: str         # Absolute path
    relative_path: str     # Relative to project root
    start_line: int        # Line where chunk starts
    end_line: int          # Line where chunk ends
    chunk_type: str        # "function", "class", "method", etc.
    name: Optional[str]    # Symbol name
    parent_name: Optional[str]
    docstring: Optional[str]
    tags: List[str]
    context_info: Dict[str, Any]
```

`content_preview` contains the **full chunk source code** (not a truncated preview — the field name is slightly misleading and is a candidate for renaming to `content` in a future refactor). This is the raw code text extracted by tree-sitter from the source file.

### Rendering Pipeline in the UI

```
API response JSON
    │
    ▼
content_preview (raw code string)
    │
    ├── language detected from file_path extension
    │       (e.g. ".py" → "python", ".ts" → "typescript")
    │
    ▼
Shiki highlighter (runs in Web Worker to avoid blocking UI)
    │  transforms raw code → themed HTML with token colors
    ▼
<pre> block rendered in result card
    │
    ├── line numbers overlaid via CSS counter
    ├── "start_line" offset applied so displayed numbers match the real file
    └── highlighted "hot" lines if similarity > 0.9
```

### Example Rendered Result Card

> *The code below is illustrative only. Production authentication should use constant-time comparison (e.g. `hmac.compare_digest`) to prevent timing-based enumeration attacks.*

```
┌─────────────────────────────────────────────────────────────────┐
│ src/auth/authenticator.py  ·  function  ·  lines 42–67          │
│ authenticate_user                                  [0.91] ●●●●○  │
├─────────────────────────────────────────────────────────────────┤
│ 42  def authenticate_user(                                       │
│ 43      username: str,                                           │
│ 44      password: str,                                           │
│ 45      db: Session,                                             │
│ 46  ) -> Optional[User]:                                         │
│ 47      """Authenticate user by username and password.           │
│ 48                                                               │
│ 49      Returns None if credentials are invalid.                 │
│ 50      """                                                       │
│ 51      user = db.query(User).filter(                            │
│ 52          User.username == username                            │
│ 53      ).first()                                                │
│ 54      # Use hmac.compare_digest for timing-safe comparison     │
│ 55      if user and verify_password(password, user.hashed_pw):  │
│ 56          return user                                          │
│ 57      return None                                              │
├─────────────────────────────────────────────────────────────────┤
│ Docstring: Authenticate user by username and password.           │
│ Tags: authentication, database, query                            │
│ [📋 Copy snippet]  [📄 Copy as Markdown]  [🔗 Open file]       │
└─────────────────────────────────────────────────────────────────┘
```

### "Copy as Markdown" Output

Clicking this button produces text ready to paste directly into a Claude, GPT-4, or any AI assistant chat:

````markdown
**File:** `src/auth/authenticator.py` (lines 42–67)  
**Symbol:** `authenticate_user` (function)  
**Similarity:** 0.91

```python
def authenticate_user(
    username: str,
    password: str,
    db: Session,
) -> Optional[User]:
    """Authenticate user by username and password.

    Returns None if credentials are invalid.
    """
    user = db.query(User).filter(
        User.username == username
    ).first()
    if user and verify_password(password, user.hashed_pw):
        return user
    return None
```
````

This is the "manual context injection" workflow: the user queries their embeddings in the UI, finds the relevant chunks, copies them as Markdown, and pastes them into their AI assistant before asking their question. This is a common workflow observed across the r/LocalLLM and r/LocalLLaMA communities as an alternative to automated RAG when users want control over exactly what context the model sees.

---

## 10. High-Level Implementation Plan

### Phase 1: Local Web Dashboard

#### Step 1 — REST API Layer (2–3 days)

Create `ui_server/` as a new module:

```
ui_server/
  __init__.py
  app.py          ← FastAPI app factory
  routes/
    search.py     ← POST /api/v1/search
    projects.py   ← GET/POST /api/v1/projects
    index.py      ← GET/POST/DELETE /api/v1/index
    settings.py   ← GET/PUT /api/v1/settings
    health.py     ← GET /api/v1/health
  static/         ← compiled React bundle (committed)
  server.py       ← entry point: uvicorn launcher + browser open
```

The `app.py` instantiates `CodeSearchServer` (or accepts one already running) and wires routes. Routes are thin: validate Pydantic input → call existing Python method → serialize response.

Add entry point in `pyproject.toml`:
```toml
agent-context-local-ui = "ui_server.server:main"
```

Add `fastapi` and `uvicorn[standard]` to dependencies (or `ui` optional extra if wanting to keep base install lean).

#### Step 2 — Frontend Scaffold (1 day)

```
ui/
  package.json
  vite.config.ts
  src/
    App.tsx
    components/
      SearchPanel.tsx
      ResultCard.tsx
      HealthDashboard.tsx
      SettingsForm.tsx
      ProjectsTable.tsx
    hooks/
      useSearch.ts
      useProjectStatus.ts
    api/
      client.ts      ← typed fetch wrappers over REST API
    lib/
      shiki.ts       ← lazy-loaded syntax highlighter
    store/
      useStore.ts    ← Zustand global state
```

Build output goes to `ui_server/static/`. Vite config sets `outDir` accordingly.

#### Step 3 — Search UI (2–3 days)

Implement `SearchPanel` + `ResultCard` with:
- Query input, filter controls, k slider
- Results list with Shiki-highlighted code blocks
- "Copy as Markdown" clipboard action
- Similarity score badges (color-coded)

#### Step 4 — Health Dashboard (1–2 days)

Implement using `GET /api/v1/index/status` data + Recharts bar/pie charts.

#### Step 5 — Settings Form (1–2 days)

Form using shadcn/ui `Form` + `Select` + `Slider` components. Write-through to REST API `PUT /api/v1/settings`.

#### Step 6 — Packaging & Testing (1 day)

- Add `ui_server/static/**` to `package_data` in `pyproject.toml`
- Add `ui/` build to CI (GitHub Actions: `npm run build` step before wheel build)
- Add integration test: server starts, `/api/v1/health` returns 200

**Phase 1 total estimate: ~2 weeks of focused development.**

### Phase 2: VSCode Extension

#### Step 1 — Extension Scaffold (1 day)

```
vscode-extension/
  package.json        ← contributes commands, viewsContainers
  src/
    extension.ts      ← activate(), register commands
    panels/
      SearchPanel.ts  ← WebviewPanel wrapping React UI
    providers/
      StatusProvider.ts ← TreeDataProvider for sidebar status
```

Use `yo code` (Yeoman VSCode generator) to scaffold. Extension targets VSCode 1.85+.

#### Step 2 — Webview with Shared React UI (2–3 days)

Vite build targeting Webview context (CSP-compatible, no `eval`, inline fonts). Reuse `SearchPanel.tsx` and `ResultCard.tsx` from Phase 1 with minor adjustments for Webview postMessage API.

#### Step 3 — File Navigation (1 day)

When user clicks a result:
```typescript
vscode.workspace.openTextDocument(Uri.file(result.file_path))
  .then(doc => vscode.window.showTextDocument(doc, {
    selection: new Range(result.start_line - 1, 0, result.end_line - 1, 0)
  }));
```

This opens the file at the exact line range of the chunk—a capability the web dashboard cannot match.

#### Step 4 — Marketplace Publishing (1 day)

- `vsce package` → `.vsix`
- Publish to Visual Studio Marketplace (free account)
- Link in `README.md`

**Phase 2 total estimate: ~1 week of focused development.**

---

## 11. Community Research: LocalLLM & RAG Ecosystem

### Patterns Observed in r/LocalLLM and r/LocalLLaMA

Several recurring themes from community discussions (threads circa 2024–2025) inform the design:

**1. "Manual RAG" is popular.** Many power users intentionally skip automated RAG in favor of manually querying their embeddings and pasting the best chunks. They cite better accuracy (no hallucinated retrieval), transparency (they see exactly what context the model gets), and faster iteration. This is precisely the use case the UI's "Copy as Markdown" feature serves.

> *"I just run my ChromaDB queries in a script, copy the 3 best chunks, and paste them before my question. The model answers way better than when I use the auto-RAG pipeline."* — common r/LocalLLM sentiment

**2. Inspection tooling is highly requested.** The most-upvoted feedback on tools like PrivateGPT, LocalGPT, and similar projects is requests for better ways to inspect what's in the index—what got chunked, what similarity scores look like, what's not retrieving well. The health dashboard directly addresses this.

**3. Settings UIs matter for adoption.** Non-technical users (and technical users who don't want to edit JSON files) cite settings discoverability as a barrier. A form-based settings UI lowers the barrier to experimenting with models or idle thresholds.

**4. React + FastAPI is the dominant local AI UI stack.** Across recent open-source projects (Open WebUI, AnythingLLM, LibreChat, Dify), the dominant UI pattern is React frontend + FastAPI backend + local storage. The community has implicitly converged on this stack.

### Similar Projects for Reference

| Project | UI Approach | Lessons |
|---|---|---|
| **AnythingLLM** | React + Express, Electron wrapper | Electron allows desktop-app distribution; adds ~100 MB to install size |
| **Open WebUI** | Svelte + FastAPI, Docker-first | Docker is great for servers but wrong for dev tools installed on workstations |
| **PrivateGPT** | Gradio UI + FastAPI | Gradio is fast to prototype but limited in customization; "looks like a demo" |
| **LM Studio** | Electron + React | Beautiful professional UI; shows that local AI tools can be design-forward |
| **Jan.ai** | Electron + React | Another example of polished local AI UI |
| **Chroma** | React dashboard, FastAPI | Closest analogy — embedded vector DB with optional dashboard |
| **Weaviate Console** | React, separate from main server | Shows separation of UI from core server works well |

**Key insight from LM Studio and Jan.ai:** professional, modern UIs drive adoption for local AI tools. The "it looks like a research demo" aesthetic of Gradio-based tools actually deters non-technical users. shadcn/ui + Tailwind achieves the "clean and professional" aesthetic that these leading tools demonstrate.

### VSCode Extension Precedent for AI Tools

- **GitHub Copilot** — the gold standard; shows that in-editor AI context is genuinely useful
- **Continue.dev** — open-source; Webview-based; shows that RAG context selection in-editor is viable
- **Codeium** — similar in-editor semantic search
- **Cursor** — entire AI editor built on VSCode extension APIs

Continue.dev is the most relevant reference: it's an open-source VSCode extension with in-editor code context management. Its architecture (TypeScript extension + local model + Webview) closely mirrors what this project would build in Phase 2.

---

## 12. Risks and Honest Trade-offs

### Technical Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Frontend build adds CI complexity | Medium | GitHub Actions node step is well-understood; commit compiled output to repo to decouple frontend build from Python release |
| Port 7432 conflicts | Low | Configurable port; fall back to random available port |
| Shiki bundle size | Low | Use CDN build or lazy-load language packs on demand |
| CORS issues in VSCode Webview | Low | Webview's `fetch` to `localhost` works with correct CSP headers |
| FastAPI startup time | Very low | uvicorn starts in ~200 ms; negligible |

### Product Trade-offs

| Trade-off | Reality |
|---|---|
| **Two separate distribution artifacts** (PyPI + Marketplace) | Unavoidable for VSCode extension; standard practice (e.g. Python extension for VSCode is separate from Python itself). Document the connection clearly. |
| **UI adds ~2 MB to wheel size** | Acceptable. Users opt in by running `agent-context-local-ui`, or keep it as an optional dependency extra. |
| **Frontend development requires Node.js** | True—but only for contributors building the UI. The wheel ships compiled output. End users never need Node. |
| **The Gradio/Streamlit shortcut** | These frameworks are faster to prototype but produce "demo-quality" UIs and limit customization. For a production tool targeting developers, the React + Vite approach is worth the extra effort. |

### What Would Not Work

- **Shipping the VSCode extension inside the PyPI wheel.** `.vsix` files cannot be auto-installed from a Python package; users must install from the Marketplace or use `code --install-extension <file>.vsix`. Don't try to automate this.
- **Using `tkinter` or PyQt for the UI.** These look outdated, are difficult to style professionally, and have platform rendering inconsistencies. A web UI is strictly better for this use case.
- **Making the UI the MCP server itself.** The MCP protocol is a separate transport (stdio); mixing HTTP server logic into it creates coupling problems. Keep them as separate entry points sharing the `CodeSearchServer` instance.

---

## 13. Conclusion and Recommendation

### Verdict

**Build it.** A UI is not only feasible for this PyPI package—it is a natural and well-precedented evolution. The technology exists, the patterns are proven, and the community clearly wants it.

### Prioritized Recommendation

| Priority | Action |
|---|---|
| **1 — REST API** | Add `ui_server/` with FastAPI routes wrapping existing Python classes. Thin layer, high value. Opens the door to all downstream UIs. |
| **2 — Search UI** | React frontend with Shiki-highlighted result cards and "Copy as Markdown" action. This is the highest-value feature for the target user. |
| **3 — Health Dashboard** | Index health, project list, re-index controls. Reduces support questions about "is my index working?" |
| **4 — Settings UI** | Form for `install_config.json`. Reduces friction for non-technical users. |
| **5 — VSCode Extension** | Phase 2. Highest developer UX value (file jump, in-editor search), but depends on Phase 1 REST API being stable first. |

### Technology Summary

```
Backend:     FastAPI + uvicorn (already indirect deps)
Frontend:    React 19 + Vite + TypeScript
Styling:     Tailwind CSS v4 + shadcn/ui components
Code display: Shiki (results) + Monaco Editor (full-file view)
Charts:      Recharts
State:       Zustand + TanStack Query
VSCode:      TypeScript extension + vscode-webview-ui-toolkit
```

### Estimated Effort

| Phase | Effort | Deliverable |
|---|---|---|
| Phase 1: Web Dashboard | ~2 weeks | `agent-context-local-ui` CLI command, browser-based UI |
| Phase 2: VSCode Extension | ~1 week | Marketplace extension with in-editor search + file jump |

Both phases are independently valuable and shippable. Phase 1 creates the REST API that makes Phase 2 trivial.

---

*Report prepared for the `agent-context-local` project.*  
*Architecture decisions should be revisited against the latest versions of FastAPI, React, and Vite at implementation time.*
