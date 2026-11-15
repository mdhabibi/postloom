"""Content entities: what the user writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from postloom.domain.errors import EmptyContentError
from postloom.domain.graph import NodeId, NodeKind, node_id
from postloom.domain.text import slugify


@dataclass(frozen=True, slots=True)
class Topic:
    """A top-level subject from the user's fixed taxonomy (e.g. "RAG", "AI Agents")."""

    name: str
    description: str = ""

    @property
    def id(self) -> NodeId:
        return node_id(NodeKind.TOPIC, slugify(self.name))


@dataclass(frozen=True, slots=True)
class Series:
    """A multi-part series of articles."""

    name: str

    @property
    def id(self) -> NodeId:
        return node_id(NodeKind.SERIES, slugify(self.name))


@dataclass(frozen=True, slots=True)
class Article:
    """A long-form LinkedIn article, stored as clean Markdown."""

    title: str
    body_markdown: str
    summary: str = ""
    url: str | None = None
    published_on: date | None = None
    series: Series | None = None
    series_part: int | None = None
    hashtags: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    """Named technologies, methods and organisations mentioned (e.g. "LangGraph", "Redis")."""
    key: str = ""
    """Stable identity, fixed when the article is first saved, so retitling it never
    changes its id, its file name or the comments attached to it. Empty on records
    written before keys existed: their identity is the slug of their title."""

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise EmptyContentError("article title is empty")
        if not self.body_markdown.strip():
            raise EmptyContentError("article body is empty")

    @property
    def slug(self) -> str:
        return self.key or slugify(self.title)

    @property
    def id(self) -> NodeId:
        return node_id(NodeKind.ARTICLE, self.slug)


@dataclass(frozen=True, slots=True)
class Post:
    """The short feed post that announces an article (or stands on its own)."""

    key: str
    """Stable identity, derived from the article it announces or from its URL."""
    text: str
    url: str | None = None
    published_on: date | None = None
    hashtags: tuple[str, ...] = ()
    links: tuple[str, ...] = ()
    banner_path: str | None = None
    """Path of the banner image inside the vault, relative to the vault root."""

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise EmptyContentError("post text is empty")

    @property
    def id(self) -> NodeId:
        return node_id(NodeKind.POST, self.key)

    @staticmethod
    def key_for_article(article: Article) -> str:
        return article.slug
