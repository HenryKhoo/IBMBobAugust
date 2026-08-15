"""Environment and settings for The North Star backend.

Values are read from the process environment, with `.env` loaded via
python-dotenv for local development. See `.env.example` at the repo root
for the full list of supported variables.
"""

import os

from dotenv import load_dotenv

load_dotenv(override=True)


class Settings:
    """Application settings, loaded once at import time."""

    APP_NAME: str = "The North Star"

    # BACKEND_MODE was removed here deliberately. It defaulted to "mock" and
    # pointed at `app/services/providers.py`, a module that does not exist —
    # no mock provider was ever implemented, and nothing in the codebase
    # branched on the value. Its only reader was `/health`, which echoed it
    # back, so a deployment with no credentials reported itself healthy on
    # the "mock" backend while every module endpoint returned a 500. See
    # `app.main.health`. Leaving a stale BACKEND_MODE set in a Railway
    # service's variables is harmless: nothing reads it now.

    # IBM watsonx.ai
    WATSONX_API_KEY: str = os.getenv("WATSONX_API_KEY", "")
    WATSONX_PROJECT_ID: str = os.getenv("WATSONX_PROJECT_ID", "")
    WATSONX_URL: str = os.getenv("WATSONX_URL", "https://eu-de.ml.cloud.ibm.com")

    # Granite embedding model, used for ingestion/retrieval (see services/watsonx.py)
    WATSONX_EMBEDDING_MODEL_ID: str = os.getenv(
        "WATSONX_EMBEDDING_MODEL_ID", "ibm/granite-embedding-278m-multilingual"
    )
    # Granite instruct model, used for grounded generation in each module
    WATSONX_INSTRUCT_MODEL_ID: str = os.getenv(
        "WATSONX_INSTRUCT_MODEL_ID", "ibm/granite-4-h-small"
    )
    # Failover instruct model, used automatically if the primary instruct
    # model errors (see services/watsonx.py's use of .with_fallbacks()).
    # Leave empty to disable failover.
    WATSONX_INSTRUCT_MODEL_FALLBACK_ID: str = os.getenv(
        "WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "meta-llama/llama-3-3-70b-instruct"
    )

    # Zilliz Cloud (managed Milvus), used by services/vector_store.py
    ZILLIZ_URI: str = os.getenv("ZILLIZ_URI", "")
    ZILLIZ_TOKEN: str = os.getenv("ZILLIZ_TOKEN", "")
    ZILLIZ_COLLECTION_NAME: str = os.getenv("ZILLIZ_COLLECTION_NAME", "the_north_star")

    # Server
    PORT: int = int(os.getenv("PORT", "8000"))


settings = Settings()
