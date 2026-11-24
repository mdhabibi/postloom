"""Port for the graph index (nodes and edges).

The Markdown vault is the source of truth; the repository is a queryable index that can
always be rebuilt from the vault. Implementations: in-memory (tests, reference) and
SQLite (default). Every implementation must pass ``tests/contract/test_repository.py``.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Protocol

from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.discussion import Comment
from postloom.domain.entities import Entity
from postloom.domain.graph import Edge, NodeId
from postloom.domain.people import Person


@dataclass(frozen=True, slots=True)
class GraphContents:
    """A whole graph: what a rebuild from the vault puts in place of the current one."""

    topics: tuple[Topic, ...] = ()
    series: tuple[Series, ...] = ()
    articles: tuple[Article, ...] = ()
    posts: tuple[Post, ...] = ()
    comments: tuple[Comment, ...] = ()
    people: tuple[Person, ...] = ()
    entities: tuple[Entity, ...] = ()
    edges: tuple[Edge, ...] = ()
    """Live edges and history, in the order they were recorded."""


class GraphRepository(Protocol):
    # -- topics ---------------------------------------------------------------
    def list_topics(self) -> Sequence[Topic]: ...

    def save_topic(self, topic: Topic) -> None: ...

    # -- content --------------------------------------------------------------
    def get_article(self, article_id: NodeId) -> Article | None: ...

    def save_article(self, article: Article) -> None: ...

    def list_articles(self) -> Sequence[Article]:
        """All articles, oldest first (by first save)."""
        ...

    def get_post(self, post_id: NodeId) -> Post | None: ...

    def save_post(self, post: Post) -> None: ...

    def list_posts(self) -> Sequence[Post]: ...

    def save_series(self, series: Series) -> None: ...

    # -- discussions ----------------------------------------------------------
    def get_comment(self, comment_id: NodeId) -> Comment | None: ...

    def save_comment(self, comment: Comment) -> None: ...

    def comments_on(self, post: NodeId) -> Sequence[Comment]:
        """Every comment and reply on ``post``, in pasted order (``position``)."""
        ...

    def get_person(self, person_id: NodeId) -> Person | None: ...

    def save_person(self, person: Person) -> None: ...

    def list_people(self) -> Sequence[Person]: ...

    # -- what the user's writing mentions ---------------------------------------
    def get_entity(self, entity_id: NodeId) -> Entity | None: ...

    def save_entity(self, entity: Entity) -> None: ...

    def list_entities(self) -> Sequence[Entity]: ...

    # -- edges ----------------------------------------------------------------
    def save_edge(self, edge: Edge) -> None:
        """Insert or replace the live edge for ``edge.key`` (source, target, kind).

        ``edge.superseded_at`` must be None; use :meth:`supersede_edge` to retire one.
        """
        ...

    def supersede_edge(self, edge: Edge) -> None:
        """Move the live edge for ``edge.key`` into history.

        ``edge`` is the superseded version (``superseded_at`` set). History is never deleted.
        """
        ...

    def edges_from(self, node: NodeId, *, include_history: bool = False) -> Sequence[Edge]:
        """Edges leaving ``node``.

        Without history: every non-superseded edge, *including* rejected ones, so callers
        can respect the user's decisions. Filter with ``Edge.is_current`` for retrieval.
        """
        ...

    def edges_to(self, node: NodeId, *, include_history: bool = False) -> Sequence[Edge]: ...

    def all_edges(self) -> Sequence[Edge]:
        """Every edge ever recorded, history included, in the order they were recorded."""
        ...

    # -- whole-graph operations -----------------------------------------------
    def remove_node(self, node: NodeId) -> None:
        """Remove a node and leave its edges alone (callers supersede the live ones first).

        For a provisional person merged into a permanent identity, or a topic the author
        renamed: the node is gone, the history of what was linked to it stays.
        """
        ...

    def erase_nodes(self, nodes: Collection[NodeId]) -> None:
        """Erase nodes and every edge that touches them, history included.

        The one exception to "history is never deleted": when the author deletes an
        article or a person, nothing about them may remain, in the index or its history.
        """
        ...

    def replace_graph(self, contents: GraphContents) -> None:
        """Atomically replace every node and edge with ``contents``.

        Edges are applied in order with the same rules as :meth:`save_edge` and
        :meth:`supersede_edge`, so ``replace_graph`` of a graph's own contents changes
        nothing.
        """
        ...
