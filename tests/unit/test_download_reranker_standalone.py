"""Unit tests for scripts/download_reranker_standalone.py.

All tests mock out the HuggingFace network calls so they are safe to run
in CI without credentials or internet access.
"""

import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ---------------------------------------------------------------------------
# Module import helper — the script does a transformers import at module level,
# so we must stub it before importing.
# ---------------------------------------------------------------------------

def _import_download_module():
    """Import the download_reranker_standalone script with transformers mocked."""
    # Build a minimal fake transformers module so the top-level import succeeds
    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoModelForCausalLM = MagicMock()
    fake_transformers.AutoTokenizer = MagicMock()

    with patch.dict(sys.modules, {"transformers": fake_transformers}):
        spec = importlib.util.spec_from_file_location(
            "download_reranker_standalone",
            Path(__file__).resolve().parent.parent.parent
            / "scripts" / "download_reranker_standalone.py",
        )
        module = importlib.util.module_from_spec(spec)
        # Patch huggingface_auth and common_utils before exec_module
        fake_auth_module = types.ModuleType("embeddings.huggingface_auth")
        fake_auth_module.build_huggingface_auth_error = lambda model, exc: str(exc)
        fake_auth_module.configure_huggingface_auth = lambda: False

        fake_common_utils = types.ModuleType("common_utils")
        fake_common_utils.save_reranker_config = MagicMock(return_value=Path("/fake/config"))

        with patch.dict(
            sys.modules,
            {
                "transformers": fake_transformers,
                "embeddings.huggingface_auth": fake_auth_module,
                "common_utils": fake_common_utils,
            },
        ):
            spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def download_module(tmp_path):
    """Import the download script with all external dependencies mocked."""
    fake_transformers = types.ModuleType("transformers")
    fake_model_cls = MagicMock()
    fake_tok_cls = MagicMock()
    fake_transformers.AutoModelForCausalLM = fake_model_cls
    fake_transformers.AutoTokenizer = fake_tok_cls

    fake_auth = types.ModuleType("embeddings.huggingface_auth")
    fake_auth.build_huggingface_auth_error = lambda model, exc: f"auth error: {exc}"
    fake_auth.configure_huggingface_auth = lambda: False

    fake_utils = types.ModuleType("common_utils")
    fake_save = MagicMock(return_value=tmp_path / "install_config.json")
    fake_utils.save_reranker_config = fake_save

    with patch.dict(
        sys.modules,
        {
            "transformers": fake_transformers,
            "embeddings.huggingface_auth": fake_auth,
            "common_utils": fake_utils,
        },
    ):
        spec = importlib.util.spec_from_file_location(
            "download_reranker_standalone",
            Path(__file__).resolve().parent.parent.parent
            / "scripts" / "download_reranker_standalone.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

    # Attach mocks so tests can configure them
    mod._fake_model_cls = fake_model_cls
    mod._fake_tok_cls = fake_tok_cls
    mod._fake_save = fake_save
    return mod


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

class TestDownloadRerankerSuccess:
    """download_reranker() returns True and writes config on success."""

    def test_returns_true_on_success(self, download_module, tmp_path):
        mock_tok = MagicMock()
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.logits.shape = (1, 1, 32000)
        mock_model.return_value = mock_output
        download_module._fake_tok_cls.from_pretrained.return_value = mock_tok
        download_module._fake_model_cls.from_pretrained.return_value = mock_model

        result = download_module.download_reranker(
            model_name="Qwen/Qwen3-Reranker-4B",
            storage_dir=str(tmp_path),
        )
        assert result is True

    def test_creates_models_subdir(self, download_module, tmp_path):
        mock_tok = MagicMock()
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.logits.shape = (1, 1, 32000)
        mock_model.return_value = mock_output
        download_module._fake_tok_cls.from_pretrained.return_value = mock_tok
        download_module._fake_model_cls.from_pretrained.return_value = mock_model

        download_module.download_reranker(
            model_name="Qwen/Qwen3-Reranker-4B",
            storage_dir=str(tmp_path),
        )
        assert (tmp_path / "models").is_dir()

    def test_downloads_tokenizer(self, download_module, tmp_path):
        mock_tok = MagicMock()
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.logits.shape = (1, 1, 32000)
        mock_model.return_value = mock_output
        download_module._fake_tok_cls.from_pretrained.return_value = mock_tok
        download_module._fake_model_cls.from_pretrained.return_value = mock_model

        download_module.download_reranker(
            model_name="Qwen/Qwen3-Reranker-4B",
            storage_dir=str(tmp_path),
        )
        download_module._fake_tok_cls.from_pretrained.assert_called_once()
        call_kwargs = download_module._fake_tok_cls.from_pretrained.call_args
        assert call_kwargs[0][0] == "Qwen/Qwen3-Reranker-4B"

    def test_downloads_model(self, download_module, tmp_path):
        mock_tok = MagicMock()
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.logits.shape = (1, 1, 32000)
        mock_model.return_value = mock_output
        download_module._fake_tok_cls.from_pretrained.return_value = mock_tok
        download_module._fake_model_cls.from_pretrained.return_value = mock_model

        download_module.download_reranker(
            model_name="Qwen/Qwen3-Reranker-4B",
            storage_dir=str(tmp_path),
        )
        download_module._fake_model_cls.from_pretrained.assert_called_once()
        call_kwargs = download_module._fake_model_cls.from_pretrained.call_args
        assert call_kwargs[0][0] == "Qwen/Qwen3-Reranker-4B"

    def test_saves_reranker_config_with_enabled_false(self, download_module, tmp_path):
        """Config must be saved with enabled=False (opt-in pattern)."""
        mock_tok = MagicMock()
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.logits.shape = (1, 1, 32000)
        mock_model.return_value = mock_output
        download_module._fake_tok_cls.from_pretrained.return_value = mock_tok
        download_module._fake_model_cls.from_pretrained.return_value = mock_model

        download_module.download_reranker(
            model_name="Qwen/Qwen3-Reranker-4B",
            storage_dir=str(tmp_path),
        )
        download_module._fake_save.assert_called_once()
        call = download_module._fake_save.call_args
        # save_reranker_config(model_name, enabled=False, storage_dir=...)
        # enabled may be passed as keyword or positional; check both forms
        enabled_kwarg = call.kwargs.get("enabled")
        # Positional: save_reranker_config(model_name, storage_dir) — enabled defaults to False
        # The source passes enabled=False explicitly as a keyword argument
        assert enabled_kwarg is False, (
            f"Expected save_reranker_config to be called with enabled=False, "
            f"but got enabled={enabled_kwarg!r}. Full call: {call}"
        )


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------

class TestDownloadRerankerFailure:
    """download_reranker() returns False on any exception."""

    def test_returns_false_on_download_error(self, download_module, tmp_path):
        download_module._fake_tok_cls.from_pretrained.side_effect = RuntimeError("network error")

        result = download_module.download_reranker(
            model_name="Qwen/Qwen3-Reranker-4B",
            storage_dir=str(tmp_path),
        )
        assert result is False

    def test_returns_false_on_model_error(self, download_module, tmp_path):
        mock_tok = MagicMock()
        download_module._fake_tok_cls.from_pretrained.return_value = mock_tok
        download_module._fake_model_cls.from_pretrained.side_effect = OSError("disk full")

        result = download_module.download_reranker(
            model_name="Qwen/Qwen3-Reranker-4B",
            storage_dir=str(tmp_path),
        )
        assert result is False

    def test_no_config_written_on_failure(self, download_module, tmp_path):
        download_module._fake_tok_cls.from_pretrained.side_effect = RuntimeError("auth error")

        download_module.download_reranker(
            model_name="Qwen/Qwen3-Reranker-4B",
            storage_dir=str(tmp_path),
        )
        download_module._fake_save.assert_not_called()


# ---------------------------------------------------------------------------
# Default storage dir
# ---------------------------------------------------------------------------

class TestDefaultStorageDir:
    """When storage_dir is None, the script must default to ~/.agent_code_search."""

    def test_default_storage_dir_uses_home(self, download_module, tmp_path):
        mock_tok = MagicMock()
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.logits.shape = (1, 1, 32000)
        mock_model.return_value = mock_output
        download_module._fake_tok_cls.from_pretrained.return_value = mock_tok
        download_module._fake_model_cls.from_pretrained.return_value = mock_model

        with patch("os.path.expanduser", return_value=str(tmp_path / "home")):
            download_module.download_reranker(
                model_name="Qwen/Qwen3-Reranker-4B",
                storage_dir=None,
            )

        # tokenizer should have been called with a cache_dir under the expanded home
        call_kwargs = download_module._fake_tok_cls.from_pretrained.call_args[1]
        assert "cache_dir" in call_kwargs
