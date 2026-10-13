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
from postloom.adapters.storage.sqlite import SqliteGraphRepository
from postloom.adapters.vault.markdown_vault import MarkdownVault
from postloom.application.ports import Clock, ContentExtractor, GraphRepository, Vault
from postloom.application.use_cases import IngestArticle, SeedTopics

HOME_ENV = "POSTLOOM_HOME"


@dataclass(frozen=True, slots=True)
class Settings:
    home: Path = field(default_factory=lambda: _default_home())

    @property
    def vault_dir(self) -> Path:
        return self.home / "vault"

    @property
    def index_path(self) -> Path:
        return self.home / "index.db"


def _default_home() -> Path:
    override = os.environ.get(HOME_ENV)
    return Path(override).expanduser() if override else Path.home() / "Postloom"


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
            raise RuntimeError("No content extractor configured; add an LLM API key in setup.")
        return IngestArticle(self.extractor, self.repository, self.vault, self.clock)


def build_container(settings: Settings, extractor: ContentExtractor | None = None) -> Container:
    repository = SqliteGraphRepository(settings.index_path)
    return Container(
        repository=repository,
        vault=MarkdownVault(settings.vault_dir),
        clock=SystemClock(),
        extractor=extractor,
        closers=(repository.close,),
    )
