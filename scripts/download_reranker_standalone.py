#!/usr/bin/env python3
"""Standalone reranker model download script.

Parallels ``download_model_standalone.py`` but downloads a causal LM
reranker via ``AutoModelForCausalLM`` + ``AutoTokenizer`` instead of
SentenceTransformer.

Called by the installer scripts when ``CODE_SEARCH_PROFILE`` is set to
``reranker`` or ``full``, or manually via:

    uv run scripts/download_reranker_standalone.py \
        --storage-dir ~/.agent_code_search \
        --model Qwen/Qwen3-Reranker-4B -v

Exit code semantics (same as download_model_standalone.py):
- 0: model downloaded and verified successfully.
- 1: download failed (auth, network, or model error).
"""

import os
import sys
import logging
from pathlib import Path

try:
    from common_utils import save_reranker_config
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from common_utils import save_reranker_config

try:
    from transformers import AutoModelForCausalLM, AutoTokenizer
except ImportError:
    print("transformers not installed. Install with: uv sync")
    sys.exit(1)

from embeddings.huggingface_auth import (
    build_huggingface_auth_error,
    configure_huggingface_auth,
)


def download_reranker(
    model_name: str = "Qwen/Qwen3-Reranker-4B",
    storage_dir: str = None,
):
    """Download and verify a reranker model, then persist the config.

    Downloads the tokenizer and model weights into ``<storage_dir>/models/``
    using ``AutoModelForCausalLM`` / ``AutoTokenizer``.  Runs a quick
    forward-pass sanity check and writes the reranker config into
    ``install_config.json``.

    Returns ``True`` on success, ``False`` on failure.
    """
    if storage_dir is None:
        storage_dir = os.path.expanduser("~/.agent_code_search")

    storage_path = Path(storage_dir)
    models_dir = storage_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading reranker model: {model_name}")
    print(f"Storage directory: {models_dir}")
    if configure_huggingface_auth():
        print("Detected Hugging Face credentials from your environment or local token cache.")

    try:
        print("Downloading tokenizer...")
        tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            cache_dir=str(models_dir),
        )

        print("Downloading model weights (this may take a while)...")
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            cache_dir=str(models_dir),
        )

        # Quick sanity check — tokenize a short prompt
        print("Testing model...")
        test_input = tokenizer("test", return_tensors="pt")
        output = model(**test_input)
        vocab_size = output.logits.shape[-1]

        print(f"Reranker downloaded successfully!")
        print(f"Vocab size: {vocab_size}")
        print(f"Model cached in: {models_dir}")

        config_path = save_reranker_config(
            model_name,
            enabled=False,  # Opt-in: user must enable via CLI
            storage_dir=storage_path,
        )
        print(f"Reranker config written: {config_path}")
        print("Run 'python scripts/cli.py config reranker on' to enable reranking.")

        # Release memory
        del model
        del tokenizer

        return True

    except Exception as e:
        print(f"Error downloading reranker: {build_huggingface_auth_error(model_name, e)}")
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download reranker model")
    parser.add_argument(
        "--model",
        default="Qwen/Qwen3-Reranker-4B",
        help="Reranker model name to download",
    )
    parser.add_argument(
        "--storage-dir",
        help="Storage directory (default: ~/.agent_code_search)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO)

    success = download_reranker(args.model, args.storage_dir)
    sys.exit(0 if success else 1)
