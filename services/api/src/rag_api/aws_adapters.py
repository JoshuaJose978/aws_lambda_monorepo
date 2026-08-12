from __future__ import annotations

from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from rag_api.repositories import ChatStore, DocumentStore


def chat_pk(owner_id: str) -> str:
    return f"USER#{owner_id}"


def conversation_sk(conversation_id: str) -> str:
    return f"CONVERSATION#{conversation_id}"


def message_sk(conversation_id: str, created_at: str, message_id: str) -> str:
    return f"MESSAGE#{conversation_id}#{created_at}#{message_id}"


def document_sk(document_id: str) -> str:
    return f"DOCUMENT#{document_id}"


class DynamoStores(ChatStore, DocumentStore):
    def __init__(self, dynamodb: Any, chat_table: str, documents_table: str) -> None:
        self._db, self._chat, self._documents = dynamodb, chat_table, documents_table
        self._serializer, self._deserializer = TypeSerializer(), TypeDeserializer()

    def _item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {key: self._serializer.serialize(value) for key, value in item.items()}

    def _value_map(self, values: dict[str, Any]) -> dict[str, Any]:
        return self._item(values)

    def _decode(self, item: dict[str, Any]) -> dict[str, object]:
        return {key: self._deserializer.deserialize(value) for key, value in item.items()}

    def create_conversation(
        self, owner_id: str, conversation_id: str, created_at: str
    ) -> dict[str, object]:
        item: dict[str, object] = {
            "PK": chat_pk(owner_id),
            "SK": conversation_sk(conversation_id),
            "id": conversation_id,
            "created_at": created_at,
            "updated_at": created_at,
        }
        self._db.put_item(
            TableName=self._chat,
            Item=self._item(item),
            ConditionExpression="attribute_not_exists(PK)",
        )
        return item

    def list_conversations(self, owner_id: str) -> list[dict[str, object]]:
        response = self._db.query(
            TableName=self._chat,
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
            ExpressionAttributeValues=self._value_map(
                {":pk": chat_pk(owner_id), ":sk": "CONVERSATION#"}
            ),
        )
        return [self._decode(item) for item in response.get("Items", [])]

    def conversation_owned(self, owner_id: str, conversation_id: str) -> bool:
        return "Item" in self._db.get_item(
            TableName=self._chat,
            Key=self._item({"PK": chat_pk(owner_id), "SK": conversation_sk(conversation_id)}),
        )

    def list_messages(self, owner_id: str, conversation_id: str) -> list[dict[str, object]]:
        response = self._db.query(
            TableName=self._chat,
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
            ExpressionAttributeValues=self._value_map(
                {":pk": chat_pk(owner_id), ":sk": f"MESSAGE#{conversation_id}#"}
            ),
        )
        return [self._decode(item) for item in response.get("Items", [])]

    def save_message(self, owner_id: str, conversation_id: str, message: dict[str, object]) -> None:
        item = {
            **message,
            "PK": chat_pk(owner_id),
            "SK": message_sk(conversation_id, str(message["created_at"]), str(message["id"])),
        }
        self._db.put_item(TableName=self._chat, Item=self._item(item))

    def create_document(self, owner_id: str, document: dict[str, object]) -> None:
        self._db.put_item(
            TableName=self._documents,
            Item=self._item(
                {**document, "PK": chat_pk(owner_id), "SK": document_sk(str(document["id"]))}
            ),
            ConditionExpression="attribute_not_exists(PK)",
        )

    def list_documents(self, owner_id: str) -> list[dict[str, object]]:
        response = self._db.query(
            TableName=self._documents,
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
            ExpressionAttributeValues=self._value_map(
                {":pk": chat_pk(owner_id), ":sk": "DOCUMENT#"}
            ),
        )
        return [self._decode(item) for item in response.get("Items", [])]

    def get_document(self, owner_id: str, document_id: str) -> dict[str, object] | None:
        item = self._db.get_item(
            TableName=self._documents,
            Key=self._item({"PK": chat_pk(owner_id), "SK": document_sk(document_id)}),
        ).get("Item")
        return self._decode(item) if item else None

    def mark_document_failed(
        self, owner_id: str, document_id: str, error_code: str, updated_at: str
    ) -> None:
        self._db.update_item(
            TableName=self._documents,
            Key=self._item({"PK": chat_pk(owner_id), "SK": document_sk(document_id)}),
            UpdateExpression=(
                "SET #status = :status, #error_code = :error_code, updated_at = :updated_at"
            ),
            ExpressionAttributeNames={"#status": "status", "#error_code": "error_code"},
            ExpressionAttributeValues=self._value_map(
                {
                    ":status": "failed",
                    ":error_code": error_code,
                    ":updated_at": updated_at,
                }
            ),
            ConditionExpression="attribute_exists(PK)",
        )


class S3UploadSigner:
    def __init__(self, s3: Any, bucket: str, expiry_seconds: int) -> None:
        self._s3, self._bucket, self._expiry = s3, bucket, expiry_seconds

    def put_url(self, key: str, content_type: str, size: int) -> str:
        # S3 presigned PUT URLs cannot reliably require Content-Length from browsers;
        # browsers forbid callers from setting that header themselves.
        del size
        return self._s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=self._expiry,
            HttpMethod="PUT",
        )
