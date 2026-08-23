"""Chunking layer for mission document ingestion.

Splits raw mission documents (emergency procedures, sector specs, crew
files, incident records — see `app.schemas.MissionDocument`) into
overlapping text chunks sized for embedding, then hands the chunks to
`app.services.vector_store` to be embedded with Granite and upserted into
Zilliz. This is the POST /ingest pipeline described in the dev plan
(Section 4) and API.md.
"""

from dataclasses import dataclass

from app.schemas import MissionDocument
from app.services.vector_store import upsert_chunks

DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100


@dataclass(frozen=True)
class Chunk:
    """One chunk of a mission document, ready for embedding.

    `doc_id` and `doc_type` carry through to the vector store record's
    metadata, so a retrieved chunk can always be traced back to its source
    document — the source-attribution line every module's grounded
    response depends on (see dev plan Section 7).

    `doc_text` carries the full, un-chunked source document alongside the
    chunk's own `text` (a `chunk_text`-produced piece). It exists because
    `chunk_text` collapses every whitespace run — including newlines —
    before packing words into chunks (see its docstring), so a chunk's own
    `text` has lost the line structure a document like an emergency
    procedure or a sector spec is authored in (numbered steps, one per
    line; `metric: low-high` threshold lines). `app.services.extraction`'s
    parsers are line-anchored and need that structure back, so a module
    grounding structured fields (e.g. `app.services.crisis`'s procedure
    steps) reads `doc_text` off the retrieved chunk's metadata rather than
    parsing `text`/`page_content`. Duplicated across every chunk of a
    document rather than stored once, so a single retrieval hit is always
    enough — no second lookup keyed by `doc_id` is needed. Cheap at this
    project's scale (mission documents are single-digit KB, a handful of
    chunks each).

    `domain` is the source document's `Domain` value (already a plain
    `str` by the time it gets here — see `chunk_document`), carried
    through the same way `doc_type` is: every chunk of a document gets the
    same tag, so a retrieval hit on any chunk can be scoped or filtered by
    it without a second lookup.
    """

    doc_id: str
    doc_type: str
    chunk_index: int
    text: str
    doc_text: str
    domain: str

    def metadata(self) -> dict:
        """Metadata dict attached to this chunk's vector store record."""
        return {
            "doc_id": self.doc_id,
            "doc_type": self.doc_type,
            "chunk_index": self.chunk_index,
            "doc_text": self.doc_text,
            "domain": self.domain,
        }


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split raw text into overlapping, word-safe chunks.

    Whitespace (including newlines) is collapsed first, then words are
    packed greedily into chunks of at most `chunk_size` characters. Each
    new chunk after the first is seeded with the trailing `overlap`
    characters' worth of words from the previous chunk, so a fact sitting
    near a chunk boundary still has a full window somewhere in the index.
    A chunk never cuts a word in half.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0  # len(" ".join(current))

    def word_cost(word: str) -> int:
        return len(word) if not current else len(word) + 1  # +1 for the joining space

    for word in words:
        cost = word_cost(word)
        if current and current_len + cost > chunk_size:
            chunks.append(" ".join(current))

            # Seed the next chunk with a word-safe overlap tail from the
            # chunk just closed.
            tail: list[str] = []
            tail_len = 0
            for prior in reversed(current):
                prior_cost = len(prior) if not tail else len(prior) + 1
                if tail_len + prior_cost > overlap:
                    break
                tail.insert(0, prior)
                tail_len += prior_cost

            # An aggressive overlap (close to chunk_size) can seed a tail
            # that leaves no room for the word we're about to add. Trim
            # from the front of the tail until tail + word fits — this
            # can trim the tail to empty, which just means this word
            # starts a fresh chunk with no overlap.
            while tail and (len(" ".join(tail)) + 1 + len(word)) > chunk_size:
                tail.pop(0)

            current = tail
            current_len = len(" ".join(current)) if current else 0
            cost = word_cost(word)

        current.append(word)
        current_len += cost

    if current:
        chunks.append(" ".join(current))

    return chunks


def chunk_document(
    document: MissionDocument,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """Chunk a single mission document, tagging each chunk with its source."""
    pieces = chunk_text(document.text, chunk_size=chunk_size, overlap=overlap)
    return [
        Chunk(
            doc_id=document.id,
            doc_type=document.type.value,
            chunk_index=index,
            text=piece,
            doc_text=document.text,
            domain=document.domain.value,
        )
        for index, piece in enumerate(pieces)
    ]


def chunk_documents(
    documents: list[MissionDocument],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """Chunk a batch of mission documents, in submission order."""
    result: list[Chunk] = []
    for document in documents:
        result.extend(chunk_document(document, chunk_size=chunk_size, overlap=overlap))
    return result


def ingest_and_upsert(
    documents: list[MissionDocument],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> int:
    """Chunk, embed, and upsert a batch of mission documents.

    This is what POST /ingest calls: chunk every document with
    `chunk_documents`, then hand the chunk texts and their source metadata
    to `vector_store.upsert_chunks`, which embeds them with Granite and
    upserts them into Zilliz. Returns the number of chunks stored.
    """
    chunks = chunk_documents(documents, chunk_size=chunk_size, overlap=overlap)
    if not chunks:
        return 0
    texts = [chunk.text for chunk in chunks]
    metadatas = [chunk.metadata() for chunk in chunks]
    return upsert_chunks(texts, metadatas)
