"""Port for the graph index (nodes and edges).

The Markdown vault is the source of truth; the repository is a queryable index that can
always be rebuilt from the vault. Implementations: in-memory (tests, reference) and
SQLite (default). Every implementation must pass ``tests/contract/test_repository.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.graph import Edge, NodeId


class GraphRepository(Protocol):
    # -- topics ---------------------------------------------------------------
    def list_topics(self) -> Sequence[Topic]: ...

    def save_topic(self, topic: Topic) -> None: ...

    # -- content --------------------------------------------------------------
    def get_article(self, article_id: NodeId) -> Article | None: ...

    def save_article(self, article: Article) -> None: ...

    def get_post(self, post_id: NodeId) -> Post | None: ...

    def save_post(self, post: Post) -> None: ...

    def save_series(self, series: Series) -> None: ...

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
