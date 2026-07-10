import os
import json


def load_model():
    from strands.models.litellm import LiteLLMModel

    secret_arn = os.environ.get("LITELLM_SECRET_ARN")
    if secret_arn:
        import boto3
        secret = json.loads(
            boto3.client("secretsmanager", region_name="us-east-2")
            .get_secret_value(SecretId=secret_arn)["SecretString"]
        )
        api_key = secret["LITELLM_API_KEY"]
        base_url = secret.get("LITELLM_BASE_URL", os.environ.get("LITELLM_BASE_URL"))
    else:
        api_key = os.environ["LITELLM_API_KEY"]
        base_url = os.environ.get("LITELLM_BASE_URL")

    return LiteLLMModel(
        client_args={"api_key": api_key, "base_url": base_url},
        model_id="openai/gpt-4o-mini",
    )
