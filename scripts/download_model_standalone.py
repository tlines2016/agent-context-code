#!/usr/bin/env python3
"""Standalone model download script that bootstraps repo imports for auth helpers.

Called by the installer scripts (``install.sh`` / ``install.ps1``) after
``uv sync`` completes.  It downloads the selected embedding model via
``SentenceTransformer`` and writes the model choice to ``install_config.json``
so the runtime knows which model to load.

Exit code semantics:
- 0: model downloaded and verified successfully.
- 1: download failed (auth, network, or model error).

The installers treat exit 1 as non-fatal — they let the software install
succeed but report "not ready for indexing" in the summary.  Users can re-run
this script after fixing auth (``hf auth login``) without reinstalling.
"""

import os
import sys
import logging
from pathlib import Path

try:
    from common_utils import get_storage_dir, save_local_install_config
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from common_utils import get_storage_dir, save_local_install_config

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("sentence-transformers not installed. Install with: uv add sentence-transformers")
    sys.exit(1)

from embeddings.huggingface_auth import (
    build_huggingface_auth_error,
    configure_huggingface_auth,
)

DEFAULT_MODEL = "mixedbread-ai/mxbai-embed-xsmall-v1"


def download_model(model_name: str = DEFAULT_MODEL, storage_dir: str = None):
    """Download and verify an embedding model, then persist the choice.

    Downloads the model into ``<storage_dir>/models/`` using SentenceTransformer,
    runs a quick encode sanity check, and writes the model name into
    ``install_config.json``.  Returns ``True`` on success, ``False`` on any
    failure (with an actionable HuggingFace auth error printed to stdout).
    """
    if storage_dir is None:
        storage_path = get_storage_dir()
    else:
        storage_path = Path(storage_dir)
    models_dir = storage_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Downloading model: {model_name}")
    print(f"Storage directory: {models_dir}")
    if configure_huggingface_auth():
        print("Detected Hugging Face credentials from your environment or local token cache.")
    
    try:
        # Download and cache the model
        model = SentenceTransformer(
            model_name,
            cache_folder=str(models_dir),
            device="cpu"  # Use CPU to avoid GPU issues
        )
        
        print("Testing model...")
        test_text = "def hello_world():\n    return 'Hello, World!'"
        embedding = model.encode([test_text])
        
        print(f"Model downloaded successfully!")
        print(f"Embedding dimension: {embedding.shape[1]}")
        print(f"Model cached in: {models_dir}")
        config_path = save_local_install_config(model_name, storage_dir=storage_path)
        print(f"Local install config updated: {config_path}")
        
        return True
        
    except Exception as e:
        print(f"Error downloading model: {build_huggingface_auth_error(model_name, e)}")
        return False


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Download embedding model for testing")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Model name to download"
    )
    parser.add_argument(
        "--storage-dir",
        help="Storage directory (default: get_storage_dir())"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.basicConfig(level=logging.INFO)
    
    success = download_model(args.model, args.storage_dir)
    sys.exit(0 if success else 1)
