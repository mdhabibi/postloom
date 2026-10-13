"""BrowseContent: read models for listing and opening articles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from postloom.application.ports.repository import GraphRepository
from postloom.domain.content import Article, Post
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
class ArticleDetail:
    summary: ArticleSummary
    article: Article
    posts: tuple[Post, ...]


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
        return ArticleDetail(self._summarize(article), article, tuple(posts))

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
