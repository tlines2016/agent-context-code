"""Clean-environment packaging smoke tests.

Marked ``@pytest.mark.packaging`` so they are excluded from normal test runs.
Run explicitly with::

    uv run python -m pytest tests/integration/test_packaging.py -v -m packaging

These tests build a wheel, install it into a temporary venv, and verify
the installed entry points work correctly.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

pytestmark = pytest.mark.packaging


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command and return the result, capturing output."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
        **kwargs,
    )


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory) -> Path:
    """Build a wheel from the project and return its path."""
    dist_dir = tmp_path_factory.mktemp("dist")
    result = _run(
        ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, f"uv build failed:\n{result.stderr}"
    wheels = list(dist_dir.glob("*.whl"))
    assert len(wheels) == 1, f"Expected 1 wheel, found {len(wheels)}: {wheels}"
    return wheels[0]


@pytest.fixture(scope="module")
def installed_venv(built_wheel: Path, tmp_path_factory) -> Path:
    """Create a fresh venv and install the built wheel into it."""
    venv_dir = tmp_path_factory.mktemp("venv")
    result = _run(["uv", "venv", str(venv_dir)])
    assert result.returncode == 0, f"uv venv failed:\n{result.stderr}"

    # Determine pip/python paths
    if sys.platform == "win32":
        python = str(venv_dir / "Scripts" / "python.exe")
    else:
        python = str(venv_dir / "bin" / "python")

    result = _run(["uv", "pip", "install", str(built_wheel), "--python", python])
    assert result.returncode == 0, f"pip install failed:\n{result.stderr}"
    return venv_dir


def _venv_python(venv_dir: Path) -> str:
    if sys.platform == "win32":
        return str(venv_dir / "Scripts" / "python.exe")
    return str(venv_dir / "bin" / "python")


class TestPackaging:
    """Packaging smoke tests."""

    def test_cli_version(self, installed_venv: Path) -> None:
        """agent-context-local --version exits 0."""
        python = _venv_python(installed_venv)
        result = _run([python, "-m", "scripts.cli", "version"])
        assert result.returncode == 0, f"CLI version failed:\n{result.stderr}"
        assert "agent-context-local" in result.stdout.lower() or "0.0.0" not in result.stdout

    def test_mcp_version(self, installed_venv: Path) -> None:
        """agent-context-local-mcp --version exits 0."""
        python = _venv_python(installed_venv)
        result = _run([python, "-m", "mcp_server.server", "--version"])
        assert result.returncode == 0, f"MCP --version failed:\n{result.stderr}"

    def test_version_not_dev(self, installed_venv: Path) -> None:
        """Installed package reports a real version, not 0.0.0-dev."""
        python = _venv_python(installed_venv)
        result = _run([
            python, "-c",
            "from common_utils import VERSION; print(VERSION)",
        ])
        assert result.returncode == 0, f"Import failed:\n{result.stderr}"
        version = result.stdout.strip()
        assert version != "0.0.0-dev", f"Version should not be dev: {version}"
