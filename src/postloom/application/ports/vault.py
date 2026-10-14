"""Port for the Markdown vault: the user's source of truth on disk."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from postloom.domain.content import Article, Post, Topic
from postloom.domain.discussion import Comment
from postloom.domain.graph import NodeId
from postloom.domain.people import Person


class Vault(Protocol):
    def write_article(self, article: Article, post: Post, topics: Sequence[Topic]) -> Path:
        """Write (or overwrite) the note for an article and its announcement post.

        Returns the path of the article note.
        """
        ...

    def write_topic(self, topic: Topic) -> Path: ...

    def write_discussion(
        self,
        article: Article,
        post: Post,
        comments: Sequence[Comment],
        people: Mapping[NodeId, Person],
    ) -> Path:
        """Write (or overwrite) the note holding every thread under ``post``."""
        ...

    def write_person(self, person: Person, articles: Sequence[Article]) -> Path:
        """Write (or overwrite) a person's note, linking the articles they discussed."""
        ...

    def remove_person(self, person: Person) -> None:
        """Delete a person's note (after they were merged into another identity)."""
        ...
