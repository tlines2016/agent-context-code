"""Unit tests for the CLI help and diagnostics tool."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.cli import (
    _get_storage_dir_or_report,
    cmd_doctor,
    cmd_help,
    cmd_paths,
    cmd_setup_guide,
    cmd_status,
    cmd_version,
    get_claude_config_paths,
    get_default_install_dir,
    get_platform_label,
    is_windows,
    is_wsl,
    COMMANDS,
)


class TestCLICommands:
    """Tests for CLI sub-commands."""

    def test_help_runs_without_error(self, capsys):
        """help command should print usage info."""
        cmd_help()
        out = capsys.readouterr().out
        assert "Claude Context Local" in out
        assert "COMMANDS" in out
        assert "doctor" in out

    def test_version_runs_without_error(self, capsys):
        """version command should print version and platform."""
        cmd_version()
        out = capsys.readouterr().out
        assert "agent-context-code" in out
        assert "Python:" in out

    def test_paths_runs_without_error(self, capsys):
        """paths command should list storage and config paths."""
        cmd_paths()
        out = capsys.readouterr().out
        assert "Storage directory" in out
        assert "Install directory" in out

    def test_doctor_runs_without_error(self, capsys):
        """doctor command should run diagnostics."""
        cmd_doctor()
        out = capsys.readouterr().out
        assert "Running diagnostics" in out
        assert "Python" in out

    def test_doctor_checks_runtime_fastmcp_import_path(self, monkeypatch, tmp_path, capsys):
        """doctor should report 'mcp not importable' when the mcp package is broken."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "model.bin").write_text("cached", encoding="utf-8")

        monkeypatch.setattr("scripts.cli._get_storage_dir_or_report", lambda _command: tmp_path)
        monkeypatch.setattr(
            "scripts.cli.load_local_install_config",
            lambda storage_dir=None: {"embedding_model": {"model_name": "google/embeddinggemma-300m"}},
        )
        monkeypatch.setattr("scripts.cli.shutil.which", lambda _name: "/usr/bin/mock")
        monkeypatch.setattr("scripts.cli.is_wsl", lambda: False)

        def fake_import_module(name):
            # Simulate the mcp package (and mcp.server.fastmcp) being broken,
            # while fastmcp itself is available.
            if name in ("mcp", "mcp.server.fastmcp"):
                raise ModuleNotFoundError("broken mcp runtime import")
            return object()

        monkeypatch.setattr("scripts.cli.importlib.import_module", fake_import_module)

        cmd_doctor()
        out = capsys.readouterr().out

        # The mcp check entry should report the failure with the correct package name
        assert "mcp.server.fastmcp" in out
        assert "mcp not importable" in out
        # fastmcp itself should still be reported as available
        assert "fastmcp importable" in out

    def test_status_runs_without_error(self, capsys):
        """status command should report index state."""
        cmd_status()
        out = capsys.readouterr().out
        assert "Index Status" in out

    def test_setup_guide_runs_without_error(self, capsys):
        """setup-guide should print setup instructions."""
        cmd_setup_guide()
        out = capsys.readouterr().out
        assert "Setup Guide" in out
        assert "Install" in out
        assert "Register the MCP server" in out

    def test_get_storage_dir_or_report_handles_failure(self, capsys):
        """Storage helper should report errors and return None."""
        with patch("scripts.cli.get_storage_dir", side_effect=RuntimeError("storage unavailable")):
            result = _get_storage_dir_or_report("status")

        out = capsys.readouterr().out
        assert result is None
        assert "status could not access the storage directory" in out
        assert "storage unavailable" in out
        assert "CODE_SEARCH_STORAGE" in out

    def test_status_handles_unwritable_storage_dir(self, capsys):
        """status command should fail gracefully when storage is not writable."""
        with patch("scripts.cli.get_storage_dir", side_effect=RuntimeError("storage unavailable")):
            cmd_status()

        out = capsys.readouterr().out
        assert "status could not access the storage directory" in out
        assert "CODE_SEARCH_STORAGE" in out

    def test_status_returns_before_project_lookup_when_storage_missing(self, capsys):
        """status should stop immediately when storage resolution fails."""
        with patch("scripts.cli._get_storage_dir_or_report", return_value=None) as helper:
            with patch("pathlib.Path.is_dir", side_effect=AssertionError("should not inspect directories")):
                with patch("pathlib.Path.iterdir", side_effect=AssertionError("should not enumerate directories")):
                    cmd_status()

        out = capsys.readouterr().out
        helper.assert_called_once_with("status")
        assert "Index Status" in out

    def test_unknown_command_exits_with_error(self):
        """An unknown command should exit with code 1."""
        result = subprocess.run(
            [sys.executable, "scripts/cli.py", "nonexistent"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
        assert result.returncode == 1
        assert "Unknown command" in result.stderr or "Unknown command" in result.stdout

    def test_no_args_shows_help(self):
        """Running with no args should show help."""
        result = subprocess.run(
            [sys.executable, "scripts/cli.py"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
        assert result.returncode == 0
        assert "COMMANDS" in result.stdout


class TestCLIPlatformHelpers:
    """Tests for platform detection helpers."""

    def test_is_windows_returns_bool(self):
        assert isinstance(is_windows(), bool)

    def test_is_wsl_returns_bool(self):
        assert isinstance(is_wsl(), bool)

    def test_get_platform_label_returns_string(self):
        label = get_platform_label()
        assert isinstance(label, str)
        assert len(label) > 0

    def test_get_default_install_dir_returns_path(self):
        path = get_default_install_dir()
        assert isinstance(path, Path)

    def test_get_claude_config_paths_returns_list(self):
        paths = get_claude_config_paths()
        assert isinstance(paths, list)
        assert all(isinstance(p, Path) for p in paths)

    def test_commands_dict_contains_required_entries(self):
        required = {"help", "--help", "-h", "doctor", "version", "--version", "status", "paths", "setup-guide"}
        assert required.issubset(COMMANDS.keys())
