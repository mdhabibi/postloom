"""PeopleDirectory / UpdatePerson: who engages with your writing, and your conversations.

A person pasted without a profile link has a provisional identity based on their name.
Adding the link later merges them into a permanent identity: their comments are
re-attributed, the old authorship links are superseded (kept as history), and the
provisional record is removed. If someone with that link already exists, the two are
combined.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from postloom.application.errors import ApplicationError
from postloom.application.ports.clock import Clock
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.vault import Vault
from postloom.application.use_cases.browse_content import CommentView, comment_views
from postloom.domain.content import Article
from postloom.domain.discussion import Comment
from postloom.domain.errors import InvalidProfileUrlError
from postloom.domain.graph import Edge, EdgeKind, NodeId
from postloom.domain.people import Person, ProfileObservation, ProfileUrl
from postloom.domain.provenance import Grade, Origin, Provenance


@dataclass(frozen=True, slots=True)
class PersonSummary:
    id: NodeId
    name: str
    headline: str | None
    profile_url: str | None
    messages: int
    articles: int


@dataclass(frozen=True, slots=True)
class Conversation:
    """The threads under one article that this person took part in."""

    article_id: NodeId
    article_title: str
    messages: tuple[CommentView, ...]


@dataclass(frozen=True, slots=True)
class PersonDetail:
    summary: PersonSummary
    observations: tuple[ProfileObservation, ...]
    notes: str
    tags: tuple[str, ...]
    conversations: tuple[Conversation, ...]


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


class PeopleDirectory:
    def __init__(self, repository: GraphRepository) -> None:
        self._repository = repository

    def list_people(self) -> list[PersonSummary]:
        people = [self._summarize(p) for p in self._repository.list_people()]
        people.sort(key=lambda p: p.name.casefold())
        people.sort(key=lambda p: (p.messages, p.articles), reverse=True)
        return people

    def get_person(self, person_id: NodeId) -> PersonDetail | None:
        person = self._repository.get_person(person_id)
        if person is None:
            return None
        return PersonDetail(
            summary=self._summarize(person),
            observations=person.observations,
            notes=person.notes,
            tags=person.tags,
            conversations=tuple(self._conversations(person_id)),
        )

    def _summarize(self, person: Person) -> PersonSummary:
        comments = comments_by(self._repository, person.id)
        posts = {c.post for c in comments}
        return PersonSummary(
            id=person.id,
            name=person.name,
            headline=person.headline,
            profile_url=person.profile.url if person.profile else None,
            messages=len(comments),
            articles=len(posts),
        )

    def _conversations(self, person_id: NodeId) -> list[Conversation]:
        mine = comments_by(self._repository, person_id)
        conversations: list[Conversation] = []
        for post in dict.fromkeys(c.post for c in mine):
            article = article_of_post(self._repository, post)
            everything = list(self._repository.comments_on(post))
            threads = {c.thread or c.id for c in mine if c.post == post}
            involved = [c for c in everything if (c.thread or c.id) in threads]
            conversations.append(
                Conversation(
                    article_id=article.id if article else post,
                    article_title=article.title if article else "Untitled post",
                    messages=comment_views(self._repository, involved),
                )
            )
        return conversations


class UpdatePerson:
    def __init__(self, repository: GraphRepository, vault: Vault, clock: Clock) -> None:
        self._repository = repository
        self._vault = vault
        self._clock = clock

    def execute(
        self,
        person_id: NodeId,
        *,
        profile_url: str | None = None,
        notes: str | None = None,
        tags: Sequence[str] | None = None,
    ) -> NodeId:
        """Apply the given changes (None = leave unchanged). Returns the person's id,
        which changes when a provisional person gets a profile link."""
        person = self._repository.get_person(person_id)
        if person is None:
            raise ApplicationError(f"Unknown person: {person_id}")
        if notes is not None:
            person = replace(person, notes=notes.strip())
        if tags is not None:
            cleaned = (t.strip() for t in tags if t.strip())
            person = replace(person, tags=tuple(dict.fromkeys(cleaned)))
        if profile_url is not None and profile_url.strip():
            person = person.with_profile(_parse(profile_url))

        if person.id == person_id:
            self._repository.save_person(person)
        else:
            person = self._merge(person_id, person, self._clock.now())
        self._vault.write_person(person, articles_discussed_by(self._repository, person.id))
        return person.id

    def _merge(self, old_id: NodeId, person: Person, now: datetime) -> Person:
        existing = self._repository.get_person(person.id)
        if existing is not None:
            person = _combine(existing, person)
        self._repository.save_person(person)

        moved = Provenance(Origin.MANUAL, Grade.VERIFIED, "user", now, "profile link added")
        for edge in self._repository.edges_from(old_id):
            if edge.kind is not EdgeKind.AUTHORED or not edge.is_current:
                continue
            comment = self._repository.get_comment(edge.target)
            if comment is not None:
                self._repository.save_comment(replace(comment, author=person.id))
            self._repository.supersede_edge(edge.supersede(now))
            self._repository.save_edge(Edge(person.id, edge.target, EdgeKind.AUTHORED, moved))

        old = self._repository.get_person(old_id)
        if old is not None:
            self._vault.remove_person(old)
        self._repository.delete_person(old_id)
        return person


def _parse(url: str) -> ProfileUrl:
    try:
        return ProfileUrl.parse(url)
    except InvalidProfileUrlError as error:
        raise ApplicationError(str(error)) from error


def _combine(kept: Person, incoming: Person) -> Person:
    """Merge two records of the same person; nothing either of them knew is lost."""
    seen = Counter((o.headline, o.observed_at) for o in kept.observations)
    extra = tuple(o for o in incoming.observations if not seen[(o.headline, o.observed_at)])
    observations = tuple(sorted((*kept.observations, *extra), key=lambda o: o.observed_at))
    notes = "\n\n".join(n for n in (kept.notes, incoming.notes) if n)
    tags = tuple(dict.fromkeys((*kept.tags, *incoming.tags)))
    return replace(kept, observations=observations, notes=notes, tags=tags)
