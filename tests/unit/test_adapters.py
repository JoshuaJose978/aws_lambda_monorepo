from rag_api.aws_adapters import chat_pk, conversation_sk, document_sk, message_sk
from rag_common.providers import FakeProvider, RetrievedChunk
from rag_ingestion.chunking import Chunk
from rag_ingestion.dynamodb import DynamoChunks, chunk_sk


def test_dynamodb_keys_are_owner_scoped_and_ordered() -> None:
    assert chat_pk("u") == "USER#u"
    assert conversation_sk("c") == "CONVERSATION#c"
    assert message_sk("c", "2024", "m") == "MESSAGE#c#2024#m"
    assert document_sk("d") == "DOCUMENT#d"


def test_fake_provider_is_deterministic_and_cites_context_in_answer() -> None:
    provider = FakeProvider()
    assert provider.embed(["same"]) == provider.embed(["same"])
    answer = provider.answer("question", [RetrievedChunk("d", "f", 0, "evidence")])
    assert "evidence" in answer


class VectorClient:
    def __init__(self) -> None:
        self.put_calls: list[dict[str, object]] = []

    def put_item(self, **kwargs: object) -> None:
        self.put_calls.append(kwargs)

    def search_vectors(self, **_: object) -> dict[str, object]:
        return {
            "SearchResults": [
                {
                    "Item": {
                        "document_id": {"S": "document"},
                        "filename": {"S": "notes.txt"},
                        "chunk_index": {"N": "0"},
                        "content": {"S": "owner-scoped evidence"},
                    }
                }
            ]
        }


def test_dynamo_chunks_use_owner_partitioned_vector_search() -> None:
    client = VectorClient()
    chunks = DynamoChunks(client, "documents", "ChunksByEmbedding")
    chunks.insert("owner", "document", "notes.txt", [Chunk(0, "text", "hash")], [[0.1] * 1024])
    assert chunk_sk("document", 2) == "CHUNK#document#000002"
    assert len(client.put_calls) == 1
    assert chunks.retrieve("owner", [0.1] * 1024) == [
        RetrievedChunk("document", "notes.txt", 0, "owner-scoped evidence")
    ]
