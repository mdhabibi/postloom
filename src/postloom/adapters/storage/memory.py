"""In-memory GraphRepository.

Used by tests and as the executable reference for the repository contract: when the
SQLite adapter and this one disagree, ``tests/contract`` tells you which is wrong.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

from postloom.application.ports.repository import GraphContents
from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.discussion import Comment
from postloom.domain.entities import Entity
from postloom.domain.graph import Edge, EdgeKind, NodeId
from postloom.domain.people import Person


class InMemoryGraphRepository:
    def __init__(self) -> None:
        self._topics: dict[NodeId, Topic] = {}
        self._series: dict[NodeId, Series] = {}
        self._articles: dict[NodeId, Article] = {}
        self._posts: dict[NodeId, Post] = {}
        self._comments: dict[NodeId, Comment] = {}
        self._people: dict[NodeId, Person] = {}
        self._entities: dict[NodeId, Entity] = {}
        self._live: dict[tuple[NodeId, NodeId, EdgeKind], Edge] = {}
        self._history: list[Edge] = []

    # -- topics ---------------------------------------------------------------
    def list_topics(self) -> Sequence[Topic]:
        return list(self._topics.values())

    def save_topic(self, topic: Topic) -> None:
        self._topics[topic.id] = topic

    # -- content --------------------------------------------------------------
    def get_article(self, article_id: NodeId) -> Article | None:
        return self._articles.get(article_id)

    def save_article(self, article: Article) -> None:
        self._articles[article.id] = article

    def list_articles(self) -> Sequence[Article]:
        return list(self._articles.values())

    def get_post(self, post_id: NodeId) -> Post | None:
        return self._posts.get(post_id)

    def save_post(self, post: Post) -> None:
        self._posts[post.id] = post

    def list_posts(self) -> Sequence[Post]:
        return list(self._posts.values())

    def save_series(self, series: Series) -> None:
        self._series[series.id] = series

    # -- discussions ----------------------------------------------------------
    def get_comment(self, comment_id: NodeId) -> Comment | None:
        return self._comments.get(comment_id)

    def save_comment(self, comment: Comment) -> None:
        self._comments[comment.id] = comment

    def comments_on(self, post: NodeId) -> Sequence[Comment]:
        found = [c for c in self._comments.values() if c.post == post]
        return sorted(found, key=lambda c: c.position)

    def get_person(self, person_id: NodeId) -> Person | None:
        return self._people.get(person_id)

    def save_person(self, person: Person) -> None:
        self._people[person.id] = person

    def list_people(self) -> Sequence[Person]:
        return list(self._people.values())

    def get_entity(self, entity_id: NodeId) -> Entity | None:
        return self._entities.get(entity_id)

    def save_entity(self, entity: Entity) -> None:
        self._entities[entity.id] = entity

    def list_entities(self) -> Sequence[Entity]:
        return list(self._entities.values())

    # -- edges ----------------------------------------------------------------
    def save_edge(self, edge: Edge) -> None:
        if edge.superseded_at is not None:
            raise ValueError("save_edge takes a live edge; use supersede_edge to retire one")
        self._live[edge.key] = edge

    def supersede_edge(self, edge: Edge) -> None:
        if edge.superseded_at is None:
            raise ValueError("supersede_edge takes the superseded version of an edge")
        self._live.pop(edge.key, None)
        self._history.append(edge)

    def edges_from(self, node: NodeId, *, include_history: bool = False) -> Sequence[Edge]:
        return [e for e in self._all(include_history) if e.source == node]

    def edges_to(self, node: NodeId, *, include_history: bool = False) -> Sequence[Edge]:
        return [e for e in self._all(include_history) if e.target == node]

    def all_edges(self) -> Sequence[Edge]:
        return [*self._history, *self._live.values()]

    def _all(self, include_history: bool) -> list[Edge]:
        live = list(self._live.values())
        return [*live, *self._history] if include_history else live

    # -- whole-graph operations -------------------------------------------------
    def remove_node(self, node: NodeId) -> None:
        for store in self._stores():
            store.pop(node, None)

    def erase_nodes(self, nodes: Collection[NodeId]) -> None:
        gone = set(nodes)
        for node in gone:
            self.remove_node(node)
        self._live = {
            k: e for k, e in self._live.items() if e.source not in gone and e.target not in gone
        }
        self._history = [e for e in self._history if e.source not in gone and e.target not in gone]

    def _stores(self) -> tuple[dict[NodeId, Any], ...]:
        return (
            self._topics,
            self._series,
            self._articles,
            self._posts,
            self._comments,
            self._people,
            self._entities,
        )

    def replace_graph(self, contents: GraphContents) -> None:
        self._topics = {t.id: t for t in contents.topics}
        self._series = {s.id: s for s in contents.series}
        self._articles = {a.id: a for a in contents.articles}
        self._posts = {p.id: p for p in contents.posts}
        self._comments = {c.id: c for c in contents.comments}
        self._people = {p.id: p for p in contents.people}
        self._entities = {e.id: e for e in contents.entities}
        self._live, self._history = {}, []
        for edge in contents.edges:
            if edge.superseded_at is None:
                self._live[edge.key] = edge
            else:
                self._live.pop(edge.key, None)
                self._history.append(edge)
