"""Port for the Markdown vault: the user's source of truth on disk."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from postloom.domain.content import Article, Post, Topic


class Vault(Protocol):
    def write_article(self, article: Article, post: Post, topics: Sequence[Topic]) -> Path:
        """Write (or overwrite) the note for an article and its announcement post.

        Returns the path of the article note.
        """
        ...

    def write_topic(self, topic: Topic) -> Path: ...
