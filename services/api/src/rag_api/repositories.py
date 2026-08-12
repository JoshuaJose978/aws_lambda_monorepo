from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from rag_common.providers import RetrievedChunk


class ChatStore(Protocol):
    def create_conversation(
        self, owner_id: str, conversation_id: str, created_at: str
    ) -> dict[str, object]: ...
    def list_conversations(self, owner_id: str) -> list[dict[str, object]]: ...
    def conversation_owned(self, owner_id: str, conversation_id: str) -> bool: ...
    def list_messages(self, owner_id: str, conversation_id: str) -> list[dict[str, object]]: ...
    def save_message(
        self, owner_id: str, conversation_id: str, message: dict[str, object]
    ) -> None: ...


class DocumentStore(Protocol):
    def create_document(self, owner_id: str, document: dict[str, object]) -> None: ...
    def list_documents(self, owner_id: str) -> list[dict[str, object]]: ...
    def get_document(self, owner_id: str, document_id: str) -> dict[str, object] | None: ...


class ChunkRetriever(Protocol):
    def retrieve(
        self, owner_id: str, query_embedding: Sequence[float], limit: int = 5
    ) -> list[RetrievedChunk]: ...
