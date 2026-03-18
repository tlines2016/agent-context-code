"""Unit tests for the ui_server REST API layer.

These tests use FastAPI's TestClient (via httpx) to exercise each route
without requiring a real CodeSearchServer or any external dependencies.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from fastapi.testclient import TestClient

# Use a platform-appropriate absolute path for test fixtures.
# On Windows, "/fake/project" is not considered absolute by pathlib.
_FAKE_PROJECT = "C:\\fake\\project" if os.name == "nt" else "/fake/project"

# ---------------------------------------------------------------------------
# Minimal mock that satisfies the routes' server.* calls
# ---------------------------------------------------------------------------

class _MockServer:
    """Lightweight stand-in for CodeSearchServer."""

    def search_code(self, **kwargs: Any) -> str:
        # Echo the query back so whitespace-stripping tests can verify it.
        query = kwargs.get("query", "test query")
        return json.dumps({
            "query": query,
            "project": _FAKE_PROJECT,
            "results": [
                {
                    "file": "src/auth.py",
                    "lines": "10-25",
                    "kind": "function",
                    "score": 0.92,
                    "chunk_id": "abc123",
                    "name": "authenticate",
                    "snippet": "def authenticate(user, password):",
                }
            ],
            "graph_enriched": False,
        })

    def list_projects(self) -> str:
        return json.dumps({
            "projects": [
                {
                    "project_name": "my_project",
                    "project_path": _FAKE_PROJECT,
                    "project_hash": "deadbeef",
                }
            ],
            "count": 1,
            "current_project": _FAKE_PROJECT,
        })

    def switch_project(self, project_path: str) -> str:
        return json.dumps({"success": True, "message": f"Switched to {project_path}"})

    def get_index_status(self) -> str:
        return json.dumps({
            "index_statistics": {"total_chunks": 100},
            "model_information": {"model_name": "test-model"},
            "storage_directory": "/tmp/.agent_code_search",
            "sync_status": "synced",
            "vector_indexed": True,
            "graph_indexed": True,
            "snapshot_exists": True,
        })

    def index_directory(self, **_kwargs: Any) -> str:
        return json.dumps({"success": True, "chunks_indexed": 42})

    def clear_index(self) -> str:
        return json.dumps({"success": True, "message": "Index cleared"})


@pytest.fixture(scope="module")
def client():
    """Create a TestClient backed by a mock server with isolated storage."""
    from ui_server.app import create_app

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Write a minimal install_config.json so settings routes don't error.
        (tmp_path / "install_config.json").write_text("{}", encoding="utf-8")

        with (
            patch("ui_server.routes.settings.get_storage_dir", return_value=tmp_path),
            patch("ui_server.routes.settings.load_local_install_config", return_value={}),
            patch("ui_server.routes.settings.save_local_install_config"),
            patch("ui_server.routes.settings.save_reranker_config"),
            patch("ui_server.routes.settings.save_idle_config"),
        ):
            app = create_app(_MockServer())
            with TestClient(app) as c:
                yield c


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_ok(self, client: TestClient):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body

    def test_health_schema(self, client: TestClient):
        body = client.get("/api/v1/health").json()
        assert set(body.keys()) >= {"status", "version"}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search_returns_results(self, client: TestClient):
        resp = client.post("/api/v1/search", json={"query": "test query"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "test query"
        assert body["result_count"] == 1
        assert body["results"][0]["file"] == "src/auth.py"

    def test_search_validates_empty_query(self, client: TestClient):
        """Pydantic rejects whitespace-only queries with 422."""
        resp = client.post("/api/v1/search", json={"query": "   "})
        assert resp.status_code == 422

    def test_search_rejects_empty_string_query(self, client: TestClient):
        """Pydantic rejects zero-length queries with 422."""
        resp = client.post("/api/v1/search", json={"query": ""})
        assert resp.status_code == 422

    def test_search_rejects_oversized_query(self, client: TestClient):
        """Query longer than 1000 chars is rejected with 422."""
        resp = client.post("/api/v1/search", json={"query": "a" * 1001})
        assert resp.status_code == 422

    def test_search_accepts_max_length_query(self, client: TestClient):
        """Query of exactly 1000 chars is accepted."""
        resp = client.post("/api/v1/search", json={"query": "a" * 1000})
        assert resp.status_code == 200

    def test_search_strips_whitespace_from_query(self, client: TestClient):
        """Leading/trailing whitespace is stripped before forwarding."""
        resp = client.post("/api/v1/search", json={"query": "  auth  "})
        assert resp.status_code == 200
        # Returned query should be stripped
        assert resp.json()["query"] == "auth"

    def test_search_accepts_optional_fields(self, client: TestClient):
        resp = client.post(
            "/api/v1/search",
            json={
                "query": "auth",
                "k": 3,
                "file_pattern": "**/*.py",
                "chunk_type": "function",
                "include_context": False,
            },
        )
        assert resp.status_code == 200

    def test_search_rejects_k_out_of_range(self, client: TestClient):
        """k must be 1–50 (enforced by pydantic)."""
        resp = client.post("/api/v1/search", json={"query": "q", "k": 0})
        assert resp.status_code == 422
        resp = client.post("/api/v1/search", json={"query": "q", "k": 999})
        assert resp.status_code == 422

    def test_search_rejects_invalid_chunk_type_chars(self, client: TestClient):
        """chunk_type values with special chars (e.g. path traversal) are rejected."""
        for bad in ["../../etc", "func;drop", "class name", "", " "]:
            resp = client.post("/api/v1/search", json={"query": "q", "chunk_type": bad})
            assert resp.status_code == 422, f"Expected 422 for chunk_type={bad!r}"

    def test_search_accepts_valid_chunk_types(self, client: TestClient):
        """Standard chunk type names are accepted."""
        for good in ["function", "class", "method", "module", "chunk_type_2"]:
            resp = client.post("/api/v1/search", json={"query": "q", "chunk_type": good})
            assert resp.status_code == 200, f"Expected 200 for chunk_type={good!r}"

    def test_search_rejects_max_results_per_file_too_large(self, client: TestClient):
        """max_results_per_file must be ≤ 50."""
        resp = client.post("/api/v1/search", json={"query": "q", "max_results_per_file": 51})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class TestProjects:
    def test_list_projects(self, client: TestClient):
        resp = client.get("/api/v1/projects")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["projects"][0]["project_name"] == "my_project"

    def test_switch_project(self, client: TestClient):
        resp = client.post(
            "/api/v1/projects/switch",
            json={"project_path": _FAKE_PROJECT},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_switch_project_rejects_relative_path(self, client: TestClient):
        """A relative project_path must be rejected with 422."""
        resp = client.post(
            "/api/v1/projects/switch",
            json={"project_path": "relative/path"},
        )
        assert resp.status_code == 422

    def test_switch_project_rejects_empty_path(self, client: TestClient):
        resp = client.post(
            "/api/v1/projects/switch",
            json={"project_path": ""},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

class TestIndex:
    def test_index_status(self, client: TestClient):
        resp = client.get("/api/v1/index/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["sync_status"] == "synced"

    def test_run_index(self, client: TestClient):
        resp = client.post(
            "/api/v1/index/run",
            json={"directory_path": _FAKE_PROJECT},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_clear_index(self, client: TestClient):
        resp = client.delete("/api/v1/index/clear")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_run_index_rejects_relative_path(self, client: TestClient):
        """Relative directory_path is rejected with 422."""
        resp = client.post(
            "/api/v1/index/run",
            json={"directory_path": "relative/path"},
        )
        assert resp.status_code == 422

    def test_run_index_rejects_empty_path(self, client: TestClient):
        resp = client.post(
            "/api/v1/index/run",
            json={"directory_path": ""},
        )
        assert resp.status_code == 422

    def test_run_index_rejects_too_many_file_patterns(self, client: TestClient):
        """More than 50 file patterns are rejected with 422."""
        patterns = [f"**/*.ext{i}" for i in range(51)]
        resp = client.post(
            "/api/v1/index/run",
            json={"directory_path": _FAKE_PROJECT, "file_patterns": patterns},
        )
        assert resp.status_code == 422

    def test_run_index_accepts_valid_file_patterns(self, client: TestClient):
        resp = client.post(
            "/api/v1/index/run",
            json={"directory_path": _FAKE_PROJECT, "file_patterns": ["**/*.py", "**/*.ts"]},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class TestSettings:
    def test_get_settings(self, client: TestClient):
        resp = client.get("/api/v1/settings")
        assert resp.status_code == 200

    def test_update_settings_idle(self, client: TestClient):
        """PUT with idle settings should return updated config."""
        resp = client.put(
            "/api/v1/settings",
            json={"idle": {"idle_offload_minutes": 10, "idle_unload_minutes": 20}},
        )
        assert resp.status_code == 200

    def test_update_settings_reranker(self, client: TestClient):
        resp = client.put(
            "/api/v1/settings",
            json={"reranker": {"enabled": False, "recall_k": 30}},
        )
        assert resp.status_code == 200

    def test_settings_rejects_recall_k_zero(self, client: TestClient):
        """recall_k must be ≥ 1."""
        resp = client.put(
            "/api/v1/settings",
            json={"reranker": {"recall_k": 0}},
        )
        assert resp.status_code == 422

    def test_settings_rejects_recall_k_too_large(self, client: TestClient):
        """recall_k must be ≤ 1000."""
        resp = client.put(
            "/api/v1/settings",
            json={"reranker": {"recall_k": 1001}},
        )
        assert resp.status_code == 422

    def test_settings_rejects_min_score_out_of_range(self, client: TestClient):
        """min_reranker_score must be in [0.0, 1.0]."""
        resp = client.put(
            "/api/v1/settings",
            json={"reranker": {"min_reranker_score": 1.5}},
        )
        assert resp.status_code == 422
        resp = client.put(
            "/api/v1/settings",
            json={"reranker": {"min_reranker_score": -0.1}},
        )
        assert resp.status_code == 422

    def test_settings_accepts_valid_score_range(self, client: TestClient):
        """Boundary values 0.0 and 1.0 are accepted."""
        for score in (0.0, 0.5, 1.0):
            resp = client.put(
                "/api/v1/settings",
                json={"reranker": {"min_reranker_score": score}},
            )
            assert resp.status_code == 200, f"Expected 200 for score={score}"

    def test_settings_rejects_negative_idle_minutes(self, client: TestClient):
        """Negative idle minutes are rejected."""
        resp = client.put(
            "/api/v1/settings",
            json={"idle": {"idle_offload_minutes": -1}},
        )
        assert resp.status_code == 422

    def test_settings_rejects_idle_minutes_exceeding_max(self, client: TestClient):
        """Idle minutes > 10080 (one week) are rejected."""
        resp = client.put(
            "/api/v1/settings",
            json={"idle": {"idle_offload_minutes": 10081}},
        )
        assert resp.status_code == 422

    def test_settings_rejects_oversized_model_name(self, client: TestClient):
        """Model names longer than 200 chars are rejected."""
        resp = client.put(
            "/api/v1/settings",
            json={"embedding_model": {"model_name": "x" * 201}},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TestModels:
    def test_list_models(self, client: TestClient):
        resp = client.get("/api/v1/models")
        assert resp.status_code == 200
        body = resp.json()
        assert "models" in body
        assert "count" in body
        # The catalog has at least one model
        assert body["count"] > 0
        model = body["models"][0]
        assert "model_name" in model
        assert "description" in model

    def test_list_models_includes_gpu_available(self, client: TestClient):
        """Response must include a boolean gpu_available field."""
        resp = client.get("/api/v1/models")
        assert resp.status_code == 200
        body = resp.json()
        assert "gpu_available" in body
        assert isinstance(body["gpu_available"], bool)


# ---------------------------------------------------------------------------
# Rerankers
# ---------------------------------------------------------------------------

class TestRerankers:
    def test_list_rerankers_returns_catalog(self, client: TestClient):
        """GET /api/v1/rerankers should return the reranker catalog."""
        resp = client.get("/api/v1/rerankers")
        assert resp.status_code == 200
        body = resp.json()
        assert "rerankers" in body
        assert "count" in body
        assert body["count"] >= 1
        assert isinstance(body["rerankers"], list)
        # Each item should have the expected fields
        for item in body["rerankers"]:
            assert "model_name" in item
            assert "short_name" in item
            assert "gpu_default" in item
        # Verify well-known models are present
        model_names = [r["model_name"] for r in body["rerankers"]]
        assert "cross-encoder/ms-marco-MiniLM-L-6-v2" in model_names
        assert "Qwen/Qwen3-Reranker-0.6B" in model_names


# ---------------------------------------------------------------------------
# SPA fallback
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Server Control
# ---------------------------------------------------------------------------

class TestServerControl:
    def test_restart_returns_message(self, client: TestClient):
        """POST /api/v1/server/restart should return a restart message."""
        # We need to mock the signal to prevent the test process from actually shutting down.
        with patch("ui_server.routes.server_control._signal_shutdown"):
            resp = client.post("/api/v1/server/restart")
        assert resp.status_code == 200
        body = resp.json()
        assert "message" in body
        assert "restart" in body["message"].lower() or "restarting" in body["message"].lower()

    def test_restart_sets_flag(self, client: TestClient):
        """Restart endpoint should set the restart-requested flag."""
        from ui_server.routes.server_control import is_restart_requested, clear_restart_flag
        clear_restart_flag()
        with patch("ui_server.routes.server_control._signal_shutdown"):
            client.post("/api/v1/server/restart")
        assert is_restart_requested() is True
        clear_restart_flag()


# ---------------------------------------------------------------------------
# SPA fallback
# ---------------------------------------------------------------------------

class TestSPAFallback:
    def test_api_root_returns_json_when_no_static(self, client: TestClient):
        """When no static directory is built, the root should return JSON."""
        resp = client.get("/")
        # Could be JSON API message or index.html (if static exists)
        assert resp.status_code in (200, 503)
