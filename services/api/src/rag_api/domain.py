from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

SUPPORTED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/markdown",
    "text/plain",
}
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,199}$")


class ValidationError(ValueError):
    pass


def owner_from_claims(claims: object) -> str:
    if not isinstance(claims, dict) or not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise ValidationError("authenticated subject is required")
    return claims["sub"]


def require_object(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValidationError("JSON body must be an object")
    return payload


def required_text(payload: object, name: str, maximum: int = 10000) -> str:
    value = require_object(payload).get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValidationError(f"{name} must be a non-empty string up to {maximum} characters")
    return value.strip()


@dataclass(frozen=True)
class UploadRequest:
    filename: str
    content_type: str
    size: int
    sha256: str

    @classmethod
    def from_payload(cls, payload: object, maximum_size: int) -> UploadRequest:
        body = require_object(payload)
        filename = required_text(body, "filename", 200)
        content_type = required_text(body, "content_type", 150)
        sha256 = required_text(body, "sha256", 64)
        size = body.get("size")
        if not SAFE_FILENAME.fullmatch(filename) or "/" in filename or "\\" in filename:
            raise ValidationError("filename is invalid")
        if content_type not in SUPPORTED_CONTENT_TYPES:
            raise ValidationError("content_type is unsupported")
        if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= maximum_size:
            raise ValidationError("size is invalid")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", sha256):
            raise ValidationError("sha256 is invalid")
        return cls(filename, content_type, size, sha256.lower())


def document_key(owner_id: str, document_id: str, filename: str) -> str:
    return f"private/{owner_id}/{document_id}/source/{filename}"


def new_id() -> str:
    return str(uuid.uuid4())


def now() -> str:
    return datetime.now(UTC).isoformat()
