from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import boto3
from rag_common.config import Settings
from rag_common.providers import BedrockProvider, FakeProvider
from rag_ingestion.dynamodb import DynamoChunks

from rag_api.aws_adapters import DynamoStores, S3UploadSigner
from rag_api.domain import (
    UploadRequest,
    ValidationError,
    document_key,
    new_id,
    now,
    owner_from_claims,
    required_text,
)


def _response(status: int, body: dict[str, object]) -> dict[str, object]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json_dumps(body),
    }


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        # boto3's DynamoDB TypeDeserializer returns Decimal for numbers.
        # Make them JSON serializable.
        if value % 1 == 0:
            return int(value)
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def json_dumps(value: object) -> str:
    return json.dumps(value, default=_json_default)


def _error(status: int, code: str, message: str, request_id: str) -> dict[str, object]:
    return _response(status, {"code": code, "message": message, "request_id": request_id})


def _event_body(event: dict[str, Any]) -> object:
    body = event.get("body") or "{}"
    return json.loads(body) if isinstance(body, str) else body


def _provider(
    settings: Settings, client_args: Mapping[str, object]
) -> FakeProvider | BedrockProvider:
    if settings.model_provider == "fake":
        return FakeProvider()
    return BedrockProvider(
        boto3.client("bedrock-runtime", **client_args),
        settings.bedrock_model_id or "",
        settings.embedding_model_id or "",
    )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, object]:
    request_id = getattr(context, "aws_request_id", "unknown")
    try:
        claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims")
        try:
            owner_id = owner_from_claims(claims)
        except ValidationError:
            return _error(401, "unauthorized", "Valid token required", request_id)
        settings = Settings.from_env()
        client_args = {"region_name": settings.region}
        if settings.endpoint_url:
            client_args["endpoint_url"] = settings.endpoint_url
        dynamodb = boto3.client("dynamodb", **client_args)
        stores = DynamoStores(dynamodb, settings.chat_table, settings.documents_table)
        method = event.get("requestContext", {}).get("http", {}).get("method")
        path = event.get("rawPath", "")
        if method == "GET" and path == "/me":
            return _response(200, {"sub": owner_id})
        if method == "GET" and path == "/conversations":
            return _response(200, {"items": stores.list_conversations(owner_id)})
        if method == "POST" and path == "/conversations":
            conversation_id, created_at = new_id(), now()
            return _response(201, stores.create_conversation(owner_id, conversation_id, created_at))
        conversation_id = event.get("pathParameters", {}).get("id")
        if (
            isinstance(conversation_id, str)
            and path == f"/conversations/{conversation_id}/messages"
        ):
            if not stores.conversation_owned(owner_id, conversation_id):
                return _error(404, "not_found", "Conversation not found", request_id)
            if method == "GET":
                return _response(200, {"items": stores.list_messages(owner_id, conversation_id)})
            if method == "POST":
                text = required_text(_event_body(event), "text")
                provider = _provider(settings, client_args)
                user_message: dict[str, object] = {
                    "id": new_id(),
                    "role": "user",
                    "text": text,
                    "citations": [],
                    "created_at": now(),
                }
                stores.save_message(owner_id, conversation_id, user_message)
                chunks = DynamoChunks(
                    dynamodb, settings.documents_table, settings.vector_index_name
                ).retrieve(owner_id, provider.embed([text])[0])
                citations = [
                    {
                        "document_id": chunk.document_id,
                        "filename": chunk.filename,
                        "chunk_index": chunk.chunk_index,
                        "excerpt": chunk.content[:500],
                    }
                    for chunk in chunks
                ]
                answer_message: dict[str, object] = {
                    "id": new_id(),
                    "role": "assistant",
                    "text": provider.answer(text, chunks),
                    "citations": citations,
                    "model": settings.model_provider,
                    "created_at": now(),
                }
                stores.save_message(owner_id, conversation_id, answer_message)
                return _response(
                    201, {"user_message": user_message, "assistant_message": answer_message}
                )
        if method == "POST" and path == "/documents/upload-url":
            upload = UploadRequest.from_payload(_event_body(event), settings.max_upload_bytes)
            document_id, created_at = new_id(), now()
            key = document_key(owner_id, document_id, upload.filename)
            document: dict[str, object] = {
                "id": document_id,
                "filename": upload.filename,
                "content_type": upload.content_type,
                "size": upload.size,
                "sha256": upload.sha256,
                "s3_key": key,
                "status": "pending",
                "created_at": created_at,
                "updated_at": created_at,
                "chunk_count": 0,
            }
            stores.create_document(owner_id, document)
            s3 = boto3.client("s3", **client_args)
            url = S3UploadSigner(
                s3, settings.document_bucket, settings.presigned_upload_ttl_seconds
            ).put_url(key, upload.content_type, upload.size)
            return _response(201, {"document": document, "upload_url": url})
        if method == "GET" and path == "/documents":
            return _response(200, {"items": stores.list_documents(owner_id)})
        document_id = event.get("pathParameters", {}).get("id")
        path_parts = path.split("/")
        if (
            isinstance(document_id, str)
            and len(path_parts) >= 3
            and path_parts[1] == "documents"
            and path_parts[2] == document_id
        ):
            if method == "GET" and len(path_parts) == 3:
                fetched_document = stores.get_document(owner_id, document_id)
                return (
                    _response(200, fetched_document)
                    if fetched_document
                    else _error(404, "not_found", "Document not found", request_id)
                )
            if method == "POST" and len(path_parts) == 4 and path_parts[3] == "cancel":
                if not stores.get_document(owner_id, document_id):
                    return _error(404, "not_found", "Document not found", request_id)
                stores.mark_document_failed(owner_id, document_id, "canceled", now())
                return _response(200, {"status": "canceled"})
        return _error(404, "not_found", "Route not found", request_id)
    except ValidationError as exc:
        return _error(400, "validation_error", str(exc), request_id)
    except json.JSONDecodeError:
        return _error(400, "validation_error", "Invalid JSON body", request_id)
    except Exception:
        print(
            f"internal_error request_id={request_id}\n{traceback.format_exc()}",
            file=sys.stderr,
            flush=True,
        )
        return _error(500, "internal_error", "Unexpected server error", request_id)
