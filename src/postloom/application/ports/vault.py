"""Port for the Markdown vault: the user's source of truth on disk.

The vault is written by postloom and may be edited by the user (in Obsidian or any
editor). ``read`` returns everything the notes say, which is what a rebuild puts in the
index; ``changes`` tells whether notes were edited since postloom last looked.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from postloom.domain.content import Article, Post, Topic
from postloom.domain.discussion import Comment
from postloom.domain.entities import Entity
from postloom.domain.graph import NodeId
from postloom.domain.people import Person

VAULT_FORMAT = 2
"""Version of the note format. 1 (before rebuilds existed) could not be read back."""


@dataclass(frozen=True, slots=True)
class ArticleNote:
    article: Article
    topics: tuple[NodeId, ...]
    """Topics the note lists, in order."""
    related: tuple[NodeId, ...]
    """Articles the note lists as related (the author's accepted links)."""
    path: str = field(default="", compare=False)
    """The note's path in the vault, to tell whether it is among the edited ones."""


@dataclass(frozen=True, slots=True)
class PostNote:
    post: Post
    announces: NodeId | None
    """The article this post announces; None for a post that stands on its own."""
    topics: tuple[NodeId, ...] = ()
    """Topics of a stand-alone post (an announcement post shares its article's)."""
    path: str = field(default="", compare=False)


@dataclass(frozen=True, slots=True)
class NoteProblem:
    path: str
    """Relative to the vault, with forward slashes."""
    reason: str


@dataclass(frozen=True, slots=True)
class VaultSnapshot:
    """Everything the notes say, parsed. Notes postloom didn't write are ignored."""

    topics: tuple[Topic, ...] = ()
    articles: tuple[ArticleNote, ...] = ()
    posts: tuple[PostNote, ...] = ()
    comments: tuple[Comment, ...] = ()
    people: tuple[Person, ...] = ()
    entities: tuple[Entity, ...] = ()
    problems: tuple[NoteProblem, ...] = ()
    """Notes that look like postloom's but can't be read (e.g. broken frontmatter)."""

    @property
    def is_empty(self) -> bool:
        return not (
            self.topics
            or self.articles
            or self.posts
            or self.comments
            or self.people
            or self.entities
        )


@dataclass(frozen=True, slots=True)
class VaultChanges:
    """Notes that differ from what postloom last wrote or read."""

    added: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.added) + len(self.modified) + len(self.removed)

    def __bool__(self) -> bool:
        return self.count > 0


Stamp = tuple[int, int]
"""A note's modification time (ns) and size: cheap to read, enough to notice an edit."""


class NoteStamps(Protocol):
    """Remembers how each note looked when postloom last wrote or read it."""

    def all(self) -> dict[str, Stamp]: ...

    def put(self, path: str, stamp: Stamp) -> None: ...

    def remove(self, path: str) -> None: ...

    def replace_all(self, stamps: Mapping[str, Stamp]) -> None: ...


class Vault(Protocol):
    # -- writing ----------------------------------------------------------------
    def write_article(
        self,
        article: Article,
        post: Post,
        topics: Sequence[Topic],
        related: Sequence[Article] = (),
    ) -> Path:
        """Write (or overwrite) the note for an article and its announcement post.

        ``related`` are the articles the author linked it to. Returns the article note path.
        """
        ...

    def write_post(self, post: Post, topics: Sequence[Topic]) -> Path:
        """Write (or overwrite) the note of a post that stands on its own."""
        ...

    def write_topic(self, topic: Topic) -> Path: ...

    def write_discussion(
        self,
        item: Article | Post,
        post: Post,
        comments: Sequence[Comment],
        people: Mapping[NodeId, Person],
    ) -> Path:
        """Write (or overwrite) the note holding every thread under ``post``. ``item`` is
        what the discussion is about: the article the post announces, or the post itself.

        With no comments left, the note is removed.
        """
        ...

    def write_entity(self, entity: Entity, mentioned_in: Sequence[Article | Post]) -> Path:
        """The note of something the user's writing mentions, with where it is mentioned."""
        ...

    def remove_entity(self, entity: Entity) -> None: ...

    def write_person(
        self,
        person: Person,
        items: Sequence[Article | Post],
        mentioned_in: Sequence[Article | Post] = (),
    ) -> Path:
        """Write (or overwrite) a person's note, linking the articles and posts they
        discussed."""
        ...

    # -- removing ---------------------------------------------------------------
    def remove_article(self, article: Article, post: Post | None) -> None:
        """Delete the notes of an article, its post and their discussion."""
        ...

    def remove_post(self, post: Post) -> None:
        """Delete the notes of a stand-alone post and its discussion."""
        ...

    def remove_person(self, person: Person) -> None: ...

    def remove_topic(self, topic: Topic) -> None: ...

    def prune(self, keep: Collection[str], protect: Collection[str] = ()) -> list[str]:
        """Move postloom's notes whose ``id`` is not in ``keep`` to the vault's trash.

        Nothing is destroyed: a note the user may still want is only moved aside. Notes
        postloom didn't write, and the paths in ``protect``, are left alone. Returns the
        moved paths.
        """
        ...

    # -- reading ----------------------------------------------------------------
    def read(self) -> VaultSnapshot: ...

    def changes(self) -> VaultChanges:
        """Notes added, edited or removed outside postloom since the last sync."""
        ...

    def mark_synced(self) -> None:
        """Record that the index now reflects the notes as they are on disk."""
        ...

    @property
    def format(self) -> int:
        """The note format this vault was written in; 0 for a vault never written to."""
        ...

    def mark_format(self) -> None:
        """Record that every note is in the current format."""
        ...
