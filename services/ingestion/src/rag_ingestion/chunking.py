from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    index: int
    content: str
    content_hash: str


def chunk_text(text: str, maximum_chars: int = 1200, overlap_chars: int = 200) -> list[Chunk]:
    if maximum_chars <= 0 or not 0 <= overlap_chars < maximum_chars:
        raise ValueError("invalid chunk bounds")
    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + maximum_chars, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        content = text[start:end].strip()
        if content:
            chunks.append(Chunk(len(chunks), content, hashlib.sha256(content.encode()).hexdigest()))
        if end == len(text):
            break
        start = end - overlap_chars
    return chunks
