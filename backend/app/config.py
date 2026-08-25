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
    # Embeddings, too, switch to Gemini once GEMINI_API_KEY is set — added
    # after watsonx's Granite embedding quota (a separate quota from the
    # instruct model's) started rejecting every retrieval call outright.
    # gemini-embedding-001 is the current model; the older
    # text-embedding-004 was deprecated and shut down in Jan 2026.
    GEMINI_EMBEDDING_MODEL_ID: str = os.getenv("GEMINI_EMBEDDING_MODEL_ID", "gemini-embedding-001")

    ZILLIZ_URI: str = os.getenv("ZILLIZ_URI", "")
    ZILLIZ_TOKEN: str = os.getenv("ZILLIZ_TOKEN", "")
    ZILLIZ_COLLECTION_NAME: str = os.getenv("ZILLIZ_COLLECTION_NAME", "chortlechat")
    # A SEPARATE collection for Gemini-embedded documents, used instead of
    # ZILLIZ_COLLECTION_NAME whenever Gemini embeddings are active (see
    # app.services.watsonx.using_gemini_embeddings). Deliberately never the
    # same collection: embeddings from different providers are different
    # vector spaces, and comparing a Gemini query vector against a
    # Granite-embedded document vector produces a meaningless similarity
    # score without raising any error — the retrieval equivalent of the
    # quota failure this was added to work around, just silent instead of
    # a 403. Defaults to ZILLIZ_COLLECTION_NAME + "_gemini" so it never
    # collides with the existing collection by accident.
    ZILLIZ_COLLECTION_NAME_GEMINI: str = os.getenv(
        "ZILLIZ_COLLECTION_NAME_GEMINI",
        os.getenv("ZILLIZ_COLLECTION_NAME", "chortlechat") + "_gemini",
    )

    PORT: int = int(os.getenv("PORT", "8000"))


settings = Settings()
