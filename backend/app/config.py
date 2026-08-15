"""Environment and settings for The North Star backend.

Values are read from the process environment, with `.env` loaded via
python-dotenv for local development. See `.env.example` at the repo root
for the full list of supported variables.
"""

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings, loaded once at import time."""

    APP_NAME: str = "The North Star"

    # "mock" or "watsonx" — see backend/app/services/providers.py
    BACKEND_MODE: str = os.getenv("BACKEND_MODE", "mock")

    # IBM watsonx.ai
    WATSONX_API_KEY: str = os.getenv("WATSONX_API_KEY", "")
    WATSONX_PROJECT_ID: str = os.getenv("WATSONX_PROJECT_ID", "")
    WATSONX_URL: str = os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")

    # Pinecone
    PINECONE_API_KEY: str = os.getenv("PINECONE_API_KEY", "")
    PINECONE_INDEX_NAME: str = os.getenv("PINECONE_INDEX_NAME", "the-north-star")

    # Server
    PORT: int = int(os.getenv("PORT", "8000"))


settings = Settings()
