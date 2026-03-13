"""Embedding model presets and prompt configuration."""

from dataclasses import dataclass
from typing import Optional


DEFAULT_EMBEDDING_MODEL = "mixedbread-ai/mxbai-embed-xsmall-v1"
GPU_DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"

# ── Qwen3-Embedding constants ────────────────────────────────────────────────
# The Qwen3-Embedding family requires an instruction prefix on *queries* to
# steer the model toward the retrieval task, but documents/passages must be
# embedded WITHOUT any prefix.  The dimension is determined by the model's
# hidden_size (2560 for the 4B variant).
QWEN3_4B_EMBEDDING_DIM = 2560
QWEN3_QUERY_INSTRUCTION = (
    "Instruct: Given a code search query, retrieve the most relevant code chunks "
    "from a software codebase\nQuery:"
    # Format follows the Qwen3-Embedding reference implementation exactly:
    #   def get_detailed_instruct(task_description, query):
    #       return f'Instruct: {task_description}\nQuery:{query}'
    # No trailing space — the query text is appended directly after "Query:".
    #
    # "software codebase" is intentionally language-agnostic: this system
    # indexes Python, JavaScript, TypeScript, Go, Java, Rust, Svelte, and more.
    # Using a language-specific phrase like "Python codebase" would steer the
    # model toward Python-only retrieval and degrade quality for other languages.
    # Per the model card: "developers customize the instruct according to their
    # specific scenarios, tasks, and languages."
)


@dataclass(frozen=True)
class EmbeddingModelConfig:
    """Embedding model configuration used by the local installer/runtime."""

    model_name: str
    short_name: str = ""
    document_prompt_name: Optional[str] = None
    query_prompt_name: Optional[str] = None
    document_prefix: str = ""
    query_prefix: str = ""
    # embedding_dimension is informational; the real value is read from the
    # loaded model at runtime, but tests and schema definitions rely on this
    # constant to size vector columns correctly.
    embedding_dimension: Optional[int] = None
    description: str = ""
    recommended_for: str = ""
    gpu_default: bool = False
    trust_remote_code: bool = False


MODEL_CATALOG = {
    # ── Mixedbread mxbai-embed-xsmall-v1 ─────────────────────────────────
    # 22.7M parameters, 384-dim, 4K token context.  Fastest CPU option —
    # roughly 5–14k sentences/sec on a modern CPU.  Outperforms MiniLM on
    # long-document retrieval (LoCo: 76.34 vs 67.34) due to 4K context window.
    # Uses asymmetric retrieval: queries get the "Represent this sentence…"
    # prefix; documents are embedded without any prefix.
    # Apache 2.0 license; NOT gated.
    "mixedbread-ai/mxbai-embed-xsmall-v1": EmbeddingModelConfig(
        model_name="mixedbread-ai/mxbai-embed-xsmall-v1",
        short_name="mxbai-xsmall",
        query_prefix="Represent this sentence for searching relevant passages: ",
        document_prefix="",
        embedding_dimension=384,
        description="Default model — 22.7M params, CPU-optimised, 4K context. Fast indexing on any machine.",
        recommended_for="New installs. Best CPU speed/quality balance. No GPU or HuggingFace auth required.",
    ),
    "google/embeddinggemma-300m": EmbeddingModelConfig(
        model_name="google/embeddinggemma-300m",
        short_name="gemma-300m",
        document_prompt_name="Retrieval-document",
        query_prompt_name="InstructionRetrieval",
        embedding_dimension=768,
        description="Legacy default — gated on HuggingFace (requires account + license + token).",
        recommended_for="Existing installs that already have HF auth configured.",
    ),
    # ── Qwen3-Embedding-0.6B ─────────────────────────────────────────────
    # Uses the same asymmetric instruction prefix format as the 4B variant.
    # Without query_prefix, retrieval quality degrades 1-5% per official docs.
    "Qwen/Qwen3-Embedding-0.6B": EmbeddingModelConfig(
        model_name="Qwen/Qwen3-Embedding-0.6B",
        short_name="qwen-embed-0.6b",
        query_prefix=QWEN3_QUERY_INSTRUCTION,
        document_prefix="",  # Documents must NOT be prefixed
        embedding_dimension=1024,
        description="CPU-friendly, non-gated, 1024-dim. Better quality than mxbai-xsmall at the cost of speed.",
        recommended_for="Users who want higher embedding quality on CPU and can tolerate slower indexing.",
        gpu_default=True,
    ),
    # ── Unsloth-optimised Qwen3-Embedding-4B ─────────────────────────────
    # This is the primary target model for GPU-accelerated local search.
    # Loaded in float16 on CUDA (~8 GB VRAM), flash_attn optional.
    #
    # IMPORTANT: query_prefix is set so search queries are prefixed with the
    # retrieval instruction, but document_prefix is deliberately empty — the
    # Qwen3-Embedding architecture expects raw text for passages.
    "unsloth/Qwen3-Embedding-4B": EmbeddingModelConfig(
        model_name="unsloth/Qwen3-Embedding-4B",
        short_name="qwen-embed-4b",
        query_prefix=QWEN3_QUERY_INSTRUCTION,
        document_prefix="",  # Documents must NOT be prefixed
        embedding_dimension=QWEN3_4B_EMBEDDING_DIM,
        description="Unsloth-optimised Qwen3-Embedding-4B for RTX 5080 (16 GB VRAM).",
        recommended_for="Primary GPU-accelerated model for high-quality local code search.",
    ),
    # ── Unsloth-optimised Qwen3-Embedding-8B ─────────────────────────
    # Ranks #1 on MTEB multilingual.  Requires 24 GB+ VRAM recommended
    # (16 GB weights in float16, plus activation memory during encoding).
    # Suitable for users with high-end GPUs who want the best embedding
    # quality available locally.
    "unsloth/Qwen3-Embedding-8B": EmbeddingModelConfig(
        model_name="unsloth/Qwen3-Embedding-8B",
        short_name="qwen-embed-8b",
        query_prefix=QWEN3_QUERY_INSTRUCTION,
        document_prefix="",  # Documents must NOT be prefixed
        embedding_dimension=4096,
        description="Unsloth-optimised Qwen3-Embedding-8B — top MTEB multilingual quality, 24 GB+ VRAM recommended.",
        recommended_for="Users with high-end GPUs (RTX 4090/5090, A100) who want maximum embedding quality.",
    ),
    "Salesforce/SFR-Embedding-Code-400M_R": EmbeddingModelConfig(
        model_name="Salesforce/SFR-Embedding-Code-400M_R",
        short_name="sfr-code-400m",
        embedding_dimension=1024,
        description="Code-focused embedding model for repositories where symbol and implementation search matters most.",
        recommended_for="Good code-search-specific candidate when source retrieval quality matters more than raw speed.",
        trust_remote_code=True,
    ),
}

# Short-name reverse lookup: maps e.g. "gemma-300m" → "google/embeddinggemma-300m"
EMBEDDING_SHORT_NAMES = {
    config.short_name: name
    for name, config in MODEL_CATALOG.items()
    if config.short_name
}


def get_model_config(model_name: Optional[str]) -> EmbeddingModelConfig:
    """Return a preset config when known, otherwise a generic SentenceTransformer config."""
    if not model_name:
        model_name = DEFAULT_EMBEDDING_MODEL
    return MODEL_CATALOG.get(model_name, EmbeddingModelConfig(model_name=model_name))
