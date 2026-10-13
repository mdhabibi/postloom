"""EmbeddingProvider backed by Gemini embeddings.

``gemini-embedding-2`` takes the retrieval task as a prefix inside the text instead of a
``taskType`` field; older models (``gemini-embedding-001``) use ``taskType``. Vectors are
always L2-normalized here so a dot product is the cosine similarity, whatever the model.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from postloom.adapters.llm.gemini import DEFAULT_EMBEDDING_MODEL, GeminiClient
from postloom.application.ports.embeddings import DocumentText, Vector

DEFAULT_DIMENSIONS = 768
_BATCH_SIZE = 50


class GeminiEmbeddings:
    def __init__(
        self,
        client: GeminiClient,
        model: str = DEFAULT_EMBEDDING_MODEL,
        dimensions: int = DEFAULT_DIMENSIONS,
    ) -> None:
        self._client = client
        self._model = model
        self._dimensions = dimensions
        self._prefixed = model.startswith("gemini-embedding-2")

    @property
    def name(self) -> str:
        return f"{self._model}@{self._dimensions}"

    def embed_documents(self, documents: Sequence[DocumentText]) -> list[Vector]:
        if self._prefixed:
            texts = [f"title: {d.title or 'none'} | text: {d.text}" for d in documents]
            task = None
        else:
            texts = [f"{d.title}\n\n{d.text}" if d.title else d.text for d in documents]
            task = "RETRIEVAL_DOCUMENT"
        return self._embed(texts, task)

    def embed_query(self, query: str) -> Vector:
        if self._prefixed:
            return self._embed([f"task: search result | query: {query}"], None)[0]
        return self._embed([query], "RETRIEVAL_QUERY")[0]

    def _embed(self, texts: list[str], task: str | None) -> list[Vector]:
        vectors: list[Vector] = []
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[start : start + _BATCH_SIZE]
            raw = self._client.embed_texts(
                self._model, batch, dimensions=self._dimensions, task_type=task
            )
            vectors.extend(_normalize(v) for v in raw)
        return vectors


def _normalize(vector: Vector) -> Vector:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector
