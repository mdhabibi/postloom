"""Curating the library: fix an article's details, manage topics, delete things.

Deleting is the one place where history is not kept. An article or a person the author
deletes is erased everywhere: the index, the history of their links, the search index
and the notes. For people this is what data-protection law expects (a commenter can ask
to be removed); for articles it is simply what "delete" means.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import date

from postloom.application.errors import ApplicationError, BudgetExceededError, ProviderError
from postloom.application.ports.clock import Clock
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.search_index import SearchIndex
from postloom.application.ports.vault import Vault
from postloom.application.use_cases.index_content import IndexArticle
from postloom.application.use_cases.links import related_edges
from postloom.application.use_cases.relations import (
    article_of_post,
    post_of,
    set_series,
    set_topics,
    write_article_note,
    write_discussion_note,
    write_mentions,
    write_person_note,
)
from postloom.domain.content import Article, Series, Topic
from postloom.domain.discussion import OWNER, without_authors
from postloom.domain.graph import Edge, EdgeKind, NodeId
from postloom.domain.provenance import Grade, Origin, Provenance

USER = "user"


class _Unset:
    """Marks "leave this field as it is", where None means "clear it"."""


UNSET = _Unset()


def _article(repository: GraphRepository, article_id: NodeId) -> Article:
    article = repository.get_article(article_id)
    if article is None:
        raise ApplicationError(f"Unknown article: {article_id}")
    return article


def _topic(repository: GraphRepository, topic_id: NodeId) -> Topic:
    for topic in repository.list_topics():
        if topic.id == topic_id:
            return topic
    raise ApplicationError(f"Unknown topic: {topic_id}")


def _articles_in(repository: GraphRepository, topic_id: NodeId) -> list[NodeId]:
    """Articles with any live link to the topic (current or rejected)."""
    return list(
        dict.fromkeys(
            e.source for e in repository.edges_to(topic_id) if e.kind is EdgeKind.BELONGS_TO
        )
    )


# -- articles ------------------------------------------------------------------------
class UpdateArticle:
    """Fix what the model got wrong: title, summary, topics, series, date, URL."""

    def __init__(
        self,
        repository: GraphRepository,
        vault: Vault,
        index_article: IndexArticle,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._index_article = index_article
        self._clock = clock

    def execute(
        self,
        article_id: NodeId,
        *,
        title: str | None = None,
        summary: str | None = None,
        topics: Sequence[str] | None = None,
        series: str | _Unset | None = UNSET,
        series_part: int | _Unset | None = UNSET,
        url: str | _Unset | None = UNSET,
        published_on: date | _Unset | None = UNSET,
    ) -> Article:
        """Apply the given changes. ``topics`` are topic names; None leaves them alone."""
        repo = self._repository
        old = _article(repo, article_id)
        article = replace(old, key=old.slug)  # pin the identity before the title changes
        if title is not None:
            if not title.strip():
                raise ApplicationError("An article needs a title.")
            article = replace(article, title=title.strip())
        if summary is not None:
            article = replace(article, summary=summary.strip())
        if not isinstance(series, _Unset):
            name = (series or "").strip()
            article = replace(article, series=Series(name) if name else None)
        if not isinstance(series_part, _Unset):
            article = replace(article, series_part=series_part)
        if article.series is None:
            article = replace(article, series_part=None)
        if not isinstance(url, _Unset):
            article = replace(article, url=(url or "").strip() or None)
        if not isinstance(published_on, _Unset):
            article = replace(article, published_on=published_on)

        now = self._clock.now()
        repo.save_article(article)
        set_series(repo, article, now, producer=USER)
        if topics is not None:
            by_name = {t.name.casefold(): t for t in repo.list_topics()}
            wanted: list[NodeId] = []
            for name in topics:
                topic = by_name.get(name.strip().casefold())
                if topic is None:
                    raise ApplicationError(f"Unknown topic: {name}. Add it in Settings first.")
                wanted.append(topic.id)
            set_topics(repo, article.id, wanted, now, producer=USER, confirm=True)

        write_article_note(repo, self._vault, article.id)
        if article.title != old.title:
            write_mentions(repo, self._vault, article)
        if (article.title, article.summary) != (old.title, old.summary):
            self._index_article.execute(article.id)
        return article


class DeleteArticle:
    def __init__(self, repository: GraphRepository, vault: Vault, index: SearchIndex) -> None:
        self._repository = repository
        self._vault = vault
        self._index = index

    def execute(self, article_id: NodeId) -> Article:
        """Erase an article, its post and every comment under it. People are kept."""
        repo = self._repository
        article = _article(repo, article_id)
        post = post_of(repo, article_id)
        comments = list(repo.comments_on(post.id)) if post is not None else []
        related = {
            edge.target if edge.source == article_id else edge.source
            for edge in related_edges(repo, article_id)
        }
        authors = list(dict.fromkeys(c.author for c in comments if not c.is_own))

        gone: list[NodeId] = [article_id, *(c.id for c in comments)]
        if post is not None:
            gone.append(post.id)
        last_of_series = article.series is not None and not any(
            a.series == article.series for a in repo.list_articles() if a.id != article_id
        )
        if article.series is not None and last_of_series:
            gone.append(article.series.id)
        repo.erase_nodes(gone)
        self._index.remove(article_id)
        if post is not None:
            self._index.remove(post.id)

        self._vault.remove_article(article, post)
        for other in related:
            write_article_note(repo, self._vault, other)
        for author in authors:
            write_person_note(repo, self._vault, author)
        return article


# -- people --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PersonDeleted:
    name: str
    comments: int
    """How many of their messages were erased."""


class DeletePerson:
    def __init__(
        self,
        repository: GraphRepository,
        vault: Vault,
        index_article: IndexArticle,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._index_article = index_article
        self._clock = clock

    def execute(self, person_id: NodeId) -> PersonDeleted:
        """Erase a person and everything they wrote.

        Conversations they took part in stay readable: a reply to one of their messages
        is re-attached to the message above it. Your own replies are kept as you wrote
        them, so they may still mention the person by name.
        """
        repo = self._repository
        person = repo.get_person(person_id)
        if person is None or person_id == OWNER:
            raise ApplicationError(f"Unknown person: {person_id}")

        now = self._clock.now()
        erased: list[NodeId] = [person_id]
        rewritten: list[NodeId] = []
        relinked: list[Edge] = []
        fact = Provenance(Origin.STRUCTURAL, Grade.VERIFIED, "delete", now)
        for post in repo.list_posts():
            comments = list(repo.comments_on(post.id))
            if not any(c.author == person_id for c in comments):
                continue
            kept = without_authors(comments, {person_id})
            before = {c.id: c for c in comments}
            erased += [c.id for c in comments if c.author == person_id]
            for comment in kept:
                if comment == before[comment.id]:
                    continue
                repo.save_comment(comment)
                if comment.reply_to != before[comment.id].reply_to and comment.reply_to:
                    relinked.append(Edge(comment.id, comment.reply_to, EdgeKind.REPLIED_TO, fact))
            rewritten.append(post.id)

        repo.erase_nodes(erased)
        for edge in relinked:
            repo.save_edge(edge)
        self._vault.remove_person(person)
        for post_id in rewritten:
            post = repo.get_post(post_id)
            article = article_of_post(repo, post_id)
            if post is not None and article is not None:
                write_discussion_note(repo, self._vault, article, post)
                # Their words must leave the search index too. If the provider fails, the
                # keyword index has already been replaced, which is what matters here.
                with suppress(ProviderError, BudgetExceededError):
                    self._index_article.execute(article.id)
        return PersonDeleted(person.name, len(erased) - 1)


# -- topics --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TopicUsage:
    topic: Topic
    articles: int
    """How many articles currently belong to it."""


class ManageTopics:
    """Add, describe, rename, merge and remove the author's topics."""

    def __init__(self, repository: GraphRepository, vault: Vault, clock: Clock) -> None:
        self._repository = repository
        self._vault = vault
        self._clock = clock

    def list(self) -> list[TopicUsage]:
        """Every topic with its number of articles, by name."""
        repo = self._repository
        usage = [
            TopicUsage(
                topic,
                sum(
                    1
                    for e in repo.edges_to(topic.id)
                    if e.kind is EdgeKind.BELONGS_TO and e.is_current
                ),
            )
            for topic in repo.list_topics()
        ]
        return sorted(usage, key=lambda u: u.topic.name.casefold())

    def add(self, name: str, description: str = "") -> Topic:
        topic = Topic(_clean_name(name), description.strip())
        if any(t.id == topic.id for t in self._repository.list_topics()):
            raise ApplicationError(f'You already have a topic called "{topic.name}".')
        self._repository.save_topic(topic)
        self._vault.write_topic(topic)
        return topic

    def update(
        self, topic_id: NodeId, *, name: str | None = None, description: str | None = None
    ) -> Topic:
        """Change a topic. Renaming it to the name of another topic merges the two."""
        repo, vault = self._repository, self._vault
        old = _topic(repo, topic_id)
        new = Topic(
            _clean_name(name) if name is not None else old.name,
            description.strip() if description is not None else old.description,
        )
        if new == old:
            return old
        articles = _articles_in(repo, old.id)
        if new.id == old.id:  # same identity: a description, or a change of capitals
            repo.save_topic(new)
        else:
            target = next((t for t in repo.list_topics() if t.id == new.id), None)
            if target is not None:  # merge into the existing topic, which keeps its text
                new = replace(target, description=target.description or new.description)
            repo.save_topic(new)
            self._move_links(old, new)
            repo.remove_node(old.id)
        if new.name != old.name:
            vault.remove_topic(old)  # the note is named after the topic
        vault.write_topic(new)
        for article_id in articles:
            write_article_note(repo, vault, article_id)
        return new

    def delete(self, topic_id: NodeId) -> Topic:
        """Remove a topic. Articles stay; they just no longer belong to it."""
        repo = self._repository
        topic = _topic(repo, topic_id)
        articles = _articles_in(repo, topic.id)
        now = self._clock.now()
        for edge in repo.edges_to(topic.id):
            repo.supersede_edge(edge.supersede(now))
        repo.remove_node(topic.id)
        self._vault.remove_topic(topic)
        for article_id in articles:
            write_article_note(repo, self._vault, article_id)
        return topic

    def _move_links(self, old: Topic, new: Topic) -> None:
        """Re-point every article from ``old`` to ``new``, keeping each link's standing
        (suggested, confirmed or rejected). Where an article already belongs to ``new``,
        that link wins; a rejection of ``new`` gives way to a live link to ``old``."""
        repo = self._repository
        now = self._clock.now()
        for edge in repo.edges_to(old.id):
            repo.supersede_edge(edge.supersede(now))
            if edge.kind is not EdgeKind.BELONGS_TO:
                continue
            existing = next(
                (
                    e
                    for e in repo.edges_from(edge.source)
                    if e.target == new.id and e.kind is EdgeKind.BELONGS_TO
                ),
                None,
            )
            if existing is not None and (existing.is_current or not edge.is_current):
                continue
            if existing is not None:  # a rejection of ``new`` gives way to a live ``old``
                repo.supersede_edge(existing.supersede(now))
            provenance = replace(
                edge.provenance, recorded_at=now, evidence=f"topic renamed from {old.name}"
            )
            repo.save_edge(Edge(edge.source, new.id, EdgeKind.BELONGS_TO, provenance))


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ApplicationError("A topic needs a name.")
    if len(cleaned) > 60:
        raise ApplicationError("Topic names can be at most 60 characters.")
    return cleaned
