from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: str
    filename: str
    chunk_index: int
    content: str


class EmbeddingProvider(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class ChatProvider(Protocol):
    def answer(self, question: str, chunks: Sequence[RetrievedChunk]) -> str: ...


class FakeProvider(EmbeddingProvider, ChatProvider):
    """Deterministic provider for tests and local development."""

    dimensions = 1024

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [
            [byte / 255 for byte in hashlib.shake_256(text.encode()).digest(self.dimensions)]
            for text in texts
        ]

    def answer(self, question: str, chunks: Sequence[RetrievedChunk]) -> str:
        if not chunks:
            return "I could not find relevant information in your documents."
        excerpts = " ".join(chunk.content for chunk in chunks[:2])
        return f"Based on your documents: {excerpts[:800]}"


class BedrockProvider(EmbeddingProvider, ChatProvider):
    def __init__(self, client: object, model_id: str, embedding_model_id: str) -> None:
        self._client = client
        self._model_id = model_id
        self._embedding_model_id = embedding_model_id

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        result: list[list[float]] = []
        for text in texts:
            response = self._client.invoke_model(  # type: ignore[attr-defined]
                modelId=self._embedding_model_id,
                body=json.dumps({"inputText": text, "dimensions": 1024, "normalize": True}),
            )
            result.append(json.loads(response["body"].read())["embedding"])
        return result

    def answer(self, question: str, chunks: Sequence[RetrievedChunk]) -> str:
        context = "\n\n".join(f"[{i + 1}] {chunk.content}" for i, chunk in enumerate(chunks))
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "text": "Answer only from this context. If it is empty, say that you "
                            f"could not find relevant information.\n\nContext:\n{context}\n\n"
                            f"Question: {question}"
                        }
                    ],
                }
            ],
            "inferenceConfig": {"maxTokens": 512, "temperature": 0.2},
        }
        response = self._client.invoke_model(  # type: ignore[attr-defined]
            modelId=self._model_id, body=json.dumps(payload)
        )
        return json.loads(response["body"].read())["output"]["message"]["content"][0]["text"]
