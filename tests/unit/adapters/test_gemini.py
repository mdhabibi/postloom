"""Gemini client and extractor, tested against a fake transport (no network)."""

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from postloom.adapters.llm.gemini import GeminiClient
from postloom.adapters.llm.gemini_chat import GeminiChat
from postloom.adapters.llm.gemini_embeddings import GeminiEmbeddings
from postloom.adapters.llm.gemini_extractor import GeminiContentExtractor
from postloom.adapters.llm.http import CertificateError, HttpResponse, JsonObject
from postloom.application.errors import (
    ExtractionError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from postloom.application.ports.chat import ChatMessage, Role
from postloom.application.ports.embeddings import DocumentText
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


def test_certificate_failures_are_explained_and_not_retried() -> None:
    subject, transport = extractor(CertificateError("unable to get local issuer certificate"))
    with pytest.raises(ProviderUnavailableError, match="certificate"):
        subject.extract(request())
    assert len(transport.calls) == 1


# -- embeddings ------------------------------------------------------------------
def embedding_reply(*vectors: list[float]) -> HttpResponse:
    return HttpResponse(200, {"embeddings": [{"values": v} for v in vectors]})


def test_embedding_2_uses_task_prefixes_and_normalizes() -> None:
    transport = FakeTransport([embedding_reply([3.0, 4.0]), embedding_reply([0.0, 2.0])])
    embeddings = GeminiEmbeddings(GeminiClient("k", transport=transport), dimensions=2)

    (doc,) = embeddings.embed_documents([DocumentText("Data Leakage", "Split by time.")])
    query = embeddings.embed_query("leaky splits")

    assert doc == pytest.approx([0.6, 0.8])
    assert query == pytest.approx([0.0, 1.0])
    assert embeddings.name == "gemini-embedding-2@2"
    first = transport.calls[0]
    assert first.url.endswith("/models/gemini-embedding-2:batchEmbedContents")
    item = first.payload["requests"][0]
    assert item["content"]["parts"][0]["text"] == "title: Data Leakage | text: Split by time."
    assert item["outputDimensionality"] == 2
    assert "taskType" not in item
    query_item = transport.calls[1].payload["requests"][0]
    assert query_item["content"]["parts"][0]["text"] == "task: search result | query: leaky splits"


def test_older_embedding_models_use_task_type() -> None:
    transport = FakeTransport([embedding_reply([1.0, 0.0])])
    embeddings = GeminiEmbeddings(
        GeminiClient("k", transport=transport), model="gemini-embedding-001", dimensions=2
    )
    embeddings.embed_query("q")
    assert transport.calls[0].payload["requests"][0]["taskType"] == "RETRIEVAL_QUERY"


def test_large_batches_are_split() -> None:
    transport = FakeTransport([embedding_reply(*[[1.0, 0.0]] * 50), embedding_reply([0.0, 1.0])])
    embeddings = GeminiEmbeddings(GeminiClient("k", transport=transport), dimensions=2)
    vectors = embeddings.embed_documents([DocumentText("t", f"chunk {i}") for i in range(51)])
    assert len(vectors) == 51
    assert [len(c.payload["requests"]) for c in transport.calls] == [50, 1]


@pytest.mark.parametrize(
    "body",
    [{}, {"embeddings": []}, {"embeddings": [{"values": [1.0]}]}, {"embeddings": ["x"]}],
)
def test_malformed_embedding_responses_are_errors(body: JsonObject) -> None:
    transport = FakeTransport([HttpResponse(200, body)])
    embeddings = GeminiEmbeddings(GeminiClient("k", transport=transport), dimensions=2)
    with pytest.raises(ProviderError, match="embedding"):
        embeddings.embed_query("q")


# -- chat -------------------------------------------------------------------------
def text_reply(text: str) -> HttpResponse:
    body = {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
    return HttpResponse(200, body)


def busy() -> HttpResponse:
    return HttpResponse(503, {"error": {"message": "This model is experiencing high demand."}})


def test_chat_sends_roles_and_returns_text() -> None:
    transport = FakeTransport([text_reply("  Split by time [1].  ")])
    chat = GeminiChat(GeminiClient("k", transport=transport, sleep=Sleeps()), "big")
    answer = chat.complete(
        "system", [ChatMessage(Role.USER, "q1"), ChatMessage(Role.ASSISTANT, "a1")]
    )
    assert answer == "Split by time [1]."
    assert chat.last_model == "big"
    roles = [c["role"] for c in transport.calls[0].payload["contents"]]
    assert roles == ["user", "model"]


def test_overloaded_chat_model_falls_back_to_the_next_model() -> None:
    transport = FakeTransport([busy(), busy(), busy(), text_reply("From the lite model.")])
    chat = GeminiChat(GeminiClient("k", transport=transport, sleep=Sleeps()), "big", ["lite"])
    assert chat.complete("system", [ChatMessage(Role.USER, "q")]) == "From the lite model."
    assert chat.last_model == "lite"
    assert [c.url.rsplit("/", 1)[1] for c in transport.calls] == [
        "big:generateContent",
        "big:generateContent",
        "big:generateContent",
        "lite:generateContent",
    ]


def test_all_models_busy_gives_one_clear_error() -> None:
    transport = FakeTransport([busy() for _ in range(6)])
    chat = GeminiChat(GeminiClient("k", transport=transport, sleep=Sleeps()), "big", ["lite"])
    with pytest.raises(ProviderUnavailableError, match="big, lite all busy"):
        chat.complete("system", [ChatMessage(Role.USER, "q")])


def test_bad_key_is_not_masked_by_the_fallback() -> None:
    transport = FakeTransport([HttpResponse(403, {"error": {"message": "denied"}})])
    chat = GeminiChat(GeminiClient("k", transport=transport, sleep=Sleeps()), "big", ["lite"])
    with pytest.raises(ProviderAuthError):
        chat.complete("system", [ChatMessage(Role.USER, "q")])
    assert len(transport.calls) == 1
