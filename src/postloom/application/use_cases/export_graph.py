"""ExportGraph: the whole library, written in a format other graph tools read.

The export is a snapshot of the index (which mirrors the vault): every node with its
properties and every edge with its provenance. It is read-only and never changes the
library. Formats live in ``adapters/export``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from postloom.application.errors import ApplicationError
from postloom.application.ports.clock import Clock
from postloom.application.ports.graph_export import ExportOptions, GraphFormat
from postloom.application.ports.repository import GraphContents, GraphRepository
from postloom.domain.content import Series
from postloom.domain.discussion import Comment
from postloom.domain.graph import Edge


@dataclass(frozen=True, slots=True)
class FormatInfo:
    name: str
    title: str
    extension: str


@dataclass(frozen=True, slots=True)
class GraphExport:
    filename: str
    media_type: str
    content: bytes
    nodes: int
    edges: int


class ExportGraph:
    def __init__(
        self, repository: GraphRepository, formats: Sequence[GraphFormat], clock: Clock
    ) -> None:
        self._repository = repository
        self._formats = {f.name: f for f in formats}
        self._clock = clock

    def formats(self) -> list[FormatInfo]:
        return [FormatInfo(f.name, f.title, f.extension) for f in self._formats.values()]

    def snapshot(self, *, history: bool = False) -> GraphContents:
        repo = self._repository
        articles = tuple(repo.list_articles())
        posts = tuple(repo.list_posts())
        series: dict[str, Series] = {}
        for article in articles:
            if article.series is not None:
                series.setdefault(article.series.id, article.series)
        comments: dict[str, Comment] = {}
        for post in posts:
            for comment in repo.comments_on(post.id):
                comments.setdefault(comment.id, comment)
        edges = tuple(_edges(repo.all_edges(), history=history))
        return GraphContents(
            topics=tuple(repo.list_topics()),
            series=tuple(series.values()),
            articles=articles,
            posts=posts,
            comments=tuple(comments.values()),
            people=tuple(repo.list_people()),
            entities=tuple(repo.list_entities()),
            edges=edges,
        )

    def execute(self, format_name: str, options: ExportOptions | None = None) -> GraphExport:
        options = options or ExportOptions()
        chosen = self._formats.get(format_name)
        if chosen is None:
            known = ", ".join(self._formats)
            raise ApplicationError(
                f"Unknown export format {format_name!r}. Choose one of: {known}."
            )
        graph = self.snapshot(history=options.history)
        nodes = sum(
            len(group)
            for group in (
                graph.topics,
                graph.series,
                graph.articles,
                graph.posts,
                graph.comments,
                graph.people,
                graph.entities,
            )
        )
        stamp = self._clock.now().strftime("%Y-%m-%d")
        return GraphExport(
            filename=f"postloom-graph-{stamp}.{chosen.extension}",
            media_type=chosen.media_type,
            content=chosen.write(graph, options),
            nodes=nodes,
            edges=len(graph.edges),
        )


def _edges(recorded: Sequence[Edge], *, history: bool) -> list[Edge]:
    """Edges to export: everything ever recorded, or only the live, not rejected ones."""
    return list(recorded) if history else [e for e in recorded if e.is_current]
