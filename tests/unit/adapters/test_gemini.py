"""Gemini backend and the provider-neutral adapters on it, against a fake transport."""

import json
from typing import Any

import pytest

from postloom.adapters.llm.base import Turn
from postloom.adapters.llm.chat import LlmChat
from postloom.adapters.llm.content import LlmContentExtractor, LlmThreadParser
from postloom.adapters.llm.embeddings import RemoteEmbeddings
from postloom.adapters.llm.gemini import GeminiBackend, to_gemini_schema
from postloom.adapters.llm.http import CertificateError, HttpResponse, JsonObject
from postloom.adapters.llm.prompts import extraction_schema
from postloom.application.errors import (
    ExtractionError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from postloom.application.ports.chat import ChatMessage, Role
from postloom.application.ports.embeddings import DocumentText
from postloom.application.ports.extraction import ExtractionRequest
from postloom.application.ports.usage import Task
from tests.llm_support import FakeTransport, Sleeps, metered, ok

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
USAGE: JsonObject = {
    "promptTokenCount": 1200,
    "candidatesTokenCount": 300,
    "thoughtsTokenCount": 50,
}


def answer(payload: object, finish: str = "STOP") -> HttpResponse:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return ok(
        {
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish}
            ],
            "usageMetadata": USAGE,
        }
    )


def backend(*responses: HttpResponse | OSError) -> tuple[GeminiBackend, FakeTransport, Sleeps]:
    transport, sleeps = FakeTransport(list(responses)), Sleeps()
    return GeminiBackend("test-key", transport=transport, sleep=sleeps), transport, sleeps


def extractor(*responses: HttpResponse | OSError) -> tuple[LlmContentExtractor, FakeTransport]:
    subject, transport, _ = backend(*responses)
    gateway, _ = metered(subject)
    return LlmContentExtractor(gateway, "gemini-test"), transport


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
    schema = config["responseSchema"]
    assert schema["properties"]["topics"]["items"]["enum"] == list(TOPICS)
    assert schema["propertyOrdering"][-1] == "body_markdown"  # long body written last
    assert schema["properties"]["series_name"] == {"type": "STRING", "nullable": True}

    prompt = call.payload["contents"][0]["parts"][0]["text"]
    assert "<article>" in prompt and "<announcement_post>" in prompt
    assert "Preserve the author's wording" in call.payload["systemInstruction"]["parts"][0]["text"]


def test_json_schema_translation_drops_what_gemini_rejects() -> None:
    converted = to_gemini_schema(extraction_schema(("RAG",)))
    assert "additionalProperties" not in converted
    assert converted["type"] == "OBJECT"
    assert converted["properties"]["series_part"] == {"type": "INTEGER", "nullable": True}


def test_usage_counts_thinking_tokens_as_output() -> None:
    subject, _, _ = backend(answer(GOOD_ANSWER))
    gateway, ledger = metered(subject)
    LlmContentExtractor(gateway, "gemini-test").extract(request())
    (entry,) = ledger.month("2026-10")
    assert (entry.task, entry.input_tokens, entry.output_tokens) == (Task.EXTRACTION, 1200, 350)


def test_rate_limits_are_retried_with_backoff() -> None:
    subject, transport, sleeps = backend(
        HttpResponse(429, {}, retry_after=3.0), HttpResponse(503, {}), answer(GOOD_ANSWER)
    )
    LlmContentExtractor(metered(subject)[0], "m").extract(request())
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
    subject, _ = extractor(ok({"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(ExtractionError, match="SAFETY"):
        subject.extract(request())


def test_truncated_answer_is_not_retried() -> None:
    subject, transport = extractor(answer('{"title": "x", "body', finish="MAX_TOKENS"))
    with pytest.raises(ExtractionError, match="cut off"):
        subject.extract(request())
    assert len(transport.calls) == 1


def test_non_json_answer_gets_one_repair_attempt() -> None:
    subject, transport = extractor(answer("Sure! Here is your article:"), answer(GOOD_ANSWER))
    assert subject.extract(request()).title == GOOD_ANSWER["title"]
    retry = transport.calls[1].payload["contents"][0]["parts"][0]["text"]
    assert "Your previous answer could not be used: Gemini's answer was not a JSON object." in retry


def test_schema_violations_name_the_bad_fields_after_the_retry() -> None:
    bad = answer({**GOOD_ANSWER, "title": "", "series_part": 0})
    subject, transport = extractor(bad, bad)
    with pytest.raises(ExtractionError, match=r"title: .*series_part: "):
        subject.extract(request())
    assert len(transport.calls) == 2


def test_fenced_json_is_accepted() -> None:
    subject, _ = extractor(answer(f"```json\n{json.dumps(GOOD_ANSWER)}\n```"))
    assert subject.extract(request()).series_part == 3


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
    subject, _ = extractor(ok(body))
    assert subject.extract(request()).title == GOOD_ANSWER["title"]


def test_empty_key_is_rejected_up_front() -> None:
    with pytest.raises(ProviderAuthError):
        GeminiBackend("  ")


def test_certificate_failures_are_explained_and_not_retried() -> None:
    subject, transport = extractor(CertificateError("unable to get local issuer certificate"))
    with pytest.raises(ProviderUnavailableError, match="certificate"):
        subject.extract(request())
    assert len(transport.calls) == 1


def test_models_are_listed_without_the_prefix() -> None:
    subject, transport, _ = backend(
        ok({"models": [{"name": "models/gemini-3.8-flash"}, {"name": "models/gemini-embedding-2"}]})
    )
    assert subject.list_models() == ["gemini-3.8-flash", "gemini-embedding-2"]
    assert transport.last.method == "GET"


# -- embeddings ------------------------------------------------------------------
def embedding_reply(*vectors: list[float]) -> HttpResponse:
    return ok({"embeddings": [{"values": v} for v in vectors]})


def embeddings(transport: FakeTransport, model: str = "gemini-embedding-2") -> RemoteEmbeddings:
    gateway, _ = metered(GeminiBackend("k", transport=transport, sleep=Sleeps()))
    return RemoteEmbeddings(gateway, model, dimensions=2)


def test_embedding_2_uses_task_prefixes_and_normalizes() -> None:
    transport = FakeTransport([embedding_reply([3.0, 4.0]), embedding_reply([0.0, 2.0])])
    subject = embeddings(transport)

    (doc,) = subject.embed_documents([DocumentText("Data Leakage", "Split by time.")])
    query = subject.embed_query("leaky splits")

    assert doc == pytest.approx([0.6, 0.8])
    assert query == pytest.approx([0.0, 1.0])
    assert subject.name == "gemini-embedding-2@2"  # unchanged, so existing indexes stay valid
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
    embeddings(transport, "gemini-embedding-001").embed_query("q")
    assert transport.calls[0].payload["requests"][0]["taskType"] == "RETRIEVAL_QUERY"


def test_large_batches_are_split() -> None:
    transport = FakeTransport([embedding_reply(*[[1.0, 0.0]] * 50), embedding_reply([0.0, 1.0])])
    vectors = embeddings(transport).embed_documents(
        [DocumentText("t", f"chunk {i}") for i in range(51)]
    )
    assert len(vectors) == 51
    assert [len(c.payload["requests"]) for c in transport.calls] == [50, 1]


@pytest.mark.parametrize(
    "body",
    [{}, {"embeddings": []}, {"embeddings": [{"values": [1.0]}]}, {"embeddings": ["x"]}],
)
def test_malformed_embedding_responses_are_errors(body: JsonObject) -> None:
    with pytest.raises(ProviderError, match="embedding"):
        embeddings(FakeTransport([ok(body)])).embed_query("q")


# -- chat -------------------------------------------------------------------------
def text_reply(text: str) -> HttpResponse:
    body = {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
    return ok(body)


def busy() -> HttpResponse:
    return HttpResponse(503, {"error": {"message": "This model is experiencing high demand."}})


def chat(transport: FakeTransport, fallbacks: tuple[str, ...] = ()) -> LlmChat:
    gateway, _ = metered(GeminiBackend("k", transport=transport, sleep=Sleeps()))
    return LlmChat(gateway, "big", fallbacks=fallbacks)


def test_chat_sends_roles_and_returns_text() -> None:
    transport = FakeTransport([text_reply("  Split by time [1].  ")])
    subject = chat(transport)
    reply = subject.complete(
        "system", [ChatMessage(Role.USER, "q1"), ChatMessage(Role.ASSISTANT, "a1")]
    )
    assert reply == "Split by time [1]."
    assert subject.last_model == "big"
    roles = [c["role"] for c in transport.calls[0].payload["contents"]]
    assert roles == ["user", "model"]


def test_overloaded_chat_model_falls_back_to_the_next_model() -> None:
    transport = FakeTransport([busy(), busy(), busy(), text_reply("From the lite model.")])
    subject = chat(transport, ("lite",))
    assert subject.complete("system", [ChatMessage(Role.USER, "q")]) == "From the lite model."
    assert subject.last_model == "lite"
    assert [c.url.rsplit("/", 1)[1] for c in transport.calls] == [
        "big:generateContent",
        "big:generateContent",
        "big:generateContent",
        "lite:generateContent",
    ]


def test_all_models_busy_gives_one_clear_error() -> None:
    with pytest.raises(ProviderUnavailableError, match=r"\(big, lite\)"):
        chat(FakeTransport([busy() for _ in range(6)]), ("lite",)).complete(
            "system", [ChatMessage(Role.USER, "q")]
        )


def test_one_busy_model_keeps_the_providers_own_message() -> None:
    with pytest.raises(ProviderUnavailableError, match="Gemini is busy"):
        chat(FakeTransport([busy() for _ in range(3)])).complete(
            "system", [ChatMessage(Role.USER, "q")]
        )


def test_bad_key_is_not_masked_by_the_fallback() -> None:
    transport = FakeTransport([HttpResponse(403, {"error": {"message": "denied"}})])
    with pytest.raises(ProviderAuthError):
        chat(transport, ("lite",)).complete("system", [ChatMessage(Role.USER, "q")])
    assert len(transport.calls) == 1


# -- comment threads -----------------------------------------------------------------
def test_thread_parser_sends_owner_post_and_comments() -> None:
    reply = {
        "messages": [
            {"author_name": "Jane Example", "text": "Question?", "is_post_author": False},
            {"author_name": "Alex Author", "text": "Answer.", "is_post_author": True, "thread": 0},
        ]
    }
    transport = FakeTransport([answer(reply)])
    gateway, ledger = metered(GeminiBackend("k", transport=transport, sleep=Sleeps()))
    parsed = LlmThreadParser(gateway, "lite").parse(
        "Jane Example\n • 2nd\nQuestion?", "My post", "Alex Author"
    )

    assert [m.author_name for m in parsed.messages] == ["Jane Example", "Alex Author"]
    assert parsed.messages[1].thread == 0 and parsed.messages[1].is_post_author
    payload = transport.calls[0].payload
    prompt = payload["contents"][0]["parts"][0]["text"]
    assert prompt.startswith("Owner (the post's author): Alex Author")
    assert "<post>\nMy post\n</post>" in prompt and "<comments>" in prompt
    assert payload["generationConfig"]["temperature"] == 0.0
    assert "Interface words are noise" in payload["systemInstruction"]["parts"][0]["text"]
    assert ledger.month("2026-10")[0].task is Task.COMMENTS


def test_thread_parser_rejects_malformed_answers() -> None:
    bad = answer({"messages": [{"author_name": "", "text": "x"}]})
    transport = FakeTransport([bad, bad])
    gateway, _ = metered(GeminiBackend("k", transport=transport, sleep=Sleeps()))
    with pytest.raises(ExtractionError, match="couldn't split"):
        LlmThreadParser(gateway, "lite").parse("x", "post", None)


# -- thinking -------------------------------------------------------------------------
def thinking_of(call_payload: JsonObject) -> object:
    config: dict[str, object] = call_payload["generationConfig"]
    return config.get("thinkingConfig")


def test_the_thinking_level_follows_the_requested_effort() -> None:
    subject, transport, _ = backend(answer("Fine."), answer("Fine."), answer(GOOD_ANSWER))
    turns: list[Turn] = [("user", "Hi")]
    subject.complete_text("m", system="s", turns=turns, temperature=0, max_output_tokens=64)
    assert thinking_of(transport.last.payload) == {"thinkingLevel": "low"}
    subject.complete_text(
        "m", system="s", turns=turns, temperature=0, max_output_tokens=64, effort="high"
    )
    assert thinking_of(transport.last.payload) == {"thinkingLevel": "medium"}
    subject.complete_json(
        "m",
        system="s",
        prompt="p",
        schema=extraction_schema(TOPICS),
        schema_name="article",
        temperature=0,
        max_output_tokens=64,
    )
    assert thinking_of(transport.last.payload) == {"thinkingLevel": "low"}


def test_a_model_that_refuses_a_thinking_level_is_asked_without_one_from_then_on() -> None:
    refusal = HttpResponse(
        400, {"error": {"message": "Thinking level is not supported for this model."}}
    )
    subject, transport, _ = backend(refusal, answer("Fine."), answer("Again."))
    turns: list[Turn] = [("user", "Hi")]
    first = subject.complete_text(
        "old", system="s", turns=turns, temperature=0, max_output_tokens=64
    )
    assert first.text == "Fine."
    assert thinking_of(transport.calls[0].payload) == {"thinkingLevel": "low"}
    assert thinking_of(transport.calls[1].payload) is None
    subject.complete_text("old", system="s", turns=turns, temperature=0, max_output_tokens=64)
    assert len(transport.calls) == 3 and thinking_of(transport.last.payload) is None


def test_other_bad_requests_are_not_mistaken_for_a_thinking_refusal() -> None:
    subject, transport, _ = backend(HttpResponse(400, {"error": {"message": "Bad schema."}}))
    with pytest.raises(ProviderError, match="Bad schema"):
        subject.complete_text(
            "m", system="s", turns=[("user", "Hi")], temperature=0, max_output_tokens=64
        )
    assert len(transport.calls) == 1


def test_an_answer_lost_to_thinking_is_reported_not_returned_empty() -> None:
    empty = ok(
        {
            "candidates": [
                {"content": {"role": "model", "parts": []}, "finishReason": "MAX_TOKENS"}
            ],
            "usageMetadata": {"promptTokenCount": 10, "thoughtsTokenCount": 64},
        }
    )
    subject, _, _ = backend(empty)
    with pytest.raises(ExtractionError, match="thinking and wrote no answer"):
        subject.complete_text(
            "m", system="s", turns=[("user", "Hi")], temperature=0, max_output_tokens=64
        )


def test_retries_are_logged_so_a_slow_answer_can_be_explained(
    caplog: pytest.LogCaptureFixture,
) -> None:
    busy = HttpResponse(503, {"error": {"message": "This model is experiencing high demand."}})
    subject, _, sleeps = backend(busy, answer("Fine."))
    with caplog.at_level("WARNING", logger="postloom.llm"):
        subject.complete_text(
            "m", system="s", turns=[("user", "Hi")], temperature=0, max_output_tokens=64
        )
    (record,) = caplog.records
    assert record.getMessage() == (
        "Gemini answered HTTP 503 (This model is experiencing high demand.); retrying in 2s"
    )
    assert sleeps.seconds == [2.0]
