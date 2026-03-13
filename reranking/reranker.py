"""Two-stage reranker supporting CrossEncoder and Causal LM architectures.

Scores each (query, passage) pair and re-sorts by relevance.  Designed for
lazy loading — the model is not instantiated until the first ``rerank()`` call.

Supported architectures:
- **cross_encoder**: sentence-transformers CrossEncoder (e.g. ms-marco-MiniLM).
  Calls ``model.predict()`` which returns raw relevance scores.
- **causal_lm**: Qwen3-Reranker-style yes/no token classification via
  ``AutoModelForCausalLM``.  Extracts yes/no logits from the last token.

Input/output contract:
- ``rerank()`` accepts the same ``List[Tuple[str, float, Dict]]`` format
  returned by ``CodeIndexManager.search()``.
- It returns a re-sorted list in the same format, with the ``float``
  replaced by the reranker relevance score (0-1).
"""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from reranking.reranker_catalog import RerankerModelConfig, get_reranker_config

logger = logging.getLogger(__name__)


class CodeReranker:
    """Lazy-loaded two-stage reranker with multi-architecture support."""

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        cache_dir: Optional[str] = None,
        device: str = "auto",
    ):
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._device = device
        self._config: RerankerModelConfig = get_reranker_config(model_name)

        # Lazily initialised
        self._model = None
        self._tokenizer = None
        self._yes_token_id: Optional[int] = None
        self._no_token_id: Optional[int] = None

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Import and load the model on first use."""
        if self._model is not None:
            return

        if self._config.architecture == "cross_encoder":
            self._load_cross_encoder()
        else:
            self._load_causal_lm()

    def _load_cross_encoder(self) -> None:
        """Load a sentence-transformers CrossEncoder model."""
        from sentence_transformers import CrossEncoder
        import torch

        logger.info("Loading CrossEncoder reranker: %s", self._model_name)

        device = self._resolve_device()

        # Only GPU-exclusive models (cpu_feasible=False) benefit from float16.
        # CPU-default models (MiniLM) stay float32 to avoid inference slowdown
        # and known dtype mismatch bugs in the CrossEncoder path.
        model_kwargs = {}
        if device in ("cuda", "mps") and not self._config.cpu_feasible:
            model_kwargs["torch_dtype"] = torch.float16

        self._model = CrossEncoder(
            self._model_name,
            max_length=self._config.max_length,
            device=device,
            model_kwargs=model_kwargs if model_kwargs else None,
        )

        logger.info(
            "CrossEncoder reranker loaded on %s",
            device,
        )

    def _load_causal_lm(self) -> None:
        """Load a Qwen-style causal LM reranker."""
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        logger.info("Loading causal LM reranker: %s", self._model_name)

        device = self._resolve_device()
        # float16 on CUDA (NVIDIA + AMD ROCm) and MPS (Apple Silicon).
        # CPU float16 is 5-10x slower on x86 — keep float32 there.
        dtype = torch.float16 if device in ("cuda", "mps") else torch.float32

        self._tokenizer = AutoTokenizer.from_pretrained(
            self._model_name,
            cache_dir=self._cache_dir,
            padding_side="left",
        )

        self._model = AutoModelForCausalLM.from_pretrained(
            self._model_name,
            cache_dir=self._cache_dir,
            torch_dtype=dtype,
        ).to(device).eval()

        # Cache yes/no token IDs for logit extraction
        self._yes_token_id = self._tokenizer.convert_tokens_to_ids("yes")
        self._no_token_id = self._tokenizer.convert_tokens_to_ids("no")

        logger.info(
            "Causal LM reranker loaded on %s (dtype=%s, yes_id=%s, no_id=%s)",
            device, dtype, self._yes_token_id, self._no_token_id,
        )

    def _resolve_device(self) -> str:
        """Resolve the target device string."""
        if self._device != "auto":
            return self._device

        import torch
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    # ------------------------------------------------------------------
    # Reranking
    # ------------------------------------------------------------------

    def rerank(
        self,
        query: str,
        passages: List[Tuple[str, float, Dict[str, Any]]],
        top_k: Optional[int] = None,
        min_score: float = 0.0,
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """Rerank passages by relevance to the query.

        Args:
            query: The search query string.
            passages: List of (chunk_id, similarity_score, metadata) tuples
                     as returned by ``CodeIndexManager.search()``.
            top_k: Maximum number of results to return. If None, returns all.
            min_score: Minimum reranker score threshold. 0.0 disables filtering.

        Returns:
            Re-sorted list in the same format, with scores replaced by
            reranker relevance probabilities (0-1).  Each metadata dict
            gains a ``"reranked": True`` flag and the original vector
            similarity is preserved as ``"vector_similarity"``.
        """
        if not passages:
            return []

        self._ensure_loaded()

        if self._config.architecture == "cross_encoder":
            scores = self._score_cross_encoder(query, passages)
        else:
            scores = self._score_causal_lm(query, passages)

        # Build results with reranker scores
        reranked = []
        for (chunk_id, original_score, metadata), rerank_score in zip(passages, scores):
            enriched_meta = dict(metadata)
            enriched_meta["reranked"] = True
            enriched_meta["vector_similarity"] = original_score
            reranked.append((chunk_id, rerank_score, enriched_meta))

        # Sort by reranker score descending
        reranked.sort(key=lambda x: x[1], reverse=True)

        # Filter before top_k truncation so strict thresholds can still use the
        # full recall buffer produced upstream by reranker_recall_k.
        if min_score > 0.0:
            reranked = [r for r in reranked if r[1] >= min_score]

        if top_k is not None:
            reranked = reranked[:top_k]

        return reranked

    def _score_cross_encoder(
        self,
        query: str,
        passages: List[Tuple[str, float, Dict[str, Any]]],
    ) -> List[float]:
        """Score passages using a CrossEncoder model."""
        pairs = []
        for chunk_id, score, metadata in passages:
            content = metadata.get("content_preview", "") or metadata.get("content", "")
            pairs.append((query, content))

        raw_scores = self._model.predict(pairs)

        # Normalize raw scores to [0, 1] via sigmoid
        normalized = []
        for s in raw_scores:
            s_float = float(s)
            # Clamp to prevent overflow in exp
            clamped = max(-20.0, min(20.0, s_float))
            normalized.append(1.0 / (1.0 + math.exp(-clamped)))

        return normalized

    def _score_causal_lm(
        self,
        query: str,
        passages: List[Tuple[str, float, Dict[str, Any]]],
    ) -> List[float]:
        """Score passages using Qwen-style yes/no token classification."""
        import torch

        prompts = []
        for chunk_id, score, metadata in passages:
            content = metadata.get("content_preview", "") or metadata.get("content", "")
            prompts.append(self._build_prompt(query, content))

        inputs = self._tokenizer(
            prompts,
            padding=True,
            truncation=True,
            max_length=self._config.max_length,
            return_tensors="pt",
        ).to(self._model.device)

        with torch.no_grad():
            outputs = self._model(**inputs)

        scores = []
        for i in range(len(passages)):
            logits = outputs.logits[i, -1, :]
            yes_logit = logits[self._yes_token_id].float().item()
            no_logit = logits[self._no_token_id].float().item()
            # Numerically stable softmax over yes/no logits.
            shift = max(yes_logit, no_logit)
            yes_exp = math.exp(yes_logit - shift)
            no_exp = math.exp(no_logit - shift)
            score = yes_exp / (yes_exp + no_exp)
            score = max(0.0, min(1.0, score))
            scores.append(score)

        return scores

    def _build_prompt(self, query: str, document: str) -> str:
        """Build the official Qwen3-Reranker chat-template prompt."""
        instruction = self._config.instruction
        return (
            "<|im_start|>system\n"
            "Judge whether the document is relevant to the search query. "
            "Answer only \"yes\" or \"no\".<|im_end|>\n"
            "<|im_start|>user\n"
            f"<Instruct>: {instruction}\n"
            f"<Query>: {query}\n"
            f"<Document>: {document}<|im_end|>\n"
            "<|im_start|>assistant\n"
            "<think>\n\n</think>\n"
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Release model resources."""
        if self._model is not None:
            import torch

            del self._model
            del self._tokenizer
            self._model = None
            self._tokenizer = None
            self._yes_token_id = None
            self._no_token_id = None

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            logger.info("Reranker model unloaded")

    def get_model_info(self) -> Dict[str, Any]:
        """Return information about the reranker model."""
        return {
            "model_name": self._model_name,
            "short_name": self._config.short_name,
            "architecture": self._config.architecture,
            "loaded": self._model is not None,
            "device": str(self._model.device) if self._model is not None and hasattr(self._model, 'device') else None,
            "max_length": self._config.max_length,
            "description": self._config.description,
        }
