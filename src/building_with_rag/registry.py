"""The one shared registry of course modes and their model IDs."""

from typing import Literal, get_args

Pattern = Literal["semantic", "hybrid", "hybrid-reranked", "structured", "decomposition", "hyde"]

MODES: tuple[str, ...] = get_args(Pattern)
MODEL_IDS: dict[str, str] = {mode: f"rag-{mode}" for mode in MODES}
MODE_BY_MODEL_ID: dict[str, str] = {model: mode for mode, model in MODEL_IDS.items()}
