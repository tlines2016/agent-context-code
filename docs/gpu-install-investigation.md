# GPU Installation Auto-Detection — Investigation Prompt

## Problem Statement

The GPU installation and auto-detection flow has a critical gap: **`uv run` without `--extra cu128` reverts PyTorch to CPU-only**, even when the GPU version was previously installed via `uv sync --extra cu128`. This means:

1. The install scripts correctly detect the GPU and configure `install_config.json` with `nvidia-cu128`
2. `uv sync --extra cu128` correctly installs `torch==2.10.0+cu128`
3. But any subsequent `uv run python ...` command (without `--extra cu128`) re-resolves dependencies and **downgrades torch back to CPU**
4. The MCP server launched by Claude Code uses `uv run --directory ... python mcp_server/server.py` — this does NOT include `--extra cu128`

## Current State (as of 2026-03-12)

- **User's machine**: NVIDIA GeForce RTX 5080, Windows 11
- **install_config.json** correctly shows:
  ```json
  {
    "gpu": {"vendor": "nvidia", "torch_index_url": "https://download.pytorch.org/whl/cu128", "extra": "cu128", "status": "nvidia-cu128"},
    "embedding_model": {"model_name": "Qwen/Qwen3-Embedding-0.6B"},
    "reranker": {"model_name": "Qwen/Qwen3-Reranker-0.6B", "enabled": true}
  }
  ```
- **`torch.__version__`** shows `2.10.0+cpu` when run without `--extra cu128`
- **`torch.__version__`** shows `2.10.0+cu128` when run WITH `--extra cu128`

## Root Cause

In `pyproject.toml`, PyTorch is configured as:
```toml
dependencies = [
    "torch>=2.10.0",           # default: resolves to CPU from PyPI
]

[project.optional-dependencies]
cu128 = ["torch>=2.10.0"]      # same spec, but with different source

[tool.uv.sources]
torch = [
    { index = "pytorch-cu126", extra = "cu126" },
    { index = "pytorch-cu128", extra = "cu128" },
]
```

The `[tool.uv.sources]` directive only routes torch to the CUDA index **when the corresponding extra is active**. Without the extra, `torch>=2.10.0` resolves from the default PyPI index, which serves CPU-only wheels.

## What Needs to Be Fixed

### Option A: Persist the extra selection
Make `uv run` automatically include the right extra based on `install_config.json`:
- The install script already writes `gpu.extra = "cu128"` to `install_config.json`
- The MCP server registration command (`claude mcp add ...`) needs to use `uv run --extra cu128`
- Update `scripts/install.sh` and `scripts/install.ps1` to register the MCP command with the correct extra

### Option B: Remove torch from default dependencies
Move `torch` entirely to optional dependencies:
- `cpu = ["torch>=2.10.0"]` (source: PyPI)
- `cu126 = ["torch>=2.10.0"]` (source: pytorch-cu126)
- `cu128 = ["torch>=2.10.0"]` (source: pytorch-cu128)
- The install script would pick the right extra during installation
- The MCP registration command would include the extra

### Option C: Runtime GPU-torch installation
- Keep CPU torch as default
- At MCP server startup, check `install_config.json` for GPU config
- If GPU configured but CPU torch detected, warn the user or trigger a `uv sync --extra cu128`

## Files to Investigate and Modify

| File | What to Check/Fix |
|------|-------------------|
| `pyproject.toml` | torch dependency structure, extras, UV sources |
| `scripts/install.sh` | MCP registration command — does it include `--extra`? |
| `scripts/install.ps1` | Same as above for Windows |
| `README.md` | MCP registration instructions — should include extra |
| `CLAUDE.md` | MCP registration commands shown there |
| `mcp_server/server.py` | Could add startup GPU check and warning |
| `scripts/download_model_standalone.py` | Line 68 hardcodes `device="cpu"` for model download — should be reviewed |
| `common_utils.py` | `detect_gpu()` and `detect_gpu_index_url()` functions |
| `embeddings/embedder.py` | `_maybe_gpu_upgrade_model()` auto-upgrade logic |

## Additional Finding

`scripts/download_model_standalone.py` line 68 hardcodes `device="cpu"`:
```python
model = SentenceTransformer(model_name, cache_folder=str(models_dir), device="cpu")
```
This is intentional (download doesn't need GPU), but should be documented.

## Acceptance Criteria

1. After running the install script on a GPU machine, `uv run python -c "import torch; print(torch.cuda.is_available())"` returns `True`
2. The MCP server (launched via `claude mcp add`) uses GPU for embedding and reranking
3. CPU-only machines still work without errors
4. The GPU auto-upgrade logic in `embeddings/embedder.py` correctly selects GPU models when CUDA is available
5. Indexing performance is validated on GPU (should be significantly faster than CPU)
