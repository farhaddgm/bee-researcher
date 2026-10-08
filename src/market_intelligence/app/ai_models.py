"""The explicit, shared catalog of supported news-analysis models.

Names are API identifiers, not display aliases. Adding an option does not
change the deployment default or any workspace's persisted selection.
"""
from __future__ import annotations

ANALYSIS_MODELS: tuple[tuple[str, str], ...] = (
    ("gpt-6.1-sol", "GPT-6.1 Sol"),
    ("gpt-6-luna", "GPT-6 Luna"),
    ("gpt-5.6-sol", "GPT-5.6 Sol"),
    ("gpt-5.6-luna", "GPT-5.6 Luna"),
    ("gpt-5.5", "GPT-5.5"),
    ("gpt-5.4", "GPT-5.4"),
)
SUPPORTED_ANALYSIS_MODELS = frozenset(model_id for model_id, _ in ANALYSIS_MODELS)

# Standard text-token prices verified against the official model pages.
# Existing models keep the deployment's configured estimates. These new
# models must not inherit the old Luna rates when selected in a workspace.
NEW_MODEL_TOKEN_PRICES = {
    "gpt-6.1-sol": (2.0, 10.0),
    "gpt-6-luna": (0.1, 0.5),
}


def analysis_model_options() -> list[dict[str, str]]:
    return [{"id": model_id, "label": label} for model_id, label in ANALYSIS_MODELS]
