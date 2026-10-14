"""In-memory GraphRepository.

Used by tests and as the executable reference for the repository contract: when the
SQLite adapter and this one disagree, ``tests/contract`` tells you which is wrong.
"""

from __future__ import annotations

from collections.abc import Sequence

from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.discussion import Comment
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

    def delete_person(self, person_id: NodeId) -> None:
        self._people.pop(person_id, None)

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

    def _all(self, include_history: bool) -> list[Edge]:
        live = list(self._live.values())
        return [*live, *self._history] if include_history else live
