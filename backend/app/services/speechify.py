"""Speechify TTS for the companion's spoken answers.

Server-side only: `SPEECHIFY_API_KEY` must never reach the frontend, since
`frontend/app.html` is a static file served as-is (any visitor can view
source, per its own Quickstart in `README.md`). `app.main.speak` is the
only caller — it holds the key and calls out to Speechify on the
frontend's behalf, mirroring how `WATSONX_API_KEY`/`ZILLIZ_TOKEN` already
work in this codebase (see `app.services.watsonx`, `app.services.vector_store`).

This is an additive, degrade-safe feature, not a required credential like
watsonx/Zilliz: an environment with `missing_credentials()` non-empty is
still a fully healthy Q&A service (see why `GET /health` does not fold
this in, in `app.main.speak`'s docstring) — the frontend just falls back
to the browser's own `SpeechSynthesis` API instead of a Speechify voice.

Voice selection is keyed on BOTH persona and gender, not gender alone —
see the four `SPEECHIFY_VOICE_ID_*` settings in `app.config`. Banter gets
its own voice pair so the two personas actually sound different, not just
read different (jokier) text — deliberately NOT a real celebrity voice:
Speechify's licensed celebrity voices (e.g. Snoop Dogg) are a
consumer-app-only feature, absent from every tier of the developer API's
voice catalog, and cloning a real, identifiable person's voice without
their consent is a right-of-publicity problem regardless of which product
does the cloning. See speechify-voice-plan.md §5.
"""

import logging
from typing import Literal

import httpx

from app.config import settings
from app.schemas import SpeakResponse, SpeechMarkChunk

logger = logging.getLogger(__name__)

_SPEECH_ENDPOINT = "https://api.speechify.ai/v1/audio/speech"
_REQUEST_TIMEOUT = 30

# Speechify's actual per-request character cap for this endpoint was not
# confirmed against live docs while building this (the API reference page
# 404'd during research — see speechify-voice-plan.md §3.2's open TODO).
# 2000 matches SpeakRequest's own max_length, so this can only ever
# truncate input that validation already let through unexpectedly (e.g. a
# future caller relaxing that limit) — a defensive backstop, not the
# primary length control.
_MAX_INPUT_CHARS = 2000

_VOICE_ID_SETTINGS = {
    ("baseline", "male"): "SPEECHIFY_VOICE_ID_BASELINE_MALE",
    ("baseline", "female"): "SPEECHIFY_VOICE_ID_BASELINE_FEMALE",
    ("banter", "male"): "SPEECHIFY_VOICE_ID_BANTER_MALE",
    ("banter", "female"): "SPEECHIFY_VOICE_ID_BANTER_FEMALE",
}


class SpeechifySynthesisError(RuntimeError):
    """Raised when a request actually reached Speechify but failed there.

    Distinct from a missing-credentials condition (`missing_credentials`
    below): this covers a bad key, an exhausted quota, or a network
    failure reaching Speechify at all. `app.main.speak` maps this to a
    502, versus the 503 an unconfigured voice gets — "we talked to
    Speechify and it failed" versus "we never configured this voice."
    """


def _voice_setting_name(persona: str, gender: str) -> str:
    return _VOICE_ID_SETTINGS[(persona, gender)]


def _voice_id(persona: str, gender: str) -> str:
    return getattr(settings, _voice_setting_name(persona, gender))


def missing_credentials(persona: Literal["baseline", "banter"], gender: Literal["male", "female"]) -> list[str]:
    """Return the names of settings required to voice this persona/gender combo.

    Checked per-combo, not for all four voice IDs at once: an operator may
    have only auditioned and configured the baseline pair so far, and that
    should degrade cleanly for banter requests without blocking baseline
    ones. Mirrors `app.services.watsonx.missing_credentials` /
    `app.services.vector_store.missing_credentials`.
    """
    missing = []
    if not settings.SPEECHIFY_API_KEY:
        missing.append("SPEECHIFY_API_KEY")
    if not _voice_id(persona, gender):
        missing.append(_voice_setting_name(persona, gender))
    return missing


def _require_credentials(persona: str, gender: str) -> None:
    """Raise a clear local error if this persona/gender combo isn't configured.

    A plain `RuntimeError`, not `SpeechifySynthesisError` — this is a
    *local* configuration problem, never having actually reached Speechify,
    which is exactly the distinction `SpeechifySynthesisError`'s docstring
    draws. Mirrors `app.services.watsonx._require_credentials` /
    `app.services.vector_store._require_credentials`: `synthesize_speech`
    calls this itself rather than only trusting a caller to have checked
    `missing_credentials()` first (as `app.main.speak` does, to map this
    condition to a 503), so an unconfigured combo fails fast with an
    actionable message instead of silently POSTing an empty Bearer token to
    Speechify.
    """
    missing = missing_credentials(persona, gender)
    if missing:
        raise RuntimeError(
            f"Missing Speechify configuration for persona={persona!r}, gender={gender!r}: "
            + ", ".join(missing)
            + ". Set them in a local .env at the repo root (see .env.example)."
        )


def _parse_speech_marks(body: dict) -> list[SpeechMarkChunk]:
    """Parse Speechify's word-level timing marks, tolerantly.

    The exact response shape for `speech_marks` was not confirmed against
    a live response while building this (see `_MAX_INPUT_CHARS`'s note on
    the same research gap). Handles both a top-level `{"chunks": [...]}`
    wrapper and a bare top-level list, and skips any entry missing an
    expected field rather than failing the whole synthesis call over marks
    alone — lip sync degrades to the frontend's flap-timer fallback, but
    the audio itself still plays.
    """
    raw = body.get("speech_marks", [])
    if isinstance(raw, dict):
        raw = raw.get("chunks", [])
    marks = []
    for chunk in raw:
        try:
            marks.append(SpeechMarkChunk(**chunk))
        except (TypeError, ValueError) as exc:
            logger.warning("Skipping malformed Speechify speech mark %r: %s", chunk, exc)
    return marks


def synthesize_speech(
    text: str,
    gender: Literal["male", "female"],
    persona: Literal["baseline", "banter"],
) -> SpeakResponse:
    """Call Speechify's /v1/audio/speech and return audio + word-level marks.

    Raises `SpeechifySynthesisError` on any failure reaching or talking to
    Speechify. Callers that want to distinguish "not configured" from
    "Speechify itself failed" should check `missing_credentials()` first —
    `app.main.speak` does exactly this; `_require_credentials()` above is
    only a fast-fail backstop for a caller that didn't.
    """
    _require_credentials(persona, gender)
    if len(text) > _MAX_INPUT_CHARS:
        logger.warning(
            "Truncating a %d-char answer to %d chars for Speechify (persona=%s, gender=%s)",
            len(text), _MAX_INPUT_CHARS, persona, gender,
        )
        text = text[:_MAX_INPUT_CHARS]

    try:
        response = httpx.post(
            _SPEECH_ENDPOINT,
            json={
                "input": text,
                "voice_id": _voice_id(persona, gender),
                "model": settings.SPEECHIFY_MODEL,
                "audio_format": "mp3",
            },
            headers={"Authorization": f"Bearer {settings.SPEECHIFY_API_KEY}"},
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SpeechifySynthesisError(
            f"Speechify rejected the request: {exc.response.status_code} {exc.response.text[:200]}"
        ) from exc
    except httpx.RequestError as exc:
        raise SpeechifySynthesisError(f"Could not reach Speechify: {exc}") from exc

    body = response.json()
    return SpeakResponse(
        audio_data=body["audio_data"],
        audio_format=body.get("audio_format", "mp3"),
        speech_marks=_parse_speech_marks(body),
    )
