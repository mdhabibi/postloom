"""Anthropic and Ollama backends against a fake transport."""

import json

import pytest

from postloom.adapters.llm.anthropic import AnthropicBackend
from postloom.adapters.llm.base import EmbeddingKind
from postloom.adapters.llm.chat import LlmChat
from postloom.adapters.llm.content import LlmContentExtractor
from postloom.adapters.llm.http import HttpResponse, JsonObject
from postloom.adapters.llm.ollama import OllamaBackend
from postloom.application.errors import ExtractionError, ProviderError, ProviderUnavailableError
from postloom.application.ports.chat import ChatMessage, Role
from postloom.application.ports.extraction import ExtractionRequest
from tests.llm_support import FakeTransport, Sleeps, metered, ok

ARTICLE: JsonObject = {
    "title": "T",
    "summary": "S",
    "topics": ["RAG"],
    "entities": ["Redis"],
    "series_name": None,
    "series_part": None,
    "body_markdown": "Body",
}


def request(text: str = "article") -> ExtractionRequest:
    return ExtractionRequest(article_text=text, post_text="post", allowed_topics=("RAG",))


# -- Anthropic ---------------------------------------------------------------------
def tool_answer(data: JsonObject, stop: str = "tool_use") -> HttpResponse:
    return ok(
        {
            "content": [{"type": "tool_use", "name": "article", "input": data}],
            "stop_reason": stop,
            "usage": {"input_tokens": 700, "output_tokens": 90, "cache_read_input_tokens": 300},
        }
    )


def anthropic(*responses: HttpResponse) -> tuple[AnthropicBackend, FakeTransport]:
    transport = FakeTransport(list(responses))
    return AnthropicBackend("sk-ant", transport=transport, sleep=Sleeps()), transport


def test_structured_output_uses_a_forced_tool() -> None:
    backend, transport = anthropic(tool_answer(ARTICLE))
    gateway, ledger = metered(backend)
    result = LlmContentExtractor(gateway, "claude-haiku-5-5").extract(request())
    assert result.entities == ("Redis",)

    call = transport.last
    assert call.url == "https://api.anthropic.com/v1/messages"
    assert call.headers == {"x-api-key": "sk-ant", "anthropic-version": "2023-06-01"}
    payload = call.payload
    assert payload["tool_choice"] == {"type": "tool", "name": "article"}
    assert payload["tools"][0]["input_schema"]["properties"]["topics"]["items"]["enum"] == ["RAG"]
    assert payload["max_tokens"] == 32_000
    assert payload["system"].startswith("You restore LinkedIn articles")
    (entry,) = ledger.month("2026-10")
    assert (entry.input_tokens, entry.output_tokens) == (1000, 90)  # cached input counts


def test_cut_off_tool_answers_are_reported() -> None:
    backend, _ = anthropic(tool_answer(ARTICLE, stop="max_tokens"))
    with pytest.raises(ExtractionError, match="cut off"):
        LlmContentExtractor(metered(backend)[0], "m").extract(request())


def test_chat_text_and_roles() -> None:
    backend, transport = anthropic(
        ok({"content": [{"type": "text", "text": "Use time splits."}], "usage": {}})
    )
    chat = LlmChat(metered(backend)[0], "claude-haiku-5-5")
    reply = chat.complete("sys", [ChatMessage(Role.USER, "q"), ChatMessage(Role.ASSISTANT, "a")])
    assert reply == "Use time splits."
    assert [m["role"] for m in transport.last.payload["messages"]] == ["user", "assistant"]


def test_a_refused_temperature_is_dropped_for_that_model() -> None:
    refused = HttpResponse(
        400, {"type": "error", "error": {"message": "temperature is not supported for this model"}}
    )
    text = ok({"content": [{"type": "text", "text": "ok"}]})
    backend, transport = anthropic(refused, text, text)
    for _ in range(2):
        backend.complete_text(
            "m", system="s", turns=[("user", "q")], temperature=0.3, max_output_tokens=9
        )
    assert [("temperature" in c.payload) for c in transport.calls] == [True, False, False]


def test_overloaded_529_is_retried() -> None:
    backend, transport = anthropic(
        HttpResponse(529, {"error": {"message": "Overloaded"}}), tool_answer(ARTICLE)
    )
    LlmContentExtractor(metered(backend)[0], "m").extract(request())
    assert len(transport.calls) == 2


def test_anthropic_has_no_embeddings() -> None:
    backend, _ = anthropic()
    with pytest.raises(ProviderError, match="local embeddings"):
        backend.embed("x", ["a"], kind=EmbeddingKind.QUERY, dimensions=None)


# -- Ollama --------------------------------------------------------------------------
def ollama_answer(content: str, reason: str = "stop") -> HttpResponse:
    return ok(
        {
            "message": {"role": "assistant", "content": content},
            "done": True,
            "done_reason": reason,
            "prompt_eval_count": 1500,
            "eval_count": 400,
        }
    )


def ollama(
    *responses: HttpResponse | OSError, context: int = 32_768
) -> tuple[OllamaBackend, FakeTransport]:
    transport = FakeTransport(list(responses))
    return OllamaBackend(context_limit=context, transport=transport, sleep=Sleeps()), transport


def test_ollama_sizes_the_context_and_sends_the_schema() -> None:
    backend, transport = ollama(ollama_answer(json.dumps(ARTICLE)))
    gateway, ledger = metered(backend)
    LlmContentExtractor(gateway, "qwen3:14b").extract(request("x" * 30_000))

    call = transport.last
    assert call.url == "http://localhost:11434/api/chat"
    payload = call.payload
    assert payload["stream"] is False
    assert payload["format"]["properties"]["topics"]["items"]["enum"] == ["RAG"]
    options = payload["options"]
    assert options["num_ctx"] == 32_768  # ~10k input + ~12k output, rounded up
    assert 10_000 < options["num_predict"] < 32_000
    entry = ledger.month("2026-10")[0]
    assert (entry.input_tokens, entry.output_tokens, entry.cost_usd) == (1500, 400, 0.0)


def test_texts_too_long_for_the_local_context_are_refused_before_sending() -> None:
    backend, transport = ollama(context=8192)
    with pytest.raises(ProviderError, match="Ollama context limit"):
        LlmContentExtractor(metered(backend)[0], "m").extract(request("x" * 40_000))
    assert transport.calls == []


def test_local_models_are_never_blocked_by_the_budget() -> None:
    backend, _ = ollama(ollama_answer("Fine."))
    gateway, _ = metered(backend, budget=0.0)
    chat = LlmChat(gateway, "llama")
    assert chat.complete("s", [ChatMessage(Role.USER, "q")]) == "Fine."


def test_ollama_not_running_says_how_to_start_it() -> None:
    backend, _ = ollama(OSError("Connection refused"), OSError("Connection refused"))
    with pytest.raises(ProviderUnavailableError, match="Is Ollama running"):
        backend.list_models()


def test_missing_ollama_model_suggests_pulling_it() -> None:
    backend, _ = ollama(
        HttpResponse(404, {"error": "model 'qwen3' not found, try pulling it first"})
    )
    with pytest.raises(ProviderError, match="ollama pull"):
        backend.complete_text(
            "qwen3", system="s", turns=[("user", "q")], temperature=0, max_output_tokens=9
        )


def test_ollama_lists_and_embeds() -> None:
    backend, transport = ollama(
        ok({"models": [{"name": "qwen3:14b"}, {"name": "nomic-embed-text:latest"}]}),
        ok({"embeddings": [[1.0, 0.0], [0.0, 1.0]], "prompt_eval_count": 6}),
    )
    assert backend.list_models() == ["nomic-embed-text:latest", "qwen3:14b"]
    reply = backend.embed(
        "nomic-embed-text", ["a", "b"], kind=EmbeddingKind.DOCUMENT, dimensions=None
    )
    assert reply.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert transport.last.payload == {"model": "nomic-embed-text", "input": ["a", "b"]}


def test_cut_off_local_answers_suggest_a_bigger_context() -> None:
    backend, _ = ollama(ollama_answer('{"title": "T"', reason="length"))
    with pytest.raises(ExtractionError, match="context limit"):
        LlmContentExtractor(metered(backend)[0], "m").extract(request())
