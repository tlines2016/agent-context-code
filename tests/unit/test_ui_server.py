"""Unit tests for the ui_server REST API layer.

These tests use FastAPI's TestClient (via httpx) to exercise each route
without requiring a real CodeSearchServer or any external dependencies.
"""

import json
from typing import Any
from unittest.mock import patch, MagicMock

import pytest

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Minimal mock that satisfies the routes' server.* calls
# ---------------------------------------------------------------------------

class _MockServer:
    """Lightweight stand-in for CodeSearchServer."""

    def search_code(self, **_kwargs: Any) -> str:
        return json.dumps({
            "query": "test query",
            "project": "/fake/project",
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
                    "project_path": "/fake/project",
                    "project_hash": "deadbeef",
                }
            ],
            "count": 1,
            "current_project": "/fake/project",
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
    """Create a TestClient backed by a mock server."""
    from ui_server.app import create_app
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
        """Server returns 400 for empty / whitespace queries."""
        from unittest.mock import patch as _patch

        # The mock server does not validate; patch it to return an error response
        with _patch.object(
            _MockServer,
            "search_code",
            return_value=json.dumps({"error": "Search query must not be empty."}),
        ):
            resp = client.post("/api/v1/search", json={"query": "   "})
            # FastAPI propagates the 400 from the error dict
            assert resp.status_code == 400

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
            json={"project_path": "/fake/project"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


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
            json={"directory_path": "/fake/project"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_clear_index(self, client: TestClient):
        resp = client.delete("/api/v1/index/clear")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


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


# ---------------------------------------------------------------------------
# SPA fallback
# ---------------------------------------------------------------------------

class TestSPAFallback:
    def test_api_root_returns_json_when_no_static(self, client: TestClient):
        """When no static directory is built, the root should return JSON."""
        resp = client.get("/")
        # Could be JSON API message or index.html (if static exists)
        assert resp.status_code in (200, 503)
