"""Settings endpoints — GET/PUT /api/v1/settings.

Reads and writes install_config.json through the common_utils helpers so the
UI never touches the file directly, keeping all config I/O in one place.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

try:
    from common_utils import (
        load_local_install_config,
        save_local_install_config,
        save_reranker_config,
        save_idle_config,
        get_storage_dir,
    )
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from common_utils import (
        load_local_install_config,
        save_local_install_config,
        save_reranker_config,
        save_idle_config,
        get_storage_dir,
    )

logger = logging.getLogger(__name__)

router = APIRouter()


class EmbeddingModelSettings(BaseModel):
    model_name: Optional[str] = None


class RerankerSettings(BaseModel):
    enabled: Optional[bool] = None
    model_name: Optional[str] = None
    recall_k: Optional[int] = None
    min_reranker_score: Optional[float] = None


class IdleSettings(BaseModel):
    idle_offload_minutes: Optional[int] = None
    idle_unload_minutes: Optional[int] = None


class SettingsUpdate(BaseModel):
    embedding_model: Optional[EmbeddingModelSettings] = None
    reranker: Optional[RerankerSettings] = None
    idle: Optional[IdleSettings] = None


@router.get("/settings")
async def get_settings() -> Dict[str, Any]:
    """Return the full install_config.json contents plus the storage path."""
    config = load_local_install_config()
    config["_storage_dir"] = str(get_storage_dir())
    return config


@router.put("/settings")
async def update_settings(update: SettingsUpdate) -> Dict[str, Any]:
    """Apply partial settings updates and return the resulting config."""
    try:
        if update.embedding_model and update.embedding_model.model_name:
            save_local_install_config(model_name=update.embedding_model.model_name)

        if update.reranker:
            current = load_local_install_config().get("reranker", {})

            def _coalesce(new_val, current_key: str, default):
                """Return new_val when provided, else fall back to existing config or default."""
                return new_val if new_val is not None else current.get(current_key, default)

            save_reranker_config(
                model_name=_coalesce(update.reranker.model_name, "model_name", ""),
                enabled=_coalesce(update.reranker.enabled, "enabled", False),
                recall_k=_coalesce(update.reranker.recall_k, "recall_k", 50),
                min_reranker_score=_coalesce(update.reranker.min_reranker_score, "min_reranker_score", 0.0),
            )

        if update.idle:
            save_idle_config(
                idle_offload_minutes=update.idle.idle_offload_minutes,
                idle_unload_minutes=update.idle.idle_unload_minutes,
            )

        config = load_local_install_config()
        config["_storage_dir"] = str(get_storage_dir())
        return config
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Settings update failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
