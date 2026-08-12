from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from rag_api.aws_adapters import chat_pk
from rag_common.providers import RetrievedChunk

from rag_ingestion.chunking import Chunk


def chunk_sk(document_id: str, chunk_index: int) -> str:
    return f"CHUNK#{document_id}#{chunk_index:06d}"


class DynamoChunks:
    """Stores owner-scoped chunks and delegates similarity ranking to DynamoDB."""

    def __init__(self, dynamodb: Any, table_name: str, vector_index_name: str) -> None:
        self._db = dynamodb
        self._table = table_name
        self._index = vector_index_name
        self._serializer = TypeSerializer()
        self._deserializer = TypeDeserializer()

    def _item(self, values: dict[str, object]) -> dict[str, Any]:
        return {key: self._serializer.serialize(value) for key, value in values.items()}

    def _decode(self, values: dict[str, Any]) -> dict[str, object]:
        return {key: self._deserializer.deserialize(value) for key, value in values.items()}

    def insert(
        self,
        owner_id: str,
        document_id: str,
        filename: str,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            self._db.put_item(
                TableName=self._table,
                Item=self._item(
                    {
                        "PK": chat_pk(owner_id),
                        "SK": chunk_sk(document_id, chunk.index),
                        "owner_id": owner_id,
                        "document_id": document_id,
                        "filename": filename,
                        "chunk_index": chunk.index,
                        "content": chunk.content,
                        "content_hash": chunk.content_hash,
                        "embedding": [Decimal(str(value)) for value in embedding],
                    }
                ),
                ConditionExpression="attribute_not_exists(PK)",
            )

    def retrieve(
        self, owner_id: str, embedding: Sequence[float], limit: int = 5
    ) -> list[RetrievedChunk]:
        response = self._db.search_vectors(
            TableName=self._table,
            IndexName=self._index,
            SearchVector=[{"N": str(value)} for value in embedding],
            SearchConditionExpression="owner_id = :owner_id",
            ExpressionAttributeValues={":owner_id": {"S": owner_id}},
            TopK=limit,
        )
        return [
            RetrievedChunk(
                str(item["Item"]["document_id"]["S"]),
                str(item["Item"]["filename"]["S"]),
                int(item["Item"]["chunk_index"]["N"]),
                str(item["Item"]["content"]["S"]),
            )
            for item in response.get("SearchResults", [])
        ]
