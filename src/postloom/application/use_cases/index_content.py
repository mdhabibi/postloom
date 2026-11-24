"""IndexArticle / ReindexAll: keep the search index in sync with the graph.

An article is indexed as two nodes: the article itself (summary and sections), and its
post (the announcement text, then one chunk per comment thread). Keeping the discussion
under the post's node means search and chat can find what people said, while link
suggestions, which compare articles by what they are about, never see the comments.

Embeddings cost money and time, so each chunk's vector is reused whenever a chunk with
the same content hash was already embedded in the same vector space. Re-ingesting an
article after fixing a typo only re-embeds the section that changed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from postloom.application.errors import ApplicationError, BudgetExceededError, ProviderError
from postloom.application.ports.embeddings import DocumentText, EmbeddingProvider
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.search_index import IndexedChunk, SearchIndex
from postloom.application.use_cases.relations import get_item, post_of
from postloom.domain.chunking import Chunk, chunk_markdown
from postloom.domain.content import Article, Post
from postloom.domain.discussion import Comment, thread_texts
from postloom.domain.graph import NodeId
from postloom.domain.text import plain_letters


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
        """Index an article, its post and the discussion under it; or a stand-alone post
        and its discussion."""
        item = get_item(self._repository, article_id)
        if isinstance(item, Post):
            comments = self._repository.comments_on(item.id)
            return self._store(item.id, discussion_chunks(item, item, comments))
        article = item
        if article is None:
            raise ApplicationError(f"Unknown article: {article_id}")
        result = self._store(article.id, article_chunks(article))
        post = post_of(self._repository, article.id)
        if post is None:
            return result
        comments = self._repository.comments_on(post.id)
        discussion = self._store(post.id, discussion_chunks(article, post, comments))
        return IndexResult(
            result.chunks + discussion.chunks,
            result.embedded + discussion.embedded,
            result.reused + discussion.reused,
            semantic=result.semantic,
        )

    def _store(self, node: NodeId, chunks: list[Chunk]) -> IndexResult:
        if self._embedder is None:
            self._index.replace_chunks(node, [IndexedChunk(c, None, None) for c in chunks])
            return IndexResult(len(chunks), 0, 0, semantic=False)

        space = self._embedder.name
        cached = self._index.cached_vectors(space, {c.content_hash for c in chunks})
        missing = [c for c in chunks if c.content_hash not in cached]
        if missing:
            try:
                fresh = self._embedder.embed_documents(
                    [DocumentText(plain_letters(c.title), _embedding_text(c)) for c in missing]
                )
            except (ProviderError, BudgetExceededError):
                # Keep the text findable by keywords, then report why meaning search
                # isn't available for it; a later reindex fills the vectors in.
                self._index.replace_chunks(node, [IndexedChunk(c, None, None) for c in chunks])
                raise
            cached.update(zip((c.content_hash for c in missing), fresh, strict=True))

        indexed = [IndexedChunk(c, cached[c.content_hash], space) for c in chunks]
        self._index.replace_chunks(node, indexed)
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


POST_HEADING = "Announcement post"
STANDALONE_HEADING = "Post"
COMMENTS_HEADING = "Comments: thread started by "
MAX_THREAD_CHARS = 2400


def discussion_chunks(item: Article | Post, post: Post, comments: Sequence[Comment]) -> list[Chunk]:
    """The post's text, then each comment thread as one chunk (long threads are split
    between messages, never inside one). ``item`` is what they are about: the article the
    post announces, or the post itself."""
    title = item.title
    heading_of_post = POST_HEADING if isinstance(item, Article) else STANDALONE_HEADING
    chunks = [Chunk(post.id, 0, heading_of_post, post.text, title)]
    for thread in thread_texts(comments):
        heading = f"{COMMENTS_HEADING}{thread.starter}"
        piece: list[str] = []
        for message in thread.text.split("\n\n"):
            if piece and sum(map(len, piece)) + len(message) > MAX_THREAD_CHARS:
                chunks.append(Chunk(post.id, len(chunks), heading, "\n\n".join(piece), title))
                piece = []
            piece.append(message)
        chunks.append(Chunk(post.id, len(chunks), heading, "\n\n".join(piece), title))
    return chunks


def _embedding_text(chunk: Chunk) -> str:
    text = f"{chunk.heading}\n\n{chunk.text}" if chunk.heading else chunk.text
    return plain_letters(text)
