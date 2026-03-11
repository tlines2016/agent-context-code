"""Unit tests for workspace/workspace_config.WorkspaceConfig."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from workspace.workspace_config import (
    WorkspaceConfig,
    MODE_CODING,
    MODE_WRITING,
    CODING_EXTENSIONS,
    WRITING_EXTENSIONS,
)


# ---------------------------------------------------------------------------
# Default behaviour (no user config)
# ---------------------------------------------------------------------------

class TestDefaults:
    """Verify built-in defaults without any user configuration."""

    def test_source_code_defaults_to_coding(self):
        cfg = WorkspaceConfig()
        for ext in [".py", ".js", ".ts", ".go", ".java", ".rs", ".cpp"]:
            assert cfg.get_mode(f"example{ext}") == MODE_CODING

    def test_documentation_defaults_to_writing(self):
        cfg = WorkspaceConfig()
        for ext in [".md", ".txt", ".csv", ".json", ".yaml", ".toml", ".xml"]:
            assert cfg.get_mode(f"example{ext}") == MODE_WRITING

    def test_unknown_extension_uses_default_mode(self):
        cfg = WorkspaceConfig()
        # Default mode is "coding" when no config provided.
        assert cfg.get_mode("file.unknown") == MODE_CODING

    def test_default_mode_property(self):
        cfg = WorkspaceConfig()
        assert cfg.default_mode == MODE_CODING


# ---------------------------------------------------------------------------
# User overrides
# ---------------------------------------------------------------------------

class TestUserOverrides:
    """Verify user overrides via project config."""

    def test_override_default_mode(self):
        cfg = WorkspaceConfig({"workspace_mode": {"default_mode": "writing"}})
        assert cfg.default_mode == MODE_WRITING
        # Unknown extensions should now fall back to writing.
        assert cfg.get_mode("file.unknown") == MODE_WRITING

    def test_override_extension_to_coding(self):
        """A documentation extension can be forced to coding mode."""
        cfg = WorkspaceConfig({
            "workspace_mode": {
                "extension_overrides": {".md": "coding"}
            }
        })
        assert cfg.get_mode("README.md") == MODE_CODING

    def test_override_extension_to_writing(self):
        """A source-code extension can be forced to writing mode."""
        cfg = WorkspaceConfig({
            "workspace_mode": {
                "extension_overrides": {".py": "writing"}
            }
        })
        assert cfg.get_mode("script.py") == MODE_WRITING

    def test_override_new_extension(self):
        """A custom extension not in defaults can be mapped."""
        cfg = WorkspaceConfig({
            "workspace_mode": {
                "extension_overrides": {".proto": "coding"}
            }
        })
        assert cfg.get_mode("schema.proto") == MODE_CODING

    def test_extension_without_dot_is_normalised(self):
        cfg = WorkspaceConfig({
            "workspace_mode": {
                "extension_overrides": {"proto": "coding"}
            }
        })
        assert cfg.get_mode("schema.proto") == MODE_CODING

    def test_invalid_mode_in_override_is_ignored(self):
        cfg = WorkspaceConfig({
            "workspace_mode": {
                "extension_overrides": {".py": "invalid_mode"}
            }
        })
        # Should keep the built-in default (coding) for .py.
        assert cfg.get_mode("script.py") == MODE_CODING

    def test_invalid_default_mode_falls_back(self):
        cfg = WorkspaceConfig({"workspace_mode": {"default_mode": "bogus"}})
        assert cfg.default_mode == MODE_CODING


# ---------------------------------------------------------------------------
# Convenience methods
# ---------------------------------------------------------------------------

class TestConvenienceMethods:

    def test_is_coding(self):
        cfg = WorkspaceConfig()
        assert cfg.is_coding("main.py") is True
        assert cfg.is_coding("README.md") is False

    def test_is_writing(self):
        cfg = WorkspaceConfig()
        assert cfg.is_writing("README.md") is True
        assert cfg.is_writing("main.py") is False

    def test_get_coding_extensions(self):
        cfg = WorkspaceConfig()
        coding = cfg.get_coding_extensions()
        assert ".py" in coding
        assert ".md" not in coding

    def test_get_writing_extensions(self):
        cfg = WorkspaceConfig()
        writing = cfg.get_writing_extensions()
        assert ".md" in writing
        assert ".py" not in writing

    def test_extension_map_is_copy(self):
        """Modifying the returned map must not affect the config."""
        cfg = WorkspaceConfig()
        ext_map = cfg.extension_map
        ext_map[".py"] = MODE_WRITING  # mutate the copy
        assert cfg.get_mode("main.py") == MODE_CODING  # original unchanged


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

class TestSerialisation:

    def test_to_dict_with_no_overrides(self):
        cfg = WorkspaceConfig()
        d = cfg.to_dict()
        assert d["default_mode"] == MODE_CODING
        # No overrides beyond defaults — dict should be empty or small.
        assert isinstance(d["extension_overrides"], dict)

    def test_to_dict_with_overrides(self):
        cfg = WorkspaceConfig({
            "workspace_mode": {
                "extension_overrides": {".proto": "coding", ".md": "coding"}
            }
        })
        d = cfg.to_dict()
        # .proto is a new extension → must appear.
        assert ".proto" in d["extension_overrides"]
        # .md was changed from writing to coding → must appear.
        assert ".md" in d["extension_overrides"]

    def test_empty_config_is_safe(self):
        """None and empty dict must not crash."""
        cfg1 = WorkspaceConfig(None)
        cfg2 = WorkspaceConfig({})
        assert cfg1.default_mode == MODE_CODING
        assert cfg2.default_mode == MODE_CODING
