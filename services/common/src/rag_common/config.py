from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigurationError(ValueError):
    """Raised when environment settings describe an unsafe deployment."""


def _required(name: str, values: dict[str, str]) -> str:
    value = values.get(name, "")
    if not value:
        raise ConfigurationError(f"{name} is required")
    return value


@dataclass(frozen=True)
class Settings:
    app_env: str
    region: str
    endpoint_url: str | None
    chat_table: str
    documents_table: str
    document_bucket: str
    vector_index_name: str
    model_provider: str
    max_upload_bytes: int
    presigned_upload_ttl_seconds: int
    bedrock_model_id: str | None
    embedding_model_id: str | None

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Settings:
        values = dict(os.environ if environ is None else environ)
        app_env = _required("APP_ENV", values)
        endpoint = values.get("AWS_ENDPOINT_URL") or None
        if app_env == "local":
            if endpoint:
                raise ConfigurationError(
                    "local uses AWS services directly and must not set AWS_ENDPOINT_URL"
                )
            _required("AWS_ACCESS_KEY_ID", values)
            _required("AWS_SECRET_ACCESS_KEY", values)
        elif app_env in {"dev", "integration", "prod"}:
            if endpoint:
                raise ConfigurationError("AWS environments must not set AWS_ENDPOINT_URL")
        else:
            raise ConfigurationError("APP_ENV must be local, dev, integration, or prod")
        provider = _required("MODEL_PROVIDER", values)
        if provider not in {"fake", "bedrock"}:
            raise ConfigurationError("MODEL_PROVIDER must be fake or bedrock")
        model_id = values.get("BEDROCK_MODEL_ID") or None
        embedding_model_id = values.get("EMBEDDING_MODEL_ID") or None
        if provider == "bedrock" and not (model_id and embedding_model_id):
            raise ConfigurationError("bedrock requires BEDROCK_MODEL_ID and EMBEDDING_MODEL_ID")
        return cls(
            app_env=app_env,
            region=values.get("AWS_REGION", "us-east-1"),
            endpoint_url=endpoint,
            chat_table=_required("DYNAMODB_CHAT_TABLE", values),
            documents_table=_required("DYNAMODB_DOCUMENTS_TABLE", values),
            document_bucket=_required("DOCUMENT_BUCKET", values),
            vector_index_name=_required("DYNAMODB_VECTOR_INDEX_NAME", values),
            model_provider=provider,
            max_upload_bytes=int(values.get("MAX_UPLOAD_BYTES", "10485760")),
            presigned_upload_ttl_seconds=int(values.get("PRESIGNED_UPLOAD_TTL_SECONDS", "900")),
            bedrock_model_id=model_id,
            embedding_model_id=embedding_model_id,
        )
