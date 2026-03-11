"""Unit tests for reranking.reranker_catalog module."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from reranking.reranker_catalog import (
    DEFAULT_RERANKER_MODEL,
    RERANKER_CATALOG,
    RERANKER_INSTRUCTION,
    RERANKER_SHORT_NAMES,
    RerankerModelConfig,
    get_reranker_config,
)


class TestRerankerModelConfig:
    """Tests for the RerankerModelConfig dataclass."""

    def test_config_is_frozen(self):
        """RerankerModelConfig instances should be immutable (frozen dataclass)."""
        config = RerankerModelConfig(
            model_name="test/model",
            short_name="test-model",
            instruction="test instruction",
        )
        with pytest.raises(AttributeError):
            config.model_name = "changed"

    def test_config_defaults(self):
        """Default values should be populated correctly."""
        config = RerankerModelConfig(
            model_name="test/model",
            short_name="test-model",
            instruction="test instruction",
        )
        assert config.max_length == 8192
        assert config.description == ""
        assert config.recommended_for == ""
        assert config.vram_requirement_gb == 8.0
        assert config.cpu_feasible is True
        assert config.architecture == "causal_lm"


class TestRerankerCatalog:
    """Tests for RERANKER_CATALOG entries."""

    def test_catalog_is_not_empty(self):
        assert len(RERANKER_CATALOG) > 0

    def test_qwen_reranker_in_catalog(self):
        """The Qwen3-Reranker-4B model must be registered."""
        assert "Qwen/Qwen3-Reranker-4B" in RERANKER_CATALOG

    def test_default_reranker_in_catalog(self):
        """The default reranker model must be in the catalog."""
        assert DEFAULT_RERANKER_MODEL in RERANKER_CATALOG

    def test_default_reranker_is_cpu_feasible(self):
        """The default reranker should be CPU-feasible."""
        config = RERANKER_CATALOG[DEFAULT_RERANKER_MODEL]
        assert config.cpu_feasible is True

    def test_qwen4b_entry_has_correct_fields(self):
        config = RERANKER_CATALOG["Qwen/Qwen3-Reranker-4B"]
        assert config.model_name == "Qwen/Qwen3-Reranker-4B"
        assert config.short_name == "qwen-reranker-4b"
        assert config.instruction == RERANKER_INSTRUCTION
        assert config.max_length == 8192
        assert config.vram_requirement_gb == 10.0
        assert config.cpu_feasible is False
        assert config.architecture == "causal_lm"

    def test_minilm_entry_has_correct_fields(self):
        config = RERANKER_CATALOG["cross-encoder/ms-marco-MiniLM-L-6-v2"]
        assert config.model_name == "cross-encoder/ms-marco-MiniLM-L-6-v2"
        assert config.short_name == "minilm-reranker"
        assert config.max_length == 512
        assert config.cpu_feasible is True
        assert config.architecture == "cross_encoder"

    def test_all_catalog_entries_are_reranker_model_configs(self):
        for name, config in RERANKER_CATALOG.items():
            assert isinstance(config, RerankerModelConfig), (
                f"Catalog entry '{name}' is not a RerankerModelConfig"
            )

    def test_all_catalog_entries_have_short_names(self):
        for name, config in RERANKER_CATALOG.items():
            assert config.short_name, f"Catalog entry '{name}' has no short_name"

    def test_all_catalog_entries_have_valid_architecture(self):
        valid_architectures = {"cross_encoder", "causal_lm"}
        for name, config in RERANKER_CATALOG.items():
            assert config.architecture in valid_architectures, (
                f"Catalog entry '{name}' has invalid architecture: {config.architecture}"
            )

    def test_instruction_is_not_empty(self):
        assert len(RERANKER_INSTRUCTION) > 0


class TestRerankerShortNames:
    """Tests for the RERANKER_SHORT_NAMES reverse lookup dict."""

    def test_short_names_not_empty(self):
        assert len(RERANKER_SHORT_NAMES) > 0

    def test_short_name_maps_to_full_name(self):
        assert RERANKER_SHORT_NAMES["qwen-reranker-4b"] == "Qwen/Qwen3-Reranker-4B"

    def test_minilm_short_name_maps(self):
        assert RERANKER_SHORT_NAMES["minilm-reranker"] == "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def test_short_names_are_unique(self):
        short_names = [c.short_name for c in RERANKER_CATALOG.values()]
        assert len(short_names) == len(set(short_names)), "Short names must be unique"

    def test_all_catalog_entries_have_reverse_lookup(self):
        """Every catalog entry with a short_name should appear in RERANKER_SHORT_NAMES."""
        for name, config in RERANKER_CATALOG.items():
            if config.short_name:
                assert config.short_name in RERANKER_SHORT_NAMES
                assert RERANKER_SHORT_NAMES[config.short_name] == name


class TestGetRerankerConfig:
    """Tests for the get_reranker_config function."""

    def test_lookup_by_full_name(self):
        config = get_reranker_config("Qwen/Qwen3-Reranker-4B")
        assert config.model_name == "Qwen/Qwen3-Reranker-4B"

    def test_lookup_by_short_name(self):
        config = get_reranker_config("qwen-reranker-4b")
        assert config.model_name == "Qwen/Qwen3-Reranker-4B"

    def test_lookup_minilm_by_full_name(self):
        config = get_reranker_config("cross-encoder/ms-marco-MiniLM-L-6-v2")
        assert config.architecture == "cross_encoder"

    def test_lookup_minilm_by_short_name(self):
        config = get_reranker_config("minilm-reranker")
        assert config.model_name == "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def test_unknown_model_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown reranker model"):
            get_reranker_config("nonexistent/model")

    def test_unknown_short_name_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown reranker model"):
            get_reranker_config("totally-fake-short-name")

    def test_error_message_lists_available_models(self):
        """The KeyError message should list available model names."""
        with pytest.raises(KeyError) as exc_info:
            get_reranker_config("bad-name")
        error_msg = str(exc_info.value)
        assert "Qwen/Qwen3-Reranker-4B" in error_msg
        assert "qwen-reranker-4b" in error_msg
