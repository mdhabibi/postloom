"""Test doubles for the application ports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
