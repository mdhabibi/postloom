"""BrowseContent: read models for listing and opening articles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from postloom.application.ports.repository import GraphRepository
from postloom.domain.content import Article, Post
from postloom.domain.discussion import Comment, conversation_depth
from postloom.domain.graph import EdgeKind, NodeId
from postloom.domain.provenance import Grade


@dataclass(frozen=True, slots=True)
class TopicLink:
    name: str
    grade: Grade
    """ASSERTED until the user confirms the model's choice."""


@dataclass(frozen=True, slots=True)
class ArticleSummary:
    id: NodeId
    title: str
    summary: str
    published_on: date | None
    url: str | None
    topics: tuple[TopicLink, ...]
    series: str | None
    series_part: int | None


@dataclass(frozen=True, slots=True)
class CommentView:
    id: NodeId
    author_name: str
    author_headline: str | None
    is_own: bool
    text: str
    posted_label: str
    thread: NodeId | None
    reply_to: NodeId | None
    reply_to_name: str | None
    """Who this message answers, for "replying to Jane" labels."""
    depth: int


@dataclass(frozen=True, slots=True)
class ArticleDetail:
    summary: ArticleSummary
    article: Article
    posts: tuple[Post, ...]
    discussion: tuple[CommentView, ...] = ()
    """Every comment and reply under the article's posts, in conversation order."""


class BrowseContent:
    def __init__(self, repository: GraphRepository) -> None:
        self._repository = repository

    def list_articles(self) -> list[ArticleSummary]:
        summaries = [self._summarize(a) for a in self._repository.list_articles()]
        # Newest first; undated articles after dated ones, alphabetically.
        summaries.sort(key=lambda s: s.title.casefold())
        summaries.sort(key=lambda s: s.published_on or date.min, reverse=True)
        return summaries

    def get_article(self, article_id: NodeId) -> ArticleDetail | None:
        article = self._repository.get_article(article_id)
        if article is None:
            return None
        posts = [
            post
            for edge in self._repository.edges_to(article.id)
            if edge.kind is EdgeKind.ANNOUNCES and edge.is_current
            if (post := self._repository.get_post(edge.source)) is not None
        ]
        comments = [c for post in posts for c in self._repository.comments_on(post.id)]
        return ArticleDetail(
            self._summarize(article), article, tuple(posts), self._discussion(comments)
        )

    def _discussion(self, comments: list[Comment]) -> tuple[CommentView, ...]:
        by_id = {c.id: c for c in comments}
        headlines: dict[NodeId, str | None] = {}
        for comment in comments:
            if comment.author not in headlines:
                person = self._repository.get_person(comment.author)
                headlines[comment.author] = person.headline if person else None
        return tuple(
            CommentView(
                id=c.id,
                author_name=c.author_name,
                author_headline=headlines.get(c.author),
                is_own=c.is_own,
                text=c.text,
                posted_label=c.posted_label,
                thread=c.thread,
                reply_to=c.reply_to,
                reply_to_name=by_id[c.reply_to].author_name if c.reply_to in by_id else None,
                depth=conversation_depth(c, by_id),
            )
            for c in _conversation_order(comments)
        )

    def _summarize(self, article: Article) -> ArticleSummary:
        names = {t.id: t.name for t in self._repository.list_topics()}
        topics = tuple(
            TopicLink(names[edge.target], edge.provenance.grade)
            for edge in self._repository.edges_from(article.id)
            if edge.kind is EdgeKind.BELONGS_TO and edge.is_current and edge.target in names
        )
        return ArticleSummary(
            id=article.id,
            title=article.title,
            summary=article.summary,
            published_on=article.published_on,
            url=article.url,
            topics=topics,
            series=article.series.name if article.series else None,
            series_part=article.series_part,
        )


def _conversation_order(comments: list[Comment]) -> list[Comment]:
    """Threads in pasted order; inside a thread, each reply right after what it answers."""
    children: dict[NodeId | None, list[Comment]] = {}
    known = {c.id for c in comments}
    for comment in sorted(comments, key=lambda c: c.position):
        parent = comment.reply_to if comment.reply_to in known else None
        children.setdefault(parent, []).append(comment)
    ordered: list[Comment] = []
    seen: set[NodeId] = set()

    def visit(comment: Comment) -> None:
        if comment.id in seen:
            return
        seen.add(comment.id)
        ordered.append(comment)
        for child in children.get(comment.id, []):
            visit(child)

    for root in children.get(None, []):
        visit(root)
    ordered += [c for c in comments if c.id not in seen]  # defensive: never drop a message
    return ordered
