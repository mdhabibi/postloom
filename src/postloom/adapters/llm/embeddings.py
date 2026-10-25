"""EmbeddingProvider for providers that offer embeddings (Gemini, OpenAI, OpenRouter...).

Many embedding models were trained with a task marker in the text itself; using it
noticeably improves retrieval. The known conventions are applied here, per model family,
so backends only ever see final strings.

Vectors are L2-normalized, so a dot product is the cosine similarity whatever the model.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from postloom.adapters.llm.base import EmbeddingKind
from postloom.adapters.llm.gateway import LlmGateway
from postloom.application.ports.embeddings import DocumentText, Vector

BATCH_SIZE = 50


class RemoteEmbeddings:
    def __init__(
        self,
        gateway: LlmGateway,
        model: str,
        *,
        dimensions: int | None = None,
        space: str | None = None,
    ) -> None:
        self._gateway = gateway
        self._model = model
        self._dimensions = dimensions
        self._space = space or vector_space(gateway.provider, model, dimensions)

    @property
    def name(self) -> str:
        return self._space

    def embed_documents(self, documents: Sequence[DocumentText]) -> list[Vector]:
        texts = [document_text(self._model, d) for d in documents]
        return self._embed(texts, EmbeddingKind.DOCUMENT)

    def embed_query(self, query: str) -> Vector:
        return self._embed([query_text(self._model, query)], EmbeddingKind.QUERY)[0]

    def _embed(self, texts: list[str], kind: EmbeddingKind) -> list[Vector]:
        vectors: list[Vector] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            raw = self._gateway.embed(self._model, batch, kind=kind, dimensions=self._dimensions)
            vectors.extend(normalize(v) for v in raw)
        return vectors


def vector_space(provider: str, model: str, dimensions: int | None) -> str:
    """Stable name of a vector space; vectors from different spaces are never compared.

    Gemini keeps the bare ``model@dims`` name it always had, so existing indexes stay valid.
    """
    size = str(dimensions) if dimensions else "native"
    return f"{model}@{size}" if provider == "gemini" else f"{provider}:{model}@{size}"


def document_text(model: str, document: DocumentText) -> str:
    name = model.lower()
    if "gemini-embedding-2" in name:
        return f"title: {document.title or 'none'} | text: {document.text}"
    body = f"{document.title}\n\n{document.text}" if document.title else document.text
    if "nomic-embed" in name:
        return f"search_document: {body}"
    if "e5" in name.split("/")[-1].split("-"):
        return f"passage: {body}"
    return body


def query_text(model: str, query: str) -> str:
    name = model.lower()
    if "gemini-embedding-2" in name:
        return f"task: search result | query: {query}"
    if "nomic-embed" in name:
        return f"search_query: {query}"
    if "e5" in name.split("/")[-1].split("-"):
        return f"query: {query}"
    if "bge-" in name and "-en" in name:
        return f"Represent this sentence for searching relevant passages: {query}"
    return query


def normalize(vector: Sequence[float]) -> Vector:
    values = [float(x) for x in vector]
    norm = math.sqrt(sum(x * x for x in values))
    return [x / norm for x in values] if norm else values
