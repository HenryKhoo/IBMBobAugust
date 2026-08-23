from fastapi.testclient import TestClient

from app import main
from app.main import app
from app.services import chortlechat

client = TestClient(app)

# `main` imports these two under aliases, so they are patched on `main`
# itself rather than on their defining modules.


def test_health_ok_when_every_credential_is_configured(monkeypatch):
    monkeypatch.setattr(main, "watsonx_missing_credentials", list)
    monkeypatch.setattr(main, "zilliz_missing_credentials", list)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["backend"] == "watsonx"
    assert body["missing_config"] == []


def test_health_reports_degraded_when_credentials_are_missing(monkeypatch):
    """Regression test for the deployment bug this endpoint used to hide.

    /health used to return a hardcoded healthy status regardless of
    whether watsonx/Zilliz were actually configured, so a deployment
    missing credentials looked healthy while every real endpoint failed.
    Status now derives from the same credential check a real request runs.
    """
    monkeypatch.setattr(main, "watsonx_missing_credentials", lambda: ["WATSONX_API_KEY"])
    monkeypatch.setattr(main, "zilliz_missing_credentials", lambda: ["ZILLIZ_URI"])

    response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["backend"] == "watsonx"
    assert body["missing_config"] == ["WATSONX_API_KEY", "ZILLIZ_URI"]


def test_unhandled_exception_still_carries_cors_headers(monkeypatch):
    """Regression test: an *uncaught* exception's fallback 500 response is
    sent by Starlette's ServerErrorMiddleware, which sits outside every
    middleware added via `add_middleware` — including CORSMiddleware — so
    it carries no Access-Control-Allow-Origin header at all. A browser
    can't tell that apart from an actual CORS misconfiguration.
    app.main._UnhandledExceptionToJSON fixes this: it's a middleware added
    *before* CORSMiddleware (so it ends up inside it), which catches the
    exception itself and returns a normal Response, letting it flow back up
    through CORSMiddleware like any other response.
    """

    def _boom():
        raise RuntimeError("simulated unexpected failure")

    monkeypatch.setattr(chortlechat, "get_vector_store", _boom)

    response = client.post(
        "/ask",
        json={"question": "What is Veggie?"},
        headers={"Origin": "https://chortlechat.up.railway.app"},
    )

    assert response.status_code == 500
    # allow_credentials=True means CORSMiddleware echoes back the actual
    # request Origin rather than "*" — what matters here is that the
    # header is present at all on an error response.
    assert (
        response.headers.get("access-control-allow-origin")
        == "https://chortlechat.up.railway.app"
    )
