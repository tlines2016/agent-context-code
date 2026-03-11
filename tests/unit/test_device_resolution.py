"""Unit tests for device resolution across embedding and reranker backends."""

from unittest.mock import MagicMock, patch, PropertyMock
import pytest


# ---------------------------------------------------------------------------
# EmbeddingModel._resolve_device()
# ---------------------------------------------------------------------------

class TestEmbeddingModelResolveDevice:
    """Test EmbeddingModel._resolve_device() for all four backends."""

    def _make_model(self, device="cpu"):
        """Create a minimal EmbeddingModel subclass for testing."""
        import numpy as np
        from embeddings.embedding_model import EmbeddingModel

        class Stub(EmbeddingModel):
            def encode(self, texts, **kw):
                return np.zeros((len(texts), 4))
            def get_embedding_dimension(self):
                return 4
            def get_model_info(self):
                return {}
            def cleanup(self):
                pass

        return Stub(device=device)

    @patch("torch.cuda.is_available", return_value=False)
    def test_auto_cpu_fallback(self, _cuda):
        """Auto mode falls back to CPU when no GPU is available."""
        with patch("torch.backends.mps", create=True) as mps_backend:
            mps_backend.is_available.return_value = False
            m = self._make_model("auto")
            assert m._device == "cpu"

    @patch("torch.cuda.is_available", return_value=True)
    def test_auto_selects_cuda(self, _cuda):
        """Auto mode selects CUDA when available."""
        m = self._make_model("auto")
        assert m._device == "cuda"

    @patch("torch.cuda.is_available", return_value=False)
    def test_auto_selects_mps(self, _cuda):
        """Auto mode selects MPS when CUDA unavailable but MPS is."""
        with patch("torch.backends.mps", create=True) as mps_backend:
            mps_backend.is_available.return_value = True
            m = self._make_model("auto")
            assert m._device == "mps"

    @patch("torch.cuda.is_available", return_value=True)
    def test_explicit_cuda(self, _cuda):
        """Explicit 'cuda' selects CUDA when available."""
        m = self._make_model("cuda")
        assert m._device == "cuda"

    @patch("torch.cuda.is_available", return_value=False)
    def test_explicit_cuda_falls_back(self, _cuda):
        """Explicit 'cuda' falls back to CPU when unavailable."""
        m = self._make_model("cuda")
        assert m._device == "cpu"

    @patch("torch.cuda.is_available", return_value=False)
    def test_explicit_mps(self, _cuda):
        """Explicit 'mps' selects MPS when available."""
        with patch("torch.backends.mps", create=True) as mps_backend:
            mps_backend.is_available.return_value = True
            m = self._make_model("mps")
            assert m._device == "mps"

    @patch("torch.cuda.is_available", return_value=False)
    def test_explicit_mps_falls_back(self, _cuda):
        """Explicit 'mps' falls back to CPU when unavailable."""
        with patch("torch.backends.mps", create=True) as mps_backend:
            mps_backend.is_available.return_value = False
            m = self._make_model("mps")
            assert m._device == "cpu"

    @patch("torch.cuda.is_available", return_value=False)
    def test_explicit_cpu(self, _cuda):
        """Explicit 'cpu' always returns CPU."""
        m = self._make_model("cpu")
        assert m._device == "cpu"

    @patch("torch.cuda.is_available", return_value=False)
    def test_none_treated_as_auto(self, _cuda):
        """None device is treated as auto."""
        with patch("torch.backends.mps", create=True) as mps_backend:
            mps_backend.is_available.return_value = False
            m = self._make_model(None)
            assert m._device == "cpu"


# ---------------------------------------------------------------------------
# CodeReranker device + dtype resolution in _ensure_loaded()
# ---------------------------------------------------------------------------

class TestRerankerDeviceResolution:
    """Test CodeReranker._ensure_loaded() device and dtype selection."""

    def _patch_and_load(self, cuda_available, hip_version, mps_available=False):
        """Create a reranker, mock torch, and call _ensure_loaded().

        Returns (device_used, dtype_used) from the model.to() and from_pretrained calls.
        """
        import torch as real_torch
        from reranking.reranker import CodeReranker

        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="auto")

        mock_model = MagicMock()
        mock_model.to.return_value = mock_model
        mock_model.eval.return_value = mock_model

        mock_tokenizer = MagicMock()
        mock_tokenizer.convert_tokens_to_ids.return_value = 1

        with patch("torch.cuda.is_available", return_value=cuda_available), \
             patch("torch.version", create=True) as mock_version, \
             patch("torch.backends.mps", create=True) as mock_mps, \
             patch("transformers.AutoTokenizer.from_pretrained", return_value=mock_tokenizer), \
             patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=mock_model):

            mock_version.hip = hip_version
            mock_mps.is_available.return_value = mps_available

            reranker._ensure_loaded()

            # Extract the dtype from the from_pretrained call
            call_kwargs = mock_model.to.call_args
            device_used = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("device")

            from_pretrained_kwargs = real_torch.float32  # default
            for call in mock_model.from_pretrained.call_args_list if hasattr(mock_model, 'from_pretrained') else []:
                if 'torch_dtype' in call.kwargs:
                    from_pretrained_kwargs = call.kwargs['torch_dtype']

        return device_used, reranker

    @patch("torch.cuda.is_available", return_value=True)
    def test_nvidia_cuda_selects_float16(self, _cuda):
        """NVIDIA CUDA uses float16."""
        import torch
        from reranking.reranker import CodeReranker

        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="auto")

        mock_model = MagicMock()
        mock_model.to.return_value = mock_model
        mock_model.eval.return_value = mock_model
        mock_tokenizer = MagicMock()
        mock_tokenizer.convert_tokens_to_ids.return_value = 1

        with patch("torch.version", create=True) as mock_ver, \
             patch("transformers.AutoTokenizer.from_pretrained", return_value=mock_tokenizer), \
             patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=mock_model) as mock_from:
            mock_ver.hip = None
            reranker._ensure_loaded()
            call_kwargs = mock_from.call_args[1]
            assert call_kwargs["torch_dtype"] == torch.float16

    @patch("torch.cuda.is_available", return_value=True)
    def test_rocm_selects_float16(self, _cuda):
        """AMD ROCm also uses float16 (safe for consumer RDNA GPUs)."""
        import torch
        from reranking.reranker import CodeReranker

        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="auto")

        mock_model = MagicMock()
        mock_model.to.return_value = mock_model
        mock_model.eval.return_value = mock_model
        mock_tokenizer = MagicMock()
        mock_tokenizer.convert_tokens_to_ids.return_value = 1

        with patch("torch.version", create=True) as mock_ver, \
             patch("transformers.AutoTokenizer.from_pretrained", return_value=mock_tokenizer), \
             patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=mock_model) as mock_from:
            mock_ver.hip = "6.2.0"
            reranker._ensure_loaded()
            call_kwargs = mock_from.call_args[1]
            assert call_kwargs["torch_dtype"] == torch.float16

    @patch("torch.cuda.is_available", return_value=False)
    def test_cpu_selects_float32(self, _cuda):
        """CPU uses float32."""
        import torch
        from reranking.reranker import CodeReranker

        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="auto")

        mock_model = MagicMock()
        mock_model.to.return_value = mock_model
        mock_model.eval.return_value = mock_model
        mock_tokenizer = MagicMock()
        mock_tokenizer.convert_tokens_to_ids.return_value = 1

        with patch("torch.backends.mps", create=True) as mock_mps, \
             patch("transformers.AutoTokenizer.from_pretrained", return_value=mock_tokenizer), \
             patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=mock_model) as mock_from:
            mock_mps.is_available.return_value = False
            reranker._ensure_loaded()
            call_kwargs = mock_from.call_args[1]
            assert call_kwargs["torch_dtype"] == torch.float32

    @patch("torch.cuda.is_available", return_value=False)
    def test_mps_auto_detected(self, _cuda):
        """MPS is selected in auto mode when available."""
        import torch
        from reranking.reranker import CodeReranker

        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="auto")

        mock_model = MagicMock()
        mock_model.to.return_value = mock_model
        mock_model.eval.return_value = mock_model
        mock_tokenizer = MagicMock()
        mock_tokenizer.convert_tokens_to_ids.return_value = 1

        with patch("torch.backends.mps", create=True) as mock_mps, \
             patch("transformers.AutoTokenizer.from_pretrained", return_value=mock_tokenizer), \
             patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=mock_model) as mock_from:
            mock_mps.is_available.return_value = True
            reranker._ensure_loaded()
            # MPS should use float32
            call_kwargs = mock_from.call_args[1]
            assert call_kwargs["torch_dtype"] == torch.float32
            # Device should be mps
            mock_model.to.assert_called_with("mps")

    @patch("torch.cuda.is_available", return_value=False)
    def test_mps_uses_float32(self, _cuda):
        """MPS uses float32 (bfloat16 unsupported on MPS)."""
        import torch
        from reranking.reranker import CodeReranker

        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="auto")

        mock_model = MagicMock()
        mock_model.to.return_value = mock_model
        mock_model.eval.return_value = mock_model
        mock_tokenizer = MagicMock()
        mock_tokenizer.convert_tokens_to_ids.return_value = 1

        with patch("torch.backends.mps", create=True) as mock_mps, \
             patch("transformers.AutoTokenizer.from_pretrained", return_value=mock_tokenizer), \
             patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=mock_model) as mock_from:
            mock_mps.is_available.return_value = True
            reranker._ensure_loaded()
            call_kwargs = mock_from.call_args[1]
            assert call_kwargs["torch_dtype"] == torch.float32


# ---------------------------------------------------------------------------
# _detect_gpu_info() in cli.py
# ---------------------------------------------------------------------------

class TestDetectGpuInfo:
    """Test _detect_gpu_info() output for each backend."""

    def test_nvidia_cuda(self):
        from scripts.cli import _detect_gpu_info

        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.device_count", return_value=1), \
             patch("torch.cuda.get_device_name", return_value="NVIDIA RTX 4090"), \
             patch("torch.version", create=True) as mock_ver:
            mock_ver.hip = None
            result = _detect_gpu_info()
            assert "NVIDIA CUDA" in result
            assert "RTX 4090" in result

    def test_amd_rocm(self):
        from scripts.cli import _detect_gpu_info

        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.device_count", return_value=1), \
             patch("torch.cuda.get_device_name", return_value="AMD Radeon RX 7900 XTX"), \
             patch("torch.version", create=True) as mock_ver:
            mock_ver.hip = "6.2.0"
            result = _detect_gpu_info()
            assert "AMD ROCm" in result
            assert "7900 XTX" in result

    def test_apple_mps(self):
        from scripts.cli import _detect_gpu_info

        with patch("torch.cuda.is_available", return_value=False), \
             patch("torch.backends.mps", create=True) as mock_mps:
            mock_mps.is_available.return_value = True
            result = _detect_gpu_info()
            assert result == "Apple MPS"

    def test_cpu_only(self):
        from scripts.cli import _detect_gpu_info

        with patch("torch.cuda.is_available", return_value=False), \
             patch("torch.backends.mps", create=True) as mock_mps:
            mock_mps.is_available.return_value = False
            result = _detect_gpu_info()
            assert result == "CPU only"

    def test_torch_not_importable(self):
        from scripts.cli import _detect_gpu_info

        with patch.dict("sys.modules", {"torch": None}):
            result = _detect_gpu_info()
            assert "unknown" in result
