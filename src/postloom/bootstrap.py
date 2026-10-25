"""Composition root: the only place that knows which adapter implements which port.

Interfaces (CLI, web API) ask this module for ready-to-use use cases. Choosing a provider
is a setting; the matching backend is built here and every model-backed port (extractor,
thread parser, chat, reply drafts, embeddings) runs on it through one metered gateway.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType

from postloom.adapters.clock import SystemClock
from postloom.adapters.llm.base import LlmBackend
from postloom.adapters.llm.chat import LlmChat
from postloom.adapters.llm.content import LlmContentExtractor, LlmThreadParser
from postloom.adapters.llm.embeddings import RemoteEmbeddings, vector_space
from postloom.adapters.llm.gateway import LlmGateway
from postloom.adapters.llm.local_embeddings import LocalEmbeddings, local_embeddings_installed
from postloom.adapters.llm.providers import PRICES, build_backend
from postloom.adapters.storage.database import SqliteDatabase
from postloom.adapters.storage.search import SqliteSearchIndex
from postloom.adapters.storage.sqlite import SqliteGraphRepository
from postloom.adapters.storage.usage import SqliteUsageLedger
from postloom.adapters.vault.markdown_vault import MarkdownVault
from postloom.application.errors import NotConfiguredError
from postloom.application.ports import (
    ChatModel,
    Clock,
    ContentExtractor,
    EmbeddingProvider,
    GraphRepository,
    SearchIndex,
    UsageLedger,
    Vault,
)
from postloom.application.ports.thread_parser import ThreadParser
from postloom.application.ports.usage import Task
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
from postloom.application.use_cases.usage import BudgetPolicy, PriceBook, UsageReport
from postloom.settings import Settings

__all__ = ["Container", "Settings", "build_container", "setup_hint"]

REPLY_MAX_OUTPUT = 2048


def setup_hint(settings: Settings) -> str:
    """What to do next when a model-backed feature isn't available yet."""
    spec = settings.spec
    if spec is None:
        return (
            "postloom isn't connected to a model yet. Start the app (uv run postloom start), "
            "open Settings and choose a provider."
        )
    if spec.needs_key and not settings.api_key:
        where = f" Create one at {spec.key_url}." if spec.key_url else ""
        return (
            f"{spec.label} needs an API key.{where} Save it in the app's Settings (every "
            f"command uses it), or set {spec.key_envs[0] if spec.key_envs else 'it'} in this "
            "terminal."
        )
    return f"Choose the models to use with {spec.label} in Settings."


@dataclass(frozen=True, slots=True)
class Container:
    repository: GraphRepository
    search_index: SearchIndex
    vault: Vault
    clock: Clock
    usage_ledger: UsageLedger | None = None
    gateway: LlmGateway | None = None
    extractor: ContentExtractor | None = None
    embedder: EmbeddingProvider | None = None
    chat: ChatModel | None = None
    thread_parser: ThreadParser | None = None
    reply_chat: ChatModel | None = None
    """Model for reply drafts; falls back to ``chat``."""
    min_similarity: float = 0.0
    related_similarity: float = 0.75
    monthly_budget_usd: float | None = None
    not_configured: str = "Connect a model provider in Settings first."
    """Shown when a model-backed feature is used before setup."""
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

    def _needs(self, port: object | None) -> None:
        if port is None:
            raise NotConfiguredError(self.not_configured)

    def seed_topics(self) -> SeedTopics:
        return SeedTopics(self.repository, self.vault)

    def ingest_article(self) -> IngestArticle:
        self._needs(self.extractor)
        assert self.extractor is not None
        return IngestArticle(self.extractor, self.repository, self.vault, self.clock)

    def index_article(self) -> IndexArticle:
        return IndexArticle(self.repository, self.search_index, self.embedder)

    def reindex_all(self) -> ReindexAll:
        return ReindexAll(self.repository, self.index_article())

    def preview_comments(self) -> PreviewComments:
        self._needs(self.thread_parser)
        assert self.thread_parser is not None
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
        self._needs(self.chat)
        assert self.chat is not None
        return AskQuestion(
            self.chat, self.search_index, self.repository, self.embedder, self.min_similarity
        )

    def draft_reply(self) -> DraftReply:
        chat = self.reply_chat or self.chat
        self._needs(chat)
        assert chat is not None
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

    def usage(self) -> UsageReport:
        if self.usage_ledger is None:
            raise NotConfiguredError("Usage tracking isn't available in this setup.")
        return UsageReport(self.usage_ledger, self.clock, self.monthly_budget_usd)


def _default_embedder(settings: Settings, gateway: LlmGateway | None) -> EmbeddingProvider | None:
    """Local embeddings unless the user chose otherwise. Where they can't be installed
    (Intel Macs), fall back to the provider's embeddings, else to keyword search."""
    if settings.embeddings == "off":
        return None
    spec = settings.spec
    remote_ok = gateway is not None and spec is not None and spec.offers_embeddings
    wants_local = not settings.uses_provider_embeddings
    if wants_local and local_embeddings_installed():
        return LocalEmbeddings(settings.models_dir, settings.local_embedding_model)
    if remote_ok and gateway is not None and spec is not None:
        model = settings.model("embedding") or spec.models.embedding
        return RemoteEmbeddings(
            gateway,
            model,
            dimensions=settings.embedding_dimensions,
            space=vector_space(gateway.provider, model, settings.embedding_dimensions),
        )
    return None


def build_container(
    settings: Settings,
    *,
    backend: LlmBackend | None = None,
    extractor: ContentExtractor | None = None,
    embedder: EmbeddingProvider | None = None,
    chat: ChatModel | None = None,
    thread_parser: ThreadParser | None = None,
    reply_chat: ChatModel | None = None,
    clock: Clock | None = None,
) -> Container:
    """Wire the app from settings. Anything passed explicitly wins (tests, embedding apps).

    ``backend`` replaces the provider's real backend, e.g. a fake HTTP-free one in tests;
    the rest of the wiring (gateway, metering, budget) stays real.
    """
    clock = clock or SystemClock()
    database = SqliteDatabase(settings.index_path)
    ledger = SqliteUsageLedger(database)

    gateway: LlmGateway | None = None
    if backend is None and settings.configured and settings.provider:
        backend = build_backend(
            settings.provider,
            api_key=settings.api_key,
            base_url=settings.base_url,
            ollama_context=settings.ollama_context,
        )
    if backend is not None:
        gateway = LlmGateway(
            backend,
            clock=clock,
            ledger=ledger,
            prices=PriceBook(PRICES, settings.prices),
            budget=BudgetPolicy(ledger, clock, settings.monthly_budget_usd),
        )
        fallbacks = settings.spec.models.chat_fallbacks if settings.spec else ()
        extractor = extractor or LlmContentExtractor(gateway, settings.model("extraction"))
        thread_parser = thread_parser or LlmThreadParser(gateway, settings.model("comments"))
        chat = chat or LlmChat(gateway, settings.model("chat"), fallbacks=fallbacks)
        reply_chat = reply_chat or LlmChat(
            gateway,
            settings.model("reply"),
            task=Task.REPLY,
            fallbacks=fallbacks,
            max_output_tokens=REPLY_MAX_OUTPUT,
            temperature=0.6,
            effort="high",
        )
    if embedder is None:
        embedder = _default_embedder(settings, gateway)
    cutoffs = settings.cutoffs_for(embedder.name if embedder else "")

    return Container(
        repository=SqliteGraphRepository(database),
        search_index=SqliteSearchIndex(database),
        vault=MarkdownVault(settings.vault_dir),
        clock=clock,
        usage_ledger=ledger,
        gateway=gateway,
        extractor=extractor,
        embedder=embedder,
        chat=chat,
        thread_parser=thread_parser,
        reply_chat=reply_chat,
        min_similarity=cutoffs.search,
        related_similarity=cutoffs.related,
        monthly_budget_usd=settings.monthly_budget_usd,
        not_configured=setup_hint(settings),
        closers=(database.close,),
    )
