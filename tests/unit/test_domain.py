import pytest
from rag_api.domain import UploadRequest, ValidationError, document_key, owner_from_claims


def test_owner_is_taken_only_from_jwt_sub() -> None:
    assert owner_from_claims({"sub": "user-1", "owner_id": "attacker"}) == "user-1"
    with pytest.raises(ValidationError):
        owner_from_claims({})


def test_upload_request_rejects_unsafe_or_unsupported_uploads() -> None:
    valid = {"filename": "notes.md", "content_type": "text/markdown", "size": 1, "sha256": "a" * 64}
    assert UploadRequest.from_payload(valid, 10).filename == "notes.md"
    valid["filename"] = "../private.txt"
    with pytest.raises(ValidationError):
        UploadRequest.from_payload(valid, 10)


def test_document_key_is_scoped_to_owner() -> None:
    assert document_key("owner", "doc", "file.txt") == "private/owner/doc/source/file.txt"
