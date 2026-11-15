"""Reads and writes of an article's relations that more than one use case needs.

The same functions apply a change whether it was made in the app or by editing a note,
so the two can never follow different rules.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import replace
from datetime import datetime

from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.vault import Vault
from postloom.application.use_cases.links import related_edges, rewrite_article_note
from postloom.domain.content import Article, Post, Topic
from postloom.domain.discussion import Comment
from postloom.domain.graph import Edge, EdgeKind, NodeId
from postloom.domain.provenance import Grade, Origin, Provenance

__all__ = [
    "article_of_post",
    "articles_discussed_by",
    "comments_by",
    "current_topics",
    "post_of",
    "set_series",
    "set_topics",
    "write_article_note",
    "write_discussion_note",
    "write_mentions",
    "write_person_note",
]

write_article_note = rewrite_article_note


def post_of(repository: GraphRepository, article_id: NodeId) -> Post | None:
    """The post that announces an article."""
    for edge in repository.edges_to(article_id):
        if edge.kind is EdgeKind.ANNOUNCES and edge.is_current:
            post = repository.get_post(edge.source)
            if post is not None:
                return post
    return None


def comments_by(repository: GraphRepository, person_id: NodeId) -> list[Comment]:
    found: list[Comment] = []
    for edge in repository.edges_from(person_id):
        if edge.kind is EdgeKind.AUTHORED and edge.is_current:
            comment = repository.get_comment(edge.target)
            if comment is not None:
                found.append(comment)
    return found


def article_of_post(repository: GraphRepository, post: NodeId) -> Article | None:
    for edge in repository.edges_from(post):
        if edge.kind is EdgeKind.ANNOUNCES and edge.is_current:
            return repository.get_article(edge.target)
    return None


def articles_discussed_by(repository: GraphRepository, person_id: NodeId) -> list[Article]:
    articles: dict[NodeId, Article] = {}
    for post in dict.fromkeys(c.post for c in comments_by(repository, person_id)):
        article = article_of_post(repository, post)
        if article is not None:
            articles.setdefault(article.id, article)
    return list(articles.values())


def current_topics(repository: GraphRepository, article_id: NodeId) -> list[Topic]:
    taxonomy = {t.id: t for t in repository.list_topics()}
    return [
        taxonomy[edge.target]
        for edge in repository.edges_from(article_id)
        if edge.kind is EdgeKind.BELONGS_TO and edge.is_current and edge.target in taxonomy
    ]


def set_topics(
    repository: GraphRepository,
    article_id: NodeId,
    wanted: Collection[NodeId],
    now: datetime,
    *,
    producer: str,
    confirm: bool,
) -> bool:
    """Make ``wanted`` the article's topics, as the author's decision. True if changed.

    A topic that is added is verified; one that is taken away is rejected, so a later
    re-ingest doesn't bring it back. With ``confirm``, topics a model had only suggested
    and the author kept become verified too (they looked at the list and saved it).
    """
    existing = {
        e.target: e for e in repository.edges_from(article_id) if e.kind is EdgeKind.BELONGS_TO
    }
    changed = False
    for topic in wanted:
        old = existing.get(topic)
        if old is not None and old.is_current:
            if not (confirm and old.provenance.grade is Grade.ASSERTED):
                continue
            new = replace(old, provenance=old.provenance.verified(now, producer))
        else:
            manual = Provenance(Origin.MANUAL, Grade.VERIFIED, producer, now)
            new = Edge(article_id, topic, EdgeKind.BELONGS_TO, manual)
        if old is not None:
            repository.supersede_edge(old.supersede(now))
        repository.save_edge(new)
        changed = True
    for topic, old in existing.items():
        if topic in wanted or not old.is_current:
            continue
        repository.supersede_edge(old.supersede(now))
        repository.save_edge(replace(old, provenance=old.provenance.rejected(now, producer)))
        changed = True
    return changed


def set_series(
    repository: GraphRepository, article: Article, now: datetime, *, producer: str
) -> bool:
    """Make the article's ``part_of`` link match its ``series`` field. True if changed."""
    wanted = article.series.id if article.series is not None else None
    changed = False
    linked = False
    for edge in repository.edges_from(article.id):
        if edge.kind is not EdgeKind.PART_OF or not edge.is_current:
            continue
        if edge.target == wanted:
            linked = True
        else:
            repository.supersede_edge(edge.supersede(now))
            changed = True
    if article.series is not None and not linked:
        repository.save_series(article.series)
        manual = Provenance(Origin.MANUAL, Grade.VERIFIED, producer, now)
        repository.save_edge(Edge(article.id, article.series.id, EdgeKind.PART_OF, manual))
        changed = True
    return changed


def write_discussion_note(
    repository: GraphRepository, vault: Vault, article: Article, post: Post
) -> None:
    comments = repository.comments_on(post.id)
    people = {
        c.author: person
        for c in comments
        if (person := repository.get_person(c.author)) is not None
    }
    vault.write_discussion(article, post, comments, people)


def write_person_note(repository: GraphRepository, vault: Vault, person_id: NodeId) -> None:
    person = repository.get_person(person_id)
    if person is not None:
        vault.write_person(person, articles_discussed_by(repository, person_id))


def write_mentions(repository: GraphRepository, vault: Vault, article: Article) -> None:
    """Rewrite the notes that show this article's title in a link, after it was retitled:
    related articles, its discussion and the people who took part in it."""
    for edge in related_edges(repository, article.id):
        other = edge.target if edge.source == article.id else edge.source
        rewrite_article_note(repository, vault, other)
    post = post_of(repository, article.id)
    if post is None:
        return
    comments = repository.comments_on(post.id)
    if comments:
        write_discussion_note(repository, vault, article, post)
    for author in dict.fromkeys(c.author for c in comments if not c.is_own):
        write_person_note(repository, vault, author)
