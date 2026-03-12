"""Code embedding wrapper with install-time model selection."""

import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, fields, replace
import os
import numpy as np

from chunking.code_chunk import CodeChunk
from embeddings.embedding_models_register import AVAILABLE_MODELS
from embeddings.model_catalog import DEFAULT_EMBEDDING_MODEL, GPU_DEFAULT_EMBEDDING_MODEL, EmbeddingModelConfig, get_model_config
from embeddings.sentence_transformer import SentenceTransformerModel
from common_utils import get_storage_dir, load_local_install_config, detect_gpu, has_explicit_model_choice

# Chunk types that represent members of a parent type (class, impl block,
# interface, …).  Embedding content for these includes a parent-context
# prefix so queries like "Calculator.add" can find the method even though
# the method body does not mention the parent class name.
_MEMBER_CHUNK_TYPES: frozenset[str] = frozenset({
    'method',
    'constructor',
    'property',
    'init',
    'destructor',
    'event',
})


@dataclass
class EmbeddingResult:
    """Result of embedding generation."""
    embedding: np.ndarray
    chunk_id: str
    metadata: Dict[str, Any]


def _resolve_model_config(model_name: Optional[str]) -> EmbeddingModelConfig:
    """Resolve the selected embedding model from args, env, or local install config."""
    if model_name:
        return get_model_config(model_name)

    env_model_name = os.getenv("CODE_SEARCH_MODEL")
    if env_model_name:
        return get_model_config(env_model_name)

    install_config = load_local_install_config()
    configured_model = install_config.get("embedding_model")

    if isinstance(configured_model, str):
        return get_model_config(configured_model)

    if isinstance(configured_model, dict):
        selected_model_name = configured_model.get("model_name", DEFAULT_EMBEDDING_MODEL)
        config = get_model_config(selected_model_name)
        overrides = {
            field.name: configured_model[field.name]
            for field in fields(EmbeddingModelConfig)
            if field.name != "model_name" and field.name in configured_model
            and (
                configured_model[field.name] is None
                or isinstance(configured_model[field.name], str)
            )
        }
        return replace(config, **overrides)

    return _maybe_gpu_upgrade_model(get_model_config(DEFAULT_EMBEDDING_MODEL))


def _maybe_gpu_upgrade_model(default_config: EmbeddingModelConfig) -> EmbeddingModelConfig:
    """Auto-upgrade to the GPU-optimised model when a GPU is available.

    Only upgrades when:
    1. The resolved model is still the CPU default (no explicit user choice).
    2. A GPU (CUDA or MPS) is detected at runtime.
    3. The user has not set an explicit model in install_config.json.

    This ensures GPU users get better defaults transparently while
    respecting any explicit user configuration.
    """
    if default_config.model_name != DEFAULT_EMBEDDING_MODEL:
        return default_config

    if has_explicit_model_choice():
        return default_config

    device = detect_gpu()
    if device in ("cuda", "mps"):
        _logger = logging.getLogger(__name__)
        _logger.info(
            "GPU detected (%s). Auto-upgrading embedding model from %s to %s",
            device,
            DEFAULT_EMBEDDING_MODEL,
            GPU_DEFAULT_EMBEDDING_MODEL,
        )
        return get_model_config(GPU_DEFAULT_EMBEDDING_MODEL)

    return default_config


class CodeEmbedder:
    """Wrapper for embedding code chunks using the configured local embedding model."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        cache_dir: Optional[str] = None,
        device: str = "auto"
    ):
        """Initialize code embedder.

        Args:
            model_name: Name of the embedding model to use
            cache_dir: Directory to cache the model
            device: Device to load model on
        """
        self.model_config = _resolve_model_config(model_name)
        model_name = self.model_config.model_name
        if not cache_dir: # if not provided, use default
            cache_dir = str(get_storage_dir() / "models")
        self.device = device

        # Get model class from available models
        model_class = AVAILABLE_MODELS.get(model_name)
        if model_class:
            self._model = model_class(cache_dir=cache_dir, device=device)
        elif model_name and model_name.strip():
            self._model = SentenceTransformerModel(
                model_name=model_name,
                cache_dir=cache_dir,
                device=device
            )
        else:
            raise ValueError("Embedding model name must not be empty.")

        self._logger = logging.getLogger(__name__)
        logging.basicConfig(level=logging.INFO)
        self._logger.info(f"Using embedding model: {model_name}")

    @property
    def model(self):
        """Get the underlying embedding model."""
        return self._model.model

    def create_embedding_content(self, chunk: CodeChunk, max_chars: int = 6000) -> str:
        """Create clean content for embedding generation.

        Args:
            chunk: Code chunk to create content for
            max_chars: Maximum characters to include

        Returns:
            Content string for embedding
        """
        content_parts = []

        # For methods and constructors, prepend parent context so queries
        # like "Calculator.add" or "methods in Calculator" can find them
        # even though the method body doesn't contain the class name.
        if chunk.parent_name and chunk.chunk_type in _MEMBER_CHUNK_TYPES:
            content_parts.append(f"# In {chunk.parent_name}:")

        # Add docstring if available
        docstring_budget = 300
        if chunk.docstring:
            docstring = chunk.docstring[:docstring_budget] + "..." if len(chunk.docstring) > docstring_budget else chunk.docstring
            content_parts.append(f'"""{docstring}"""')

        # Calculate remaining budget for code content
        docstring_len = len(content_parts[0]) if content_parts else 0
        remaining_budget = max_chars - docstring_len - 10

        # Add code content with smart truncation
        if len(chunk.content) <= remaining_budget:
            content_parts.append(chunk.content)
        else:
            lines = chunk.content.split('\n')
            if len(lines) > 3:
                head_lines = []
                tail_lines = []
                current_length = docstring_len

                # Add head lines
                for line in lines[:min(len(lines)//2, 20)]:
                    if current_length + len(line) + 1 > remaining_budget * 0.7:
                        break
                    head_lines.append(line)
                    current_length += len(line) + 1

                # Add tail lines
                remaining_space = remaining_budget - current_length - 20
                for line in reversed(lines[-min(len(lines)//3, 10):]):
                    if len('\n'.join(tail_lines)) + len(line) + 1 > remaining_space:
                        break
                    tail_lines.insert(0, line)

                if tail_lines:
                    truncated_content = '\n'.join(head_lines) + '\n    # ... (truncated) ...\n' + '\n'.join(tail_lines)
                else:
                    truncated_content = '\n'.join(head_lines) + '\n    # ... (truncated) ...'
                content_parts.append(truncated_content)
            else:
                content_parts.append(chunk.content[:remaining_budget] + "..." if len(chunk.content) > remaining_budget else chunk.content)

        return '\n'.join(content_parts)

    @staticmethod
    def _make_chunk_id(chunk: CodeChunk) -> str:
        """Build a stable, unique identifier for a code chunk."""
        chunk_id = f"{chunk.relative_path}:{chunk.start_line}-{chunk.end_line}:{chunk.chunk_type}"
        if chunk.name:
            chunk_id += f":{chunk.name}"
        return chunk_id

    @staticmethod
    def _make_chunk_metadata(chunk: CodeChunk) -> Dict[str, Any]:
        """Build the metadata dict stored alongside a chunk's FAISS vector."""
        return {
            'file_path': chunk.file_path,
            'relative_path': chunk.relative_path,
            'folder_structure': chunk.folder_structure,
            'chunk_type': chunk.chunk_type,
            'start_line': chunk.start_line,
            'end_line': chunk.end_line,
            'name': chunk.name,
            'parent_name': chunk.parent_name,
            'docstring': chunk.docstring,
            'decorators': chunk.decorators,
            'imports': chunk.imports,
            'complexity_score': chunk.complexity_score,
            'tags': chunk.tags,
            'content_preview': (
                chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content
            ),
        }

    def embed_chunk(self, chunk: CodeChunk) -> EmbeddingResult:
        """Generate embedding for a single code chunk.

        Args:
            chunk: Code chunk to embed

        Returns:
            EmbeddingResult with embedding and metadata
        """
        content = self.create_embedding_content(chunk)

        # Encode using model with proper prompt
        embedding = self._encode_texts(
            [content],
            prompt_name=self.model_config.document_prompt_name,
            prefix=self.model_config.document_prefix,
            show_progress_bar=False,
        )[0]

        return EmbeddingResult(
            embedding=embedding,
            chunk_id=self._make_chunk_id(chunk),
            metadata=self._make_chunk_metadata(chunk),
        )

    def embed_chunks(self, chunks: List[CodeChunk], batch_size: int = 32) -> List[EmbeddingResult]:
        """Generate embeddings for multiple chunks with batching.

        Args:
            chunks: List of code chunks to embed
            batch_size: Batch size for processing

        Returns:
            List of EmbeddingResults
        """
        results = []

        self._logger.info(f"Generating embeddings for {len(chunks)} chunks")

        # Process in batches
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            batch_contents = [self.create_embedding_content(chunk) for chunk in batch]

            # Generate embeddings for batch
            batch_embeddings = self._encode_texts(
                batch_contents,
                prompt_name=self.model_config.document_prompt_name,
                prefix=self.model_config.document_prefix,
                show_progress_bar=False
            )

            # Create results
            for chunk, embedding in zip(batch, batch_embeddings):
                results.append(EmbeddingResult(
                    embedding=embedding,
                    chunk_id=self._make_chunk_id(chunk),
                    metadata=self._make_chunk_metadata(chunk),
                ))

            if i + batch_size < len(chunks):
                self._logger.info(f"Processed {i + batch_size}/{len(chunks)} chunks")

        self._logger.info("Embedding generation completed")
        return results

    def embed_query(self, query: str) -> np.ndarray:
        """Generate embedding for a search query.

        Args:
            query: Search query text

        Returns:
            Embedding vector
        """
        embedding = self._encode_texts(
            [query],
            prompt_name=self.model_config.query_prompt_name,
            prefix=self.model_config.query_prefix,
            show_progress_bar=False,
        )[0]
        return embedding

    def _encode_texts(
        self,
        texts: List[str],
        *,
        prompt_name: Optional[str] = None,
        prefix: str = "",
        **kwargs,
    ) -> np.ndarray:
        """Encode texts with optional prompt names or prefixes."""
        prepared_texts = [f"{prefix}{text}" if prefix else text for text in texts]
        encode_kwargs = dict(kwargs)
        if prompt_name:
            encode_kwargs["prompt_name"] = prompt_name
        return self._model.encode(prepared_texts, **encode_kwargs)

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the embedding model.

        Returns:
            Dictionary with model information
        """
        return self._model.get_model_info()

    def cleanup(self):
        """Clean up model resources."""
        self._model.cleanup()

    def __del__(self):
        """Ensure cleanup on object destruction."""
        try:
            self.cleanup()
        except Exception:
            pass
