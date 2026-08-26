import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import speechify

client = TestClient(app)


def _configure_all_voices(monkeypatch):
    monkeypatch.setattr(settings, "SPEECHIFY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "SPEECHIFY_VOICE_ID_BASELINE_MALE", "baseline-male-id")
    monkeypatch.setattr(settings, "SPEECHIFY_VOICE_ID_BASELINE_FEMALE", "baseline-female-id")
    monkeypatch.setattr(settings, "SPEECHIFY_VOICE_ID_BANTER_MALE", "banter-male-id")
    monkeypatch.setattr(settings, "SPEECHIFY_VOICE_ID_BANTER_FEMALE", "banter-female-id")
    monkeypatch.setattr(settings, "SPEECHIFY_VOICE_ID_CAT", "cat-id")


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", speechify._SPEECH_ENDPOINT)
            response = httpx.Response(self.status_code, request=request, text=self.text)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self):
        return self._payload


# --- missing_credentials -----------------------------------------------


def test_missing_credentials_empty_once_key_and_voice_id_are_set(monkeypatch):
    _configure_all_voices(monkeypatch)

    assert speechify.missing_credentials("baseline", "male") == []


def test_missing_credentials_reports_missing_api_key(monkeypatch):
    monkeypatch.setattr(settings, "SPEECHIFY_API_KEY", "")
    monkeypatch.setattr(settings, "SPEECHIFY_VOICE_ID_BASELINE_MALE", "baseline-male-id")

    assert speechify.missing_credentials("baseline", "male") == ["SPEECHIFY_API_KEY"]


def test_missing_credentials_is_scoped_to_the_requested_persona_gender_combo(monkeypatch):
    """A voice ID configured for one (persona, gender) combo must not mask
    another combo being unconfigured — see the function's docstring on why
    this is checked per-combo rather than for all settings at once."""
    monkeypatch.setattr(settings, "SPEECHIFY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "SPEECHIFY_VOICE_ID_BASELINE_MALE", "baseline-male-id")
    monkeypatch.setattr(settings, "SPEECHIFY_VOICE_ID_BASELINE_FEMALE", "")
    monkeypatch.setattr(settings, "SPEECHIFY_VOICE_ID_BANTER_MALE", "")
    monkeypatch.setattr(settings, "SPEECHIFY_VOICE_ID_BANTER_FEMALE", "")

    assert speechify.missing_credentials("baseline", "male") == []
    assert speechify.missing_credentials("baseline", "female") == ["SPEECHIFY_VOICE_ID_BASELINE_FEMALE"]
    assert speechify.missing_credentials("banter", "male") == ["SPEECHIFY_VOICE_ID_BANTER_MALE"]


# --- synthesize_speech ---------------------------------------------------


def test_synthesize_speech_sends_the_right_voice_id_for_persona_and_gender(monkeypatch):
    _configure_all_voices(monkeypatch)
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse(200, {"audio_data": "abc123", "audio_format": "mp3", "speech_marks": []})

    monkeypatch.setattr(speechify.httpx, "post", fake_post)

    result = speechify.synthesize_speech("Why did the cyclone break up?", "female", "banter")

    assert captured["url"] == "https://api.speechify.ai/v1/audio/speech"
    assert captured["json"]["voice_id"] == "banter-female-id"
    assert captured["json"]["input"] == "Why did the cyclone break up?"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert result.audio_data == "abc123"
    assert result.audio_format == "mp3"
    assert result.speech_marks == []


@pytest.mark.parametrize(
    ("persona", "gender", "expected_voice_id"),
    [
        ("baseline", "male", "baseline-male-id"),
        ("baseline", "female", "baseline-female-id"),
        ("baseline", "cat", "cat-id"),
        ("banter", "male", "banter-male-id"),
        ("banter", "female", "banter-female-id"),
        ("banter", "cat", "cat-id"),
    ],
)
def test_synthesize_speech_selects_the_right_voice_id_for_every_combo(
    monkeypatch, persona, gender, expected_voice_id
):
    _configure_all_voices(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        speechify.httpx,
        "post",
        lambda url, json, headers, timeout: captured.update(json=json)
        or _FakeResponse(200, {"audio_data": "abc", "audio_format": "mp3"}),
    )

    speechify.synthesize_speech("hello", gender, persona)

    assert captured["json"]["voice_id"] == expected_voice_id


# --- cat's persona-shifted SSML, not a second voice ID -------------------


def test_cat_banter_wraps_input_in_prosody_ssml(monkeypatch):
    _configure_all_voices(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        speechify.httpx,
        "post",
        lambda url, json, headers, timeout: captured.update(json=json)
        or _FakeResponse(200, {"audio_data": "abc", "audio_format": "mp3"}),
    )

    speechify.synthesize_speech("Why did the cyclone break up?", "cat", "banter")

    assert captured["json"]["input"] == (
        '<speak><prosody pitch="+10%" rate="+12%">'
        "Why did the cyclone break up?"
        "</prosody></speak>"
    )
    # Same voice as baseline cat — persona comes from the SSML wrapper, not
    # a second sourced voice ID.
    assert captured["json"]["voice_id"] == "cat-id"


def test_cat_baseline_sends_plain_unwrapped_text(monkeypatch):
    _configure_all_voices(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        speechify.httpx,
        "post",
        lambda url, json, headers, timeout: captured.update(json=json)
        or _FakeResponse(200, {"audio_data": "abc", "audio_format": "mp3"}),
    )

    speechify.synthesize_speech("Why did the cyclone break up?", "cat", "baseline")

    assert captured["json"]["input"] == "Why did the cyclone break up?"


def test_cat_banter_escapes_xml_special_characters(monkeypatch):
    """LLM-generated answer text may contain &, <, or > — these must be
    escaped before being embedded in SSML markup, or Speechify would parse
    them as (broken) tags instead of speaking them literally."""
    _configure_all_voices(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        speechify.httpx,
        "post",
        lambda url, json, headers, timeout: captured.update(json=json)
        or _FakeResponse(200, {"audio_data": "abc", "audio_format": "mp3"}),
    )

    speechify.synthesize_speech("Wind < 20 mph & rain > 1 inch", "cat", "banter")

    assert captured["json"]["input"] == (
        '<speak><prosody pitch="+10%" rate="+12%">'
        "Wind &lt; 20 mph &amp; rain &gt; 1 inch"
        "</prosody></speak>"
    )


def test_male_female_banter_input_stays_plain_text(monkeypatch):
    """The SSML wrapper is cat-only — male/female Banter still gets its own
    distinct voice ID (george/geffenv1-style), not a prosody-shifted one."""
    _configure_all_voices(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        speechify.httpx,
        "post",
        lambda url, json, headers, timeout: captured.update(json=json)
        or _FakeResponse(200, {"audio_data": "abc", "audio_format": "mp3"}),
    )

    speechify.synthesize_speech("Why did the cyclone break up?", "male", "banter")

    assert captured["json"]["input"] == "Why did the cyclone break up?"


def test_synthesize_speech_passes_base64_audio_through_unmodified(monkeypatch):
    _configure_all_voices(monkeypatch)
    monkeypatch.setattr(
        speechify.httpx,
        "post",
        lambda *a, **k: _FakeResponse(200, {"audio_data": "==NOT_REAL_BASE64==", "audio_format": "wav"}),
    )

    result = speechify.synthesize_speech("hello", "male", "baseline")

    assert result.audio_data == "==NOT_REAL_BASE64=="
    assert result.audio_format == "wav"


def test_synthesize_speech_parses_speech_marks_chunks_wrapper(monkeypatch):
    _configure_all_voices(monkeypatch)
    payload = {
        "audio_data": "abc",
        "audio_format": "mp3",
        "speech_marks": {
            "chunks": [
                {"start_time": 0, "end_time": 250, "start": 0, "end": 3, "value": "Why"},
                {"start_time": 250, "end_time": 500, "start": 4, "end": 7, "value": "did"},
            ]
        },
    }
    monkeypatch.setattr(speechify.httpx, "post", lambda *a, **k: _FakeResponse(200, payload))

    result = speechify.synthesize_speech("Why did", "male", "baseline")

    assert [m.value for m in result.speech_marks] == ["Why", "did"]
    assert result.speech_marks[0].start_time == 0
    assert result.speech_marks[1].end_time == 500


def test_synthesize_speech_skips_a_malformed_speech_mark_without_failing(monkeypatch):
    payload = {
        "audio_data": "abc",
        "audio_format": "mp3",
        "speech_marks": [
            {"start_time": 0, "end_time": 250, "start": 0, "end": 3, "value": "Why"},
            {"start_time": "not-a-number"},
        ],
    }
    _configure_all_voices(monkeypatch)
    monkeypatch.setattr(speechify.httpx, "post", lambda *a, **k: _FakeResponse(200, payload))

    result = speechify.synthesize_speech("Why", "male", "baseline")

    assert [m.value for m in result.speech_marks] == ["Why"]


def test_synthesize_speech_truncates_input_over_the_char_cap(monkeypatch):
    _configure_all_voices(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        speechify.httpx,
        "post",
        lambda url, json, headers, timeout: captured.update(json=json) or _FakeResponse(
            200, {"audio_data": "abc", "audio_format": "mp3"}
        ),
    )

    speechify.synthesize_speech("x" * 3000, "male", "baseline")

    assert len(captured["json"]["input"]) == speechify._MAX_INPUT_CHARS


def test_synthesize_speech_fails_fast_when_unconfigured_without_calling_speechify(monkeypatch):
    """Regression test for the self-guard `synthesize_speech` calls before
    ever making an HTTP request — a caller that skips `missing_credentials()`
    (unlike `app.main.speak`, which always checks first) must still fail
    with a clear local error instead of POSTing an empty Bearer token."""
    monkeypatch.setattr(settings, "SPEECHIFY_API_KEY", "")

    def fail_if_called(*a, **k):
        raise AssertionError("must not call Speechify when unconfigured")

    monkeypatch.setattr(speechify.httpx, "post", fail_if_called)

    with pytest.raises(RuntimeError, match="SPEECHIFY_API_KEY"):
        speechify.synthesize_speech("hello", "male", "baseline")


def test_synthesize_speech_wraps_an_http_error_status(monkeypatch):
    _configure_all_voices(monkeypatch)
    monkeypatch.setattr(
        speechify.httpx, "post", lambda *a, **k: _FakeResponse(401, text="invalid api key")
    )

    with pytest.raises(speechify.SpeechifySynthesisError):
        speechify.synthesize_speech("hello", "male", "baseline")


def test_synthesize_speech_wraps_a_network_failure(monkeypatch):
    _configure_all_voices(monkeypatch)

    def fake_post(*a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(speechify.httpx, "post", fake_post)

    with pytest.raises(speechify.SpeechifySynthesisError):
        speechify.synthesize_speech("hello", "male", "baseline")


# --- POST /speak endpoint -------------------------------------------------


def test_speak_endpoint_returns_503_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "SPEECHIFY_API_KEY", "")

    response = client.post("/speak", json={"text": "hello", "gender": "male", "persona": "baseline"})

    assert response.status_code == 503
    assert "SPEECHIFY_API_KEY" in response.json()["detail"]


def test_speak_endpoint_happy_path(monkeypatch):
    _configure_all_voices(monkeypatch)
    monkeypatch.setattr(
        speechify.httpx,
        "post",
        lambda *a, **k: _FakeResponse(200, {"audio_data": "YWJj", "audio_format": "mp3", "speech_marks": []}),
    )

    response = client.post("/speak", json={"text": "hello", "gender": "female", "persona": "banter"})

    assert response.status_code == 200
    body = response.json()
    assert body["audio_url"].startswith("/speak/audio/")
    assert body["audio_url"].endswith(".mp3")
    assert body["audio_format"] == "mp3"
    assert body["speech_marks"] == []

    # The returned URL is a real, servable resource -- not embedded data.
    audio_response = client.get(body["audio_url"])
    assert audio_response.status_code == 200
    assert audio_response.content == b"abc"


def test_speak_endpoint_returns_502_when_speechify_fails(monkeypatch):
    _configure_all_voices(monkeypatch)
    monkeypatch.setattr(speechify.httpx, "post", lambda *a, **k: _FakeResponse(500, text="upstream error"))

    response = client.post("/speak", json={"text": "hello", "gender": "male", "persona": "baseline"})

    assert response.status_code == 502


def test_speak_endpoint_defaults_gender_and_persona(monkeypatch):
    _configure_all_voices(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        speechify.httpx,
        "post",
        lambda url, json, headers, timeout: captured.update(json=json) or _FakeResponse(
            200, {"audio_data": "YWJj", "audio_format": "mp3"}
        ),
    )

    response = client.post("/speak", json={"text": "hello"})

    assert response.status_code == 200
    assert captured["json"]["voice_id"] == "baseline-female-id"


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "", "gender": "male", "persona": "baseline"},
        {"text": "hi", "gender": "robot", "persona": "baseline"},
        {"text": "hi", "gender": "male", "persona": "sarcastic"},
    ],
)
def test_speak_endpoint_rejects_invalid_requests(payload):
    response = client.post("/speak", json=payload)

    assert response.status_code == 422
