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
    CHAT_FALLBACK_MODELS,
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EXTRACTION_MODEL,
    GeminiClient,
)
from postloom.adapters.llm.gemini_chat import GeminiChat
from postloom.adapters.llm.gemini_embeddings import GeminiEmbeddings
from postloom.adapters.llm.gemini_extractor import GeminiContentExtractor
from postloom.adapters.llm.gemini_threads import GeminiThreadParser
from postloom.adapters.storage.database import SqliteDatabase
from postloom.adapters.storage.search import SqliteSearchIndex
from postloom.adapters.storage.sqlite import SqliteGraphRepository
from postloom.adapters.vault.markdown_vault import MarkdownVault
from postloom.application.errors import NotConfiguredError
from postloom.application.ports import (
    ChatModel,
    Clock,
    ContentExtractor,
    EmbeddingProvider,
    GraphRepository,
    SearchIndex,
    Vault,
)
from postloom.application.ports.thread_parser import ThreadParser
from postloom.application.use_cases import (
    AskQuestion,
    BrowseContent,
    DraftReply,
    GraphOverview,
    IndexArticle,
    IngestArticle,
    PeopleDirectory,
    PreviewComments,
    ReindexAll,
    ReviewLink,
    SaveComments,
    SearchContent,
    SeedTopics,
    SuggestLinks,
    UpdatePerson,
)
from postloom.config import read_config

HOME_ENV = "POSTLOOM_HOME"
GEMINI_KEY_ENVS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
EXTRACTION_MODEL_ENV = "POSTLOOM_EXTRACTION_MODEL"
EMBEDDING_MODEL_ENV = "POSTLOOM_EMBEDDING_MODEL"
CHAT_MODEL_ENV = "POSTLOOM_CHAT_MODEL"
REPLY_MODEL_ENV = "POSTLOOM_REPLY_MODEL"
OWNER_NAME_ENV = "POSTLOOM_OWNER_NAME"
MIN_SIMILARITY_ENV = "POSTLOOM_MIN_SIMILARITY"
RELATED_SIMILARITY_ENV = "POSTLOOM_RELATED_SIMILARITY"
DEFAULT_RELATED_SIMILARITY = 0.75
"""Article-to-article similarity (centroids of section embeddings) needed for a suggested
link. Whole articles in one field score higher than a query against a passage, so this is
stricter than the search cutoff. Calibrate with `postloom links --explain`."""
DEFAULT_MIN_SIMILARITY = 0.66
"""Calibrated for gemini-embedding-2 @768 on real articles: on-topic passages scored
0.72-0.73, a same-field but wrong-topic query 0.62, an unrelated query 0.51."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration. Use :meth:`load` to read the environment and config file."""

    home: Path = field(default_factory=lambda: _default_home())
    gemini_api_key: str | None = field(default_factory=lambda: _first_env(GEMINI_KEY_ENVS))
    extraction_model: str = field(
        default_factory=lambda: os.environ.get(EXTRACTION_MODEL_ENV) or DEFAULT_EXTRACTION_MODEL
    )
    embedding_model: str = field(
        default_factory=lambda: os.environ.get(EMBEDDING_MODEL_ENV) or DEFAULT_EMBEDDING_MODEL
    )
    chat_model: str = field(
        default_factory=lambda: os.environ.get(CHAT_MODEL_ENV) or DEFAULT_CHAT_MODEL
    )
    reply_model: str = field(
        default_factory=lambda: os.environ.get(REPLY_MODEL_ENV) or DEFAULT_CHAT_MODEL
    )
    """Model for reply drafts; worth setting to your strongest model."""
    min_similarity: float = field(
        default_factory=lambda: float(os.environ.get(MIN_SIMILARITY_ENV) or DEFAULT_MIN_SIMILARITY)
    )
    """Semantic matches below this cosine similarity are treated as unrelated."""
    related_similarity: float = field(
        default_factory=lambda: float(
            os.environ.get(RELATED_SIMILARITY_ENV) or DEFAULT_RELATED_SIMILARITY
        )
    )
    """Articles at least this similar get a suggested link."""
    owner_name: str = ""
    """The user's name as shown on LinkedIn, to recognise their own replies."""
    api_key_source: str = "environment"
    """Where the key came from: "environment", "config" or "missing"."""

    @classmethod
    def load(cls, home: Path | None = None) -> Settings:
        """Environment variables win; otherwise values saved in ``<home>/config.json``."""
        resolved = (home or _default_home()).expanduser()
        saved = read_config(resolved)
        env_key = _first_env(GEMINI_KEY_ENVS)
        saved_key = saved.get("gemini_api_key")
        key = env_key or (saved_key if isinstance(saved_key, str) and saved_key else None)
        source = "environment" if env_key else ("config" if key else "missing")

        def pick(env: str, name: str, default: str) -> str:
            value = os.environ.get(env) or saved.get(name)
            return value if isinstance(value, str) and value else default

        cutoff = os.environ.get(MIN_SIMILARITY_ENV) or saved.get("min_similarity")
        related = os.environ.get(RELATED_SIMILARITY_ENV) or saved.get("related_similarity")
        return cls(
            home=resolved,
            gemini_api_key=key,
            extraction_model=pick(
                EXTRACTION_MODEL_ENV, "extraction_model", DEFAULT_EXTRACTION_MODEL
            ),
            embedding_model=pick(EMBEDDING_MODEL_ENV, "embedding_model", DEFAULT_EMBEDDING_MODEL),
            chat_model=pick(CHAT_MODEL_ENV, "chat_model", DEFAULT_CHAT_MODEL),
            reply_model=pick(REPLY_MODEL_ENV, "reply_model", DEFAULT_CHAT_MODEL),
            min_similarity=float(cutoff) if cutoff else DEFAULT_MIN_SIMILARITY,
            related_similarity=float(related) if related else DEFAULT_RELATED_SIMILARITY,
            owner_name=pick(OWNER_NAME_ENV, "owner_name", ""),
            api_key_source=source,
        )

    def __repr__(self) -> str:  # never print the key
        key = "set" if self.gemini_api_key else "missing"
        return (
            f"Settings(home={self.home!s}, gemini_api_key={key}, "
            f"extraction_model={self.extraction_model}, embedding_model={self.embedding_model}, "
            f"chat_model={self.chat_model}, reply_model={self.reply_model})"
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
    chat: ChatModel | None = None
    thread_parser: ThreadParser | None = None
    reply_chat: ChatModel | None = None
    """Model for reply drafts; falls back to ``chat``."""
    min_similarity: float = 0.0
    related_similarity: float = DEFAULT_RELATED_SIMILARITY
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

    def preview_comments(self) -> PreviewComments:
        if self.thread_parser is None:
            raise NotConfiguredError("Reading comments needs a Gemini API key. Add it in settings.")
        return PreviewComments(self.thread_parser, self.repository)

    def save_comments(self) -> SaveComments:
        return SaveComments(self.repository, self.vault, self.clock)

    def people(self) -> PeopleDirectory:
        return PeopleDirectory(self.repository)

    def update_person(self) -> UpdatePerson:
        return UpdatePerson(self.repository, self.vault, self.clock)

    def browse(self) -> BrowseContent:
        return BrowseContent(self.repository)

    def ask_question(self) -> AskQuestion:
        if self.chat is None:
            raise NotConfiguredError("Chat needs a Gemini API key. Add one in settings.")
        return AskQuestion(
            self.chat, self.search_index, self.repository, self.embedder, self.min_similarity
        )

    def draft_reply(self) -> DraftReply:
        chat = self.reply_chat or self.chat
        if chat is None:
            raise NotConfiguredError("Reply drafts need a Gemini API key. Add one in settings.")
        return DraftReply(chat, self.repository)

    def suggest_links(self) -> SuggestLinks:
        return SuggestLinks(
            self.repository, self.search_index, self.embedder, self.clock, self.related_similarity
        )

    def review_link(self) -> ReviewLink:
        return ReviewLink(self.repository, self.vault, self.clock)

    def graph(self) -> GraphOverview:
        return GraphOverview(self.repository)

    def search(self) -> SearchContent:
        return SearchContent(self.search_index, self.repository, self.embedder, self.min_similarity)


def build_container(
    settings: Settings,
    *,
    extractor: ContentExtractor | None = None,
    embedder: EmbeddingProvider | None = None,
    chat: ChatModel | None = None,
    thread_parser: ThreadParser | None = None,
    reply_chat: ChatModel | None = None,
) -> Container:
    """Wire the app. Gemini fills in any provider not passed explicitly, if a key is set."""
    missing = None in (extractor, embedder, chat, thread_parser, reply_chat)
    if settings.gemini_api_key and missing:
        client = GeminiClient(settings.gemini_api_key)
        extractor = extractor or GeminiContentExtractor(client, settings.extraction_model)
        embedder = embedder or GeminiEmbeddings(client, settings.embedding_model)
        chat = chat or GeminiChat(client, settings.chat_model, CHAT_FALLBACK_MODELS)
        thread_parser = thread_parser or GeminiThreadParser(client, settings.extraction_model)
        reply_chat = reply_chat or GeminiChat(client, settings.reply_model, CHAT_FALLBACK_MODELS)
    database = SqliteDatabase(settings.index_path)
    return Container(
        repository=SqliteGraphRepository(database),
        search_index=SqliteSearchIndex(database),
        vault=MarkdownVault(settings.vault_dir),
        clock=SystemClock(),
        extractor=extractor,
        embedder=embedder,
        chat=chat,
        thread_parser=thread_parser,
        reply_chat=reply_chat,
        min_similarity=settings.min_similarity,
        related_similarity=settings.related_similarity,
        closers=(database.close,),
    )
