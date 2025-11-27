import os
from typing import Optional

# Central helper to read the OpenAI API key from the required secret.
SECRET_NAME = "OPENAI_API_KEY"
_FALLBACK_ENV = "openevent-api-test-key"


def load_openai_api_key(required: bool = True) -> Optional[str]:
    """
    Fetch the OpenAI API key from the environment.

    Args:
        required: When True, raise if the key is missing.
    """
    key = os.getenv(SECRET_NAME) or os.getenv(_FALLBACK_ENV)
    if key:
        return key
    if required:
        raise RuntimeError(
            f"Environment variable '{SECRET_NAME}' (or fallback '{_FALLBACK_ENV}') is required to call OpenAI."
        )
    return None
