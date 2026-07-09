import os


def load_model():
    from strands.models.litellm import LiteLLMModel
    return LiteLLMModel(
        client_args={
            "api_key": os.environ["LITELLM_API_KEY"],
            "base_url": os.environ.get("LITELLM_BASE_URL"),
        },
        model_id="openai/gpt-4o-mini",
    )
