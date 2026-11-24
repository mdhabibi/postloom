"""Finding what an article or post names, and adding what the user confirms to the graph.

1. ``FindMentions`` proposes people, organisations, places, events, projects, datasets,
   methods and links, plus topics. Links are parsed, never guessed. A model proposes the
   rest, and postloom keeps a name only if it appears in the text. The author themselves,
   what is already confirmed or was turned down, and repeats are left out. Each proposal
   is matched to what the graph already has ("same as Jane, who commented on 3 posts").
2. The proposals wait as a review (a cache in the index) until the user decides.
3. ``ConfirmMentions`` adds what the user accepted, possibly renamed or recategorised, as
   verified ``mentions`` links, and remembers what they turned down for this item.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date

from postloom.application.errors import ApplicationError
from postloom.application.ports.clock import Clock
from postloom.application.ports.extraction import MentionFinder
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.reviews import Review, ReviewStore, Suggestion, TopicSuggestion
from postloom.application.ports.vault import Vault
from postloom.application.use_cases.curation import UNSET, Unset
from postloom.application.use_cases.relations import (
    Item,
    current_topics,
    discussion_post,
    get_item,
    items_discussed_by,
    mention_edges,
    mentioned_in,
    set_topics,
    write_entity_note,
    write_item_note,
    write_mentioned_notes,
)
from postloom.domain.content import Post, Topic
from postloom.domain.entities import PERSON, Category, Entity, same_name
from postloom.domain.graph import Edge, EdgeKind, NodeId, NodeKind, kind_of
from postloom.domain.people import Person, ProfileUrl
from postloom.domain.provenance import Grade, Origin, Provenance
from postloom.domain.text import extract_urls, mentions, sentence_with, slugify, web_url

CATEGORIES = (PERSON, *(c.value for c in Category))
_TITLES = frozenset({"dr", "dr.", "prof", "prof.", "mr", "mr.", "ms", "ms.", "mrs", "mrs."})
MAX_TOPICS = 3


def item_text(repository: GraphRepository, item: Item) -> str:
    """The text postloom reads for an item: an article with the post announcing it."""
    if isinstance(item, Post):
        return item.text
    post = discussion_post(repository, item.id)
    return item.body_markdown + (f"\n\n{post.text}" if post is not None else "")


def link_name(url: str) -> str:
    shown = url.split("://", 1)[-1].removeprefix("www.")
    return shown.rstrip("/")


def _is_profile_or_tag(url: str) -> bool:
    lowered = url.lower()
    return "linkedin.com/in/" in lowered or "linkedin.com/feed/hashtag" in lowered


def is_owner(name: str, owner_name: str | None) -> bool:
    """True for the author's own name, also with a title ("Dr. Jane Example")."""
    if not owner_name:
        return False
    words = [w for w in same_name(name).split() if w not in _TITLES]
    owner = [w for w in same_name(owner_name).split() if w not in _TITLES]
    return bool(owner) and words == owner


def clean_name(name: str) -> str:
    words = name.split()
    while words and words[0].casefold() in _TITLES:
        words = words[1:]
    return " ".join(words).strip(" ,;:")


class FindMentions:
    def __init__(
        self,
        finder: MentionFinder | None,
        repository: GraphRepository,
        reviews: ReviewStore,
        clock: Clock,
    ) -> None:
        self._finder = finder
        self._repository = repository
        self._reviews = reviews
        self._clock = clock

    def execute(self, item_id: NodeId, owner_name: str | None = None) -> Review:
        repo = self._repository
        item = get_item(repo, item_id)
        if item is None:
            raise ApplicationError(f"Unknown article or post: {item_id}")
        text = item_text(repo, item)
        previous = self._reviews.get(item_id)
        refused: set[str] = self._decided_names(item_id)
        if previous is not None:
            refused |= {same_name(n) for n in previous.dismissed}

        found: list[Suggestion] = []
        seen: set[tuple[str, str]] = set()

        def keep(suggestion: Suggestion) -> None:
            key = (suggestion.category, same_name(suggestion.url or suggestion.name))
            if same_name(suggestion.name) in refused or key in seen:
                return
            seen.add(key)
            found.append(self._matched(suggestion))

        topics: list[TopicSuggestion] = []
        if self._finder is not None:
            taxonomy = tuple(t.name for t in repo.list_topics())
            result = self._finder.find(text, taxonomy, owner_name)
            for mention in result.mentions:
                name = clean_name(mention.name)
                if not name or not mentions(text, name) or is_owner(name, owner_name):
                    continue  # not in the text: the model made it up
                evidence = mention.evidence.strip()
                if not evidence or not mentions(evidence, name) or evidence not in text:
                    evidence = sentence_with(text, name)
                keep(Suggestion(name, mention.category, evidence))
            topics = self._topics(item_id, result.topics, result.new_topics, taxonomy)
        for url in extract_urls(text):
            if not _is_profile_or_tag(url):
                keep(Suggestion(link_name(url), Category.LINK.value, "", url=url))

        review = Review(
            item=item_id,
            suggestions=tuple(found),
            topics=tuple(topics),
            found_at=self._clock.now(),
            finder=self._finder.name if self._finder is not None else None,
            dismissed=previous.dismissed if previous else (),
        )
        self._reviews.put(review)
        return review

    def _decided_names(self, item_id: NodeId) -> set[str]:
        """Names already confirmed or turned down for this item (live or rejected)."""
        names: set[str] = set()
        for edge in self._repository.edges_from(item_id):
            if edge.kind is not EdgeKind.MENTIONS:
                continue
            names.update(same_name(n) for n in _names_of(self._repository, edge.target))
        return names

    def _matched(self, suggestion: Suggestion) -> Suggestion:
        repo = self._repository
        if suggestion.category == PERSON:
            wanted = same_name(suggestion.name)
            for person in repo.list_people():
                if same_name(person.name) == wanted:
                    talked = len(items_discussed_by(repo, person.id))
                    noted = len(mentioned_in(repo, person.id))
                    note = (
                        f"commented on {talked} of your posts"
                        if talked
                        else f"mentioned in {noted} of your posts"
                        if noted
                        else "already in your graph"
                    )
                    return replace(
                        suggestion, match=person.id, match_name=person.name, match_note=note
                    )
            return suggestion
        for entity in repo.list_entities():
            same = (
                entity.url == suggestion.url
                if suggestion.url
                else entity.is_called(suggestion.name)
            )
            if same:
                count = len(mentioned_in(repo, entity.id))
                return replace(
                    suggestion,
                    match=entity.id,
                    match_name=entity.name,
                    match_note=f"mentioned in {count} of your posts",
                )
        return suggestion

    def _topics(
        self,
        item_id: NodeId,
        chosen: Sequence[str],
        new: Sequence[str],
        taxonomy: Sequence[str],
    ) -> list[TopicSuggestion]:
        have = {same_name(t.name) for t in current_topics(self._repository, item_id)}
        rejected = {
            same_name(t.name)
            for t in self._repository.list_topics()
            for e in self._repository.edges_from(item_id)
            if e.kind is EdgeKind.BELONGS_TO and e.target == t.id and not e.is_current
        }
        known = {same_name(t): t for t in taxonomy}
        out: list[TopicSuggestion] = []
        for name in [*chosen, *new]:
            name = " ".join(name.split())[:60]
            key = same_name(name)
            repeated = any(same_name(o.name) == key for o in out)
            if not key or key in have or key in rejected or repeated:
                continue
            out.append(TopicSuggestion(known.get(key, name), exists=key in known))
        return out[: MAX_TOPICS * 2]


@dataclass(frozen=True, slots=True)
class Accepted:
    name: str
    category: str
    evidence: str = ""
    url: str | None = None
    match: NodeId | None = None
    """Join this existing person or entity instead of adding a new one."""
    found_as: str | None = None
    """The name it was found under, when the user changed it; kept as another name."""


@dataclass(frozen=True, slots=True)
class Confirmed:
    added: tuple[NodeId, ...]
    topics: tuple[str, ...]
    review: Review | None


class ConfirmMentions:
    def __init__(
        self, repository: GraphRepository, vault: Vault, reviews: ReviewStore, clock: Clock
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._reviews = reviews
        self._clock = clock

    def execute(
        self,
        item_id: NodeId,
        accepted: Sequence[Accepted],
        dismissed: Sequence[str] = (),
        topics: Sequence[str] = (),
    ) -> Confirmed:
        repo = self._repository
        item = get_item(repo, item_id)
        if item is None:
            raise ApplicationError(f"Unknown article or post: {item_id}")
        now = self._clock.now()
        added: list[NodeId] = []
        for choice in accepted:
            name = clean_name(choice.name)
            if not name:
                raise ApplicationError("A name can't be empty.")
            if choice.category not in CATEGORIES:
                raise ApplicationError(f"Unknown category: {choice.category}")
            target = (
                self._person(name, choice)
                if choice.category == PERSON
                else self._entity(name, Category(choice.category), choice)
            )
            evidence = choice.evidence.strip()[:500] or None
            provenance = Provenance(Origin.MANUAL, Grade.VERIFIED, "user", now, evidence)
            repo.save_edge(Edge(item_id, target, EdgeKind.MENTIONS, provenance))
            added.append(target)

        topic_names = self._add_topics(item, topics)
        write_mentioned_notes(repo, self._vault, added)
        review = self._settle(item_id, accepted, dismissed)
        return Confirmed(tuple(dict.fromkeys(added)), tuple(topic_names), review)

    def _person(self, name: str, choice: Accepted) -> NodeId:
        repo = self._repository
        match = choice.match
        if match and kind_of(match) is NodeKind.PERSON and repo.get_person(match) is not None:
            return match
        for person in repo.list_people():
            if same_name(person.name) == same_name(name):
                return person.id
        profile = None
        if choice.url and "linkedin.com/in/" in choice.url.lower():
            try:
                profile = ProfileUrl.parse(choice.url)
            except ValueError:
                profile = None
        person = Person(name, profile)
        if repo.get_person(person.id) is None:
            repo.save_person(person)
        return person.id

    def _entity(self, name: str, category: Category, choice: Accepted) -> NodeId:
        repo = self._repository
        entity: Entity | None = None
        if choice.match is not None and kind_of(choice.match) is NodeKind.ENTITY:
            entity = repo.get_entity(choice.match)
        if entity is None:
            entity = next(
                (
                    e
                    for e in repo.list_entities()
                    if (choice.url and e.url == choice.url) or e.is_called(name)
                ),
                None,
            )
        names = [n for n in (name, choice.found_as) if n]
        if entity is None:
            key = _free_key(repo, slugify(name) or "entity")
            entity = Entity(key, name, category, choice.url)
        for other in names:  # what the user called it here, and what it was found as
            if not entity.is_called(other):
                entity = replace(entity, aliases=(*entity.aliases, other))
        repo.save_entity(entity)
        return entity.id

    def _add_topics(self, item: Item, names: Sequence[str]) -> list[str]:
        repo = self._repository
        if not names:
            return []
        existing = {same_name(t.name): t for t in repo.list_topics()}
        chosen: list[Topic] = []
        for raw in names:
            name = " ".join(raw.split())[:60]
            if not name:
                continue
            topic = existing.get(same_name(name))
            if topic is None:
                topic = Topic(name)
                repo.save_topic(topic)
                self._vault.write_topic(topic)
                existing[same_name(name)] = topic
            chosen.append(topic)
        wanted = {t.id for t in current_topics(repo, item.id)} | {t.id for t in chosen}
        set_topics(repo, item.id, wanted, self._clock.now(), producer="user", confirm=False)
        write_item_note(repo, self._vault, item.id)
        return [t.name for t in chosen]

    def _settle(
        self, item_id: NodeId, accepted: Sequence[Accepted], dismissed: Sequence[str]
    ) -> Review | None:
        review = self._reviews.get(item_id)
        if review is None:
            return None
        decided = {same_name(a.name) for a in accepted} | {same_name(d) for d in dismissed}
        decided |= {same_name(a.found_as) for a in accepted if a.found_as}
        decided |= {same_name(a.url) for a in accepted if a.url}
        left = tuple(
            s
            for s in review.suggestions
            if same_name(s.name) not in decided and same_name(s.url or "") not in decided
        )
        review = replace(
            review,
            suggestions=left,
            topics=(),
            dismissed=tuple(dict.fromkeys((*review.dismissed, *dismissed))),
        )
        self._reviews.put(review)
        return review


@dataclass(frozen=True, slots=True)
class MentionOf:
    item: Item
    evidence: str | None


@dataclass(frozen=True, slots=True)
class EntitySummary:
    entity: Entity
    count: int
    """How many articles and posts mention it."""


@dataclass(frozen=True, slots=True)
class EntityDetail:
    entity: Entity
    mentions: tuple[MentionOf, ...]


@dataclass(frozen=True, slots=True)
class PendingItem:
    item: Item
    review: Review


class ManageEntities:
    """Look through, correct, merge and remove what the user's writing mentions.

    The id never changes, so renaming or recategorising keeps every link; a merge moves
    links and keeps every name as an alias; history is superseded, not deleted, except
    when the user deletes an entity outright (erasure, like deleting a person).
    """

    def __init__(
        self, repository: GraphRepository, vault: Vault, reviews: ReviewStore, clock: Clock
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._reviews = reviews
        self._clock = clock

    def summaries(self) -> list[EntitySummary]:
        repo = self._repository
        found = [EntitySummary(e, len(mentioned_in(repo, e.id))) for e in repo.list_entities()]
        return sorted(found, key=lambda s: (s.entity.category, -s.count, same_name(s.entity.name)))

    def get(self, entity_id: NodeId) -> EntityDetail:
        entity = self._entity(entity_id)
        found: list[MentionOf] = []
        for edge in self._repository.edges_to(entity_id):
            if edge.kind is not EdgeKind.MENTIONS or not edge.is_current:
                continue
            item = get_item(self._repository, edge.source)
            if item is not None:
                found.append(MentionOf(item, edge.provenance.evidence))
        found.sort(key=lambda m: m.item.published_on or date.min, reverse=True)
        return EntityDetail(entity, tuple(found))

    def update(
        self,
        entity_id: NodeId,
        *,
        name: str | None = None,
        category: str | None = None,
        url: str | Unset | None = UNSET,
    ) -> Entity:
        entity = self._entity(entity_id)
        if name is not None:
            name = clean_name(name)
            if not name:
                raise ApplicationError("A name can't be empty.")
            entity = entity.renamed(name)
        if category is not None:
            if category not in {c.value for c in Category}:
                raise ApplicationError(f"Unknown category: {category}")
            entity = replace(entity, category=Category(category))
        if not isinstance(url, Unset):
            entity = replace(entity, url=web_url(url) if url else None)
        self._repository.save_entity(entity)
        write_entity_note(self._repository, self._vault, entity.id)
        return entity

    def merge(self, source_id: NodeId, into_id: NodeId) -> Entity:
        """Make ``source`` part of ``into``: its mentions move, its names become aliases."""
        if source_id == into_id:
            raise ApplicationError("Choose two different entries to merge.")
        repo = self._repository
        source, into = self._entity(source_id), self._entity(into_id)
        now = self._clock.now()
        for edge in list(repo.edges_to(source_id)):
            if edge.kind is not EdgeKind.MENTIONS:
                continue
            repo.supersede_edge(edge.supersede(now))
            moved = Edge(edge.source, into_id, EdgeKind.MENTIONS, edge.provenance)
            existing = [e for e in repo.edges_from(edge.source) if e.key == moved.key]
            if not existing or (not existing[0].is_current and edge.is_current):
                repo.save_edge(moved)
        into = into.absorbing(source)
        repo.save_entity(into)
        repo.remove_node(source_id)
        self._vault.remove_entity(source)
        write_entity_note(repo, self._vault, into_id)
        return into

    def remove_mention(self, item_id: NodeId, target: NodeId) -> None:
        """Take one mention off one article or post; it won't be suggested there again."""
        repo = self._repository
        live = [
            e
            for e in repo.edges_from(item_id)
            if e.kind is EdgeKind.MENTIONS and e.target == target and e.is_current
        ]
        if not live:
            raise ApplicationError("That isn't mentioned there.")
        repo.save_edge(live[0].reject(self._clock.now()))
        write_mentioned_notes(repo, self._vault, [target])

    def delete(self, entity_id: NodeId) -> Entity:
        """Erase an entity and every mention of it (the user's choice, so no history)."""
        entity = self._entity(entity_id)
        self._repository.erase_nodes([entity_id])
        self._vault.remove_entity(entity)
        return entity

    def pending(self) -> list[PendingItem]:
        """Articles and posts with found mentions still waiting for a decision."""
        out: list[PendingItem] = []
        for review in self._reviews.pending():
            item = get_item(self._repository, review.item)
            if item is None:
                self._reviews.remove(review.item)  # the item was deleted
            else:
                out.append(PendingItem(item, review))
        return out

    def _entity(self, entity_id: NodeId) -> Entity:
        entity = self._repository.get_entity(entity_id) if entity_id.startswith("entity:") else None
        if entity is None:
            raise ApplicationError(f"Unknown entry: {entity_id}")
        return entity


def _free_key(repository: GraphRepository, key: str) -> str:
    key = key[:60].strip("-") or "entity"
    candidate, number = key, 2
    while repository.get_entity(Entity(candidate, "x", Category.OTHER).id) is not None:
        candidate, number = f"{key}-{number}", number + 1
    return candidate


def _names_of(repository: GraphRepository, target: NodeId) -> tuple[str, ...]:
    if kind_of(target) is NodeKind.PERSON:
        person = repository.get_person(target)
        return (person.name,) if person else ()
    entity = repository.get_entity(target)
    return (*entity.names(), *(e for e in (entity.url,) if e)) if entity else ()


def mentions_of(repository: GraphRepository, item_id: NodeId) -> list[tuple[Edge, str, str]]:
    """(edge, name, category) for what an item mentions, as confirmed."""
    out: list[tuple[Edge, str, str]] = []
    for edge in mention_edges(repository, item_id):
        if not edge.is_current:
            continue
        if kind_of(edge.target) is NodeKind.PERSON:
            person = repository.get_person(edge.target)
            if person is not None:
                out.append((edge, person.name, PERSON))
        else:
            entity = repository.get_entity(edge.target)
            if entity is not None:
                out.append((edge, entity.name, entity.category.value))
    return out


__all__ = [
    "CATEGORIES",
    "Accepted",
    "ConfirmMentions",
    "Confirmed",
    "EntityDetail",
    "EntitySummary",
    "FindMentions",
    "ManageEntities",
    "MentionOf",
    "PendingItem",
    "item_text",
    "mentions_of",
]
