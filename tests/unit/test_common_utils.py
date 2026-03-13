"""Unit tests for common_utils module additions."""

import json
import os
import platform
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from common_utils import (
    VERSION,
    get_storage_dir,
    is_windows,
    load_local_install_config,
    load_reranker_config,
    normalize_path,
    save_local_install_config,
    save_idle_config,
    save_reranker_config,
)


class TestCommonUtilsAdditions:
    """Tests for new utilities in common_utils."""

    def test_version_is_string(self):
        assert isinstance(VERSION, str)
        assert len(VERSION) > 0

    def test_is_windows_returns_bool(self):
        assert isinstance(is_windows(), bool)

    def test_normalize_path_strips_redundant_separators(self):
        """normalize_path should resolve redundant separators."""
        result = normalize_path("/tmp//foo///bar")
        assert "//" not in result

    def test_normalize_path_expands_tilde(self):
        """normalize_path should expand ~ to the home directory."""
        result = normalize_path("~/somefile")
        assert "~" not in result

    def test_normalize_path_resolves_to_absolute(self):
        """normalize_path should always return an absolute path."""
        result = normalize_path("relative/path")
        assert os.path.isabs(result)

    def test_load_local_install_config_returns_empty_on_missing(self, tmp_path):
        """Should return {} when config file does not exist."""
        config = load_local_install_config(storage_dir=tmp_path / "nonexistent")
        assert config == {}

    def test_load_local_install_config_handles_corrupt_json(self, tmp_path):
        """Should return {} and log warning on corrupt JSON."""
        config_path = tmp_path / "install_config.json"
        config_path.write_text("not valid json {{{", encoding="utf-8")
        config = load_local_install_config(storage_dir=tmp_path)
        assert config == {}

    def test_load_local_install_config_reads_valid_json(self, tmp_path):
        """Should successfully load valid config."""
        config_path = tmp_path / "install_config.json"
        expected = {"embedding_model": {"model_name": "test/model"}}
        config_path.write_text(json.dumps(expected), encoding="utf-8")
        config = load_local_install_config(storage_dir=tmp_path)
        assert config == expected

    def test_get_storage_dir_returns_path(self):
        result = get_storage_dir()
        assert isinstance(result, Path)

    def test_get_storage_dir_creates_directory(self, tmp_path):
        """get_storage_dir should create the directory if missing."""
        test_dir = str(tmp_path / "new_storage")
        # Need to clear the lru_cache for this test
        get_storage_dir.cache_clear()
        with patch.dict(os.environ, {"CODE_SEARCH_STORAGE": test_dir}):
            result = get_storage_dir()
            assert result.is_dir()
        get_storage_dir.cache_clear()


class TestSaveLocalInstallConfig:
    """Tests for save_local_install_config."""

    def test_save_creates_config_file(self, tmp_path):
        """save_local_install_config should create install_config.json."""
        config_path = save_local_install_config("test/model", storage_dir=tmp_path)
        assert config_path.exists()
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["embedding_model"]["model_name"] == "test/model"

    def test_save_merges_with_existing_config(self, tmp_path):
        """save_local_install_config should preserve existing keys."""
        # Write an initial config with extra data
        config_path = tmp_path / "install_config.json"
        config_path.write_text(
            json.dumps({"other_key": "keep_me", "embedding_model": {"old_key": "old_val"}}),
            encoding="utf-8",
        )
        save_local_install_config("new/model", storage_dir=tmp_path)
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["other_key"] == "keep_me"
        assert data["embedding_model"]["model_name"] == "new/model"
        # The old key in embedding_model should be preserved
        assert data["embedding_model"]["old_key"] == "old_val"

    def test_save_with_overrides(self, tmp_path):
        """save_local_install_config should apply overrides."""
        save_local_install_config(
            "test/model",
            storage_dir=tmp_path,
            overrides={"embedding_dimension": 768},
        )
        config_path = tmp_path / "install_config.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["embedding_model"]["embedding_dimension"] == 768

    def test_save_ignores_empty_string_overrides(self, tmp_path):
        """Empty string overrides should not be written."""
        save_local_install_config(
            "test/model",
            storage_dir=tmp_path,
            overrides={"empty_val": ""},
        )
        config_path = tmp_path / "install_config.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert "empty_val" not in data["embedding_model"]

    def test_save_ignores_none_overrides(self, tmp_path):
        """None overrides should not be written."""
        save_local_install_config(
            "test/model",
            storage_dir=tmp_path,
            overrides={"none_val": None},
        )
        config_path = tmp_path / "install_config.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert "none_val" not in data["embedding_model"]


class TestRerankerConfig:
    """Tests for load_reranker_config and save_reranker_config."""

    def test_load_reranker_config_returns_empty_when_missing(self, tmp_path):
        """Should return {} when no reranker section exists."""
        config = load_reranker_config(storage_dir=tmp_path / "nonexistent")
        assert config == {}

    def test_load_reranker_config_returns_empty_when_no_reranker_key(self, tmp_path):
        """Should return {} when config exists but has no reranker key."""
        config_path = tmp_path / "install_config.json"
        config_path.write_text(json.dumps({"embedding_model": {}}), encoding="utf-8")
        config = load_reranker_config(storage_dir=tmp_path)
        assert config == {}

    def test_load_reranker_config_returns_empty_for_non_object_section(self, tmp_path):
        """Malformed reranker values (non-dict) should safely normalize to {}."""
        config_path = tmp_path / "install_config.json"
        config_path.write_text(json.dumps({"reranker": "invalid"}), encoding="utf-8")
        config = load_reranker_config(storage_dir=tmp_path)
        assert config == {}

    def test_load_reranker_config_reads_reranker_section(self, tmp_path):
        """Should return the reranker section when present."""
        reranker_data = {"model_name": "Qwen/Qwen3-Reranker-4B", "enabled": True}
        config_path = tmp_path / "install_config.json"
        config_path.write_text(
            json.dumps({"reranker": reranker_data}), encoding="utf-8"
        )
        config = load_reranker_config(storage_dir=tmp_path)
        assert config == reranker_data

    def test_save_reranker_config_creates_file(self, tmp_path):
        """save_reranker_config should create install_config.json with reranker."""
        config_path = save_reranker_config(
            "Qwen/Qwen3-Reranker-4B", enabled=True, recall_k=100, storage_dir=tmp_path
        )
        assert config_path.exists()
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["reranker"]["model_name"] == "Qwen/Qwen3-Reranker-4B"
        assert data["reranker"]["enabled"] is True
        assert data["reranker"]["recall_k"] == 100
        assert data["reranker"]["min_reranker_score"] == pytest.approx(0.0)

    def test_save_reranker_config_defaults(self, tmp_path):
        """save_reranker_config should use correct defaults."""
        save_reranker_config("test/reranker", storage_dir=tmp_path)
        config_path = tmp_path / "install_config.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["reranker"]["enabled"] is False
        assert data["reranker"]["recall_k"] == 50
        assert data["reranker"]["min_reranker_score"] == pytest.approx(0.0)

    def test_save_reranker_config_persists_min_reranker_score(self, tmp_path):
        """save_reranker_config should persist min_reranker_score when provided."""
        save_reranker_config(
            "Qwen/Qwen3-Reranker-4B",
            enabled=True,
            recall_k=50,
            min_reranker_score=0.35,
            storage_dir=tmp_path,
        )
        config_path = tmp_path / "install_config.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["reranker"]["min_reranker_score"] == pytest.approx(0.35)

    def test_save_reranker_config_positional_storage_dir_is_backward_compatible(self, tmp_path):
        """Legacy 4th positional arg should still map to storage_dir."""
        save_reranker_config("Qwen/Qwen3-Reranker-4B", True, 42, tmp_path)
        config_path = tmp_path / "install_config.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["reranker"]["model_name"] == "Qwen/Qwen3-Reranker-4B"
        assert data["reranker"]["enabled"] is True
        assert data["reranker"]["recall_k"] == 42
        assert data["reranker"]["min_reranker_score"] == pytest.approx(0.0)

    def test_save_reranker_config_preserves_embedding_config(self, tmp_path):
        """save_reranker_config should not overwrite embedding_model."""
        # First save an embedding config
        save_local_install_config("google/embeddinggemma-300m", storage_dir=tmp_path)
        # Then save reranker config
        save_reranker_config("Qwen/Qwen3-Reranker-4B", storage_dir=tmp_path)

        config_path = tmp_path / "install_config.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        # Both sections should coexist
        assert data["embedding_model"]["model_name"] == "google/embeddinggemma-300m"
        assert data["reranker"]["model_name"] == "Qwen/Qwen3-Reranker-4B"

    def test_roundtrip_save_then_load_reranker(self, tmp_path):
        """Saving and loading reranker config should produce identical data."""
        save_reranker_config(
            "Qwen/Qwen3-Reranker-4B",
            enabled=True,
            recall_k=75,
            min_reranker_score=0.2,
            storage_dir=tmp_path,
        )
        loaded = load_reranker_config(storage_dir=tmp_path)
        assert loaded["model_name"] == "Qwen/Qwen3-Reranker-4B"
        assert loaded["enabled"] is True
        assert loaded["recall_k"] == 75
        assert loaded["min_reranker_score"] == pytest.approx(0.2)


class TestIdleConfig:
    """Tests for save_idle_config validation and persistence."""

    def test_save_idle_config_persists_values(self, tmp_path):
        save_idle_config(
            idle_offload_minutes=20,
            idle_unload_minutes=45,
            storage_dir=tmp_path,
        )
        data = json.loads((tmp_path / "install_config.json").read_text(encoding="utf-8"))
        assert data["idle_offload_minutes"] == 20
        assert data["idle_unload_minutes"] == 45

    def test_save_idle_config_rejects_negative_values(self, tmp_path):
        with pytest.raises(ValueError):
            save_idle_config(idle_offload_minutes=-1, storage_dir=tmp_path)

    def test_save_idle_config_rejects_non_integer_values(self, tmp_path):
        with pytest.raises(ValueError):
            save_idle_config(idle_unload_minutes="abc", storage_dir=tmp_path)  # type: ignore[arg-type]
