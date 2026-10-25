"""IndexArticle / ReindexAll: keep the search index in sync with the graph.

Embeddings cost money and time, so each chunk's vector is reused whenever a chunk with
the same content hash was already embedded in the same vector space. Re-ingesting an
article after fixing a typo only re-embeds the section that changed.
"""

from __future__ import annotations

from dataclasses import dataclass

from postloom.application.errors import ApplicationError, BudgetExceededError, ProviderError
from postloom.application.ports.embeddings import DocumentText, EmbeddingProvider
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.search_index import IndexedChunk, SearchIndex
from postloom.domain.chunking import Chunk, chunk_markdown
from postloom.domain.content import Article
from postloom.domain.graph import NodeId


@dataclass(frozen=True, slots=True)
class IndexResult:
    chunks: int
    embedded: int
    """Chunks sent to the embedding provider."""
    reused: int
    """Chunks whose vector came from the cache."""
    semantic: bool
    """False when no embedding provider is configured (keyword search only)."""


class IndexArticle:
    def __init__(
        self,
        repository: GraphRepository,
        index: SearchIndex,
        embedder: EmbeddingProvider | None,
    ) -> None:
        self._repository = repository
        self._index = index
        self._embedder = embedder

    def execute(self, article_id: NodeId) -> IndexResult:
        article = self._repository.get_article(article_id)
        if article is None:
            raise ApplicationError(f"Unknown article: {article_id}")
        chunks = article_chunks(article)

        if self._embedder is None:
            self._index.replace_chunks(article.id, [IndexedChunk(c, None, None) for c in chunks])
            return IndexResult(len(chunks), 0, 0, semantic=False)

        space = self._embedder.name
        cached = self._index.cached_vectors(space, {c.content_hash for c in chunks})
        missing = [c for c in chunks if c.content_hash not in cached]
        if missing:
            try:
                fresh = self._embedder.embed_documents(
                    [DocumentText(c.title, _embedding_text(c)) for c in missing]
                )
            except (ProviderError, BudgetExceededError):
                # Keep the article findable by keywords, then report why meaning search
                # isn't available for it; a later reindex fills the vectors in.
                self._index.replace_chunks(
                    article.id, [IndexedChunk(c, None, None) for c in chunks]
                )
                raise
            cached.update(zip((c.content_hash for c in missing), fresh, strict=True))

        indexed = [IndexedChunk(c, cached[c.content_hash], space) for c in chunks]
        self._index.replace_chunks(article.id, indexed)
        return IndexResult(len(chunks), len(missing), len(chunks) - len(missing), semantic=True)


@dataclass(frozen=True, slots=True)
class ReindexResult:
    articles: int
    chunks: int
    embedded: int
    reused: int


class ReindexAll:
    """Rebuild the search index for every article (after an upgrade or a model change)."""

    def __init__(self, repository: GraphRepository, index_article: IndexArticle) -> None:
        self._repository = repository
        self._index_article = index_article

    def execute(self) -> ReindexResult:
        articles = list(self._repository.list_articles())
        totals = [self._index_article.execute(a.id) for a in articles]
        return ReindexResult(
            articles=len(articles),
            chunks=sum(t.chunks for t in totals),
            embedded=sum(t.embedded for t in totals),
            reused=sum(t.reused for t in totals),
        )


def article_chunks(article: Article) -> list[Chunk]:
    """The article's sections, preceded by its summary as a chunk of its own."""
    body = chunk_markdown(article.id, article.title, article.body_markdown)
    if not article.summary:
        return body
    summary = Chunk(article.id, 0, "Summary", article.summary, article.title)
    return [
        summary,
        *(Chunk(c.node, c.index + 1, c.heading, c.text, c.title) for c in body),
    ]


def _embedding_text(chunk: Chunk) -> str:
    return f"{chunk.heading}\n\n{chunk.text}" if chunk.heading else chunk.text
