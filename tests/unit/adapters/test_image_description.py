"""Every provider receives the image in its own format, and the description comes back."""

from __future__ import annotations

import base64
import json

import pytest

from postloom.adapters.llm.anthropic import AnthropicBackend
from postloom.adapters.llm.base import LlmBackend
from postloom.adapters.llm.content import LlmImageDescriber
from postloom.adapters.llm.gemini import GeminiBackend
from postloom.adapters.llm.http import HttpResponse, JsonObject
from postloom.adapters.llm.ollama import OllamaBackend
from postloom.adapters.llm.providers import build_backend
from postloom.application.errors import ProviderError
from postloom.application.ports.usage import Task
from tests.llm_support import FakeTransport, Sleeps, metered, ok

PNG = b"\x89PNG fake image"
ENCODED = base64.b64encode(PNG).decode()
SEEN: JsonObject = {"description": "A latency chart.", "text_in_image": "p99: 120 ms"}


def describe(backend: LlmBackend) -> str:
    gateway, ledger = metered(backend)
    seen = LlmImageDescriber(gateway, "vision-model").describe(PNG, "image/png", "Caching post")
    (entry,) = ledger.month("2026-10")
    assert entry.task is Task.IMAGES
    return seen.description


def test_gemini_gets_the_image_inline() -> None:
    answer = ok({"candidates": [{"content": {"parts": [{"text": json.dumps(SEEN)}]}}]})
    transport = FakeTransport([answer])
    text = describe(GeminiBackend("k", transport=transport, sleep=Sleeps()))
    assert text == "A latency chart.\n\nText in the image: p99: 120 ms"
    parts = transport.last.payload["contents"][0]["parts"]
    assert parts[0] == {"inline_data": {"mime_type": "image/png", "data": ENCODED}}
    assert "Caching post" in parts[1]["text"]


def test_claude_gets_an_image_block() -> None:
    answer = ok({"content": [{"type": "tool_use", "name": "image", "input": SEEN}], "usage": {}})
    transport = FakeTransport([answer])
    describe(AnthropicBackend("k", transport=transport, sleep=Sleeps()))
    content = transport.last.payload["messages"][0]["content"]
    assert content[0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": ENCODED},
    }
    assert content[1]["type"] == "text"


def test_openai_compatible_servers_get_a_data_url() -> None:
    message = {"role": "assistant", "content": json.dumps(SEEN)}
    transport = FakeTransport([ok({"choices": [{"message": message, "finish_reason": "stop"}]})])
    describe(build_backend("openai", api_key="k", transport=transport))
    content = transport.last.payload["messages"][-1]["content"]
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{ENCODED}"},
    }


def ollama_with(
    capabilities: list[str], *more: HttpResponse
) -> tuple[OllamaBackend, FakeTransport]:
    transport = FakeTransport([ok({"capabilities": capabilities}), *more])
    return OllamaBackend(transport=transport, sleep=Sleeps()), transport


def test_ollama_sends_images_to_a_model_that_can_see() -> None:
    answer = ok({"message": {"content": json.dumps(SEEN)}, "done": True, "done_reason": "stop"})
    backend, transport = ollama_with(["completion", "vision"], answer)
    describe(backend)
    assert transport.calls[0].url.endswith("/api/show")
    assert transport.last.payload["messages"][-1]["images"] == [ENCODED]


def test_ollama_refuses_a_model_that_cannot_see_instead_of_letting_it_guess() -> None:
    backend, transport = ollama_with(["completion"])
    gateway, _ = metered(backend)
    with pytest.raises(ProviderError, match="may not be able to see images"):
        LlmImageDescriber(gateway, "qwen-text").describe(PNG, "image/png", "post")
    assert len(transport.calls) == 1  # nothing was sent to the model
