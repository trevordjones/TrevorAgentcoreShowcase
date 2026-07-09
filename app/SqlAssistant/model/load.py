import os
from strands.models.litellm import LiteLLMModel


def load_model() -> LiteLLMModel:
    """Get LiteLLM model client using LITELLM_API_KEY from environment."""
    return LiteLLMModel(
        client_args={
            "api_key": os.environ["LITELLM_API_KEY"],
            "base_url": os.environ.get("LITELLM_BASE_URL"),
        },
        model_id="openai/gpt-4o-mini",
    )
