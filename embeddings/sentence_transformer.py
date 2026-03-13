"""SentenceTransformer embedding model implementation."""

from typing import Optional, Dict, Any
from pathlib import Path
from functools import cached_property
import os
import logging
import numpy as np
from sentence_transformers import SentenceTransformer
import torch

from embeddings.embedding_model import EmbeddingModel
from embeddings.huggingface_auth import (
    build_huggingface_auth_error,
    configure_huggingface_auth,
)


class SentenceTransformerModel(EmbeddingModel):
    """SentenceTransformer embedding model with caching and device management."""

    def __init__(
        self,
        model_name: str,
        cache_dir: Optional[str] = None,
        device: str = "auto",
        trust_remote_code: bool = False,
    ):
        """Initialize SentenceTransformerModel.

        Args:
            model_name: Name of the model to load
            cache_dir: Directory to cache the model
            device: Device to load model on
            trust_remote_code: Allow custom model code from HuggingFace Hub
        """
        super().__init__(device=device)
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._trust_remote_code = trust_remote_code
        self._model_loaded = False
        self._logger = logging.getLogger(__name__)

    @cached_property
    def model(self):
        """Load and cache the SentenceTransformer model."""
        self._logger.info(f"Loading model: {self.model_name}")
        if configure_huggingface_auth():
            self._logger.debug("Configured Hugging Face authentication from local environment or token cache.")

        # If the model appears to be cached locally, enable offline mode
        local_model_dir = None
        try:
            if self._is_model_cached():
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
                os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
                self._logger.info("Model cache detected. Enabling offline mode for faster startup.")
                local_model_dir = self._find_local_model_dir()
                if local_model_dir:
                    self._logger.info(f"Loading model from local cache path: {local_model_dir}")
        except Exception as e:
            self._logger.debug(f"Offline mode detection skipped: {e}")

        try:
            model_source = str(local_model_dir) if local_model_dir else self.model_name

            # Float16 on CUDA (NVIDIA + AMD ROCm) and MPS (Apple Silicon).
            # CPU float16 is 5-10x slower on x86 — keep float32 there.
            _model_kwargs = {}
            if self._device in ("cuda", "mps"):
                _model_kwargs["torch_dtype"] = torch.float16

            model = SentenceTransformer(
                model_source,
                cache_folder=self.cache_dir,
                device=self._device,
                trust_remote_code=self._trust_remote_code,
                model_kwargs=_model_kwargs if _model_kwargs else None,
            )
            self._logger.info(f"Model loaded successfully on device: {model.device}")
            self._model_loaded = True
            return model
        except Exception as e:
            detailed_error = build_huggingface_auth_error(self.model_name, e)
            self._logger.error(f"Failed to load model: {detailed_error}")
            raise RuntimeError(detailed_error) from e

    def encode(self, texts: list[str], **kwargs) -> np.ndarray:
        """Encode texts using SentenceTransformer.

        Always produces L2-normalized embeddings (``normalize_embeddings=True``).
        This matches the design intent of models like Qwen3-Embedding which
        produce normalized output, and ensures consistent cosine similarity
        scores regardless of model.

        Args:
            texts: List of texts to encode
            **kwargs: Additional arguments passed to SentenceTransformer.encode()

        Returns:
            Array of L2-normalized embeddings
        """
        kwargs['normalize_embeddings'] = True
        return self.model.encode(texts, **kwargs)

    def get_embedding_dimension(self) -> int:
        """Get embedding dimension."""
        return self.model.get_sentence_embedding_dimension()

    def get_model_info(self) -> Dict[str, Any]:
        """Get model information."""
        if not self._model_loaded:
            return {"status": "not_loaded"}

        return {
            "model_name": self.model_name,
            "embedding_dimension": self.get_embedding_dimension(),
            "max_seq_length": getattr(self.model, 'max_seq_length', 'unknown'),
            "device": str(self.model.device),
            "status": "loaded"
        }

    def cleanup(self):
        """Clean up model resources."""
        if not self._model_loaded:
            return

        try:
            model = self.model
            model.to('cpu')

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            del model
            self._logger.info("Model cleaned up and memory freed")
        except Exception as e:
            self._logger.warning(f"Error during model cleanup: {e}")

    def _is_model_cached(self) -> bool:
        """Check if model is cached locally."""
        if not self.cache_dir:
            return False
        try:
            model_key = self.model_name.split('/')[-1].lower()
            cache_root = Path(self.cache_dir)
            if not cache_root.exists():
                return False
            for path in cache_root.rglob('config_sentence_transformers.json'):
                parent_str = str(path.parent).lower()
                if model_key in parent_str:
                    return True
            for d in cache_root.glob('**/*'):
                if d.is_dir() and model_key in d.name.lower():
                    # Require a substantive model artifact, not just any README
                    if (
                        (d / 'config_sentence_transformers.json').exists()
                        or (d / 'config.json').exists()
                        or (d / 'tokenizer_config.json').exists()
                    ):
                        return True
        except Exception:
            return False
        return False

    def _find_local_model_dir(self) -> Optional[str]:
        """Locate the cached model directory."""
        if not self.cache_dir:
            return None
        try:
            model_key = self.model_name.split('/')[-1].lower()
            cache_root = Path(self.cache_dir)
            if not cache_root.exists():
                return None
            for path in cache_root.rglob('config_sentence_transformers.json'):
                parent = path.parent
                if model_key in str(parent).lower():
                    return parent
            candidates = [d for d in cache_root.glob('**/*') if d.is_dir() and model_key in d.name.lower()]
            return candidates[0] if candidates else None
        except Exception:
            return None
