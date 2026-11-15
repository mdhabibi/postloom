"""GraphOverview: the whole library as nodes and links, for the graph view.

Comments are folded into the people who wrote them: a person is linked to each article
they discussed, weighted by how many messages they wrote there. That keeps the picture
readable (one node per person, not one per message) while still showing who engages
with what.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from postloom.application.ports.repository import GraphRepository
from postloom.application.use_cases.relations import article_of_post, comments_by
from postloom.domain.discussion import OWNER
from postloom.domain.graph import EdgeKind, NodeId
from postloom.domain.provenance import Grade

_GROUPS = (EdgeKind.BELONGS_TO, EdgeKind.PART_OF)
DISCUSSED = "discussed"
"""Derived link kind: person -> article, from their comments."""


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: NodeId
    kind: str
    """"topic", "series", "article" or "person"."""
    label: str
    weight: int
    """Topics and series: articles; articles: messages; people: messages."""


@dataclass(frozen=True, slots=True)
class GraphLink:
    source: NodeId
    target: NodeId
    kind: str
    grade: Grade
    weight: float | None = None


@dataclass(frozen=True, slots=True)
class GraphData:
    nodes: tuple[GraphNode, ...]
    links: tuple[GraphLink, ...]


class GraphOverview:
    def __init__(self, repository: GraphRepository) -> None:
        self._repository = repository

    def execute(self) -> GraphData:
        repo = self._repository
        articles = {a.id: a for a in repo.list_articles()}
        topics = {t.id: t for t in repo.list_topics()}
        links: list[GraphLink] = []
        series: dict[NodeId, str] = {}
        per_group: Counter[NodeId] = Counter()

        for article in articles.values():
            if article.series is not None:
                series[article.series.id] = article.series.name
            for edge in repo.edges_from(article.id):
                if not edge.is_current:
                    continue
                grade = edge.provenance.grade
                if edge.kind in _GROUPS and (edge.target in topics or edge.target in series):
                    links.append(GraphLink(article.id, edge.target, edge.kind.value, grade))
                    per_group[edge.target] += 1
                elif edge.kind is EdgeKind.RELATED_TO and edge.target in articles:
                    link = GraphLink(article.id, edge.target, edge.kind.value, grade, edge.weight)
                    links.append(link)  # stored once per pair, so never duplicated here

        messages_on: Counter[NodeId] = Counter()
        people: list[GraphNode] = []
        for person in repo.list_people():
            if person.id == OWNER:
                continue
            discussed: Counter[NodeId] = Counter()
            for comment in comments_by(repo, person.id):
                article = article_of_post(repo, comment.post)
                if article is not None and article.id in articles:
                    discussed[article.id] += 1
            if not discussed:
                continue
            people.append(GraphNode(person.id, "person", person.name, sum(discussed.values())))
            for article_id, count in discussed.items():
                messages_on[article_id] += count
                links.append(GraphLink(person.id, article_id, DISCUSSED, Grade.VERIFIED, count))

        nodes = [
            *(
                GraphNode(t.id, "topic", t.name, per_group[t.id])
                for t in topics.values()
                if per_group[t.id]
            ),
            *(GraphNode(sid, "series", name, per_group[sid]) for sid, name in series.items()),
            *(GraphNode(a.id, "article", a.title, messages_on[a.id]) for a in articles.values()),
            *people,
        ]
        return GraphData(tuple(nodes), tuple(links))
