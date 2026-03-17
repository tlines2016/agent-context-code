"""Unit tests for the CLI help and diagnostics tool."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.cli import (
    _get_storage_dir_or_report,
    cmd_config,
    cmd_config_reranker_min_score,
    cmd_doctor,
    cmd_help,
    cmd_open_dashboard,
    cmd_create_shortcut,
    cmd_paths,
    cmd_setup_guide,
    cmd_status,
    cmd_version,
    _is_dashboard_running,
    _ui_port,
    _ui_server_cmd_parts,
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
        assert "agent-context-local" in out
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

    def test_commands_dict_contains_dashboard_entries(self):
        """New dashboard commands must be registered in COMMANDS."""
        assert "open-dashboard" in COMMANDS
        assert "create-shortcut" in COMMANDS

    def test_help_lists_dashboard_commands(self, capsys):
        """help output must mention both new dashboard commands."""
        cmd_help()
        out = capsys.readouterr().out
        assert "open-dashboard" in out
        assert "create-shortcut" in out


class TestRerankerMinScoreConfig:
    def test_config_reranker_min_score_persists_value(self, monkeypatch):
        storage = Path("/tmp/test-storage")
        captured = {}

        monkeypatch.setattr("scripts.cli._get_storage_dir_or_report", lambda _cmd: storage)
        monkeypatch.setattr(
            "scripts.cli.load_reranker_config",
            lambda storage_dir=None: {
                "model_name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                "enabled": True,
                "recall_k": 60,
                "min_reranker_score": 0.0,
            },
        )

        def _save(**kwargs):
            captured.update(kwargs)
            return Path("/tmp/install_config.json")

        monkeypatch.setattr("scripts.cli.save_reranker_config", _save)
        cmd_config_reranker_min_score("0.35")

        assert captured["model_name"] == "cross-encoder/ms-marco-MiniLM-L-6-v2"
        assert captured["enabled"] is True
        assert captured["recall_k"] == 60
        assert captured["min_reranker_score"] == pytest.approx(0.35)
        assert captured["storage_dir"] == storage

    def test_config_reranker_min_score_rejects_out_of_range(self, monkeypatch):
        monkeypatch.setattr("scripts.cli._get_storage_dir_or_report", lambda _cmd: Path("/tmp/x"))
        with pytest.raises(SystemExit):
            cmd_config_reranker_min_score("1.5")

    def test_config_reranker_min_score_rejects_non_numeric(self, monkeypatch):
        monkeypatch.setattr("scripts.cli._get_storage_dir_or_report", lambda _cmd: Path("/tmp/x"))
        with pytest.raises(SystemExit):
            cmd_config_reranker_min_score("not-a-number")

    def test_config_dispatch_routes_min_score_subcommand(self, monkeypatch):
        monkeypatch.setattr("scripts.cli.sys.argv", ["cli.py", "config", "reranker", "min-score", "0.2"])
        captured = {"value": None}

        def _capture(raw_value: str):
            captured["value"] = raw_value

        monkeypatch.setattr("scripts.cli.cmd_config_reranker_min_score", _capture)
        cmd_config()
        assert captured["value"] == "0.2"


class TestDashboardCommands:
    """Tests for open-dashboard and create-shortcut commands."""

    # ── helpers ──────────────────────────────────────────────────────

    def test_ui_port_defaults_to_7432(self, monkeypatch):
        monkeypatch.delenv("CODE_SEARCH_UI_PORT", raising=False)
        assert _ui_port() == 7432

    def test_ui_port_respects_env_var(self, monkeypatch):
        monkeypatch.setenv("CODE_SEARCH_UI_PORT", "9000")
        assert _ui_port() == 9000

    def test_ui_server_cmd_parts_returns_list(self):
        parts = _ui_server_cmd_parts()
        assert isinstance(parts, list)
        assert len(parts) > 0

    def test_is_dashboard_running_returns_false_on_closed_port(self):
        # Port 1 is effectively always closed (reserved / no process).
        assert _is_dashboard_running(1) is False

    # ── open-dashboard ────────────────────────────────────────────────

    def test_open_dashboard_opens_browser_when_server_running(self, monkeypatch, capsys):
        """When the server is already up the browser should open immediately."""
        monkeypatch.setattr("scripts.cli._is_dashboard_running", lambda _port: True)
        opened_urls: list[str] = []
        monkeypatch.setattr("webbrowser.open", lambda url: opened_urls.append(url))
        cmd_open_dashboard()
        out = capsys.readouterr().out
        assert "already running" in out
        assert len(opened_urls) == 1
        assert "127.0.0.1" in opened_urls[0]

    def test_open_dashboard_reports_failure_if_server_never_starts(self, monkeypatch, capsys):
        """When the server fails to start a clear error message must be printed."""
        import subprocess as _sp

        class _FakeProc:
            pid = 9999

        monkeypatch.setattr("scripts.cli._is_dashboard_running", lambda _port: False)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())
        # time.sleep is a no-op so the poll loop exits immediately.
        monkeypatch.setattr("time.sleep", lambda _s: None)
        cmd_open_dashboard()
        out = capsys.readouterr().out
        assert "did not start" in out

    # ── create-shortcut ───────────────────────────────────────────────

    def test_create_shortcut_linux_writes_desktop_file(self, monkeypatch, tmp_path, capsys):
        """Linux shortcut creates a .desktop file under ~/.local/share/applications."""
        import scripts.cli as cli_mod

        # Redirect home so no real files are written.
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        apps_dir = fake_home / ".local" / "share" / "applications"

        monkeypatch.setattr(cli_mod.Path, "home", staticmethod(lambda: fake_home))
        monkeypatch.setattr("scripts.cli.is_wsl", lambda: False)
        monkeypatch.setattr("scripts.cli.is_windows", lambda: False)
        monkeypatch.setattr("scripts.cli.platform.system", lambda: "Linux")
        # Suppress update-desktop-database
        monkeypatch.setattr("shutil.which", lambda name: None)

        cli_mod._create_shortcut_linux(also_desktop=False)

        desktop_file = apps_dir / "agent-context-dashboard.desktop"
        assert desktop_file.exists(), "Expected .desktop file to be created"
        content = desktop_file.read_text()
        assert "[Desktop Entry]" in content
        assert "Agent Context Dashboard" in content
        assert "Type=Application" in content

    def test_create_shortcut_macos_writes_app_bundle(self, monkeypatch, tmp_path, capsys):
        """macOS shortcut creates a minimal .app bundle."""
        import scripts.cli as cli_mod

        fake_home = tmp_path / "home"
        fake_home.mkdir()

        monkeypatch.setattr(cli_mod.Path, "home", staticmethod(lambda: fake_home))
        monkeypatch.setattr("shutil.which", lambda name: None)

        cli_mod._create_shortcut_macos()

        app_bundle = fake_home / "Applications" / "Agent Context Dashboard.app"
        assert app_bundle.is_dir(), "Expected .app bundle directory"
        info_plist = app_bundle / "Contents" / "Info.plist"
        assert info_plist.exists(), "Expected Info.plist inside .app bundle"
        app_run = app_bundle / "Contents" / "MacOS" / "AppRun"
        assert app_run.exists(), "Expected AppRun executable inside .app bundle"
        # Verify it's executable (skip on Windows — NTFS ignores chmod)
        if os.name != "nt":
            assert app_run.stat().st_mode & 0o111, "AppRun should be executable"

    def test_ui_port_falls_back_to_default_on_bad_env_var(self, monkeypatch, capsys):
        """_ui_port() must fall back to 7432 (not raise) when env var is not an integer."""
        monkeypatch.setenv("CODE_SEARCH_UI_PORT", "not-a-number")
        result = _ui_port()
        assert result == 7432
        out = capsys.readouterr().out
        assert "Warning" in out or "not a valid integer" in out.lower() or "not-a-number" in out

    def test_create_shortcut_linux_exec_cmd_no_double_extra_flag(self, monkeypatch, tmp_path):
        """GPU extra flag must not be duplicated in the Linux .desktop Exec line."""
        import scripts.cli as cli_mod

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        apps_dir = fake_home / ".local" / "share" / "applications"

        monkeypatch.setattr(cli_mod.Path, "home", staticmethod(lambda: fake_home))
        monkeypatch.setattr("scripts.cli.is_wsl", lambda: False)
        monkeypatch.setattr("scripts.cli.is_windows", lambda: False)
        monkeypatch.setattr("scripts.cli.platform.system", lambda: "Linux")
        monkeypatch.setattr("shutil.which", lambda name: None)
        # Simulate a GPU extra being configured.
        monkeypatch.setattr("scripts.cli._gpu_extra_flag", lambda: "--extra cu128 ")

        cli_mod._create_shortcut_linux(also_desktop=False)

        desktop_file = apps_dir / "agent-context-dashboard.desktop"
        content = desktop_file.read_text()
        # Should contain exactly one --extra flag, not "--extra --extra"
        assert "--extra --extra" not in content
        assert "--extra cu128" in content

    def test_create_shortcut_macos_no_double_extra_flag(self, monkeypatch, tmp_path):
        """GPU extra flag must not be duplicated in the macOS AppRun script."""
        import scripts.cli as cli_mod

        fake_home = tmp_path / "home"
        fake_home.mkdir()

        monkeypatch.setattr(cli_mod.Path, "home", staticmethod(lambda: fake_home))
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setattr("scripts.cli._gpu_extra_flag", lambda: "--extra cu128 ")

        cli_mod._create_shortcut_macos()

        app_run = fake_home / "Applications" / "Agent Context Dashboard.app" / "Contents" / "MacOS" / "AppRun"
        content = app_run.read_text()
        assert "--extra --extra" not in content
        assert "--extra cu128" in content
