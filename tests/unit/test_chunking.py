from rag_ingestion.chunking import chunk_text
from rag_ingestion.parsers import normalize_text, parse_document


def test_chunking_is_bounded_and_overlapping() -> None:
    chunks = chunk_text("one two three four five six", maximum_chars=12, overlap_chars=3)
    assert len(chunks) > 1
    assert all(len(chunk.content) <= 12 for chunk in chunks)
    assert chunks[0].index == 0


def test_text_parser_and_normalizer() -> None:
    assert normalize_text(parse_document(b"hello\n\n world", "text/plain")) == "hello world"
