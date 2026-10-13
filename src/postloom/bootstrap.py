"""Composition root: the only place that knows which adapter implements which port.

Interfaces (CLI, web API) ask this module for ready-to-use use cases. Swapping an
implementation, e.g. Gemini for a local Ollama model, is a change here and nowhere else.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType

from postloom.adapters.clock import SystemClock
from postloom.adapters.llm.gemini import DEFAULT_EXTRACTION_MODEL, GeminiClient
from postloom.adapters.llm.gemini_extractor import GeminiContentExtractor
from postloom.adapters.storage.sqlite import SqliteGraphRepository
from postloom.adapters.vault.markdown_vault import MarkdownVault
from postloom.application.errors import NotConfiguredError
from postloom.application.ports import Clock, ContentExtractor, GraphRepository, Vault
from postloom.application.use_cases import IngestArticle, SeedTopics

HOME_ENV = "POSTLOOM_HOME"
GEMINI_KEY_ENVS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
EXTRACTION_MODEL_ENV = "POSTLOOM_EXTRACTION_MODEL"


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration. Read from the environment until the setup screen exists."""

    home: Path = field(default_factory=lambda: _default_home())
    gemini_api_key: str | None = field(default_factory=lambda: _first_env(GEMINI_KEY_ENVS))
    extraction_model: str = field(
        default_factory=lambda: os.environ.get(EXTRACTION_MODEL_ENV) or DEFAULT_EXTRACTION_MODEL
    )

    def __repr__(self) -> str:  # never print the key
        key = "set" if self.gemini_api_key else "missing"
        return f"Settings(home={self.home!s}, gemini_api_key={key}, model={self.extraction_model})"

    @property
    def vault_dir(self) -> Path:
        return self.home / "vault"

    @property
    def index_path(self) -> Path:
        return self.home / "index.db"


def _default_home() -> Path:
    override = os.environ.get(HOME_ENV)
    return Path(override).expanduser() if override else Path.home() / "Postloom"


def _first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


@dataclass(frozen=True, slots=True)
class Container:
    repository: GraphRepository
    vault: Vault
    clock: Clock
    extractor: ContentExtractor | None = None
    closers: tuple[Callable[[], None], ...] = ()
    """Resources to release on shutdown (database connections...)."""

    def close(self) -> None:
        for close in self.closers:
            close()

    def __enter__(self) -> Container:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def seed_topics(self) -> SeedTopics:
        return SeedTopics(self.repository, self.vault)

    def ingest_article(self) -> IngestArticle:
        if self.extractor is None:
            raise NotConfiguredError(
                "No Gemini API key found. Create one at aistudio.google.com, then run "
                "`export GEMINI_API_KEY=...` in this terminal and try again."
            )
        return IngestArticle(self.extractor, self.repository, self.vault, self.clock)


def build_container(settings: Settings, extractor: ContentExtractor | None = None) -> Container:
    if extractor is None and settings.gemini_api_key:
        client = GeminiClient(settings.gemini_api_key)
        extractor = GeminiContentExtractor(client, settings.extraction_model)
    repository = SqliteGraphRepository(settings.index_path)
    return Container(
        repository=repository,
        vault=MarkdownVault(settings.vault_dir),
        clock=SystemClock(),
        extractor=extractor,
        closers=(repository.close,),
    )
