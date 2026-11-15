"""PreviewComments / SaveComments: paste a comment section, review it, save the threads.

Two steps on purpose. Parsing a pasted comment section is the one place where a model
guesses structure (who answers whom), so the user sees the result before anything is
stored, fixes what's wrong, and adds profile links. Saving is then deterministic.

Pasting the same section again later is safe: comments are identified by post, author
and text, so known messages are skipped and new replies attach to the right place in
the existing chains.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime

from postloom.application.errors import ApplicationError, BudgetExceededError, ProviderError
from postloom.application.ports.clock import Clock
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.thread_parser import ParsedMessage, ThreadParser
from postloom.application.ports.vault import Vault
from postloom.application.use_cases.index_content import IndexArticle
from postloom.application.use_cases.relations import articles_discussed_by
from postloom.domain.content import Article, Post
from postloom.domain.discussion import OWNER, Comment, Message, comment_key, infer_reply_targets
from postloom.domain.errors import InvalidProfileUrlError
from postloom.domain.graph import Edge, EdgeKind, NodeId, NodeKind, node_id
from postloom.domain.people import Person, ProfileUrl
from postloom.domain.provenance import Grade, Origin, Provenance


@dataclass(frozen=True, slots=True)
class DraftMessage:
    """One message as shown in the review step; the user may edit any field."""

    author_name: str
    text: str
    author_headline: str = ""
    is_own: bool = False
    posted_label: str = ""
    thread: int | None = None
    """Index of the top-level message this one sits under (None = top-level)."""
    reply_to: int | None = None
    """Index of the message it answers (None = top-level)."""
    profile_url: str | None = None
    already_saved: bool = False
    known_person: bool = False


@dataclass(frozen=True, slots=True)
class DiscussionPreview:
    article_id: NodeId
    messages: tuple[DraftMessage, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SaveResult:
    added: int
    already_saved: int
    new_people: int
    comments: tuple[Comment, ...] = field(default=())


def _post_of(repository: GraphRepository, article_id: NodeId) -> tuple[Article, Post]:
    article = repository.get_article(article_id)
    if article is None:
        raise ApplicationError(f"Unknown article: {article_id}")
    for edge in repository.edges_to(article_id):
        if edge.kind is EdgeKind.ANNOUNCES and edge.is_current:
            post = repository.get_post(edge.source)
            if post is not None:
                return article, post
    raise ApplicationError("This article has no announcement post to attach comments to.")


def _find_person(repository: GraphRepository, name: str) -> Person | None:
    wanted = " ".join(name.split()).casefold()
    for person in repository.list_people():
        if " ".join(person.name.split()).casefold() == wanted:
            return person
    return None


class PreviewComments:
    def __init__(self, parser: ThreadParser, repository: GraphRepository) -> None:
        self._parser = parser
        self._repository = repository

    def execute(self, article_id: NodeId, pasted: str, owner_name: str | None) -> DiscussionPreview:
        if not pasted.strip():
            raise ApplicationError("Paste the comments first.")
        _, post = _post_of(self._repository, article_id)
        parsed = self._parser.parse(pasted, post.text, owner_name)
        if not parsed.messages:
            raise ApplicationError("No comments found in the pasted text.")

        warnings: list[str] = []
        messages = _sanitize(parsed.messages, warnings)
        inferred = infer_reply_targets(
            [Message(m.author_name, m.text, m.thread, m.reply_to) for m in messages]
        )
        owner = (owner_name or "").strip().casefold()
        drafts: list[DraftMessage] = []
        for message, links in zip(messages, inferred, strict=True):
            is_own = message.is_post_author or (
                bool(owner) and message.author_name.strip().casefold() == owner
            )
            person = None if is_own else _find_person(self._repository, message.author_name)
            key = comment_key(post.id, message.author_name, message.text)
            drafts.append(
                DraftMessage(
                    author_name=message.author_name.strip(),
                    text=message.text.strip(),
                    author_headline=message.author_headline.strip(),
                    is_own=is_own,
                    posted_label=message.posted_label.strip(),
                    thread=links.thread,
                    reply_to=links.reply_to,
                    profile_url=person.profile.url if person and person.profile else None,
                    already_saved=self._repository.get_comment(_comment_id(key)) is not None,
                    known_person=person is not None,
                )
            )
        return DiscussionPreview(article_id, tuple(drafts), tuple(warnings))


def _sanitize(messages: Sequence[ParsedMessage], warnings: list[str]) -> list[ParsedMessage]:
    """Indexes from a model can point forward or at replies; repair what we can."""
    fixed: list[ParsedMessage] = []
    for index, message in enumerate(messages):
        thread, reply_to = message.thread, message.reply_to
        if thread is not None and not (0 <= thread < index and fixed[thread].thread is None):
            thread = None
        if thread is None or (reply_to is not None and not 0 <= reply_to < index):
            reply_to = None
        if (thread, reply_to) != (message.thread, message.reply_to):
            warnings.append(f"Check where message {index + 1} belongs; it was unclear.")
        fixed.append(message.model_copy(update={"thread": thread, "reply_to": reply_to}))
    return fixed


def _comment_id(key: str) -> NodeId:
    return node_id(NodeKind.COMMENT, key)


class SaveComments:
    def __init__(
        self,
        repository: GraphRepository,
        vault: Vault,
        clock: Clock,
        index_article: IndexArticle | None = None,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._clock = clock
        self._index_article = index_article
        """Given, new comments become findable by search and chat as they are saved."""

    def execute(self, article_id: NodeId, drafts: Sequence[DraftMessage]) -> SaveResult:
        article, post = _post_of(self._repository, article_id)
        _validate_structure(drafts)
        now = self._clock.now()
        start = len(self._repository.comments_on(post.id))

        authors = [self._author(d, now) for d in drafts]
        new_people = sum(1 for _, created in authors if created)
        ids = [_comment_id(comment_key(post.id, d.author_name, d.text)) for d in drafts]

        added: list[Comment] = []
        skipped = 0
        for index, (draft, (author, _)) in enumerate(zip(drafts, authors, strict=True)):
            if self._repository.get_comment(ids[index]) is not None:
                skipped += 1
                continue
            comment = Comment(
                post=post.id,
                author=author,
                author_name=draft.author_name.strip(),
                text=draft.text.strip(),
                position=start + len(added),
                thread=ids[draft.thread] if draft.thread is not None else None,
                reply_to=ids[draft.reply_to] if draft.reply_to is not None else None,
                posted_label=draft.posted_label.strip(),
            )
            self._repository.save_comment(comment)
            self._link(comment, now)
            added.append(comment)

        if added:
            comments = self._repository.comments_on(post.id)
            people = {
                c.author: p
                for c in comments
                if (p := self._repository.get_person(c.author)) is not None
            }
            self._vault.write_discussion(article, post, comments, people)
            for author in dict.fromkeys(c.author for c in added if not c.is_own):
                person = people.get(author)
                if person is not None:
                    articles = articles_discussed_by(self._repository, author)
                    self._vault.write_person(person, articles)
            if self._index_article is not None:
                # If the provider fails the comments are still indexed by keyword; a
                # reindex adds search by meaning later. Saving them must not fail for it.
                with suppress(ProviderError, BudgetExceededError):
                    self._index_article.execute(article.id)
        return SaveResult(len(added), skipped, new_people, tuple(added))

    def _author(self, draft: DraftMessage, now: datetime) -> tuple[NodeId, bool]:
        """Resolve the author to a person node, creating or updating it. Returns (id, new)."""
        if draft.is_own:
            return OWNER, False
        profile = _profile(draft.profile_url)
        existing = None
        if profile is not None:
            existing = self._repository.get_person(Person(draft.author_name, profile).id)
        if existing is None:
            existing = _find_person(self._repository, draft.author_name)
        person = existing or Person(draft.author_name.strip())
        if profile is not None and person.profile is None:
            person = person.with_profile(profile)
        if draft.author_headline.strip():
            person = person.observe(draft.author_headline, now)
        self._repository.save_person(person)
        return person.id, existing is None

    def _link(self, comment: Comment, now: datetime) -> None:
        fact = Provenance(Origin.STRUCTURAL, Grade.VERIFIED, "parser", now)
        reviewed = Provenance(Origin.STRUCTURAL, Grade.VERIFIED, "review", now)
        self._repository.save_edge(Edge(comment.author, comment.id, EdgeKind.AUTHORED, fact))
        self._repository.save_edge(Edge(comment.id, comment.post, EdgeKind.COMMENTED_ON, fact))
        if comment.reply_to is not None:
            self._repository.save_edge(
                Edge(comment.id, comment.reply_to, EdgeKind.REPLIED_TO, reviewed)
            )


def _profile(url: str | None) -> ProfileUrl | None:
    if not url or not url.strip():
        return None
    try:
        return ProfileUrl.parse(url)
    except InvalidProfileUrlError as error:
        raise ApplicationError(str(error)) from error


def _validate_structure(drafts: Sequence[DraftMessage]) -> None:
    if not drafts:
        raise ApplicationError("There are no comments to save.")
    for index, draft in enumerate(drafts):
        if not draft.author_name.strip() or not draft.text.strip():
            raise ApplicationError(f"Message {index + 1} needs an author and some text.")
        if draft.thread is not None:
            if not 0 <= draft.thread < index or drafts[draft.thread].thread is not None:
                raise ApplicationError(f"Message {index + 1} points at an invalid thread.")
            if draft.reply_to is None or not 0 <= draft.reply_to < index:
                raise ApplicationError(f"Message {index + 1} must answer an earlier message.")
            target = drafts[draft.reply_to]
            if draft.reply_to != draft.thread and target.thread != draft.thread:
                raise ApplicationError(
                    f"Message {index + 1} answers a message from a different thread."
                )
        elif draft.reply_to is not None:
            raise ApplicationError(f"Message {index + 1} is top-level but answers a message.")
