import os

from dotenv import load_dotenv

load_dotenv(override=True)


class Settings:
    APP_NAME: str = "C.O.S.M.O.S."

    WATSONX_API_KEY: str = os.getenv("WATSONX_API_KEY", "")
    WATSONX_PROJECT_ID: str = os.getenv("WATSONX_PROJECT_ID", "")
    WATSONX_URL: str = os.getenv("WATSONX_URL", "https://eu-de.ml.cloud.ibm.com")
    WATSONX_EMBEDDING_MODEL_ID: str = os.getenv("WATSONX_EMBEDDING_MODEL_ID", "ibm/granite-embedding-278m-multilingual")
    WATSONX_INSTRUCT_MODEL_ID: str = os.getenv("WATSONX_INSTRUCT_MODEL_ID", "ibm/granite-4-h-small")
    WATSONX_INSTRUCT_MODEL_FALLBACK_ID: str = os.getenv("WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "meta-llama/llama-3-3-70b-instruct")

    # Embeddings-only switch: when set, retrieval uses Gemini's
    # gemini-embedding-001 instead of watsonx/Granite, and a separate
    # Zilliz collection (ZILLIZ_COLLECTION_NAME_GEMINI below) — added after
    # watsonx's Granite embedding quota started rejecting every retrieval
    # call outright. Leave unset to keep watsonx/Granite embeddings,
    # unchanged. Accepts either env var name: GEMINI_API_KEY is canonical,
    # GEMINI_API is accepted too since that's the name already used in some
    # deployments (e.g. this project's Railway service variables).
    # Generation (/ask's instruct model) does not use Gemini at all — see
    # app.services.watsonx's module docstring for why that was tried and
    # deliberately removed.
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", os.getenv("GEMINI_API", ""))
    # gemini-embedding-001 is the current model; the older
    # text-embedding-004 was deprecated and shut down in Jan 2026.
    GEMINI_EMBEDDING_MODEL_ID: str = os.getenv("GEMINI_EMBEDDING_MODEL_ID", "gemini-embedding-001")
    # Generation-side Gemini fallback tier -- see get_instruct_model() in
    # app/services/watsonx.py. Only used when GEMINI_API_KEY is set AND
    # every watsonx instruct tier has failed; not the primary in any case.
    # gemini-3.6-flash is the current general-purpose stable Flash model as
    # of Aug 2026 (2.0/2.5-era Flash ids have since been retired).
    GEMINI_INSTRUCT_MODEL_ID: str = os.getenv("GEMINI_INSTRUCT_MODEL_ID", "gemini-3.6-flash")

    ZILLIZ_URI: str = os.getenv("ZILLIZ_URI", "")
    ZILLIZ_TOKEN: str = os.getenv("ZILLIZ_TOKEN", "")
    ZILLIZ_COLLECTION_NAME: str = os.getenv("ZILLIZ_COLLECTION_NAME", "cosmos")
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
        os.getenv("ZILLIZ_COLLECTION_NAME", "cosmos") + "_gemini",
    )

    PORT: int = int(os.getenv("PORT", "8000"))

    # Speechify TTS for the companion's spoken answers — additive and
    # degrade-safe, not a required credential like watsonx/Zilliz above:
    # leaving SPEECHIFY_API_KEY blank keeps the companion on the frontend's
    # existing Web Speech API path (see app/services/speechify.py and
    # speechify-voice-plan.md). api.speechify.ai is a separate developer-API
    # product from the consumer speechify.com reading app — free tier is
    # 50,000 characters/month, no card required (speechify.ai/pricing).
    SPEECHIFY_API_KEY: str = os.getenv("SPEECHIFY_API_KEY", "")
    SPEECHIFY_MODEL: str = os.getenv("SPEECHIFY_MODEL", "simba-3.0")
    # Five voice IDs, not six: male/female get the persona (baseline/banter)
    # AND companion treatment — their own voice pair each, so Banter
    # actually *sounds* different, not just reads different (jokier) text.
    # Defaults here are empty placeholders on purpose — pick real values via
    # `GET /v1/voices?type=shared&locale=en-US&model=simba-3.0` (real
    # values, e.g. jacob/evelyn/george/geffenv1, live in .env, not here) —
    # see speechify-voice-plan.md §5 for why the banter pair is a stock
    # laid-back/hype-vibe voice rather than an actual celebrity voice
    # (Speechify's licensed celebrity voices, e.g. Snoop Dogg, are a
    # consumer-app-only feature, absent from every tier of the developer
    # API's voice catalog).
    #
    # Cat gets ONE voice, not a baseline/banter pair: rather than sourcing
    # and auditioning a second "playful" cat voice from the catalog (which
    # would need the same by-ear pass as the pairs above, sight unseen),
    # persona is instead expressed by dynamically pitch/rate-shifting this
    # single voice via SSML for Banter only — see
    # `app.services.speechify._cat_banter_input`. Baseline cat gets this
    # voice completely unmodified (plain text input, Speechify's own
    # medium/medium prosody defaults).
    SPEECHIFY_VOICE_ID_BASELINE_MALE: str = os.getenv("SPEECHIFY_VOICE_ID_BASELINE_MALE", "")
    SPEECHIFY_VOICE_ID_BASELINE_FEMALE: str = os.getenv("SPEECHIFY_VOICE_ID_BASELINE_FEMALE", "")
    SPEECHIFY_VOICE_ID_BANTER_MALE: str = os.getenv("SPEECHIFY_VOICE_ID_BANTER_MALE", "")
    SPEECHIFY_VOICE_ID_BANTER_FEMALE: str = os.getenv("SPEECHIFY_VOICE_ID_BANTER_FEMALE", "")
    SPEECHIFY_VOICE_ID_CAT: str = os.getenv("SPEECHIFY_VOICE_ID_CAT", "")

    # Shared-secret gate for the internal admin tool (frontend/admin.html)
    # that appends entries to backend/data/preset_qa.json — see app.main's
    # admin routes. Unset (default) leaves those routes open, matching this
    # file's other optional-credential settings (e.g. SPEECHIFY_API_KEY);
    # set it in any environment where that write endpoint is reachable by
    # more than a trusted developer, and put the same value in the admin
    # page so it can send it back via X-Admin-Token.
    ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "")


settings = Settings()
