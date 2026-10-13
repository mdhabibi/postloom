"""AskQuestion: answer from the author's own writing, with citations, or say "not found".

Grounding rules:
- The model only sees numbered sources taken from the user's articles and posts, and is
  told to answer from them alone and cite them as [n].
- Asked about one article, it gets that whole article and its announcement post.
- Asked across everything, it gets only passages that pass the semantic similarity cutoff.
  If none do, we answer "not found" *without calling the model*: no cost, and no chance
  of a confident answer built on unrelated text.
- Citations are parsed back deterministically, so the UI only shows sources the answer
  actually used, and an invented "[9]" can't point anywhere.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from postloom.application.errors import ApplicationError
from postloom.application.ports.chat import ChatMessage, ChatModel, Role
from postloom.application.ports.embeddings import EmbeddingProvider
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.search_index import ChunkHit, SearchIndex
from postloom.domain.graph import EdgeKind, NodeId

MAX_SOURCES = 8
MAX_CONTEXT_CHARS = 40_000
MAX_HISTORY_MESSAGES = 8
NOT_FOUND = (
    "I couldn't find anything about this in your articles. Try different words, or open a "
    "specific article and ask about it there."
)

SYSTEM_PROMPT = """\
You are postloom, an assistant that answers questions about the user's own LinkedIn \
articles and posts. The user is the author.

How to answer:
- Start with the direct answer in the first sentence. If a source contains it, state it \
plainly; never claim the sources lack something you then go on to quote.
- Use only the numbered sources in the latest message, not outside knowledge.
- Cite each claim with its source number, like [1] or [2][3]. Only cite numbers that exist.
- If no source contains the answer, say in one sentence that your articles don't cover it. \
Don't suggest searching the web or LinkedIn.
- Be concise and concrete: short paragraphs or bullets. Quote code exactly when relevant.
- Answer in the language of the question.
"""

_CITATION = re.compile(r"\[(\d{1,2})\]")


@dataclass(frozen=True, slots=True)
class Source:
    number: int
    article_id: NodeId
    title: str
    section: str
    text: str


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    sources: tuple[Source, ...]
    """Only the sources the answer cites, in citation-number order."""
    grounded: bool
    """False when nothing relevant was found and the model was not asked."""


class AskQuestion:
    def __init__(
        self,
        chat: ChatModel,
        index: SearchIndex,
        repository: GraphRepository,
        embedder: EmbeddingProvider | None,
        min_similarity: float,
    ) -> None:
        self._chat = chat
        self._index = index
        self._repository = repository
        self._embedder = embedder
        self._min_similarity = min_similarity

    def execute(
        self,
        question: str,
        *,
        article_id: NodeId | None = None,
        history: Sequence[ChatMessage] = (),
    ) -> Answer:
        question = question.strip()
        if not question:
            raise ApplicationError("Ask a question first.")

        sources = (
            self._article_sources(article_id)
            if article_id is not None
            else self._library_sources(question)
        )
        if not sources:
            return Answer(NOT_FOUND, (), grounded=False)

        messages = [*history[-MAX_HISTORY_MESSAGES:], _question_message(question, sources)]
        text = self._chat.complete(SYSTEM_PROMPT, messages)
        return Answer(text, _cited(text, sources), grounded=True)

    # -- context selection ----------------------------------------------------------
    def _article_sources(self, article_id: NodeId) -> list[Source]:
        article = self._repository.get_article(article_id)
        if article is None:
            raise ApplicationError(f"Unknown article: {article_id}")
        hits = list(self._index.chunks_of(article_id))
        sources = _number([(h.node, h.title, h.heading or "Introduction", h.text) for h in hits])
        for edge in self._repository.edges_to(article_id):
            if edge.kind is EdgeKind.ANNOUNCES and edge.is_current:
                post = self._repository.get_post(edge.source)
                if post is not None:
                    item = (article_id, article.title, "Announcement post", post.text)
                    sources.append(Source(len(sources) + 1, *item))
                    sources += self._comment_sources(article_id, article.title, post.id, sources)
        return _fit(sources)

    def _comment_sources(
        self, article_id: NodeId, title: str, post: NodeId, so_far: list[Source]
    ) -> list[Source]:
        comments = list(self._repository.comments_on(post))
        names = {c.id: ("you" if c.is_own else c.author_name) for c in comments}
        sources: list[Source] = []
        for comment in comments:
            who = "Your reply" if comment.is_own else f"Comment by {comment.author_name}"
            answering = names.get(comment.reply_to) if comment.reply_to else None
            if answering:
                who += f" (answering {answering})"
            number = len(so_far) + len(sources) + 1
            sources.append(Source(number, article_id, title, who, comment.text))
        return sources

    def _library_sources(self, question: str) -> list[Source]:
        hits: Sequence[ChunkHit]
        if self._embedder is not None:
            vector = self._embedder.embed_query(question)
            nearest = self._index.vector_search(vector, self._embedder.name, MAX_SOURCES)
            hits = [h for h in nearest if h.score >= self._min_similarity]
        else:
            hits = self._index.keyword_search(question, MAX_SOURCES)
        return _fit(_number([(h.node, h.title, h.heading or "Introduction", h.text) for h in hits]))


def _number(items: Sequence[tuple[NodeId, str, str, str]]) -> list[Source]:
    return [Source(i, *item) for i, item in enumerate(items, start=1)]


def _fit(sources: list[Source]) -> list[Source]:
    """Keep sources in order until the context budget is spent."""
    kept: list[Source] = []
    used = 0
    for source in sources:
        if kept and used + len(source.text) > MAX_CONTEXT_CHARS:
            break
        kept.append(source)
        used += len(source.text)
    return kept


def _question_message(question: str, sources: Sequence[Source]) -> ChatMessage:
    blocks = [f"[{s.number}] {s.title} | {s.section}\n{s.text}" for s in sources]
    text = "Sources:\n\n" + "\n\n---\n\n".join(blocks) + f"\n\nQuestion: {question}"
    return ChatMessage(Role.USER, text)


def _cited(text: str, sources: Sequence[Source]) -> tuple[Source, ...]:
    by_number = {s.number: s for s in sources}
    numbers = sorted({int(n) for n in _CITATION.findall(text)})
    return tuple(by_number[n] for n in numbers if n in by_number)
