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

    ZILLIZ_URI: str = os.getenv("ZILLIZ_URI", "")
    ZILLIZ_TOKEN: str = os.getenv("ZILLIZ_TOKEN", "")
    ZILLIZ_COLLECTION_NAME: str = os.getenv("ZILLIZ_COLLECTION_NAME", "chortlechat")

    PORT: int = int(os.getenv("PORT", "8000"))


settings = Settings()
