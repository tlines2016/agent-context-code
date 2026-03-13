"""Unit tests for reranking.reranker.CodeReranker."""

import math
import inspect
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from reranking.reranker import CodeReranker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_passages(n: int = 3):
    """Return n fake (chunk_id, score, metadata) tuples."""
    return [
        (f"chunk_{i}", float(i) / 10, {"content_preview": f"content {i}", "tag": i})
        for i in range(n)
    ]


def _make_loaded_reranker(yes_id: int = 1, no_id: int = 0) -> CodeReranker:
    """Return a CodeReranker whose model/tokenizer attributes are pre-populated
    with mocks, bypassing the real HuggingFace download path."""
    reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")

    mock_tokenizer = MagicMock()
    mock_tokenizer.convert_tokens_to_ids.side_effect = lambda tok: yes_id if tok == "yes" else no_id

    mock_model = MagicMock()
    mock_model.device = "cpu"

    reranker._tokenizer = mock_tokenizer
    reranker._model = mock_model
    reranker._yes_token_id = yes_id
    reranker._no_token_id = no_id

    return reranker


# ---------------------------------------------------------------------------
# Lazy loading
# ---------------------------------------------------------------------------

class TestLazyLoading:
    """_model and _tokenizer should start as None and only be set after
    _ensure_loaded() runs."""

    def test_initial_state_is_not_loaded(self):
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        assert reranker._model is None
        assert reranker._tokenizer is None
        assert reranker._yes_token_id is None
        assert reranker._no_token_id is None

    def test_get_model_info_reports_not_loaded(self):
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        info = reranker.get_model_info()
        assert info["loaded"] is False
        assert info["device"] is None

    def test_get_model_info_model_name(self):
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        info = reranker.get_model_info()
        assert info["model_name"] == "Qwen/Qwen3-Reranker-4B"

    def test_get_model_info_max_length(self):
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        info = reranker.get_model_info()
        assert info["max_length"] == 8192

    def test_unknown_model_raises_key_error_at_init(self):
        """CodeReranker.__init__ calls get_reranker_config, which raises on unknown models."""
        with pytest.raises(KeyError):
            CodeReranker(model_name="not/a/real/model", device="cpu")

    def test_rerank_empty_list_does_not_trigger_load(self):
        """rerank([]) must return [] without ever calling _ensure_loaded."""
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        with patch.object(reranker, "_ensure_loaded") as mock_ensure:
            result = reranker.rerank("query", [])
        assert result == []
        mock_ensure.assert_not_called()


# ---------------------------------------------------------------------------
# Prompt format
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    """_build_prompt must produce the expected Qwen3-Reranker chat-template."""

    def test_prompt_contains_system_block(self):
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        prompt = reranker._build_prompt("search query", "some document")
        assert "<|im_start|>system" in prompt

    def test_prompt_contains_user_block(self):
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        prompt = reranker._build_prompt("search query", "some document")
        assert "<|im_start|>user" in prompt

    def test_prompt_contains_query(self):
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        prompt = reranker._build_prompt("my search query", "document text")
        assert "my search query" in prompt

    def test_prompt_contains_document(self):
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        prompt = reranker._build_prompt("query", "my document text")
        assert "my document text" in prompt

    def test_prompt_contains_assistant_block(self):
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        prompt = reranker._build_prompt("q", "d")
        assert "<|im_start|>assistant" in prompt

    def test_prompt_contains_think_block(self):
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        prompt = reranker._build_prompt("q", "d")
        assert "<think>" in prompt

    def test_prompt_uses_config_instruction(self):
        """The instruction from RerankerModelConfig must appear in the prompt."""
        from reranking.reranker_catalog import get_reranker_config
        config = get_reranker_config("Qwen/Qwen3-Reranker-4B")
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        prompt = reranker._build_prompt("q", "d")
        assert config.instruction in prompt


# ---------------------------------------------------------------------------
# Scoring and sorting (mocked model)
# ---------------------------------------------------------------------------

class TestRerank:
    """rerank() correctness with a mocked forward pass."""

    def _make_logits_for_scores(self, yes_logit: float, no_logit: float):
        """Return a mock outputs object with single-passage logits."""
        import torch
        logits = torch.zeros(1, 1, 10)  # batch=1, seq=1, vocab=10
        logits[0, 0, 1] = yes_logit   # yes_token_id = 1
        logits[0, 0, 0] = no_logit    # no_token_id  = 0
        mock_outputs = MagicMock()
        mock_outputs.logits = logits
        return mock_outputs

    def _setup_reranker_for_scoring(self, yes_logit: float, no_logit: float):
        """Wire up a CodeReranker whose forward pass returns controlled logits."""
        pytest.importorskip("torch")  # skip if torch unavailable
        reranker = _make_loaded_reranker(yes_id=1, no_id=0)

        mock_outputs = self._make_logits_for_scores(yes_logit, no_logit)
        reranker._model.return_value = mock_outputs

        # tokenizer returns a mock that supports .to(device)
        mock_inputs = MagicMock()
        mock_inputs.to.return_value = mock_inputs
        reranker._tokenizer.return_value = mock_inputs

        return reranker

    def test_rerank_empty_passages_returns_empty(self):
        reranker = _make_loaded_reranker()
        assert reranker.rerank("q", []) == []

    def test_rerank_returns_same_count_without_top_k(self):
        pytest.importorskip("torch")
        import torch

        reranker = _make_loaded_reranker(yes_id=1, no_id=0)

        n = 3
        logits = torch.zeros(n, 1, 10)
        for i in range(n):
            logits[i, 0, 1] = float(i)  # increasing yes logit
        mock_outputs = MagicMock()
        mock_outputs.logits = logits
        reranker._model.return_value = mock_outputs

        mock_inputs = MagicMock()
        mock_inputs.to.return_value = mock_inputs
        reranker._tokenizer.return_value = mock_inputs

        passages = _make_passages(n)
        results = reranker.rerank("query", passages)
        assert len(results) == n

    def test_top_k_truncates_results(self):
        pytest.importorskip("torch")
        import torch

        reranker = _make_loaded_reranker(yes_id=1, no_id=0)

        n = 5
        logits = torch.zeros(n, 1, 10)
        mock_outputs = MagicMock()
        mock_outputs.logits = logits
        reranker._model.return_value = mock_outputs

        mock_inputs = MagicMock()
        mock_inputs.to.return_value = mock_inputs
        reranker._tokenizer.return_value = mock_inputs

        passages = _make_passages(n)
        results = reranker.rerank("query", passages, top_k=2)
        assert len(results) == 2

    def test_min_score_zero_preserves_top_k_behavior(self):
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        passages = _make_passages(5)
        mocked_scores = [0.3, 0.9, 0.5, 0.8, 0.1]

        with patch.object(reranker, "_ensure_loaded"), patch.object(
            reranker, "_score_causal_lm", return_value=mocked_scores
        ):
            baseline = reranker.rerank("query", passages, top_k=3)
            with_threshold = reranker.rerank("query", passages, top_k=3, min_score=0.0)

        assert [c for c, _, _ in with_threshold] == [c for c, _, _ in baseline]
        assert [s for _, s, _ in with_threshold] == pytest.approx([s for _, s, _ in baseline])

    def test_min_score_filters_mixed_scores(self):
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        passages = _make_passages(4)
        mocked_scores = [0.2, 0.91, 0.55, 0.49]

        with patch.object(reranker, "_ensure_loaded"), patch.object(
            reranker, "_score_causal_lm", return_value=mocked_scores
        ):
            filtered = reranker.rerank("query", passages, min_score=0.5)

        assert [chunk_id for chunk_id, _, _ in filtered] == ["chunk_1", "chunk_2"]
        assert all(score >= 0.5 for _, score, _ in filtered)

    def test_min_score_can_return_empty_results(self):
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        passages = _make_passages(3)

        with patch.object(reranker, "_ensure_loaded"), patch.object(
            reranker, "_score_causal_lm", return_value=[0.9, 0.8, 0.7]
        ):
            filtered = reranker.rerank("query", passages, top_k=2, min_score=1.1)

        assert filtered == []

    def test_min_score_filter_block_precedes_top_k_block(self):
        # Guard the intentional order: thresholding must happen before truncation.
        source = inspect.getsource(CodeReranker.rerank)
        assert source.index("if min_score > 0.0") < source.index("if top_k is not None")

    def test_min_score_uses_full_recall_set_and_can_return_fewer_than_k(self):
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        passages = _make_passages(10)
        seen_passage_count = {"value": 0}

        def _mock_score(_query, scored_passages):
            seen_passage_count["value"] = len(scored_passages)
            return [0.99, 0.9, 0.45, 0.4, 0.35, 0.3, 0.25, 0.2, 0.15, 0.1]

        with patch.object(reranker, "_ensure_loaded"), patch.object(
            reranker, "_score_causal_lm", side_effect=_mock_score
        ):
            filtered = reranker.rerank("query", passages, top_k=3, min_score=0.5)

        # Keep using the full recall set (10 here), then filter and truncate.
        assert seen_passage_count["value"] == 10
        assert len(filtered) == 2
        assert all(score >= 0.5 for _, score, _ in filtered)

    def test_results_sorted_descending_by_score(self):
        pytest.importorskip("torch")
        import torch

        reranker = _make_loaded_reranker(yes_id=1, no_id=0)

        n = 4
        logits = torch.zeros(n, 1, 10)
        # Give each passage a different yes logit so scores are distinct
        for i in range(n):
            logits[i, 0, 1] = float(n - 1 - i)  # descending logits → chunk_0 scores highest
        mock_outputs = MagicMock()
        mock_outputs.logits = logits
        reranker._model.return_value = mock_outputs

        mock_inputs = MagicMock()
        mock_inputs.to.return_value = mock_inputs
        reranker._tokenizer.return_value = mock_inputs

        passages = _make_passages(n)
        results = reranker.rerank("query", passages)
        scores = [r[1] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_metadata_enrichment_sets_reranked_flag(self):
        pytest.importorskip("torch")
        import torch

        reranker = _make_loaded_reranker(yes_id=1, no_id=0)

        logits = torch.zeros(1, 1, 10)
        mock_outputs = MagicMock()
        mock_outputs.logits = logits
        reranker._model.return_value = mock_outputs

        mock_inputs = MagicMock()
        mock_inputs.to.return_value = mock_inputs
        reranker._tokenizer.return_value = mock_inputs

        passages = [("chunk_0", 0.5, {"content_preview": "hello"})]
        results = reranker.rerank("query", passages)
        assert len(results) == 1
        _, _, meta = results[0]
        assert meta["reranked"] is True

    def test_metadata_enrichment_preserves_vector_similarity(self):
        pytest.importorskip("torch")
        import torch

        reranker = _make_loaded_reranker(yes_id=1, no_id=0)

        logits = torch.zeros(1, 1, 10)
        mock_outputs = MagicMock()
        mock_outputs.logits = logits
        reranker._model.return_value = mock_outputs

        mock_inputs = MagicMock()
        mock_inputs.to.return_value = mock_inputs
        reranker._tokenizer.return_value = mock_inputs

        original_score = 0.87
        passages = [("chunk_0", original_score, {"content_preview": "hello"})]
        results = reranker.rerank("query", passages)
        _, _, meta = results[0]
        assert meta["vector_similarity"] == pytest.approx(original_score)

    def test_original_metadata_keys_preserved(self):
        pytest.importorskip("torch")
        import torch

        reranker = _make_loaded_reranker(yes_id=1, no_id=0)

        logits = torch.zeros(1, 1, 10)
        mock_outputs = MagicMock()
        mock_outputs.logits = logits
        reranker._model.return_value = mock_outputs

        mock_inputs = MagicMock()
        mock_inputs.to.return_value = mock_inputs
        reranker._tokenizer.return_value = mock_inputs

        passages = [("chunk_0", 0.5, {"content_preview": "x", "my_key": "kept"})]
        results = reranker.rerank("query", passages)
        _, _, meta = results[0]
        assert meta["my_key"] == "kept"

    def test_score_is_probability_between_0_and_1(self):
        pytest.importorskip("torch")
        import torch

        reranker = _make_loaded_reranker(yes_id=1, no_id=0)

        logits = torch.zeros(2, 1, 10)
        logits[0, 0, 1] = 5.0   # strong yes → score near 1
        logits[1, 0, 0] = 5.0   # strong no  → score near 0
        mock_outputs = MagicMock()
        mock_outputs.logits = logits
        reranker._model.return_value = mock_outputs

        mock_inputs = MagicMock()
        mock_inputs.to.return_value = mock_inputs
        reranker._tokenizer.return_value = mock_inputs

        passages = _make_passages(2)
        results = reranker.rerank("query", passages)
        for _, score, _ in results:
            assert 0.0 <= score <= 1.0

    def test_scores_are_finite_with_extreme_logits(self):
        """Extreme logits must not raise OverflowError or produce inf/nan scores.

        math.exp() raises OverflowError for inputs > ~709.  The softmax in
        reranker.rerank() uses a numerically stable implementation (log-sum-exp
        shift) to prevent this.  This test verifies that very large logit values
        are handled gracefully and the returned score is always in [0.0, 1.0].
        """
        pytest.importorskip("torch")
        import torch

        reranker = _make_loaded_reranker(yes_id=1, no_id=0)

        # Extreme logit values that would overflow naive math.exp(800)
        logits = torch.zeros(1, 1, 10)
        logits[0, 0, 1] = 800.0   # yes logit
        logits[0, 0, 0] = 0.0     # no logit

        mock_outputs = MagicMock()
        mock_outputs.logits = logits
        reranker._model.return_value = mock_outputs

        mock_inputs = MagicMock()
        mock_inputs.to.return_value = mock_inputs
        reranker._tokenizer.return_value = mock_inputs

        passages = [("chunk_0", 0.5, {"content_preview": "code"})]
        # Must not raise OverflowError
        results = reranker.rerank("query", passages)
        assert len(results) == 1
        _, score, _ = results[0]
        import math
        assert math.isfinite(score), f"Score must be finite; got {score}"
        assert 0.0 <= score <= 1.0, f"Score must be in [0, 1]; got {score}"
        # With yes_logit >> no_logit, the score should be close to 1.0
        assert score > 0.99, f"Score should be near 1.0 for dominant yes logit; got {score}"

    def test_content_preview_used_for_prompt_building(self):
        """rerank() should use content_preview from metadata to build prompts."""
        pytest.importorskip("torch")
        import torch

        reranker = _make_loaded_reranker(yes_id=1, no_id=0)

        logits = torch.zeros(1, 1, 10)
        mock_outputs = MagicMock()
        mock_outputs.logits = logits
        reranker._model.return_value = mock_outputs

        captured_prompts = []
        def capture_tokenizer(prompts, **kwargs):
            captured_prompts.extend(prompts)
            mock_inputs = MagicMock()
            mock_inputs.to.return_value = mock_inputs
            return mock_inputs

        reranker._tokenizer.side_effect = capture_tokenizer

        passages = [("chunk_0", 0.5, {"content_preview": "def foo(): pass"})]
        reranker.rerank("test query", passages)
        assert any("def foo(): pass" in p for p in captured_prompts)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    """cleanup() must release model/tokenizer and reset all internal state."""

    def test_cleanup_resets_model_to_none(self):
        pytest.importorskip("torch")
        reranker = _make_loaded_reranker()
        with patch("torch.cuda.is_available", return_value=False):
            reranker.cleanup()
        assert reranker._model is None

    def test_cleanup_resets_tokenizer_to_none(self):
        pytest.importorskip("torch")
        reranker = _make_loaded_reranker()
        with patch("torch.cuda.is_available", return_value=False):
            reranker.cleanup()
        assert reranker._tokenizer is None

    def test_cleanup_resets_token_ids(self):
        pytest.importorskip("torch")
        reranker = _make_loaded_reranker(yes_id=42, no_id=7)
        with patch("torch.cuda.is_available", return_value=False):
            reranker.cleanup()
        assert reranker._yes_token_id is None
        assert reranker._no_token_id is None

    def test_cleanup_when_not_loaded_is_safe(self):
        """cleanup() on an unloaded reranker should not raise."""
        reranker = CodeReranker(model_name="Qwen/Qwen3-Reranker-4B", device="cpu")
        reranker.cleanup()  # should not raise

    def test_get_model_info_after_cleanup_reports_not_loaded(self):
        pytest.importorskip("torch")
        reranker = _make_loaded_reranker()
        with patch("torch.cuda.is_available", return_value=False):
            reranker.cleanup()
        info = reranker.get_model_info()
        assert info["loaded"] is False
