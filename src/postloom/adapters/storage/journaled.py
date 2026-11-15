"""A GraphRepository that also records every edge write in the vault's journal.

Wrapping the repository (instead of asking each use case to remember the journal) is what
guarantees the vault never misses a decision: there is no other way to write an edge.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from postloom.application.ports.journal import EdgeJournal
from postloom.application.ports.repository import GraphContents, GraphRepository
from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.discussion import Comment
from postloom.domain.graph import Edge, NodeId
from postloom.domain.people import Person


class JournaledRepository:
    def __init__(self, inner: GraphRepository, journal: EdgeJournal) -> None:
        self._inner = inner
        self._journal = journal

    # -- edges: recorded ----------------------------------------------------------
    def save_edge(self, edge: Edge) -> None:
        self._inner.save_edge(edge)
        self._journal.append(edge)

    def supersede_edge(self, edge: Edge) -> None:
        self._inner.supersede_edge(edge)
        self._journal.append(edge)

    def erase_nodes(self, nodes: Collection[NodeId]) -> None:
        self._inner.erase_nodes(nodes)
        # Erasing means the lines are gone from the file too, not just marked.
        self._journal.rewrite(self._inner.all_edges())

    def replace_graph(self, contents: GraphContents) -> None:
        self._inner.replace_graph(contents)
        self._journal.rewrite(self._inner.all_edges())

    # -- everything else: passed through -------------------------------------------
    def list_topics(self) -> Sequence[Topic]:
        return self._inner.list_topics()

    def save_topic(self, topic: Topic) -> None:
        self._inner.save_topic(topic)

    def get_article(self, article_id: NodeId) -> Article | None:
        return self._inner.get_article(article_id)

    def save_article(self, article: Article) -> None:
        self._inner.save_article(article)

    def list_articles(self) -> Sequence[Article]:
        return self._inner.list_articles()

    def get_post(self, post_id: NodeId) -> Post | None:
        return self._inner.get_post(post_id)

    def save_post(self, post: Post) -> None:
        self._inner.save_post(post)

    def list_posts(self) -> Sequence[Post]:
        return self._inner.list_posts()

    def save_series(self, series: Series) -> None:
        self._inner.save_series(series)

    def get_comment(self, comment_id: NodeId) -> Comment | None:
        return self._inner.get_comment(comment_id)

    def save_comment(self, comment: Comment) -> None:
        self._inner.save_comment(comment)

    def comments_on(self, post: NodeId) -> Sequence[Comment]:
        return self._inner.comments_on(post)

    def get_person(self, person_id: NodeId) -> Person | None:
        return self._inner.get_person(person_id)

    def save_person(self, person: Person) -> None:
        self._inner.save_person(person)

    def list_people(self) -> Sequence[Person]:
        return self._inner.list_people()

    def edges_from(self, node: NodeId, *, include_history: bool = False) -> Sequence[Edge]:
        return self._inner.edges_from(node, include_history=include_history)

    def edges_to(self, node: NodeId, *, include_history: bool = False) -> Sequence[Edge]:
        return self._inner.edges_to(node, include_history=include_history)

    def all_edges(self) -> Sequence[Edge]:
        return self._inner.all_edges()

    def remove_node(self, node: NodeId) -> None:
        self._inner.remove_node(node)
