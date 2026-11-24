"""Test doubles for the application ports."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from postloom.adapters.llm.base import (
    EmbeddingKind,
    EmbeddingReply,
    Image,
    JsonReply,
    TextReply,
    Turn,
    Usage,
)
from postloom.adapters.llm.http import JsonObject
from postloom.application.ports.chat import ChatMessage
from postloom.application.ports.embeddings import DocumentText, Vector
from postloom.application.ports.extraction import (
    ExtractedContent,
    ExtractionRequest,
    FoundMentions,
    PostTopics,
)
from postloom.application.ports.media import ImageDescription
from postloom.application.ports.thread_parser import ParsedMessage, ParsedThread

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


@dataclass
class FakePostClassifier:
    """Chooses the given topics for every post, and records what it was asked."""

    topics: tuple[str, ...] = ("RAG",)
    requests: list[str] = field(default_factory=list[str])

    @property
    def name(self) -> str:
        return "llm:fake-posts"

    def classify(self, post_text: str, allowed_topics: tuple[str, ...]) -> PostTopics:
        self.requests.append(post_text)
        return PostTopics(topics=tuple(t for t in self.topics if t in allowed_topics))


@dataclass
class FakeImageDescriber:
    """Says the same thing about every image, and records what it was shown."""

    description: str = "A line chart of cache hit rate falling as traffic drifts."
    seen: list[tuple[bytes, str, str]] = field(default_factory=list[tuple[bytes, str, str]])

    def describe(self, image: bytes, mime: str, context: str) -> ImageDescription:
        self.seen.append((image, mime, context))
        return ImageDescription(self.description, "fake-vision")


@dataclass
class FakeMentionFinder:
    """Proposes the given mentions for every text, and records what it was asked."""

    found: FoundMentions = field(default_factory=FoundMentions)
    requests: list[tuple[str, tuple[str, ...], str | None]] = field(
        default_factory=list[tuple[str, tuple[str, ...], str | None]]
    )

    @property
    def name(self) -> str:
        return "llm:fake-mentions"

    def find(self, text: str, topics: tuple[str, ...], owner_name: str | None) -> FoundMentions:
        self.requests.append((text, topics, owner_name))
        return self.found


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


@dataclass
class FakeChat:
    """Answers with a canned reply and records what it was asked."""

    reply: str = "Use a time-ordered split [1]."
    calls: list[tuple[str, list[ChatMessage]]] = field(
        default_factory=list[tuple[str, list[ChatMessage]]]
    )

    @property
    def name(self) -> str:
        return "llm:fake-chat"

    def complete(self, system: str, messages: Sequence[ChatMessage]) -> str:
        self.calls.append((system, list(messages)))
        return self.reply

    @property
    def last_prompt(self) -> str:
        return self.calls[-1][1][-1].text


def caching_thread() -> ParsedThread:
    """What a good parser returns for ``fixtures/comments/caching_thread.txt``."""
    return ParsedThread(
        messages=(
            ParsedMessage(
                author_name="Jane Example",
                author_headline="Senior ML Engineer at Acme Analytics",
                text="How do you choose the distance threshold in practice?",
                posted_label="4h",
            ),
            ParsedMessage(
                author_name="Alex Author",
                author_headline="AI Engineer | Writing about LLM systems",
                is_post_author=True,
                text="@Jane Example I start from a labelled validation set.",
                posted_label="3h",
                thread=0,
            ),
            ParsedMessage(
                author_name="Jane Example",
                author_headline="Senior ML Engineer at Acme Analytics",
                text="And when traffic drifts? Do you re-tune it?",
                posted_label="2h",
                thread=0,
            ),
            ParsedMessage(
                author_name="Alex Author",
                is_post_author=True,
                text="Yes, weekly, with an LLM-as-a-judge sample of cache hits.",
                posted_label="1h",
                thread=0,
            ),
            ParsedMessage(
                author_name="John Sample",
                author_headline="Staff Engineer at Example Corp",
                text="Great series. Would love a part on cache invalidation.",
                posted_label="2h",
            ),
        )
    )


@dataclass
class FakeThreadParser:
    result: ParsedThread = field(default_factory=caching_thread)
    calls: list[tuple[str, str, str | None]] = field(
        default_factory=list[tuple[str, str, str | None]]
    )

    @property
    def name(self) -> str:
        return "llm:fake-threads"

    def parse(self, pasted: str, post_text: str, owner_name: str | None) -> ParsedThread:
        self.calls.append((pasted, post_text, owner_name))
        return self.result


@dataclass
class FakeBackend:
    """An LlmBackend without HTTP: canned JSON per schema, a fixed text reply, fixed usage.

    Drives the real gateway, metering, budget and provider-neutral adapters in tests.
    """

    json_replies: dict[str, dict[str, object]] = field(default_factory=dict[str, dict[str, object]])
    text_reply: str = "Use a time-ordered split [1]."
    usage: tuple[int, int] = (1000, 200)
    provider: str = "fake"
    free: bool = False
    models: list[str] = field(default_factory=lambda: ["fake-chat", "fake-small"])
    calls: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    """(kind, model) for every call: "json", "text" or "embed"."""
    images: list[Image] = field(default_factory=list[Image])
    """Every image sent with a prompt."""

    def complete_json(
        self,
        model: str,
        *,
        system: str,
        prompt: str,
        schema: JsonObject,
        schema_name: str,
        temperature: float,
        max_output_tokens: int,
        effort: str = "low",
        images: Sequence[Image] = (),
    ) -> JsonReply:
        self.calls.append(("json", model))
        self.images.extend(images)
        return JsonReply(dict(self.json_replies[schema_name]), self._usage())

    def complete_text(
        self,
        model: str,
        *,
        system: str,
        turns: Sequence[Turn],
        temperature: float,
        max_output_tokens: int,
        effort: str = "low",
    ) -> TextReply:
        self.calls.append(("text", model))
        return TextReply(self.text_reply, self._usage())

    def embed(
        self, model: str, texts: Sequence[str], *, kind: EmbeddingKind, dimensions: int | None
    ) -> EmbeddingReply:
        self.calls.append(("embed", model))
        embedder = FakeEmbedder()
        vectors = [embedder.embed_query(text) for text in texts]
        return EmbeddingReply(vectors, Usage(input_tokens=10 * len(texts)))

    def list_models(self) -> list[str]:
        return list(self.models)

    def _usage(self) -> Usage:
        return Usage(input_tokens=self.usage[0], output_tokens=self.usage[1])
