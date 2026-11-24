"""A GraphRepository that answers reads from memory while a screen is being put together.

Building a page of a large library asks the repository thousands of small questions (the
topics of each article, the comments of each person, the edges of each node). One by one
they are cheap; together they made the library screens slow. Inside :meth:`reading`, this
wrapper answers them from a snapshot loaded in a few bulk queries and keeps that snapshot
for the next screen, until something changes:

- any write through this repository drops it (so a screen never shows stale data), and
- so does a write by another process (the command line, say), seen through ``changed``.

Outside :meth:`reading` every call goes straight to the wrapped repository, so a use case
that writes and reads in turn never pays for reloading a snapshot after each write.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable, Collection, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from postloom.application.ports.repository import GraphContents, GraphRepository
from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.discussion import Comment
from postloom.domain.entities import Entity
from postloom.domain.graph import Edge, NodeId
from postloom.domain.people import Person


@dataclass(slots=True)
class _Snapshot:
    topics: list[Topic] | None = None
    articles: dict[NodeId, Article] | None = None
    posts: dict[NodeId, Post] | None = None
    people: dict[NodeId, Person] | None = None
    entities: dict[NodeId, Entity] | None = None
    comments: dict[NodeId, list[Comment]] | None = None
    """Comments by post, in pasted order."""
    comment_by_id: dict[NodeId, Comment] = field(default_factory=dict[NodeId, Comment])
    edges_from: dict[NodeId, list[Edge]] | None = None
    edges_to: dict[NodeId, list[Edge]] = field(default_factory=dict[NodeId, list[Edge]])


class CachedRepository:
    def __init__(self, inner: GraphRepository, changed: Callable[[], object] | None = None) -> None:
        """``changed`` returns a value that differs once another process wrote."""
        self._inner = inner
        self._changed = changed or (lambda: None)
        self._lock = threading.RLock()
        self._local = threading.local()
        self._snapshot = _Snapshot()
        self._seen = self._changed()
        self._version = 0

    @contextmanager
    def reading(self) -> Generator[None, None, None]:
        """Answer reads on this thread from the snapshot until the block ends."""
        depth = getattr(self._local, "depth", 0)
        if depth == 0:
            with self._lock:
                self._check()
        self._local.depth = depth + 1
        try:
            yield
        finally:
            self._local.depth = depth

    @property
    def version(self) -> int:
        """Changes whenever the library may have changed; a key for caching answers."""
        with self._lock:
            self._check()
            return self._version

    # -- the snapshot -------------------------------------------------------------------
    def _reading(self) -> bool:
        return getattr(self._local, "depth", 0) > 0

    def _check(self) -> None:
        seen = self._changed()
        if seen != self._seen:
            self._seen = seen
            self._drop()

    def _drop(self) -> None:
        with self._lock:
            self._snapshot = _Snapshot()
            self._version += 1

    def _current(self) -> _Snapshot:
        return self._snapshot

    def _articles(self) -> dict[NodeId, Article]:
        snap = self._current()
        if snap.articles is None:
            snap.articles = {a.id: a for a in self._inner.list_articles()}
        return snap.articles

    def _posts(self) -> dict[NodeId, Post]:
        snap = self._current()
        if snap.posts is None:
            snap.posts = {p.id: p for p in self._inner.list_posts()}
        return snap.posts

    def _people(self) -> dict[NodeId, Person]:
        snap = self._current()
        if snap.people is None:
            snap.people = {p.id: p for p in self._inner.list_people()}
        return snap.people

    def _entities(self) -> dict[NodeId, Entity]:
        snap = self._current()
        if snap.entities is None:
            snap.entities = {e.id: e for e in self._inner.list_entities()}
        return snap.entities

    def _comments(self) -> dict[NodeId, list[Comment]]:
        snap = self._current()
        if snap.comments is None:
            comments = {post: list(self._inner.comments_on(post)) for post in self._posts()}
            snap.comment_by_id = {c.id: c for found in comments.values() for c in found}
            snap.comments = comments
        return snap.comments

    def _edges(self) -> tuple[dict[NodeId, list[Edge]], dict[NodeId, list[Edge]]]:
        snap = self._current()
        if snap.edges_from is None:
            leaving: dict[NodeId, list[Edge]] = defaultdict(list)
            arriving: dict[NodeId, list[Edge]] = defaultdict(list)
            for edge in self._inner.all_edges():
                if edge.superseded_at is None:
                    leaving[edge.source].append(edge)
                    arriving[edge.target].append(edge)
            snap.edges_to = dict(arriving)
            snap.edges_from = dict(leaving)
        return snap.edges_from, snap.edges_to

    # -- reads ------------------------------------------------------------------------
    def list_topics(self) -> Sequence[Topic]:
        if not self._reading():
            return self._inner.list_topics()
        with self._lock:
            snap = self._current()
            if snap.topics is None:
                snap.topics = list(self._inner.list_topics())
            return list(snap.topics)

    def get_article(self, article_id: NodeId) -> Article | None:
        if not self._reading():
            return self._inner.get_article(article_id)
        with self._lock:
            return self._articles().get(article_id)

    def list_articles(self) -> Sequence[Article]:
        if not self._reading():
            return self._inner.list_articles()
        with self._lock:
            return list(self._articles().values())

    def get_post(self, post_id: NodeId) -> Post | None:
        if not self._reading():
            return self._inner.get_post(post_id)
        with self._lock:
            return self._posts().get(post_id)

    def list_posts(self) -> Sequence[Post]:
        if not self._reading():
            return self._inner.list_posts()
        with self._lock:
            return list(self._posts().values())

    def get_comment(self, comment_id: NodeId) -> Comment | None:
        if not self._reading():
            return self._inner.get_comment(comment_id)
        with self._lock:
            self._comments()
            found = self._snapshot.comment_by_id.get(comment_id)
        # A comment whose post is gone isn't in the snapshot; ask for it directly.
        return found if found is not None else self._inner.get_comment(comment_id)

    def comments_on(self, post: NodeId) -> Sequence[Comment]:
        if not self._reading():
            return self._inner.comments_on(post)
        with self._lock:
            found = self._comments().get(post)
        return list(found) if found is not None else self._inner.comments_on(post)

    def get_person(self, person_id: NodeId) -> Person | None:
        if not self._reading():
            return self._inner.get_person(person_id)
        with self._lock:
            return self._people().get(person_id)

    def list_people(self) -> Sequence[Person]:
        if not self._reading():
            return self._inner.list_people()
        with self._lock:
            return list(self._people().values())

    def get_entity(self, entity_id: NodeId) -> Entity | None:
        if not self._reading():
            return self._inner.get_entity(entity_id)
        with self._lock:
            return self._entities().get(entity_id)

    def list_entities(self) -> Sequence[Entity]:
        if not self._reading():
            return self._inner.list_entities()
        with self._lock:
            return list(self._entities().values())

    def edges_from(self, node: NodeId, *, include_history: bool = False) -> Sequence[Edge]:
        if include_history or not self._reading():
            return self._inner.edges_from(node, include_history=include_history)
        with self._lock:
            return list(self._edges()[0].get(node, ()))

    def edges_to(self, node: NodeId, *, include_history: bool = False) -> Sequence[Edge]:
        if include_history or not self._reading():
            return self._inner.edges_to(node, include_history=include_history)
        with self._lock:
            return list(self._edges()[1].get(node, ()))

    def all_edges(self) -> Sequence[Edge]:
        return self._inner.all_edges()

    # -- writes: passed through, then the snapshot is dropped ------------------------------
    @contextmanager
    def _writing(self) -> Generator[None, None, None]:
        try:
            yield
        finally:
            self._drop()

    def save_topic(self, topic: Topic) -> None:
        with self._writing():
            self._inner.save_topic(topic)

    def save_article(self, article: Article) -> None:
        with self._writing():
            self._inner.save_article(article)

    def save_post(self, post: Post) -> None:
        with self._writing():
            self._inner.save_post(post)

    def save_series(self, series: Series) -> None:
        with self._writing():
            self._inner.save_series(series)

    def save_comment(self, comment: Comment) -> None:
        with self._writing():
            self._inner.save_comment(comment)

    def save_person(self, person: Person) -> None:
        with self._writing():
            self._inner.save_person(person)

    def save_entity(self, entity: Entity) -> None:
        with self._writing():
            self._inner.save_entity(entity)

    def save_edge(self, edge: Edge) -> None:
        with self._writing():
            self._inner.save_edge(edge)

    def supersede_edge(self, edge: Edge) -> None:
        with self._writing():
            self._inner.supersede_edge(edge)

    def remove_node(self, node: NodeId) -> None:
        with self._writing():
            self._inner.remove_node(node)

    def erase_nodes(self, nodes: Collection[NodeId]) -> None:
        with self._writing():
            self._inner.erase_nodes(nodes)

    def replace_graph(self, contents: GraphContents) -> None:
        with self._writing():
            self._inner.replace_graph(contents)
