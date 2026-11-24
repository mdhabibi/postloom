"""The providers postloom supports, their defaults, and the backend factory.

Adding a provider that speaks the OpenAI format is one entry here. A provider with its
own protocol needs a backend module plus an entry. Nothing outside this package changes.

Prices are US dollars per million tokens, checked on PRICES_CHECKED. They only estimate
cost for the usage page and the budget (OpenRouter reports exact cost itself), and users
can override any of them in config.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

from postloom.adapters.llm.anthropic import AnthropicBackend
from postloom.adapters.llm.base import LlmBackend
from postloom.adapters.llm.gemini import GeminiBackend
from postloom.adapters.llm.http import HttpTransport
from postloom.adapters.llm.ollama import DEFAULT_CONTEXT_LIMIT, OllamaBackend
from postloom.adapters.llm.openai_compat import (
    OpenAICompatibleBackend,
    OpenAICompatibleConfig,
    Quirks,
)
from postloom.application.errors import NotConfiguredError
from postloom.application.use_cases.usage import Price

PRICES_CHECKED = "2026-10-25"
PROJECT_URL = "https://github.com/mdhabibi/postloom"


@dataclass(frozen=True, slots=True)
class DefaultModels:
    extraction: str = ""
    comments: str = ""
    chat: str = ""
    reply: str = ""
    """Reply drafts are what people read; worth a stronger model."""
    embedding: str = ""
    """Empty when the provider has no embeddings (postloom then embeds locally)."""
    chat_fallbacks: tuple[str, ...] = ()
    """Tried in order when the chat model is overloaded."""
    reading_fallbacks: tuple[str, ...] = ()
    """Tried in order when the model that reads articles, posts, comments and mentions
    is overloaded (a busy small model is common on free tiers)."""


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    id: str
    label: str
    description: str
    models: DefaultModels
    key: Literal["required", "optional", "none"] = "required"
    key_envs: tuple[str, ...] = ()
    key_url: str | None = None
    """Where to create an API key."""
    base_url: str | None = None
    base_url_editable: bool = False
    local: bool = False
    """Runs on this computer: free, private, and no key."""
    offers_embeddings: bool = True
    notes: tuple[str, ...] = field(default_factory=tuple[str, ...])

    @property
    def needs_key(self) -> bool:
        return self.key == "required"


PROVIDERS: dict[str, ProviderSpec] = {
    spec.id: spec
    for spec in (
        ProviderSpec(
            id="gemini",
            label="Google Gemini",
            description="Fast and cheap, with a free tier.",
            models=DefaultModels(
                extraction="gemini-3.5-flash-lite",
                comments="gemini-3.5-flash-lite",
                chat="gemini-3.8-flash",
                reply="gemini-3.8-flash",
                embedding="gemini-embedding-2",
                chat_fallbacks=("gemini-3.5-flash-lite",),
                reading_fallbacks=("gemini-3.8-flash",),
            ),
            key_envs=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            key_url="https://aistudio.google.com/apikey",
            notes=("Google may use free-tier requests to improve its models.",),
        ),
        ProviderSpec(
            id="anthropic",
            label="Anthropic Claude",
            description="Claude models; strongest for reply drafts in your voice.",
            models=DefaultModels(
                extraction="claude-haiku-5-5",
                comments="claude-haiku-5-5",
                chat="claude-haiku-5-5",
                reply="claude-sonnet-5-5",
            ),
            key_envs=("ANTHROPIC_API_KEY",),
            key_url="https://console.anthropic.com/settings/keys",
            offers_embeddings=False,
        ),
        ProviderSpec(
            id="openai",
            label="OpenAI",
            description="GPT models.",
            models=DefaultModels(
                extraction="gpt-5.6-luna",
                comments="gpt-5.6-luna",
                chat="gpt-5.6-luna",
                reply="gpt-5.6-terra",
                embedding="text-embedding-3-small",
            ),
            key_envs=("OPENAI_API_KEY",),
            key_url="https://platform.openai.com/api-keys",
            base_url="https://api.openai.com/v1",
        ),
        ProviderSpec(
            id="openrouter",
            label="OpenRouter",
            description="One key for hundreds of models from every provider; exact cost per call.",
            models=DefaultModels(
                extraction="google/gemini-3.5-flash-lite",
                comments="google/gemini-3.5-flash-lite",
                chat="google/gemini-3.8-flash",
                reply="google/gemini-3.8-flash",
                embedding="openai/text-embedding-3-small",
                chat_fallbacks=("google/gemini-3.5-flash-lite",),
                reading_fallbacks=("google/gemini-3.8-flash",),
            ),
            key_envs=("OPENROUTER_API_KEY",),
            key_url="https://openrouter.ai/keys",
            base_url="https://openrouter.ai/api/v1",
        ),
        ProviderSpec(
            id="ollama",
            label="Ollama (on this computer)",
            description="Free and fully private. Needs Ollama installed and a model pulled.",
            models=DefaultModels(),
            key="none",
            base_url="http://localhost:11434",
            base_url_editable=True,
            local=True,
            notes=(
                "Restoring long articles needs a capable model (14B+ parameters) and can take "
                "minutes on a laptop.",
            ),
        ),
        ProviderSpec(
            id="custom",
            label="Other OpenAI-compatible server",
            description="LM Studio, Groq, Mistral, DeepSeek, Together, vLLM and others.",
            models=DefaultModels(),
            key="optional",
            base_url="http://localhost:1234/v1",
            base_url_editable=True,
        ),
    )
}

PRICES: dict[str, Price] = {
    # Google (aistudio.google.com pricing; same rates via OpenRouter)
    "gemini-3.5-flash-lite": Price(0.30, 2.50),
    "gemini-3.8-flash": Price(0.75, 3.75),
    # Anthropic (Haiku 5.5: prompts up to 100k tokens, which covers postloom's)
    "claude-haiku-5-5": Price(0.10, 0.50),
    "claude-sonnet-5-5": Price(2.00, 10.00),
    # OpenAI
    "gpt-5.6-luna": Price(0.20, 1.20),
    "gpt-5.6-terra": Price(2.00, 12.00),
    "text-embedding-3-small": Price(0.02, 0.0),
    "text-embedding-3-large": Price(0.13, 0.0),
    # OpenRouter ids (OpenRouter also reports exact cost per call, which wins)
    "google/gemini-3.5-flash-lite": Price(0.30, 2.50),
    "google/gemini-3.8-flash": Price(0.75, 3.75),
    "openai/text-embedding-3-small": Price(0.02, 0.0),
}


def provider_spec(provider: str) -> ProviderSpec:
    try:
        return PROVIDERS[provider]
    except KeyError:
        known = ", ".join(PROVIDERS)
        raise NotConfiguredError(
            f"Unknown provider {provider!r}. Choose one of: {known}."
        ) from None


def build_backend(
    provider: str,
    *,
    api_key: str | None,
    base_url: str | None = None,
    ollama_context: int = DEFAULT_CONTEXT_LIMIT,
    transport: HttpTransport | None = None,
) -> LlmBackend:
    """A ready backend for ``provider``; raises NotConfiguredError if something's missing."""
    spec = provider_spec(provider)
    url = (base_url or spec.base_url or "").strip()
    if spec.needs_key and not (api_key or "").strip():
        raise NotConfiguredError(
            f"{spec.label} needs an API key. Create one at {spec.key_url} and add it in Settings."
        )
    key = (api_key or "").strip()
    if provider == "gemini":
        return GeminiBackend(key, transport=transport)
    if provider == "anthropic":
        return AnthropicBackend(key, transport=transport)
    if provider == "ollama":
        return OllamaBackend(base_url=url, context_limit=ollama_context, transport=transport)
    if not url:
        raise NotConfiguredError(f"{spec.label} needs a server address (base URL) in Settings.")
    return OpenAICompatibleBackend(_compatible_config(spec, url, key or None), transport=transport)


def _compatible_config(spec: ProviderSpec, url: str, key: str | None) -> OpenAICompatibleConfig:
    if spec.id == "openai":
        return OpenAICompatibleConfig(
            provider="openai",
            label="OpenAI",
            base_url=url,
            api_key=key,
            key_help=f"Check it in Settings, or create one at {spec.key_url}.",
            # Current OpenAI models reason: no temperature, max_completion_tokens.
            defaults=Quirks(
                token_param="max_completion_tokens", temperature=False, reasoning_effort=True
            ),
        )
    if spec.id == "openrouter":
        return OpenAICompatibleConfig(
            provider="openrouter",
            label="OpenRouter",
            base_url=url,
            api_key=key,
            key_help=f"Check it in Settings, or create one at {spec.key_url}.",
            headers={"HTTP-Referer": PROJECT_URL, "X-Title": "postloom"},
            report_cost=True,
        )
    local = is_local_url(url)
    return OpenAICompatibleConfig(
        provider="custom",
        label="The model server",
        base_url=url,
        api_key=key,
        key_help="Check the key and server address in Settings.",
        free=local,
        unreachable_help=(
            "Is the server running (for LM Studio: start the local server)?"
            if local
            else "Check the server address and your internet connection."
        ),
    )


def is_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")
