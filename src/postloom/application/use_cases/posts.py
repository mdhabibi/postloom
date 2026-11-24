"""Posts that stand on their own: add, fix and delete them.

Most of what creators write on LinkedIn is posts, not articles. A post is kept exactly as
pasted (no model rewrites it); its title is its first line. A model is only asked which of
the author's topics it belongs to, and the post is saved without topics when no model is
connected, so posts work with no provider at all.

Which post is this? As for articles: the same link, then the same text, never the first
line alone. A post that is already in the library as an article's announcement is
refused, so it can't end up there twice.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from postloom.application.errors import ApplicationError, BudgetExceededError, ProviderError
from postloom.application.ports.clock import Clock
from postloom.application.ports.extraction import PostClassifier, PostTopics
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.search_index import SearchIndex
from postloom.application.ports.vault import Vault
from postloom.application.use_cases.curation import UNSET, Unset
from postloom.application.use_cases.ingest_article import (
    DIFFERENT_TEXT,
    SAME_TEXT,
    reconcile_edges,
)
from postloom.application.use_cases.relations import (
    article_of_post,
    current_topics,
    get_item,
    mention_edges,
    set_topics,
    standalone_posts,
    write_discussion_note,
    write_mentioned_notes,
    write_person_note,
)
from postloom.domain.content import Post, Topic
from postloom.domain.graph import Edge, EdgeKind, NodeId
from postloom.domain.provenance import Grade, Origin, Provenance
from postloom.domain.text import (
    canonical_url,
    containment,
    extract_hashtags,
    extract_urls,
    looks_english,
    web_url,
)

USER = "user"
POSTED_BY_HAND = "manual"
"""Producer recorded for a post saved without a model."""


@dataclass(frozen=True, slots=True)
class IngestPostCommand:
    text: str
    url: str | None = None
    published_on: date | None = None


@dataclass(frozen=True, slots=True)
class IngestPostResult:
    post: Post
    topics: tuple[Topic, ...]
    is_update: bool
    note_path: Path
    warnings: tuple[str, ...] = ()


class IngestPost:
    def __init__(
        self,
        classifier: PostClassifier | None,
        repository: GraphRepository,
        vault: Vault,
        clock: Clock,
        *,
        english_only_search: bool = False,
    ) -> None:
        self._classifier = classifier
        self._repository = repository
        self._vault = vault
        self._clock = clock
        self._english_only_search = english_only_search

    def execute(self, command: IngestPostCommand) -> IngestPostResult:
        text = command.text.strip()
        if not text:
            raise ApplicationError("Paste the post's text first.")
        url = web_url(command.url)
        self._refuse_announcements(text, url)

        posts = standalone_posts(self._repository)
        previous = _with_link(posts, url)
        if previous is not None and containment(text, previous.text) < DIFFERENT_TEXT:
            raise ApplicationError(
                f'That link already belongs to the post "{previous.title}", and its text is '
                "different. Check the link, or delete that post first."
            )
        previous = previous or _same_text(posts, text)

        warnings: list[str] = []
        taxonomy = list(self._repository.list_topics())
        topics: list[Topic] = []
        producer = POSTED_BY_HAND
        if self._classifier is None:
            warnings.append(
                "No model is connected, so no topics were chosen. Add them with Edit details."
            )
        elif taxonomy:
            try:
                chosen = self._classifier.classify(text, tuple(t.name for t in taxonomy))
            except (ProviderError, BudgetExceededError) as error:
                chosen = PostTopics(topics=(), entities=())
                warnings.append(
                    f"Saved without topics: the model couldn't choose them ({error}). "
                    "Add them with Edit details."
                )
            by_name = {t.name.casefold(): t for t in taxonomy}
            topics = list(
                dict.fromkeys(
                    by_name[n.strip().casefold()]
                    for n in chosen.topics
                    if n.strip().casefold() in by_name
                )
            )
            if chosen.topics:
                producer = self._classifier.name
        if self._english_only_search and not looks_english(text):
            warnings.append(
                "This post isn't in English, but search by meaning uses an English-only "
                "model. In Settings, set Search by meaning to Many languages for better "
                "results; keyword search works either way."
            )

        taken = {p.key for p in self._repository.list_posts()}
        if previous is not None:
            key = previous.key
        else:
            wanted = Post.key_for_text(text)
            key = wanted if wanted not in taken else _free(wanted, taken)
        post = Post(
            key=key,
            text=text,
            url=url or (previous.url if previous else None),
            published_on=command.published_on or (previous.published_on if previous else None),
            hashtags=tuple(extract_hashtags(text)),
            links=tuple(extract_urls(text)),
            banner_path=previous.banner_path if previous else None,
        )
        self._repository.save_post(post)
        now = self._clock.now()
        llm = Provenance(Origin.TAXONOMY, Grade.ASSERTED, producer, now)
        proposed = [Edge(post.id, t.id, EdgeKind.BELONGS_TO, llm) for t in topics]
        reconcile_edges(self._repository, (post.id,), proposed, now)

        live = current_topics(self._repository, post.id)
        note_path = self._vault.write_post(post, live)
        if previous is not None and self._repository.comments_on(post.id):
            write_discussion_note(self._repository, self._vault, post, post)
        return IngestPostResult(post, tuple(live), previous is not None, note_path, tuple(warnings))

    def _refuse_announcements(self, text: str, url: str | None) -> None:
        """A post already saved as an article's announcement belongs with that article."""
        for post in self._repository.list_posts():
            article = article_of_post(self._repository, post.id)
            if article is None:
                continue
            same_link = (
                url is not None and post.url and canonical_url(post.url) == canonical_url(url)
            )
            if same_link or containment(text, post.text) >= SAME_TEXT:
                raise ApplicationError(
                    f"This post is already in your library: it announces the article "
                    f'"{article.title}". Open that article to add its comments.'
                )


class UpdatePost:
    """Fix a post's topics, link or date. Its text is edited in its note."""

    def __init__(self, repository: GraphRepository, vault: Vault, clock: Clock) -> None:
        self._repository = repository
        self._vault = vault
        self._clock = clock

    def execute(
        self,
        post_id: NodeId,
        *,
        topics: Sequence[str] | None = None,
        url: str | Unset | None = UNSET,
        published_on: date | Unset | None = UNSET,
    ) -> Post:
        repo = self._repository
        post = _post(repo, post_id)
        if not isinstance(url, Unset):
            post = replace(post, url=web_url(url))
        if not isinstance(published_on, Unset):
            post = replace(post, published_on=published_on)
        repo.save_post(post)
        if topics is not None:
            by_name = {t.name.casefold(): t for t in repo.list_topics()}
            wanted: list[NodeId] = []
            for name in topics:
                topic = by_name.get(name.strip().casefold())
                if topic is None:
                    raise ApplicationError(f"Unknown topic: {name}. Add it in Settings first.")
                wanted.append(topic.id)
            set_topics(repo, post.id, wanted, self._clock.now(), producer=USER, confirm=True)
        self._vault.write_post(post, current_topics(repo, post.id))
        return post


class DeletePost:
    def __init__(self, repository: GraphRepository, vault: Vault, index: SearchIndex) -> None:
        self._repository = repository
        self._vault = vault
        self._index = index

    def execute(self, post_id: NodeId) -> Post:
        """Erase a stand-alone post and every comment under it. People are kept."""
        repo = self._repository
        post = _post(repo, post_id)
        comments = list(repo.comments_on(post.id))
        authors = list(dict.fromkeys(c.author for c in comments if not c.is_own))
        mentioned = [e.target for e in mention_edges(repo, post.id)]
        repo.erase_nodes([post.id, *(c.id for c in comments)])
        self._index.remove(post.id)
        self._vault.remove_post(post)
        for author in authors:
            write_person_note(repo, self._vault, author)
        write_mentioned_notes(repo, self._vault, mentioned)
        return post


def _post(repository: GraphRepository, post_id: NodeId) -> Post:
    item = get_item(repository, post_id)
    if not isinstance(item, Post):
        raise ApplicationError(f"Unknown post: {post_id}")
    return item


def _with_link(posts: Sequence[Post], url: str | None) -> Post | None:
    if not url:
        return None
    wanted = canonical_url(url)
    return next((p for p in posts if p.url and canonical_url(p.url) == wanted), None)


def _same_text(posts: Sequence[Post], text: str) -> Post | None:
    scored = [(containment(text, p.text), p) for p in posts]
    best = max(scored, key=lambda item: item[0], default=None)
    return best[1] if best is not None and best[0] >= SAME_TEXT else None


def _free(wanted: str, taken: set[str]) -> str:
    return next(f"{wanted}-{n}" for n in range(2, len(taken) + 3) if f"{wanted}-{n}" not in taken)
