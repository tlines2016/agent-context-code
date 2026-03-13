"""Unit tests for SentenceTransformerModel float16 dtype and trust_remote_code."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ---------------------------------------------------------------------------
# Float16 model_kwargs on CUDA and MPS
# ---------------------------------------------------------------------------

class TestSentenceTransformerDtype:
    """Verify float16 model_kwargs when loading on CUDA or MPS."""

    def _make_and_load(self, device, trust_remote_code=False):
        """Create a SentenceTransformerModel and trigger model loading.

        Returns the MockSentenceTransformer class so callers can inspect
        the constructor call_args.
        """
        import torch  # noqa: F401
        from embeddings.sentence_transformer import SentenceTransformerModel

        mock_st_instance = MagicMock()
        mock_st_instance.device = device

        with patch("embeddings.sentence_transformer.SentenceTransformer",
                    return_value=mock_st_instance) as MockST, \
             patch("torch.cuda.is_available",
                    return_value=(device == "cuda")):
            model = SentenceTransformerModel(
                model_name="test/model",
                cache_dir="/tmp/cache",
                device=device,
                trust_remote_code=trust_remote_code,
            )
            # Access .model to trigger the cached_property
            _ = model.model

        return MockST

    @patch("torch.cuda.is_available", return_value=True)
    def test_cuda_gets_float16(self, _cuda):
        """CUDA device should pass model_kwargs with torch.float16."""
        import torch

        MockST = self._make_and_load("cuda")
        call_kwargs = MockST.call_args[1]
        assert call_kwargs["model_kwargs"] == {"torch_dtype": torch.float16}

    @patch("torch.cuda.is_available", return_value=False)
    def test_cpu_gets_no_model_kwargs(self, _cuda):
        """CPU device should pass model_kwargs=None."""
        MockST = self._make_and_load("cpu")
        call_kwargs = MockST.call_args[1]
        assert call_kwargs["model_kwargs"] is None

    @patch("torch.cuda.is_available", return_value=False)
    def test_mps_gets_float16(self, _cuda):
        """MPS device should get float16 model_kwargs."""
        import torch

        with patch("torch.backends.mps", create=True) as mock_mps:
            mock_mps.is_available.return_value = True
            MockST = self._make_and_load("mps")
        call_kwargs = MockST.call_args[1]
        assert call_kwargs["model_kwargs"] == {"torch_dtype": torch.float16}


# ---------------------------------------------------------------------------
# trust_remote_code pass-through
# ---------------------------------------------------------------------------

class TestTrustRemoteCode:
    """Verify trust_remote_code is passed to SentenceTransformer."""

    @patch("torch.cuda.is_available", return_value=False)
    def test_trust_remote_code_true(self, _cuda):
        """trust_remote_code=True should be forwarded to SentenceTransformer."""
        from embeddings.sentence_transformer import SentenceTransformerModel

        mock_st_instance = MagicMock()
        mock_st_instance.device = "cpu"

        with patch("embeddings.sentence_transformer.SentenceTransformer",
                    return_value=mock_st_instance) as MockST:
            model = SentenceTransformerModel(
                model_name="Salesforce/SFR-Embedding-Code-400M_R",
                cache_dir="/tmp/cache",
                device="cpu",
                trust_remote_code=True,
            )
            _ = model.model

        call_kwargs = MockST.call_args[1]
        assert call_kwargs["trust_remote_code"] is True

    @patch("torch.cuda.is_available", return_value=False)
    def test_trust_remote_code_false_by_default(self, _cuda):
        """Default trust_remote_code should be False."""
        from embeddings.sentence_transformer import SentenceTransformerModel

        mock_st_instance = MagicMock()
        mock_st_instance.device = "cpu"

        with patch("embeddings.sentence_transformer.SentenceTransformer",
                    return_value=mock_st_instance) as MockST:
            model = SentenceTransformerModel(
                model_name="test/model",
                cache_dir="/tmp/cache",
                device="cpu",
            )
            _ = model.model

        call_kwargs = MockST.call_args[1]
        assert call_kwargs["trust_remote_code"] is False
