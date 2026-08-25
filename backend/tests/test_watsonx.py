"""Tests for the instruct-model fallback chain in app.services.watsonx.

Focuses on chain *composition* — which tiers get wired in under which
settings — not live calls to watsonx or Gemini. `_chat_watsonx` and
`_chat_gemini` are monkeypatched to cheap stand-ins so no real client (and
no real credentials) are needed to exercise the wiring itself.
"""

import pytest

from app.services import watsonx


class _FakeRunnable:
    """Stand-in for a ChatWatsonx/ChatGoogleGenerativeAI client.

    Records what it was built from and exposes an identity-comparable
    `.with_fallbacks()`, mirroring the shape `get_instruct_model` needs
    without pulling in a real langchain runnable or network client.
    """

    def __init__(self, label):
        self.label = label
        self.fallbacks = None

    def with_fallbacks(self, fallbacks):
        self.fallbacks = list(fallbacks)
        return self


@pytest.fixture(autouse=True)
def _reset_cache_and_credentials(monkeypatch):
    # get_instruct_model is @lru_cache(maxsize=1) in production so the real
    # client is built once; tests need a fresh build every time to exercise
    # different settings combinations, so clear it before and after.
    watsonx.get_instruct_model.cache_clear()
    monkeypatch.setattr(watsonx.settings, "WATSONX_API_KEY", "test-key")
    monkeypatch.setattr(watsonx.settings, "WATSONX_PROJECT_ID", "test-project")
    yield
    watsonx.get_instruct_model.cache_clear()


def test_no_fallbacks_configured_returns_the_bare_primary(monkeypatch):
    monkeypatch.setattr(watsonx, "_chat_watsonx", lambda model_id: _FakeRunnable(model_id))
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "")
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "")

    model = watsonx.get_instruct_model()

    assert isinstance(model, _FakeRunnable)
    assert model.fallbacks is None  # with_fallbacks() never called


def test_watsonx_fallback_alone_when_gemini_key_is_unset(monkeypatch):
    """Pre-existing two-tier behavior must be unchanged by adding Gemini support."""
    monkeypatch.setattr(watsonx, "_chat_watsonx", lambda model_id: _FakeRunnable(model_id))
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "llama-fallback")
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "")

    model = watsonx.get_instruct_model()

    assert [f.label for f in model.fallbacks] == ["llama-fallback"]


def test_gemini_is_appended_as_a_third_tier_after_the_watsonx_fallback(monkeypatch):
    monkeypatch.setattr(watsonx, "_chat_watsonx", lambda model_id: _FakeRunnable(model_id))
    monkeypatch.setattr(watsonx, "_chat_gemini", lambda: _FakeRunnable("gemini"))
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "llama-fallback")
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")

    model = watsonx.get_instruct_model()

    assert [f.label for f in model.fallbacks] == ["llama-fallback", "gemini"]


def test_gemini_is_the_only_fallback_when_the_watsonx_fallback_is_unset(monkeypatch):
    monkeypatch.setattr(watsonx, "_chat_watsonx", lambda model_id: _FakeRunnable(model_id))
    monkeypatch.setattr(watsonx, "_chat_gemini", lambda: _FakeRunnable("gemini"))
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "")
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")

    model = watsonx.get_instruct_model()

    assert [f.label for f in model.fallbacks] == ["gemini"]


def test_gemini_client_is_built_from_gemini_settings(monkeypatch):
    """`_chat_gemini` itself (not just the wiring) reads the right settings."""
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(watsonx.settings, "GEMINI_INSTRUCT_MODEL_ID", "gemini-2.5-flash")

    captured = {}

    class _FakeChatGoogleGenerativeAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(watsonx, "ChatGoogleGenerativeAI", _FakeChatGoogleGenerativeAI)

    watsonx._chat_gemini()

    assert captured["model"] == "gemini-2.5-flash"
    assert captured["google_api_key"] == "test-gemini-key"
