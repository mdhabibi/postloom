"""Gemini client and extractor, tested against a fake transport (no network)."""

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from postloom.adapters.llm.gemini import GeminiClient
from postloom.adapters.llm.gemini_extractor import GeminiContentExtractor
from postloom.adapters.llm.http import HttpResponse, JsonObject
from postloom.application.errors import (
    ExtractionError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from postloom.application.ports.extraction import ExtractionRequest

TOPICS = ("RAG", "AI Agents", "MLOps")
GOOD_ANSWER: JsonObject = {
    "title": "Measuring What Matters - Part 3",
    "body_markdown": "## Metrics\n\nHit rate.",
    "summary": "How to measure a semantic cache.",
    "topics": ["RAG", "AI Agents"],
    "entities": ["LangGraph", "Redis"],
    "series_name": "Semantic Caching for AI Agents",
    "series_part": 3,
}


def answer(payload: object, finish: str = "STOP") -> HttpResponse:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return HttpResponse(
        200,
        {
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish}
            ]
        },
    )


@dataclass
class Call:
    url: str
    payload: JsonObject
    headers: dict[str, str]


@dataclass
class FakeTransport:
    responses: list[HttpResponse | OSError]
    calls: list[Call] = field(default_factory=list[Call])

    def post_json(
        self, url: str, payload: JsonObject, headers: dict[str, str], timeout: float
    ) -> HttpResponse:
        self.calls.append(Call(url, payload, headers))
        response = self.responses.pop(0)
        if isinstance(response, OSError):
            raise response
        return response


@dataclass
class Sleeps:
    seconds: list[float] = field(default_factory=list[float])

    def __call__(self, value: float) -> None:
        self.seconds.append(value)


def extractor(*responses: HttpResponse | OSError) -> tuple[GeminiContentExtractor, FakeTransport]:
    transport = FakeTransport(list(responses))
    client = GeminiClient("test-key", transport=transport, sleep=Sleeps())
    return GeminiContentExtractor(client, "gemini-test"), transport


def request() -> ExtractionRequest:
    return ExtractionRequest(
        article_text="Measuring What Matters - Part 3In Parts 1 and 2...",
        post_text="Read the final part #RAG",
        allowed_topics=TOPICS,
    )


def test_successful_extraction_is_validated_into_extracted_content() -> None:
    subject, _ = extractor(answer(GOOD_ANSWER))
    result = subject.extract(request())
    assert result.title == "Measuring What Matters - Part 3"
    assert result.topics == ("RAG", "AI Agents")
    assert result.series_part == 3
    assert subject.name == "llm:gemini-test"


def test_request_shape_key_in_header_and_topics_as_enum() -> None:
    subject, transport = extractor(answer(GOOD_ANSWER))
    subject.extract(request())
    (call,) = transport.calls

    assert call.url.endswith("/models/gemini-test:generateContent")
    assert "test-key" not in call.url
    assert call.headers == {"x-goog-api-key": "test-key"}

    config: dict[str, Any] = call.payload["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    topics_schema = config["responseSchema"]["properties"]["topics"]["items"]
    assert topics_schema["enum"] == list(TOPICS)

    prompt = call.payload["contents"][0]["parts"][0]["text"]
    assert "<article>" in prompt and "<announcement_post>" in prompt
    assert "Preserve the author's wording" in call.payload["systemInstruction"]["parts"][0]["text"]


def test_rate_limits_are_retried_with_backoff() -> None:
    transport = FakeTransport(
        [HttpResponse(429, {}, retry_after=3.0), HttpResponse(503, {}), answer(GOOD_ANSWER)]
    )
    sleeps = Sleeps()
    client = GeminiClient("k", transport=transport, sleep=sleeps)
    GeminiContentExtractor(client, "m").extract(request())
    assert len(transport.calls) == 3
    assert sleeps.seconds == [3.0, 4.0]


def test_network_errors_are_retried_then_reported_plainly() -> None:
    subject, transport = extractor(OSError("down"), OSError("down"), OSError("down"))
    with pytest.raises(ProviderUnavailableError, match="internet connection"):
        subject.extract(request())
    assert len(transport.calls) == 3


def test_persistent_rate_limit_becomes_unavailable_error() -> None:
    subject, _ = extractor(*[HttpResponse(429, {}) for _ in range(3)])
    with pytest.raises(ProviderUnavailableError, match="try again"):
        subject.extract(request())


@pytest.mark.parametrize(
    "response",
    [
        HttpResponse(400, {"error": {"message": "API key not valid. Please pass a valid key."}}),
        HttpResponse(403, {"error": {"message": "Permission denied"}}),
    ],
)
def test_bad_keys_give_an_actionable_message(response: HttpResponse) -> None:
    subject, transport = extractor(response)
    with pytest.raises(ProviderAuthError, match=r"aistudio\.google\.com"):
        subject.extract(request())
    assert len(transport.calls) == 1  # never retried


def test_retired_model_says_so() -> None:
    subject, _ = extractor(HttpResponse(404, {"error": {"message": "models/x is not found"}}))
    with pytest.raises(ProviderError, match="retired"):
        subject.extract(request())


def test_blocked_prompt_is_an_extraction_error() -> None:
    subject, _ = extractor(HttpResponse(200, {"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(ExtractionError, match="SAFETY"):
        subject.extract(request())


def test_truncated_answer_is_reported_as_too_long() -> None:
    subject, _ = extractor(answer('{"title": "x", "body', finish="MAX_TOKENS"))
    with pytest.raises(ExtractionError, match="too long"):
        subject.extract(request())


def test_non_json_answer_is_an_extraction_error() -> None:
    subject, _ = extractor(answer("Sure! Here is your article:"))
    with pytest.raises(ExtractionError, match="not valid JSON"):
        subject.extract(request())


def test_schema_violations_name_the_bad_fields() -> None:
    subject, _ = extractor(answer({**GOOD_ANSWER, "title": "", "series_part": 0}))
    with pytest.raises(ExtractionError, match="title, series_part"):
        subject.extract(request())


def test_thinking_parts_are_ignored() -> None:
    body: JsonObject = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "let me think...", "thought": True},
                        {"text": json.dumps(GOOD_ANSWER)},
                    ]
                },
                "finishReason": "STOP",
            }
        ]
    }
    subject, _ = extractor(HttpResponse(200, body))
    assert subject.extract(request()).title == GOOD_ANSWER["title"]


def test_empty_key_is_rejected_up_front() -> None:
    with pytest.raises(ProviderAuthError):
        GeminiClient("  ")
