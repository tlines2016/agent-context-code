"""FastAPI application factory for the agent-context-local web dashboard.

Usage
-----
The app is created once by ``server.py`` at startup::

    from ui_server.app import create_app
    app = create_app(server_instance)

Architecture
------------
- All ``/api/v1/*`` routes are thin wrappers over the existing
  ``CodeSearchServer`` methods.
- The compiled React frontend is served as static files mounted at ``/``.
  The SPA fallback (serving ``index.html`` for any unknown path) lets
  React Router handle client-side navigation.
- CORS is intentionally permissive for ``localhost`` origins only, to
  support development hot-reload and the future VSCode Webview client.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ui_server import dependencies
from ui_server.routes import health, index, models, projects, search, server_control, settings

logger = logging.getLogger(__name__)

# Path to the compiled React bundle shipped alongside this package.
_STATIC_DIR = Path(__file__).parent / "static"


def create_app(server_instance) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    server_instance:
        An initialised ``CodeSearchServer`` instance.  It is registered as a
        module-level singleton so all route handlers can access it via the
        ``get_server`` dependency without needing to pass it explicitly.
    """
    dependencies.set_server(server_instance)

    app = FastAPI(
        title="Agent Context Local — Web Dashboard",
        description=(
            "REST API for the agent-context-local web dashboard. "
            "Provides semantic code search, index management, project switching, "
            "and settings management over the local code index."
        ),
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # ── CORS ──────────────────────────────────────────────────────────────
    # Allow localhost origins so the Vite dev server (port 5173) and the
    # future VSCode Webview client can reach the API without CORS errors.
    # Methods and headers are restricted to the minimum set actually used by
    # the frontend to reduce the CORS attack surface.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost",
            "http://localhost:5173",   # Vite dev server
            "http://127.0.0.1",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )

    # ── API routes ────────────────────────────────────────────────────────
    api_prefix = "/api/v1"
    app.include_router(health.router, prefix=api_prefix, tags=["health"])
    app.include_router(search.router, prefix=api_prefix, tags=["search"])
    app.include_router(projects.router, prefix=api_prefix, tags=["projects"])
    app.include_router(index.router, prefix=api_prefix, tags=["index"])
    app.include_router(settings.router, prefix=api_prefix, tags=["settings"])
    app.include_router(models.router, prefix=api_prefix, tags=["models"])
    app.include_router(server_control.router, prefix=api_prefix, tags=["server"])

    # ── Static files (compiled React bundle) ─────────────────────────────
    # Only mount static files when the build output directory exists.
    # During development without a built frontend the API still works,
    # and the /api/docs OpenAPI UI is available for testing.
    if _STATIC_DIR.exists() and any(_STATIC_DIR.iterdir()):
        # Mount assets/ subdirectory first so Vite's hashed assets are served
        # directly without hitting the SPA fallback handler.
        assets_dir = _STATIC_DIR / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str, request: Request) -> Response:
            """Serve index.html for all non-API paths (SPA client-side routing)."""
            # Let the API prefix fall through to its own 404 handler.
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            index_html = _STATIC_DIR / "index.html"
            if index_html.exists():
                return FileResponse(str(index_html))
            return JSONResponse(
                {"detail": "Frontend not built. Run 'npm run build' inside ui/."},
                status_code=503,
            )
    else:
        @app.get("/", include_in_schema=False)
        async def root() -> JSONResponse:
            return JSONResponse({
                "message": "Agent Context Local API is running.",
                "docs": "/api/docs",
                "note": "Frontend not built. Run 'npm run build' inside ui/ to enable the web dashboard.",
            })

    return app
