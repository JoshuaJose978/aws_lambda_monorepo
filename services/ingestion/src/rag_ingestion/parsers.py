from __future__ import annotations

from io import BytesIO

from docx import Document
from pypdf import PdfReader


class ParseError(ValueError):
    pass


def parse_document(data: bytes, content_type: str) -> str:
    if content_type in {"text/plain", "text/markdown"}:
        return data.decode("utf-8")
    if content_type == "application/pdf":
        return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return "\n".join(paragraph.text for paragraph in Document(BytesIO(data)).paragraphs)
    raise ParseError("unsupported_content_type")


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\x00", " ").split())
