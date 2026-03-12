"""Reranker model presets and configuration."""

from dataclasses import dataclass
from typing import Optional


RERANKER_INSTRUCTION = (
    "Given a code search query, does the following code chunk "
    "answer or relate to the query?"
)


@dataclass(frozen=True)
class RerankerModelConfig:
    """Reranker model configuration used by the download script and runtime."""

    model_name: str
    short_name: str
    instruction: str
    max_length: int = 8192
    description: str = ""
    recommended_for: str = ""
    vram_requirement_gb: float = 8.0
    cpu_feasible: bool = True
    # Architecture type determines how the model is loaded and scored:
    # - "cross_encoder": sentence-transformers CrossEncoder (predict() returns scores)
    # - "causal_lm": Qwen-style yes/no token classification via AutoModelForCausalLM
    architecture: str = "causal_lm"
    gpu_default: bool = False


RERANKER_CATALOG = {
    "cross-encoder/ms-marco-MiniLM-L-6-v2": RerankerModelConfig(
        model_name="cross-encoder/ms-marco-MiniLM-L-6-v2",
        short_name="minilm-reranker",
        instruction="",  # CrossEncoder handles this internally
        max_length=512,
        description="MiniLM-L-6 cross-encoder — tiny (22.7M), fast, NDCG@10 74.30. Best CPU default.",
        recommended_for="Default reranker. Fast enough for CPU, negligible overhead.",
        vram_requirement_gb=0.1,
        cpu_feasible=True,
        architecture="cross_encoder",
    ),
    "Qwen/Qwen3-Reranker-0.6B": RerankerModelConfig(
        model_name="Qwen/Qwen3-Reranker-0.6B",
        short_name="qwen-reranker-0.6b",
        instruction=RERANKER_INSTRUCTION,
        max_length=32768,
        description="Qwen3-Reranker-0.6B causal LM — MTEB-Code 73.42, pairs with Qwen3 embedder.",
        recommended_for="GPU mid-tier reranking with long-context support (32K tokens).",
        vram_requirement_gb=2.0,
        cpu_feasible=False,
        architecture="causal_lm",
        gpu_default=True,
    ),
    "BAAI/bge-reranker-v2-m3": RerankerModelConfig(
        model_name="BAAI/bge-reranker-v2-m3",
        short_name="bge-reranker-m3",
        instruction="",  # Uses AutoModelForSequenceClassification
        max_length=8194,
        description="BGE-Reranker-v2-m3 — multilingual cross-encoder (~600M).",
        recommended_for="Multilingual codebases. GPU recommended.",
        vram_requirement_gb=2.0,
        cpu_feasible=False,
        architecture="cross_encoder",
    ),
    "Qwen/Qwen3-Reranker-4B": RerankerModelConfig(
        model_name="Qwen/Qwen3-Reranker-4B",
        short_name="qwen-reranker-4b",
        instruction=RERANKER_INSTRUCTION,
        max_length=8192,
        description="Qwen3-Reranker-4B causal LM — highest quality, GPU required.",
        recommended_for="High-precision reranking on GPU (10 GB+ VRAM).",
        vram_requirement_gb=10.0,
        cpu_feasible=False,
        architecture="causal_lm",
    ),
}

DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
GPU_DEFAULT_RERANKER_MODEL = "Qwen/Qwen3-Reranker-0.6B"

# Short-name reverse lookup: maps e.g. "qwen-reranker-4b" → "Qwen/Qwen3-Reranker-4B"
RERANKER_SHORT_NAMES = {
    config.short_name: name
    for name, config in RERANKER_CATALOG.items()
    if config.short_name
}


def get_reranker_config(model_name: str) -> RerankerModelConfig:
    """Resolve a reranker config by full HuggingFace name or short name.

    Raises ``KeyError`` if the model is not in the catalog.
    """
    # Try direct lookup first
    if model_name in RERANKER_CATALOG:
        return RERANKER_CATALOG[model_name]

    # Try short-name reverse lookup
    full_name = RERANKER_SHORT_NAMES.get(model_name)
    if full_name:
        return RERANKER_CATALOG[full_name]

    raise KeyError(
        f"Unknown reranker model: '{model_name}'. "
        f"Available: {', '.join(RERANKER_CATALOG.keys())} "
        f"(short names: {', '.join(RERANKER_SHORT_NAMES.keys())})"
    )
