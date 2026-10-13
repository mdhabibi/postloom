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
from postloom.adapters.llm.gemini import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EXTRACTION_MODEL,
    GeminiClient,
)
from postloom.adapters.llm.gemini_embeddings import GeminiEmbeddings
from postloom.adapters.llm.gemini_extractor import GeminiContentExtractor
from postloom.adapters.storage.database import SqliteDatabase
from postloom.adapters.storage.search import SqliteSearchIndex
from postloom.adapters.storage.sqlite import SqliteGraphRepository
from postloom.adapters.vault.markdown_vault import MarkdownVault
from postloom.application.errors import NotConfiguredError
from postloom.application.ports import (
    Clock,
    ContentExtractor,
    EmbeddingProvider,
    GraphRepository,
    SearchIndex,
    Vault,
)
from postloom.application.use_cases import (
    IndexArticle,
    IngestArticle,
    ReindexAll,
    SearchContent,
    SeedTopics,
)

HOME_ENV = "POSTLOOM_HOME"
GEMINI_KEY_ENVS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
EXTRACTION_MODEL_ENV = "POSTLOOM_EXTRACTION_MODEL"
EMBEDDING_MODEL_ENV = "POSTLOOM_EMBEDDING_MODEL"
MIN_SIMILARITY_ENV = "POSTLOOM_MIN_SIMILARITY"
DEFAULT_MIN_SIMILARITY = 0.66
"""Calibrated for gemini-embedding-2 @768 on real articles: on-topic passages scored
0.72-0.73, a same-field but wrong-topic query 0.62, an unrelated query 0.51."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration. Read from the environment until the setup screen exists."""

    home: Path = field(default_factory=lambda: _default_home())
    gemini_api_key: str | None = field(default_factory=lambda: _first_env(GEMINI_KEY_ENVS))
    extraction_model: str = field(
        default_factory=lambda: os.environ.get(EXTRACTION_MODEL_ENV) or DEFAULT_EXTRACTION_MODEL
    )
    embedding_model: str = field(
        default_factory=lambda: os.environ.get(EMBEDDING_MODEL_ENV) or DEFAULT_EMBEDDING_MODEL
    )
    min_similarity: float = field(
        default_factory=lambda: float(os.environ.get(MIN_SIMILARITY_ENV) or DEFAULT_MIN_SIMILARITY)
    )
    """Semantic matches below this cosine similarity are treated as unrelated."""

    def __repr__(self) -> str:  # never print the key
        key = "set" if self.gemini_api_key else "missing"
        return (
            f"Settings(home={self.home!s}, gemini_api_key={key}, "
            f"extraction_model={self.extraction_model}, embedding_model={self.embedding_model})"
        )

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
    search_index: SearchIndex
    vault: Vault
    clock: Clock
    extractor: ContentExtractor | None = None
    embedder: EmbeddingProvider | None = None
    min_similarity: float = 0.0
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

    def index_article(self) -> IndexArticle:
        return IndexArticle(self.repository, self.search_index, self.embedder)

    def reindex_all(self) -> ReindexAll:
        return ReindexAll(self.repository, self.index_article())

    def search(self) -> SearchContent:
        return SearchContent(self.search_index, self.repository, self.embedder, self.min_similarity)


def build_container(
    settings: Settings,
    *,
    extractor: ContentExtractor | None = None,
    embedder: EmbeddingProvider | None = None,
) -> Container:
    """Wire the app. Gemini fills in any provider not passed explicitly, if a key is set."""
    if settings.gemini_api_key and (extractor is None or embedder is None):
        client = GeminiClient(settings.gemini_api_key)
        extractor = extractor or GeminiContentExtractor(client, settings.extraction_model)
        embedder = embedder or GeminiEmbeddings(client, settings.embedding_model)
    database = SqliteDatabase(settings.index_path)
    return Container(
        repository=SqliteGraphRepository(database),
        search_index=SqliteSearchIndex(database),
        vault=MarkdownVault(settings.vault_dir),
        clock=SystemClock(),
        extractor=extractor,
        embedder=embedder,
        min_similarity=settings.min_similarity,
        closers=(database.close,),
    )
