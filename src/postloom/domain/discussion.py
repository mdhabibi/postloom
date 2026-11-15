"""Discussions: comments, replies and the conversation chains between people.

LinkedIn shows only two levels: top-level comments under a post, and every reply in that
thread flat underneath, even in a long back-and-forth. Who answers whom is signalled by
@mentions and order. postloom stores the real conversation instead:

- ``thread`` is the top-level comment a message sits under (LinkedIn's grouping);
- ``reply_to`` is the specific message it answers, so a six-message exchange becomes a
  chain, and two people can talk in parallel inside one thread.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace

from postloom.domain.errors import EmptyContentError
from postloom.domain.graph import NodeId, NodeKind, node_id
from postloom.domain.text import slugify

OWNER = node_id(NodeKind.PERSON, "me")
"""The app user: author of the posts and of their own replies."""

_MENTION_TRIM = re.compile(r"[\s​]+")


@dataclass(frozen=True, slots=True)
class Comment:
    """A comment or reply on a post."""

    post: NodeId
    author: NodeId
    author_name: str
    """Display name as it appeared on LinkedIn (kept even if the person is renamed)."""
    text: str
    position: int
    """Order within the post's discussion as pasted (0 = first)."""
    thread: NodeId | None = None
    """The top-level comment this message sits under; None for a top-level comment."""
    reply_to: NodeId | None = None
    """The message this one answers; None for a top-level comment."""
    posted_label: str = ""
    """LinkedIn's relative age as pasted, e.g. "4h" or "2w"."""

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise EmptyContentError("comment text is empty")

    @property
    def is_own(self) -> bool:
        return self.author == OWNER

    @property
    def key(self) -> str:
        """Stable identity: the same comment pasted again is recognised, not duplicated."""
        return comment_key(self.post, self.author_name, self.text)

    @property
    def id(self) -> NodeId:
        return node_id(NodeKind.COMMENT, self.key)


def comment_key(post: NodeId, author_name: str, text: str) -> str:
    normalized = " ".join(text.split()).casefold()
    digest = hashlib.sha256(f"{post}\x1f{normalized}".encode()).hexdigest()[:16]
    return f"{slugify(author_name, max_length=40)}-{digest}"


# -- reply inference ----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Message:
    """A message during parsing, before identities are resolved."""

    author_name: str
    text: str
    thread: int | None
    """Index of the top-level message this one sits under, or None if it is top-level."""
    reply_to: int | None = None
    """Index of the message it answers, if known."""


def infer_reply_targets(messages: Sequence[Message]) -> list[Message]:
    """Fill in ``reply_to`` for replies that don't have one yet.

    Rules, in order:
    1. An @mention of someone who already spoke in the thread answers their latest
       earlier message there.
    2. Otherwise the reply answers the latest earlier message in the thread by someone
       else (a back-and-forth alternates).
    3. Otherwise it answers the thread's top-level comment.
    """
    result = list(messages)
    for index, message in enumerate(result):
        if message.thread is None or message.reply_to is not None:
            continue
        thread_items = [
            (i, m)
            for i, m in enumerate(result[:index])
            if i == message.thread or m.thread == message.thread
        ]
        target = _mentioned(message, thread_items)
        if target is None:  # not `or`: index 0 is a valid target
            target = _previous_other(message, thread_items)
        if target is None:
            target = message.thread
        result[index] = replace(message, reply_to=target)
    return result


def _mentioned(message: Message, earlier: list[tuple[int, Message]]) -> int | None:
    text = _MENTION_TRIM.sub(" ", message.text).casefold()
    for i, candidate in reversed(earlier):
        name = candidate.author_name.strip().casefold()
        if name and name != message.author_name.strip().casefold() and f"@{name}" in text:
            return i
    # LinkedIn often mentions by first name only.
    for i, candidate in reversed(earlier):
        first = candidate.author_name.strip().split(" ")[0].casefold()
        if (
            len(first) > 2
            and candidate.author_name.casefold() != message.author_name.casefold()
            and re.search(rf"@{re.escape(first)}\b", text)
        ):
            return i
    return None


def _previous_other(message: Message, earlier: list[tuple[int, Message]]) -> int | None:
    me = message.author_name.strip().casefold()
    for i, candidate in reversed(earlier):
        if candidate.author_name.strip().casefold() != me:
            return i
    return None


def conversation_depth(comment: Comment, by_id: dict[NodeId, Comment]) -> int:
    """How many replies deep a message is (0 for top-level), robust to cycles."""
    depth, seen, current = 0, set[NodeId](), comment
    while current.reply_to is not None and current.reply_to in by_id and current.id not in seen:
        seen.add(current.id)
        current = by_id[current.reply_to]
        depth += 1
    return depth


def conversation_order(comments: Sequence[Comment]) -> list[Comment]:
    """Threads in pasted order; inside a thread, each reply right after what it answers."""
    children: dict[NodeId | None, list[Comment]] = {}
    known = {c.id for c in comments}
    for comment in sorted(comments, key=lambda c: c.position):
        parent = comment.reply_to if comment.reply_to in known else None
        children.setdefault(parent, []).append(comment)
    ordered: list[Comment] = []
    seen: set[NodeId] = set()
    pending = list(reversed(children.get(None, [])))
    while pending:
        comment = pending.pop()
        if comment.id in seen:
            continue
        seen.add(comment.id)
        ordered.append(comment)
        pending.extend(reversed(children.get(comment.id, [])))
    ordered += [c for c in comments if c.id not in seen]  # defensive: never drop a message
    return ordered


@dataclass(frozen=True, slots=True)
class ThreadText:
    """One conversation as plain text, for search and for a model to read."""

    starter: str
    """Who started it ("You" for the author)."""
    participants: frozenset[NodeId]
    comments: tuple[NodeId, ...]
    text: str
    """One paragraph per message: ``Name (replying to Name): what they wrote``."""


def thread_texts(comments: Sequence[Comment]) -> list[ThreadText]:
    """Every thread of a discussion as readable text, saying who answers whom."""
    by_id = {c.id: c for c in comments}

    def name(comment: Comment) -> str:
        return "You" if comment.is_own else comment.author_name

    threads: dict[NodeId, list[Comment]] = {}
    for comment in conversation_order(comments):
        root = comment.id
        if comment.thread is not None and comment.thread in by_id:
            root = comment.thread
        threads.setdefault(root, []).append(comment)

    texts: list[ThreadText] = []
    for root, messages in threads.items():
        lines: list[str] = []
        for message in messages:
            target = by_id.get(message.reply_to) if message.reply_to is not None else None
            who = name(message)
            if target is not None:
                answered = "you" if target.is_own else target.author_name
                who += f" (replying to {answered})"
            lines.append(f"{who}: {message.text}")
        texts.append(
            ThreadText(
                starter=name(by_id[root]) if root in by_id else name(messages[0]),
                participants=frozenset(m.author for m in messages),
                comments=tuple(m.id for m in messages),
                text="\n\n".join(lines),
            )
        )
    return texts


def without_authors(comments: Sequence[Comment], authors: Collection[NodeId]) -> list[Comment]:
    """The discussion with every message by ``authors`` removed, still a valid conversation.

    A reply to a removed message is re-attached to the nearest message above it that
    remains; if nothing above it remains, it becomes a top-level comment and the replies
    under it follow. Positions are renumbered so they stay dense.
    """
    by_id = {c.id: c for c in comments}
    gone = {c.id for c in comments if c.author in authors}

    def surviving_parent(comment: Comment) -> NodeId | None:
        seen: set[NodeId] = set()
        parent = comment.reply_to
        while parent is not None and parent in gone and parent not in seen:
            seen.add(parent)
            above = by_id.get(parent)
            parent = above.reply_to if above is not None else None
        return parent if parent in by_id and parent not in gone else None

    parents = {c.id: surviving_parent(c) for c in comments if c.id not in gone}

    def root_of(comment_id: NodeId) -> NodeId:
        seen: set[NodeId] = set()
        current = comment_id
        while (parent := parents.get(current)) is not None and current not in seen:
            seen.add(current)
            current = parent
        return current

    kept: list[Comment] = []
    for comment in sorted(comments, key=lambda c: c.position):
        if comment.id in gone:
            continue
        parent = parents[comment.id]
        root = root_of(comment.id)
        kept.append(
            replace(
                comment,
                position=len(kept),
                reply_to=parent,
                thread=None if parent is None else root,
            )
        )
    return kept
