import pytest
from rag_common.config import ConfigurationError, Settings


def test_local_configuration_is_valid() -> None:
    settings = Settings.from_env(
        {
            "APP_ENV": "local",
            "AWS_ACCESS_KEY_ID": "local-key",
            "AWS_SECRET_ACCESS_KEY": "local-secret",
            "DYNAMODB_CHAT_TABLE": "chat",
            "DYNAMODB_DOCUMENTS_TABLE": "documents",
            "DYNAMODB_VECTOR_INDEX_NAME": "vectors",
            "DOCUMENT_BUCKET": "bucket",
            "MODEL_PROVIDER": "fake",
        }
    )
    assert settings.endpoint_url is None


def test_aws_configuration_rejects_local_endpoint() -> None:
    with pytest.raises(ConfigurationError):
        Settings.from_env(
            {
                "APP_ENV": "prod",
                "AWS_ENDPOINT_URL": "http://local",
                "DYNAMODB_CHAT_TABLE": "chat",
                "DYNAMODB_DOCUMENTS_TABLE": "documents",
                "DYNAMODB_VECTOR_INDEX_NAME": "vectors",
                "DOCUMENT_BUCKET": "bucket",
                "MODEL_PROVIDER": "fake",
            }
        )
