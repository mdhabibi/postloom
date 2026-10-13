"""Test doubles for the application ports."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from postloom.application.ports.embeddings import DocumentText, Vector
from postloom.application.ports.extraction import ExtractedContent, ExtractionRequest

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(*parts: str) -> str:
    return FIXTURES.joinpath(*parts).read_text(encoding="utf-8")


@dataclass
class FixedClock:
    current: datetime = field(default_factory=lambda: datetime(2026, 10, 13, 9, 0, tzinfo=UTC))

    def now(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


@dataclass
class FakeExtractor:
    """Returns a canned result and records every request it received."""

    result: ExtractedContent
    requests: list[ExtractionRequest] = field(default_factory=list[ExtractionRequest])

    @property
    def name(self) -> str:
        return "llm:fake"

    def extract(self, request: ExtractionRequest) -> ExtractedContent:
        self.requests.append(request)
        return self.result


def part3_extraction(**overrides: object) -> ExtractedContent:
    """What a good extractor returns for the semantic-caching Part 3 fixture."""
    data: dict[str, object] = {
        "title": (
            "Measuring What Matters: Observability, Metrics, and Building a "
            "Semantic Caching Agent in LangGraph - Part 3"
        ),
        # A faithful restoration keeps all of the pasted text (the coverage check relies on it).
        "body_markdown": fixture_text("semantic_caching_part3", "article.txt"),
        "summary": "How to measure semantic cache quality and wire a cache into a LangGraph agent.",
        "topics": ("RAG", "AI Agents"),
        "entities": ("LangGraph", "Redis", "LLM-as-a-judge"),
        "series_name": "Semantic Caching for AI Agents",
        "series_part": 3,
    }
    data.update(overrides)
    return ExtractedContent.model_validate(data)


@dataclass
class FakeEmbedder:
    """Deterministic bag-of-words embeddings: texts sharing words get similar vectors.

    Good enough to test ranking logic without a model, and it records every call so tests
    can assert that unchanged chunks are not embedded twice.
    """

    dimensions: int = 256
    documents_embedded: int = 0
    queries_embedded: int = 0

    @property
    def name(self) -> str:
        return f"fake@{self.dimensions}"

    def embed_documents(self, documents: Sequence[DocumentText]) -> list[Vector]:
        self.documents_embedded += len(documents)
        return [self._vector(f"{d.title} {d.text}") for d in documents]

    def embed_query(self, query: str) -> Vector:
        self.queries_embedded += 1
        return self._vector(query)

    def _vector(self, text: str) -> Vector:
        vector = [0.0] * self.dimensions
        for word in re.findall(r"[a-z]{3,}", text.lower()):
            digest = hashlib.md5(word.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "little") % self.dimensions] += 1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]
