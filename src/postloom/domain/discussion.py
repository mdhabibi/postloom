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
from collections.abc import Sequence
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
