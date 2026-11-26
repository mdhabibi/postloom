"""The library as a labeled property graph: what the Cypher and GraphML exports write.

Every node keeps its postloom id (``article:measuring-what-matters``) as the ``id``
property and a display name as ``label``. Labels follow the node kind (``Article``,
``Person``...); a mentioned thing also gets its category (``Organisation``...). Every
relationship carries its provenance as properties.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast

from postloom.application.ports.graph_export import ExportOptions
from postloom.application.ports.repository import GraphContents
from postloom.domain.content import Article, Post
from postloom.domain.discussion import OWNER
from postloom.domain.entities import Category
from postloom.domain.graph import Edge
from postloom.domain.media import Media

Value = str | int | float | bool | date | datetime | tuple[str, ...]
"""A property value. ``datetime`` is checked before ``date`` (it is a subclass)."""

CATEGORY_LABELS: dict[Category, str] = {
    Category.ORGANISATION: "Organisation",
    Category.PLACE: "Place",
    Category.EVENT: "Event",
    Category.PROJECT: "Project",
    Category.DATASET: "Dataset",
    Category.METHOD: "Method",
    Category.LINK: "Link",
    Category.OTHER: "Other",
}
HAS_MEDIA = "HAS_MEDIA"


@dataclass(frozen=True, slots=True)
class PgNode:
    id: str
    labels: tuple[str, ...]
    properties: dict[str, Value]


@dataclass(frozen=True, slots=True)
class PgRelationship:
    key: str
    """Stable identity of this record, so loading the same export twice changes nothing."""
    source: str
    target: str
    type: str
    properties: dict[str, Value]


@dataclass(frozen=True, slots=True)
class PropertyGraph:
    nodes: tuple[PgNode, ...]
    relationships: tuple[PgRelationship, ...]


def property_graph(graph: GraphContents, options: ExportOptions) -> PropertyGraph:
    """Nodes once each; relationships only between nodes that are there (an edge to a
    node that was erased stays in the history, not in a graph other tools load)."""
    nodes = {n.id: n for n in _nodes(graph, options)}
    records = {
        record_key(edge): edge
        for edge in graph.edges
        if edge.source in nodes and edge.target in nodes
    }
    relationships = [_relationship(edge, options) for edge in records.values()]
    for item in (*graph.articles, *graph.posts):
        for position, media in enumerate(item.media):
            relationships.append(
                PgRelationship(
                    edge_key(item.id, HAS_MEDIA, media_id(media)),
                    item.id,
                    media_id(media),
                    HAS_MEDIA,
                    {"position": position},
                )
            )
    return PropertyGraph(tuple(nodes.values()), tuple(relationships))


def media_id(media: Media) -> str:
    return f"media:{media.file.removeprefix('media/')}"


def edge_key(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:16]


def record_key(edge: Edge) -> str:
    """One per recorded edge: the same link recorded twice (asserted, then verified) has
    two records when history is exported."""
    p = edge.provenance
    return edge_key(edge.source, edge.kind.value, edge.target, p.recorded_at.isoformat())


def _nodes(graph: GraphContents, options: ExportOptions) -> Iterator[PgNode]:
    text = options.text
    for topic in graph.topics:
        yield _node(
            topic.id, ("Topic",), topic.name, name=topic.name, description=topic.description
        )
    for series in graph.series:
        yield _node(series.id, ("Series",), series.name, name=series.name)
    for article in graph.articles:
        yield _node(
            article.id,
            ("Article",),
            article.title,
            title=article.title,
            url=article.url,
            published=article.published_on,
            series_part=article.series_part,
            hashtags=article.hashtags,
            summary=article.summary if text else None,
            body=article.body_markdown if text else None,
        )
        yield from _media(article, options)
    for post in graph.posts:
        yield _node(
            post.id,
            ("Post",),
            post.title,
            title=post.title,
            url=post.url,
            published=post.published_on,
            hashtags=post.hashtags,
            links=post.links,
            text=post.text if text else None,
        )
        yield from _media(post, options)
    for comment in graph.comments:
        yield _node(
            comment.id,
            ("Comment",),
            f"Comment by {comment.author_name}",
            author_name=comment.author_name,
            position=comment.position,
            posted=comment.posted_label,
            text=comment.text if text else None,
        )
    for person in graph.people:
        yield _node(
            person.id,
            ("Person",),
            person.name,
            name=person.name,
            profile_url=person.profile.url if person.profile else None,
            headline=person.headline,
            tags=person.tags,
            provisional=person.is_provisional,
            is_author=person.id == OWNER,
            notes=person.notes if text else None,
        )
    author = author_name(graph)
    if author is not None:
        yield _node(OWNER, ("Person",), author, name=author, is_author=True)
    for entity in graph.entities:
        yield _node(
            entity.id,
            ("Entity", CATEGORY_LABELS[entity.category]),
            entity.name,
            name=entity.name,
            category=entity.category.value,
            url=entity.url,
            aliases=entity.aliases,
        )


def author_name(graph: GraphContents) -> str | None:
    """The library's author is ``person:me`` and has no person note of their own. When
    their messages are in the graph, they need a node: named as their comments are."""
    if any(p.id == OWNER for p in graph.people):
        return None
    names = [c.author_name for c in graph.comments if c.author == OWNER]
    if not names and not any(OWNER in (e.source, e.target) for e in graph.edges):
        return None
    return names[0] if names else "Me"


def _media(item: Article | Post, options: ExportOptions) -> Iterator[PgNode]:
    for media in item.media:
        kind = media.kind.value
        yield _node(
            media_id(media),
            ("Media", kind.capitalize()),
            media.label(),
            kind=kind,
            file=media.file,
            media_type=media.mime,
            caption=media.caption if options.text else None,
            description=media.description if options.text else None,
            transcript=media.transcript if options.text else None,
        )


def _node(node_id: str, labels: tuple[str, ...], label: str, **properties: object) -> PgNode:
    return PgNode(node_id, labels, {"id": node_id, "label": label, **_clean(properties)})


def _relationship(edge: Edge, options: ExportOptions) -> PgRelationship:
    p = edge.provenance
    return PgRelationship(
        record_key(edge),
        edge.source,
        edge.target,
        edge.kind.value.upper(),
        _clean(
            {
                "origin": p.origin.value,
                "grade": p.grade.value,
                "producer": p.producer,
                "recorded_at": p.recorded_at,
                "evidence": p.evidence if options.text else None,
                "weight": edge.weight,
                "superseded_at": edge.superseded_at,
                "current": edge.is_current,
            }
        ),
    )


def _clean(properties: dict[str, object]) -> dict[str, Value]:
    """Drop missing values: no None, no empty strings or lists."""
    kept: dict[str, Value] = {}
    for name, value in properties.items():
        if value is None or value == "" or value == ():
            continue
        if isinstance(value, Sequence) and not isinstance(value, str):
            kept[name] = tuple(str(v) for v in cast(Sequence[object], value))
        elif isinstance(value, str | int | float | bool | date | datetime):
            kept[name] = value
    return kept
