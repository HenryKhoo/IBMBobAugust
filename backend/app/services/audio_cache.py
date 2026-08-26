"""Short-lived disk cache for generated Speechify audio clips.

`POST /speak` used to hand the frontend base64 audio and let it build a
`data:audio/...;base64,...` URL client-side. The deployed frontend's CSP
(`media-src 'self' https: *`) rejects that scheme outright -- and, when a
`Blob`/`URL.createObjectURL` was tried instead, rejects `blob:` too, since
neither is a network scheme nor matches `'self'` in Chromium's actual
enforcement. `https:` is allowed, so `/speak` now returns a real HTTP URL
(`/speak/audio/{filename}`) that `GET /speak/audio/{filename}` below
serves, and the frontend points `<audio>` at it directly instead of
embedding the bytes.

Clips are cached on disk, not just held in memory, so `FileResponse` can
serve them with Range support (Safari's media engine expects it even
without seeking) for free instead of reimplementing partial content.
"""

import base64
import re
import time
import uuid
from pathlib import Path
from tempfile import gettempdir

_CACHE_DIR = Path(gettempdir()) / "cosmos_speech_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# One companion answer's clip is at most a few seconds of speech and is
# never replayed from scratch minutes later (Pause/Resume reuses the same
# <audio> element's already-loaded src) -- 10 minutes comfortably covers
# any in-flight playback with room to spare, without clips piling up.
_TTL_SECONDS = 600

# Enforced both on write (the format always comes from Speechify's own
# `audio_format` field, but this keeps that assumption from silently
# rotting) and on read (the filename in the URL is client-supplied, so it
# must be validated before touching the filesystem).
_FILENAME_RE = re.compile(r"^[0-9a-f]{32}\.(mp3|wav|ogg)$")


def _purge_stale() -> None:
    cutoff = time.time() - _TTL_SECONDS
    for path in _CACHE_DIR.iterdir():
        if path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)


def store(audio_data_b64: str, audio_format: str) -> str:
    """Decode base64 audio, cache it to disk, and return its URL path.

    The returned path is relative to the backend's own origin (e.g.
    `/speak/audio/<id>.mp3`) -- callers must prefix it with the backend's
    base URL before handing it to a frontend on a different origin.
    """
    _purge_stale()
    filename = f"{uuid.uuid4().hex}.{audio_format}"
    (_CACHE_DIR / filename).write_bytes(base64.b64decode(audio_data_b64))
    return f"/speak/audio/{filename}"


def resolve(filename: str) -> Path:
    """Return the cached clip's path, or raise if it's invalid/expired/missing."""
    if not _FILENAME_RE.match(filename):
        raise ValueError(f"Invalid audio filename: {filename!r}")
    path = _CACHE_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(filename)
    return path
