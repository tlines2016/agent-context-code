"""Unit tests for embedder GPU batch cleanup and offload/restore helpers."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from embeddings.embedder import CodeEmbedder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunks(n: int = 3):
    """Return n fake CodeChunk-like objects."""
    chunks = []
    for i in range(n):
        chunk = MagicMock()
        chunk.relative_path = f"file_{i}.py"
        chunk.start_line = 1
        chunk.end_line = 10
        chunk.chunk_type = "function"
        chunk.name = f"func_{i}"
        chunk.parent_name = None
        chunk.docstring = None
        chunk.content = f"def func_{i}(): pass"
        chunk.file_path = f"/project/file_{i}.py"
        chunk.folder_structure = ["project"]
        chunk.decorators = []
        chunk.imports = []
        chunk.complexity_score = 1
        chunk.tags = []
        chunks.append(chunk)
    return chunks


def _make_embedder():
    """Return a CodeEmbedder with a mocked underlying model."""
    import numpy as np

    with patch("embeddings.embedder._resolve_model_config") as mock_config:
        mock_config.return_value = MagicMock(
            model_name="test-model",
            document_prompt_name=None,
            document_prefix="",
            query_prompt_name=None,
            query_prefix="",
            trust_remote_code=False,
        )
        with patch("embeddings.embedder.SentenceTransformerModel") as MockST:
            mock_model = MagicMock()
            mock_model.encode.return_value = np.zeros((1, 384))
            mock_model._model_loaded = True
            mock_model._device = "cuda"
            MockST.return_value = mock_model
            embedder = CodeEmbedder(model_name="test-model", device="cpu")
    return embedder


# ---------------------------------------------------------------------------
# Batch cleanup
# ---------------------------------------------------------------------------

class TestEmbedChunksBatchCleanup:
    """embed_chunks must call _release_gpu_cache once per batch."""

    def test_release_gpu_cache_called_per_batch(self):
        import numpy as np

        embedder = _make_embedder()
        # Patch _encode_texts to return fake embeddings
        embedder._model.encode.return_value = np.zeros((2, 384))

        chunks = _make_chunks(4)

        with patch.object(embedder, "_release_gpu_cache") as mock_release, \
             patch.object(embedder, "_encode_texts", return_value=np.zeros((2, 384))):
            # batch_size=2, 4 chunks → 2 batches
            embedder.embed_chunks(chunks, batch_size=2)

        assert mock_release.call_count == 2

    def test_release_gpu_cache_called_for_single_batch(self):
        import numpy as np

        embedder = _make_embedder()

        chunks = _make_chunks(3)

        with patch.object(embedder, "_release_gpu_cache") as mock_release, \
             patch.object(embedder, "_encode_texts", return_value=np.zeros((3, 384))):
            embedder.embed_chunks(chunks, batch_size=10)

        assert mock_release.call_count == 1


# ---------------------------------------------------------------------------
# _release_gpu_cache backend gating
# ---------------------------------------------------------------------------

class TestReleaseGpuCache:
    """_release_gpu_cache must call gc.collect + backend-aware cache release."""

    def test_calls_gc_collect_on_gpu(self):
        embedder = _make_embedder()
        with patch("gc.collect") as mock_gc, \
             patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.empty_cache"):
            embedder._release_gpu_cache()
        mock_gc.assert_called_once()

    def test_skips_gc_on_cpu_only(self):
        embedder = _make_embedder()
        with patch("gc.collect") as mock_gc, \
             patch("torch.cuda.is_available", return_value=False), \
             patch("torch.backends.mps", create=True) as mock_mps:
            mock_mps.is_available.return_value = False
            embedder._release_gpu_cache()
        mock_gc.assert_not_called()

    def test_cuda_calls_empty_cache(self):
        embedder = _make_embedder()
        with patch("gc.collect"), \
             patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.empty_cache") as mock_empty:
            embedder._release_gpu_cache()
        mock_empty.assert_called_once()

    def test_mps_calls_empty_cache(self):
        embedder = _make_embedder()
        with patch("gc.collect"), \
             patch("torch.cuda.is_available", return_value=False), \
             patch("torch.mps.empty_cache", create=True) as mock_empty, \
             patch("torch.backends.mps", create=True) as mock_mps:
            mock_mps.is_available.return_value = True
            embedder._release_gpu_cache()
        mock_empty.assert_called_once()

    def test_cpu_skips_gpu_cache_release(self):
        embedder = _make_embedder()
        with patch("gc.collect"), \
             patch("torch.cuda.is_available", return_value=False), \
             patch("torch.backends.mps", create=True) as mock_mps:
            mock_mps.is_available.return_value = False
            # Should not raise and not call any empty_cache
            embedder._release_gpu_cache()


# ---------------------------------------------------------------------------
# Offload / restore
# ---------------------------------------------------------------------------

class TestEmbedderOffloadRestore:
    """offload_to_cpu / restore_to_device lifecycle for embedder."""

    def test_offload_moves_model_to_cpu(self):
        embedder = _make_embedder()
        mock_model = MagicMock()
        embedder._model.model = mock_model
        embedder._model._model_loaded = True

        with patch.object(embedder, "_release_gpu_cache"):
            embedder.offload_to_cpu()
        mock_model.to.assert_called_with("cpu")

    def test_offload_noop_when_model_not_loaded(self):
        embedder = _make_embedder()
        embedder._model._model_loaded = False
        embedder.offload_to_cpu()  # should not raise

    def test_restore_moves_model_to_configured_device(self):
        embedder = _make_embedder()
        mock_model = MagicMock()
        embedder._model.model = mock_model
        embedder._model._model_loaded = True
        embedder._model._device = "cuda"

        embedder.restore_to_device()
        mock_model.to.assert_called_with("cuda")

    def test_restore_noop_when_model_not_loaded(self):
        embedder = _make_embedder()
        embedder._model._model_loaded = False
        embedder.restore_to_device()  # should not raise
