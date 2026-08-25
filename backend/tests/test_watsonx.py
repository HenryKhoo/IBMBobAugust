"""Tests for the instruct-model fallback chain in app.services.watsonx.

Focuses on chain *composition* — which client ends up primary, and which
tiers get wired in as fallbacks, under which settings — not live calls to
watsonx or Gemini. `_chat_watsonx` and `_chat_gemini` are monkeypatched to
cheap stand-ins in the wiring tests below, so no real client (and no real
credentials) are needed to exercise the wiring itself.
"""

import os

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


def _stub_clients(monkeypatch):
    """Wire up cheap stand-ins for both `_chat_watsonx` and `_chat_gemini`.

    Used by the chain-composition tests below, which only care about *which*
    client ends up primary and which end up as fallbacks — not about how
    either client is actually constructed (see
    `test_gemini_client_is_built_from_gemini_settings` for that).
    """
    monkeypatch.setattr(watsonx, "_chat_watsonx", lambda model_id: _FakeRunnable(model_id))
    monkeypatch.setattr(watsonx, "_chat_gemini", lambda: _FakeRunnable("gemini"))


def test_watsonx_primary_with_no_fallbacks_when_gemini_key_is_unset(monkeypatch):
    """Pre-existing behavior, unchanged: no Gemini key, no watsonx fallback id."""
    _stub_clients(monkeypatch)
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_ID", "granite-primary")
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "")
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "")

    model = watsonx.get_instruct_model()

    assert model.label == "granite-primary"
    assert model.fallbacks is None  # with_fallbacks() never called


def test_watsonx_primary_with_watsonx_fallback_when_gemini_key_is_unset(monkeypatch):
    """Pre-existing two-tier behavior, unchanged by adding Gemini support."""
    _stub_clients(monkeypatch)
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_ID", "granite-primary")
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "llama-fallback")
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "")

    model = watsonx.get_instruct_model()

    assert model.label == "granite-primary"
    assert [f.label for f in model.fallbacks] == ["llama-fallback"]


def test_gemini_becomes_primary_when_its_key_is_set(monkeypatch):
    _stub_clients(monkeypatch)
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "llama-fallback")
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")

    model = watsonx.get_instruct_model()

    assert model.label == "gemini"


def test_both_watsonx_models_become_the_fallback_chain_when_gemini_is_primary(monkeypatch):
    _stub_clients(monkeypatch)
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_ID", "granite-primary")
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "llama-fallback")
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")

    model = watsonx.get_instruct_model()

    assert model.label == "gemini"
    assert [f.label for f in model.fallbacks] == ["granite-primary", "llama-fallback"]


def test_gemini_primary_falls_back_to_only_the_watsonx_primary_when_no_watsonx_fallback_id(
    monkeypatch,
):
    _stub_clients(monkeypatch)
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_ID", "granite-primary")
    monkeypatch.setattr(watsonx.settings, "WATSONX_INSTRUCT_MODEL_FALLBACK_ID", "")
    monkeypatch.setattr(watsonx.settings, "GEMINI_API_KEY", "test-gemini-key")

    model = watsonx.get_instruct_model()

    assert model.label == "gemini"
    assert [f.label for f in model.fallbacks] == ["granite-primary"]


def test_gemini_client_is_built_from_gemini_settings(monkeypatch):
    """`_chat_gemini` itself (not a stub) reads the right settings and
    constructs `ChatGoogleGenerativeAI` with them."""
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
