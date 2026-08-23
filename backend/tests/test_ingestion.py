import pytest

from app.schemas import Domain, DocumentType, MissionDocument
from app.services.ingestion import chunk_document, chunk_documents, chunk_text


def _overlap_words(prev_chunk: str, next_chunk: str) -> int:
    """Length of the longest word-for-word suffix/prefix shared between
    two consecutive chunks, or 0 if they don't share one."""
    prev_words = prev_chunk.split()
    next_words = next_chunk.split()
    for k in range(min(len(prev_words), len(next_words)), 0, -1):
        if prev_words[-k:] == next_words[:k]:
            return k
    return 0


def test_empty_and_whitespace_only_text_produce_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_short_text_is_a_single_untouched_chunk():
    short = "The reactor coolant loop is nominal."
    assert chunk_text(short, chunk_size=800, overlap=100) == [short]


def test_long_text_chunks_respect_chunk_size_and_reconstruct_losslessly():
    words = [f"word{i}" for i in range(500)]
    text = " ".join(words)
    chunks = chunk_text(text, chunk_size=100, overlap=20)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 100

    # every consecutive pair overlaps, and stitching the chunks back
    # together (dropping the overlapping words) reproduces the original
    # word sequence with nothing dropped, duplicated, or reordered.
    reconstructed: list[str] = []
    for index, chunk in enumerate(chunks):
        chunk_words = chunk.split()
        if index == 0:
            reconstructed.extend(chunk_words)
        else:
            k = _overlap_words(chunks[index - 1], chunk)
            assert k > 0
            reconstructed.extend(chunk_words[k:])
    assert reconstructed == words


def test_single_word_longer_than_chunk_size_becomes_its_own_chunk():
    long_word = "y" * 200
    assert chunk_text(long_word, chunk_size=50, overlap=10) == [long_word]


def test_aggressive_overlap_near_chunk_size_still_respects_chunk_size():
    # overlap this close to chunk_size used to be able to seed a tail with
    # no room left for the next word — see ingestion.chunk_text's trim guard.
    text = " ".join(f"word{i}" for i in range(200))
    chunks = chunk_text(text, chunk_size=100, overlap=99)
    for chunk in chunks:
        if len(chunk.split()) > 1:
            assert len(chunk) <= 100


@pytest.mark.parametrize(
    "chunk_size,overlap",
    [(0, 0), (10, 10), (10, 11), (10, -1)],
)
def test_invalid_chunk_size_or_overlap_raises(chunk_size, overlap):
    with pytest.raises(ValueError):
        chunk_text("some text", chunk_size=chunk_size, overlap=overlap)


def test_chunk_document_tags_each_chunk_with_its_source():
    document = MissionDocument(
        id="nasa-smd-001",
        type=DocumentType.SCIENCE_REFERENCE,
        text="Step one. Step two. Step three.",
    )
    chunks = chunk_document(document, chunk_size=800, overlap=100)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.doc_id == "nasa-smd-001"
    assert chunk.doc_type == "science_reference"
    assert chunk.chunk_index == 0
    assert chunk.doc_text == document.text
    # domain defaults to "other" here since the document above never set one —
    # see test_chunk_document_carries_the_document_s_domain_onto_every_chunk
    # for a document that does.
    assert chunk.metadata() == {
        "doc_id": "nasa-smd-001",
        "doc_type": "science_reference",
        "chunk_index": 0,
        "doc_text": document.text,
        "domain": "other",
    }


def test_chunk_document_carries_full_doc_text_on_every_chunk():
    # A document long enough to split into several chunks — every chunk,
    # not just the first, should carry the *whole* original document in
    # `doc_text`, not just its own piece. This is what lets a retrieval
    # hit on any chunk reconstruct the full document for structured
    # extraction (see app.services.crisis and Chunk's docstring), without
    # a second lookup for the other chunks.
    text = " ".join(f"word{i}" for i in range(300))
    document = MissionDocument(id="nasa-smd-long", type=DocumentType.SCIENCE_REFERENCE, text=text)
    chunks = chunk_document(document, chunk_size=100, overlap=20)

    assert len(chunks) > 2
    for chunk in chunks:
        assert chunk.doc_text == text
        # doc_text is the full document; a chunk's own text is at most a
        # (usually strict) substring/piece of it.
        assert chunk.text != chunk.doc_text or len(chunks) == 1


def test_chunk_document_carries_the_document_s_domain_onto_every_chunk():
    document = MissionDocument(
        id="nasa-smd-dust-001",
        type=DocumentType.SCIENCE_REFERENCE,
        text=" ".join(f"word{i}" for i in range(300)),
        domain=Domain.SAHARAN_DUST,
    )
    chunks = chunk_document(document, chunk_size=100, overlap=20)

    assert len(chunks) > 2
    assert all(chunk.domain == "saharan_dust" for chunk in chunks)
    assert all(chunk.metadata()["domain"] == "saharan_dust" for chunk in chunks)


def test_chunk_documents_processes_a_batch_in_order():
    documents = [
        MissionDocument(id="a", type=DocumentType.SCIENCE_REFERENCE, text="alpha content"),
        MissionDocument(id="b", type=DocumentType.SCIENCE_REFERENCE, text="beta content"),
    ]
    chunks = chunk_documents(documents, chunk_size=800, overlap=100)

    assert [c.doc_id for c in chunks] == ["a", "b"]
