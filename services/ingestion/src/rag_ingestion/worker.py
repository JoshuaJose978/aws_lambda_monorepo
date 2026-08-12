from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import unquote_plus

import boto3
from boto3.dynamodb.types import TypeSerializer
from rag_api.aws_adapters import DynamoStores
from rag_api.domain import document_key
from rag_common.config import Settings
from rag_common.providers import BedrockProvider, FakeProvider

from rag_ingestion.chunking import chunk_text
from rag_ingestion.dynamodb import chunk_sk
from rag_ingestion.parsers import normalize_text, parse_document


class IngestionError(RuntimeError):
    pass


def clients(settings: Settings) -> tuple[Any, Any]:
    kwargs: dict[str, Any] = {"region_name": settings.region}
    if settings.endpoint_url:
        kwargs["endpoint_url"] = settings.endpoint_url
    return boto3.client("dynamodb", **kwargs), boto3.client("s3", **kwargs)


def _event_document(record: dict[str, Any]) -> tuple[str, str, str]:
    event = json.loads(record["body"])
    detail = event.get("detail", event)
    if "Records" in detail:
        source = detail["Records"][0]["s3"]
        key = unquote_plus(source["object"]["key"])
        parts = key.split("/", 4)
        if len(parts) != 5 or parts[0] != "private" or parts[3] != "source":
            raise IngestionError("invalid_document_key")
        return parts[1], parts[2], key
    return detail["owner_id"], detail["document_id"], unquote_plus(detail["key"])


def _provider(settings: Settings) -> FakeProvider | BedrockProvider:
    if settings.model_provider == "fake":
        return FakeProvider()
    return BedrockProvider(
        boto3.client("bedrock-runtime", region_name=settings.region),
        settings.bedrock_model_id or "",
        settings.embedding_model_id or "",
    )


def _av(values: dict[str, Any]) -> dict[str, Any]:
    serializer = TypeSerializer()
    return {key: serializer.serialize(value) for key, value in values.items()}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _progress_update(
    dynamodb: Any,
    table: str,
    owner_id: str,
    document_id: str,
    *,
    stage: str,
    percent: int,
    processed: int | None = None,
    total: int | None = None,
) -> None:
    # Best-effort: progress updates should never break ingestion.
    try:
        values: dict[str, Any] = {
            ":stage": stage,
            ":percent": int(max(0, min(100, percent))),
            ":updated_at": _now(),
        }
        update = "SET ingest_stage = :stage, ingest_percent = :percent, updated_at = :updated_at"
        if processed is not None:
            update += ", ingest_processed_chunks = :processed"
            values[":processed"] = int(processed)
        if total is not None:
            update += ", ingest_total_chunks = :total"
            values[":total"] = int(total)
        dynamodb.update_item(
            TableName=table,
            Key=_av({"PK": f"USER#{owner_id}", "SK": f"DOCUMENT#{document_id}"}),
            UpdateExpression=update,
            ExpressionAttributeValues=_av(values),
        )
    except Exception:
        return


def process_record(record: dict[str, Any], settings: Settings, dynamodb: Any, s3: Any) -> None:
    owner_id, document_id, key = _event_document(record)
    stores = DynamoStores(dynamodb, settings.chat_table, settings.documents_table)
    document = stores.get_document(owner_id, document_id)
    if not document:
        raise IngestionError("document_not_found")
    if document.get("status") == "ready":
        return
    if key != document.get("s3_key") or key != document_key(
        owner_id, document_id, str(document["filename"])
    ):
        raise IngestionError("invalid_document_key")
    # Conditional claim prevents duplicate SQS deliveries from processing concurrently.
    try:
        dynamodb.update_item(
            TableName=settings.documents_table,
            Key=_av({"PK": f"USER#{owner_id}", "SK": f"DOCUMENT#{document_id}"}),
            UpdateExpression="SET #status = :processing",
            ConditionExpression="#status = :pending",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues=_av({":pending": "pending", ":processing": "processing"}),
        )
    except dynamodb.exceptions.ConditionalCheckFailedException:
        return

    def _is_canceled() -> bool:
        current = stores.get_document(owner_id, document_id)
        return bool(
            current
            and current.get("status") == "failed"
            and current.get("error_code") == "canceled"
        )

    try:
        _progress_update(
            dynamodb,
            settings.documents_table,
            owner_id,
            document_id,
            stage="reading",
            percent=5,
            processed=0,
            total=0,
        )
        source = s3.get_object(Bucket=settings.document_bucket, Key=key)["Body"].read()
        if _is_canceled():
            return
        _progress_update(
            dynamodb,
            settings.documents_table,
            owner_id,
            document_id,
            stage="parsing",
            percent=10,
        )
        text = normalize_text(parse_document(source, str(document["content_type"])))
        if _is_canceled():
            return
        _progress_update(
            dynamodb,
            settings.documents_table,
            owner_id,
            document_id,
            stage="chunking",
            percent=15,
        )
        chunks = chunk_text(text)
        if _is_canceled():
            return

        total = len(chunks)
        _progress_update(
            dynamodb,
            settings.documents_table,
            owner_id,
            document_id,
            stage="embedding",
            percent=20,
            processed=0,
            total=total,
        )
        # Parsing stays independent from storage and AWS adapters.
        provider = _provider(settings)

        # Embed progressively so we can surface real progress.
        embeddings: list[list[float]] = []
        step = max(1, total // 50) if total else 1
        for i, chunk in enumerate(chunks):
            if _is_canceled():
                return
            embeddings.append(provider.embed([chunk.content])[0])
            done = i + 1
            if done == total or done % step == 0:
                percent = 20 + (50 * done // max(1, total))
                _progress_update(
                    dynamodb,
                    settings.documents_table,
                    owner_id,
                    document_id,
                    stage="embedding",
                    percent=percent,
                    processed=done,
                    total=total,
                )

        if _is_canceled():
            return
        _progress_update(
            dynamodb,
            settings.documents_table,
            owner_id,
            document_id,
            stage="storing",
            percent=75,
            processed=0,
            total=total,
        )

        # Insert chunks progressively (supports cancel + progress).
        serializer = TypeSerializer()
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            if _is_canceled():
                return
            dynamodb.put_item(
                TableName=settings.documents_table,
                Item={
                    k: serializer.serialize(v)
                    for k, v in {
                        "PK": f"USER#{owner_id}",
                        "SK": chunk_sk(document_id, chunk.index),
                        "owner_id": owner_id,
                        "document_id": document_id,
                        "filename": str(document["filename"]),
                        "chunk_index": chunk.index,
                        "content": chunk.content,
                        "content_hash": chunk.content_hash,
                        "embedding": [Decimal(str(value)) for value in embedding],
                    }.items()
                },
                ConditionExpression="attribute_not_exists(PK)",
            )

            done = i + 1
            if total and (done == total or done % step == 0):
                percent = 75 + (20 * done // max(1, total))
                _progress_update(
                    dynamodb,
                    settings.documents_table,
                    owner_id,
                    document_id,
                    stage="storing",
                    percent=percent,
                    processed=done,
                    total=total,
                )

        if _is_canceled():
            return
        dynamodb.update_item(
            TableName=settings.documents_table,
            Key=_av({"PK": f"USER#{owner_id}", "SK": f"DOCUMENT#{document_id}"}),
            UpdateExpression=(
                "SET #status = :ready, chunk_count = :count, ingest_stage = :stage, ingest_percent = :percent, updated_at = :updated_at"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues=_av(
                {
                    ":ready": "ready",
                    ":count": len(chunks),
                    ":stage": "done",
                    ":percent": 100,
                    ":updated_at": _now(),
                }
            ),
        )
    except Exception as exc:
        dynamodb.update_item(
            TableName=settings.documents_table,
            Key=_av({"PK": f"USER#{owner_id}", "SK": f"DOCUMENT#{document_id}"}),
            UpdateExpression=(
                "SET #status = :failed, error_code = :error, ingest_stage = :stage, updated_at = :updated_at"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues=_av(
                {
                    ":failed": "failed",
                    ":error": "ingestion_failed",
                    ":stage": "failed",
                    ":updated_at": _now(),
                }
            ),
        )
        raise IngestionError("ingestion_failed") from exc


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, list[dict[str, str]]]:
    settings = Settings.from_env()
    dynamodb, s3 = clients(settings)
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        try:
            process_record(record, settings, dynamodb, s3)
        except Exception:
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
