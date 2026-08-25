import os

from dotenv import load_dotenv

load_dotenv(override=True)


class Settings:
    APP_NAME: str = "ChortleChat"

    WATSONX_API_KEY: str = os.getenv("WATSONX_API_KEY", "")
    WATSONX_PROJECT_ID: str = os.getenv("WATSONX_PROJECT_ID", "")
    WATSONX_URL: str = os.getenv("WATSONX_URL", "https://eu-de.ml.cloud.ibm.com")
    WATSONX_EMBEDDING_MODEL_ID: str = os.getenv("WATSONX_EMBEDDING_MODEL_ID", "ibm/granite-embedding-278m-multilingual")
    WATSONX_INSTRUCT_MODEL_ID: str = os.getenv("WATSONX_INSTRUCT_MODEL_ID", "ibm/granite-4-h-small")
    WATSONX_INSTRUCT_MODEL_FALLBACK_ID: str = os.getenv("WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "meta-llama/llama-3-3-70b-instruct")

    # Primary generation model when set — watsonx's Granite trial tier kept
    # hitting its rate limit, so Gemini is tried first and both watsonx
    # models (above) become the failover chain instead. Leave unset to keep
    # watsonx as primary, exactly as before Gemini support existed. Accepts
    # either env var name: GEMINI_API_KEY is canonical, GEMINI_API is
    # accepted too since that's the name already used in some deployments
    # (e.g. this project's Railway service variables). Generation only —
    # the embedding model stays watsonx/Granite-only regardless, since the
    # Zilliz collection is already indexed against Granite's vector space
    # and switching embedding providers would make existing vectors
    # incomparable to newly embedded ones. See app.services.watsonx.
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", os.getenv("GEMINI_API", ""))
    GEMINI_INSTRUCT_MODEL_ID: str = os.getenv("GEMINI_INSTRUCT_MODEL_ID", "gemini-2.5-flash")

    ZILLIZ_URI: str = os.getenv("ZILLIZ_URI", "")
    ZILLIZ_TOKEN: str = os.getenv("ZILLIZ_TOKEN", "")
    ZILLIZ_COLLECTION_NAME: str = os.getenv("ZILLIZ_COLLECTION_NAME", "chortlechat")

    PORT: int = int(os.getenv("PORT", "8000"))


settings = Settings()
