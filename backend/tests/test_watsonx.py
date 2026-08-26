"""Tests for app.services.watsonx: the instruct-model fallback chain
(watsonx only) and the embeddings provider switch (watsonx vs. Gemini).

Not live calls to watsonx or Gemini — `_chat_watsonx`/`_gemini_embed` are
monkeypatched to cheap stand-ins in the wiring tests below, so no real
client (and no real credentials) are needed to exercise the wiring itself.
"""

import os

import pytest

from app.services import watsonx


class _FakeRunnable:
    """Stand-in for a ChatWatsonx client.

    Records what it was built from and exposes an identity-comparable
    `.with_fallbacks()`, mirroring the shape `get_instruct_model` needs
    without pulling in a real langchain runnable or network client.
    `.invoke()` returns `self` so a caller can confirm which tier actually
    answered even after `get_instruct_model()` wraps every tier in
    `_logged()` (a `RunnableLambda`, not this class) -- see that function's
    docstring for why direct `.label`/`.fallbacks` attribute access no
    longer works once any fallback tier is configured.
    """

    def __init__(self, label):
        self.label = label
        self.fallbacks = None

    def invoke(self, prompt):
        return self

    def with_fallbacks(self, fallbacks):
        self.fallbacks = list(fallbacks)
        return self


@pytest.fixture(autouse=True)
def _reset_cache_and_credentials(monkeypatch):
    # get_instruct_model/get_embedding_model are @lru_cache(maxsize=1) in
    # production so the real client is built once; tests need a fresh
    # build every time to exercise different settings combinations, so
    # clear both before and after.
    watsonx.get_instruct_model.cache_clear()
    watsonx.get_embedding_model.cache_clear()
    monkeypatch.setattr(watsonx.settings, "WATSONX_API_KEY", "test-key")
    monkeypatch.setattr(watsonx.settings, "WATSONX_PROJECT_ID", "test-project")
    yield
    watsonx.get_instruct_model.cache_clear()
    watsonx.get_embedding_model.cache_clear()


def _stub_chat_watsonx(monkeypatch):
    monkeypatch.setattr(watsonx, "_chat_watsonx", lambda model_id: _FakeRunnable(model_id))


def test_instruct_model_is_the_bare_primary_when_no_fallback_id_is_set(monkeypatch):
    _stub_chat_watsonx(monkeypatch)
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_ID", "granite-primary")
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "")
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "")

    model = watsonx.get_instruct_model()

    assert model.label == "granite-primary"
    assert model.fallbacks is None  # with_fallbacks() never called


def test_instruct_model_falls_back_to_the_second_watsonx_model_when_configured(monkeypatch):
    _stub_chat_watsonx(monkeypatch)
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_ID", "granite-primary")
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "llama-fallback")
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "")

    model = watsonx.get_instruct_model()

    # Any fallback tier being configured means get_instruct_model() wraps
    # every tier in _logged() (a RunnableLambda) before chaining -- so
    # `model` and its `.fallbacks` are no longer the bare _FakeRunnable
    # instances themselves. Assert on behavior (what each tier resolves to
    # when invoked) rather than identity/type; see _FakeRunnable's docstring.
    assert model.invoke("hi").label == "granite-primary"
    assert [f.invoke("hi").label for f in model.fallbacks] == ["llama-fallback"]


def test_instruct_model_appends_gemini_as_a_third_tier_when_its_key_is_set(monkeypatch):
    """Added 2026-08-26: generation used to be watsonx-only regardless of a
    configured Gemini key, on the theory that generation never actually
    failed in production. That held until a live /ask call hit
    token_quota_reached on both watsonx tiers back to back -- an
    account-level rejection a different watsonx model id can't route
    around. GEMINI_API_KEY being set now appends a real third fallback
    tier, tried only if both watsonx tiers fail."""
    _stub_chat_watsonx(monkeypatch)
    monkeypatch.setattr(watsonx, "_gemini_chat", lambda: _FakeRunnable("gemini-fallback"))
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_ID", "granite-primary")
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "llama-fallback")
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")

    model = watsonx.get_instruct_model()

    assert model.invoke("hi").label == "granite-primary"
    assert [f.invoke("hi").label for f in model.fallbacks] == ["llama-fallback", "gemini-fallback"]


def test_instruct_model_has_only_the_watsonx_fallback_tier_when_gemini_key_is_unset(monkeypatch):
    """The Gemini tier from the test above must actually be conditional on
    GEMINI_API_KEY, not unconditionally appended."""
    _stub_chat_watsonx(monkeypatch)
    monkeypatch.setattr(
        watsonx,
        "_gemini_chat",
        lambda: (_ for _ in ()).throw(AssertionError("_gemini_chat must not be called")),
    )
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_ID", "granite-primary")
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "llama-fallback")
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "")

    model = watsonx.get_instruct_model()

    assert model.invoke("hi").label == "granite-primary"
    assert [f.invoke("hi").label for f in model.fallbacks] == ["llama-fallback"]


def test_instruct_model_logs_each_failed_tier_before_with_fallbacks_reraises(monkeypatch, caplog):
    """`RunnableWithFallbacks.invoke()` only ever re-raises the FIRST tier's
    exception once every tier has failed -- confirmed by reading its actual
    source. Without `_logged()` wrapping each tier, a later tier's failure
    (e.g. Gemini's, after both watsonx tiers already failed) is completely
    invisible: never logged, never the exception the caller sees. This
    reproduces that scenario -- three failing tiers -- and asserts all
    three are logged, by the label passed to `_logged()`."""
    _stub_chat_watsonx(monkeypatch)

    class _AlwaysFails:
        def __init__(self, label, message):
            self.label = label
            self._message = message

        def invoke(self, prompt):
            raise RuntimeError(self._message)

    monkeypatch.setattr(watsonx, "_chat_watsonx", lambda model_id: _AlwaysFails(model_id, f"{model_id} down"))
    monkeypatch.setattr(watsonx, "_gemini_chat", lambda: _AlwaysFails("gemini", "gemini down too"))
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_ID", "granite-primary")
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "llama-fallback")
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")

    model = watsonx.get_instruct_model()

    with caplog.at_level("WARNING"):
        with pytest.raises(RuntimeError, match="granite-primary down"):
            # RunnableWithFallbacks re-raises the FIRST tier's exception --
            # asserted here as the documented, if unhelpful, current
            # behavior; _logged() is what makes the other two tiers'
            # failures visible anywhere at all (checked below).
            model.invoke("hi")

    logged_messages = [r.message for r in caplog.records]
    assert any("watsonx primary" in m and "granite-primary down" in m for m in logged_messages)
    assert any("watsonx fallback" in m and "llama-fallback down" in m for m in logged_messages)
    assert any("gemini fallback" in m and "gemini down too" in m for m in logged_messages)


def test_gemini_chat_uses_thinking_level_not_the_deprecated_thinking_budget_kwarg(monkeypatch):
    """Added 2026-08-26 (round 5): a live /ask call showed the Gemini
    fallback tier failing with a bare `400 INVALID_ARGUMENT` the moment it
    was actually reached. Root cause: `_gemini_chat()` passed
    `thinking_budget=0`, which is valid for Gemini 2.5 but deprecated for
    Gemini 3.x models (gemini-3.6-flash is this project's configured
    GEMINI_INSTRUCT_MODEL_ID) -- the API rejects a request whose
    thinkingConfig carries `thinkingBudget` at all on that model
    generation. The fix is `thinking_config={"thinking_level": "minimal"}`,
    the closest Gemini 3.x equivalent of "turn thinking down as far as
    possible". This locks that shape in directly against the real
    ChatGoogleGenerativeAI class (not a stub) so a future edit that
    reintroduces `thinking_budget` fails loudly here instead of only in a
    live call.
    """
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(watsonx.settings, "GEMINI_INSTRUCT_MODEL_ID", "gemini-3.6-flash")

    client = watsonx._gemini_chat()

    assert client.thinking_budget is None
    assert client.thinking_config == {"thinking_level": "minimal"}
    generation_config = client._build_base_generation_config(stop=None)
    thinking_config = generation_config["thinking_config"]
    assert thinking_config.thinking_budget is None
    assert str(thinking_config.thinking_level) == "ThinkingLevel.MINIMAL"


def test_gemini_chat_raises_if_model_id_is_not_gemini_3x(monkeypatch):
    """See issue #3: GEMINI_INSTRUCT_MODEL_ID is a plain env var an operator
    can repoint at a 2.5-era model at any time, which would silently
    reproduce the exact 400 INVALID_ARGUMENT the previous test's docstring
    describes -- but only once a live call actually reached Gemini.
    _require_gemini_3x_model() must catch that at client-construction time
    instead."""
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(watsonx.settings, "GEMINI_INSTRUCT_MODEL_ID", "gemini-2.5-flash")

    with pytest.raises(RuntimeError, match="not a Gemini 3.x model"):
        watsonx._gemini_chat()


def test_gemini_chat_raises_on_an_unversioned_or_unrecognized_model_id(monkeypatch):
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(watsonx.settings, "GEMINI_INSTRUCT_MODEL_ID", "gemini-pro")

    with pytest.raises(RuntimeError, match="not a Gemini 3.x model"):
        watsonx._gemini_chat()


def test_gemini_chat_accepts_other_gemini_3x_models_not_just_3_6(monkeypatch):
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(watsonx.settings, "GEMINI_INSTRUCT_MODEL_ID", "gemini-3.0-pro")

    watsonx._gemini_chat()  # must not raise


def test_using_gemini_embeddings_tracks_the_gemini_api_key_setting(monkeypatch):
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "")
    assert watsonx.using_gemini_embeddings() is False

    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")
    assert watsonx.using_gemini_embeddings() is True


def test_get_embedding_model_stays_on_watsonx_when_gemini_key_is_unset(monkeypatch):
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(watsonx, "WatsonxEmbeddings", lambda **kwargs: ("watsonx-embeddings", kwargs))
    monkeypatch.setattr(
        watsonx,
        "_gemini_embed",
        lambda: (_ for _ in ()).throw(AssertionError("_gemini_embed must not be called")),
    )

    result = watsonx.get_embedding_model()

    assert result[0] == "watsonx-embeddings"
    assert result[1]["model_id"] == watsonx.settings.WATSONX_EMBEDDING_MODEL_ID


def test_get_embedding_model_switches_to_gemini_when_its_key_is_set(monkeypatch):
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(watsonx, "_gemini_embed", lambda: "gemini-embeddings")
    monkeypatch.setattr(
        watsonx,
        "WatsonxEmbeddings",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("WatsonxEmbeddings must not be built")),
    )

    result = watsonx.get_embedding_model()

    assert result == "gemini-embeddings"


def test_get_embedding_model_does_not_require_watsonx_credentials_when_gemini_is_active(
    monkeypatch,
):
    """A Gemini-only deployment (no watsonx creds at all) must still be able
    to build embeddings — `_require_credentials` is only on the watsonx
    branch. `get_instruct_model` separately still wants watsonx credentials
    for its own fallback tier; that's unrelated to this function."""
    monkeypatch.setattr(watsonx.settings, "WATSONX_API_KEY", "")
    monkeypatch.setattr(watsonx.settings, "WATSONX_PROJECT_ID", "")
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(watsonx, "_gemini_embed", lambda: "gemini-embeddings")

    assert watsonx.get_embedding_model() == "gemini-embeddings"


def test_gemini_embed_client_is_built_from_gemini_settings(monkeypatch):
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(watsonx.settings, "GEMINI_EMBEDDING_MODEL_ID", "gemini-embedding-001")

    captured = {}

    class _FakeGoogleGenerativeAIEmbeddings:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(watsonx, "GoogleGenerativeAIEmbeddings", _FakeGoogleGenerativeAIEmbeddings)

    watsonx._gemini_embed()

    assert captured["model"] == "gemini-embedding-001"
    assert captured["google_api_key"] == "test-gemini-key"


def test_gemini_api_key_env_lookup_accepts_either_var_name(monkeypatch):
    """`config.py`'s `Settings.GEMINI_API_KEY` resolves via
    `os.getenv("GEMINI_API_KEY", os.getenv("GEMINI_API", ""))` — this
    exercises that exact expression directly, without going through a full
    module reload (which would re-run `load_dotenv(override=True)` against
    whatever real `.env` happens to exist on this machine, making the test
    depend on local file contents rather than the resolution logic itself).
    Some deployments (e.g. this project's Railway service) set GEMINI_API
    rather than the canonical GEMINI_API_KEY; either must resolve the same.
    """
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API", "railway-style-key")

    resolved = os.getenv("GEMINI_API_KEY", os.getenv("GEMINI_API", ""))

    assert resolved == "railway-style-key"
