"""The OpenAI-compatible backend: request shapes, adaptations, usage and errors."""

import json

import pytest

from postloom.adapters.llm.base import EmbeddingKind
from postloom.adapters.llm.content import LlmContentExtractor
from postloom.adapters.llm.http import HttpResponse, JsonObject
from postloom.adapters.llm.openai_compat import (
    OpenAICompatibleBackend,
    OpenAICompatibleConfig,
    Quirks,
    adapt,
)
from postloom.adapters.llm.providers import build_backend
from postloom.application.errors import ExtractionError, ProviderAuthError, ProviderError
from postloom.application.ports.extraction import ExtractionRequest
from postloom.application.ports.usage import Task
from tests.llm_support import FakeTransport, Sleeps, metered, ok

ARTICLE: JsonObject = {
    "title": "T",
    "summary": "S",
    "topics": ["RAG"],
    "entities": [],
    "series_name": None,
    "series_part": None,
    "body_markdown": "Body",
}


def completion(content: str, finish: str = "stop", cost: float | None = None) -> HttpResponse:
    usage: JsonObject = {"prompt_tokens": 900, "completion_tokens": 120}
    if cost is not None:
        usage["cost"] = cost
    return ok(
        {
            "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": finish}
            ],
            "usage": usage,
        }
    )


def refused(message: str) -> HttpResponse:
    return HttpResponse(400, {"error": {"message": message, "type": "invalid_request_error"}})


def openai(*responses: HttpResponse) -> tuple[OpenAICompatibleBackend, FakeTransport]:
    transport = FakeTransport(list(responses))
    backend = build_backend("openai", api_key="sk-test", transport=transport)
    assert isinstance(backend, OpenAICompatibleBackend)
    return backend, transport


def request() -> ExtractionRequest:
    return ExtractionRequest(article_text="a", post_text="p", allowed_topics=("RAG",))


def test_openai_requests_use_reasoning_model_parameters() -> None:
    backend, transport = openai(completion(json.dumps(ARTICLE)))
    gateway, ledger = metered(backend)
    LlmContentExtractor(gateway, "gpt-5.6-luna").extract(request())

    call = transport.last
    assert call.url == "https://api.openai.com/v1/chat/completions"
    assert call.headers["Authorization"] == "Bearer sk-test"
    payload = call.payload
    assert "temperature" not in payload and "max_tokens" not in payload
    assert payload["max_completion_tokens"] == 32_000
    assert payload["reasoning_effort"] == "low"
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["name"] == "article"
    assert payload["messages"][0]["role"] == "system"
    (entry,) = ledger.month("2026-10")
    assert (entry.input_tokens, entry.output_tokens) == (900, 120)


def test_openrouter_reports_exact_cost_and_attribution() -> None:
    transport = FakeTransport([completion("Hi", cost=0.0042)])
    backend = build_backend("openrouter", api_key="or-key", transport=transport)
    gateway, ledger = metered(backend)
    assert (
        gateway.text(
            Task.CHAT,
            "google/gemini-3.8-flash",
            system="s",
            turns=[("user", "q")],
            temperature=0.3,
            max_output_tokens=100,
        )
        == "Hi"
    )
    payload = transport.last.payload
    assert payload["usage"] == {"include": True}
    assert transport.last.headers["X-Title"] == "postloom"
    assert ledger.month("2026-10")[0].cost_usd == pytest.approx(0.0042)


def test_refused_parameters_are_dropped_retried_and_remembered() -> None:
    config = OpenAICompatibleConfig("custom", "Server", "https://x.example/v1", "k", "check it")
    transport = FakeTransport(
        [
            refused("Unsupported parameter: 'max_tokens' is not supported with this model."),
            refused("Unsupported value: 'temperature' does not support 0.2 with this model."),
            refused("response_format json_schema is not supported by this model"),
            completion(json.dumps(ARTICLE)),
            completion(json.dumps(ARTICLE)),
        ]
    )
    backend = OpenAICompatibleBackend(config, transport=transport, sleep=Sleeps())
    gateway, _ = metered(backend)
    extractor = LlmContentExtractor(gateway, "m")
    extractor.extract(request())

    final = transport.calls[3].payload
    assert "max_tokens" not in final and final["max_completion_tokens"] == 32_000
    assert "temperature" not in final
    assert final["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in final["messages"][0]["content"]
    assert backend.quirks("m") == Quirks(
        token_param="max_completion_tokens", temperature=False, json_mode="object"
    )
    extractor.extract(request())
    assert len(transport.calls) == 5  # learned: no more refusals


def test_a_servers_output_limit_is_learned_from_its_error() -> None:
    quirks = adapt(Quirks(), "max_tokens must be less than or equal to `8192`", 32_000)
    assert quirks == Quirks(max_output_cap=8192)


def test_context_overflow_is_explained_not_retried() -> None:
    config = OpenAICompatibleConfig("custom", "Server", "https://x.example/v1", None, "")
    transport = FakeTransport(
        [refused("This model's maximum context length is 8192 tokens. You requested 40000.")]
    )
    backend = OpenAICompatibleBackend(config, transport=transport, sleep=Sleeps())
    with pytest.raises(ProviderError, match="too long for m's context window"):
        LlmContentExtractor(metered(backend)[0], "m").extract(request())
    assert len(transport.calls) == 1


def test_unrelated_bad_requests_are_not_retried() -> None:
    backend, transport = openai(refused("Invalid 'messages[1].content': string too long."))
    with pytest.raises(ProviderError, match="refused the request"):
        LlmContentExtractor(metered(backend)[0], "m").extract(request())
    assert len(transport.calls) == 1


def test_cut_off_json_is_reported() -> None:
    backend, _ = openai(completion('{"title": "T", "bo', finish="length"))
    with pytest.raises(ExtractionError, match="cut off"):
        LlmContentExtractor(metered(backend)[0], "m").extract(request())


def test_refusals_and_empty_answers_are_errors() -> None:
    body = {"choices": [{"message": {"content": None, "refusal": "I can't help"}}]}
    backend, _ = openai(ok(body), ok(body))
    with pytest.raises(ExtractionError, match="I can't help"):
        LlmContentExtractor(metered(backend)[0], "m").extract(request())


def test_bad_key_names_where_to_get_one() -> None:
    backend, _ = openai(HttpResponse(401, {"error": {"message": "Incorrect API key"}}))
    with pytest.raises(ProviderAuthError, match=r"platform\.openai\.com"):
        backend.list_models()


def test_out_of_credits_is_explained() -> None:
    transport = FakeTransport([HttpResponse(402, {"error": {"message": "Insufficient credits"}})])
    backend = build_backend("openrouter", api_key="k", transport=transport)
    with pytest.raises(ProviderError, match="out of credits"):
        backend.list_models()


def test_embeddings_keep_input_order() -> None:
    body = {
        "data": [
            {"index": 1, "embedding": [0.0, 1.0]},
            {"index": 0, "embedding": [1.0, 0.0]},
        ],
        "usage": {"prompt_tokens": 8},
    }
    backend, transport = openai(ok(body))
    reply = backend.embed(
        "text-embedding-3-small", ["a", "b"], kind=EmbeddingKind.DOCUMENT, dimensions=None
    )
    assert reply.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert reply.usage.input_tokens == 8
    assert transport.last.payload == {"model": "text-embedding-3-small", "input": ["a", "b"]}


def test_thinking_blocks_from_local_models_are_removed() -> None:
    config = OpenAICompatibleConfig(
        "custom", "LM Studio", "http://localhost:1234/v1", None, "", free=True
    )
    transport = FakeTransport([completion("<think>hmm</think>\nThe answer.")])
    backend = OpenAICompatibleBackend(config, transport=transport)
    reply = backend.complete_text(
        "m", system="s", turns=[("user", "q")], temperature=0, max_output_tokens=10
    )
    assert reply.text == "The answer."
    assert "Authorization" not in transport.last.headers


def test_custom_localhost_servers_are_free() -> None:
    local = build_backend("custom", api_key=None, base_url="http://localhost:1234/v1")
    remote = build_backend("custom", api_key="k", base_url="https://api.groq.com/openai/v1")
    assert (local.free, remote.free) == (True, False)
