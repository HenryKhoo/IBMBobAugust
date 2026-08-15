"""FastAPI application entrypoint for The North Star backend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.schemas import HealthResponse, IngestRequest, IngestResponse
from app.services.ingestion import ingest_and_upsert

app = FastAPI(title=settings.APP_NAME)

# The frontend is a single static HTML file served separately (locally or
# on Railway); allow it to call this API from any origin during
# development. Tighten this once a deployed frontend origin is known.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report service status and which backend mode is active."""
    return HealthResponse(status="ok", backend=settings.BACKEND_MODE)


@app.post("/ingest", response_model=IngestResponse)
def ingest(request: IngestRequest) -> IngestResponse:
    """Chunk, embed with Granite, and upsert mission documents into Zilliz."""
    chunks_ingested = ingest_and_upsert(request.documents)
    return IngestResponse(chunks_ingested=chunks_ingested)
