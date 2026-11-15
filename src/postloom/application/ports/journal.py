"""Port for the edge journal: where each link came from, kept next to the notes.

Notes say what is linked to what. They can't say that a link was suggested by a model
and accepted by the author on a certain day, or that a suggestion was dismissed. The
journal records exactly that, so a rebuild from the vault restores decisions and history
and not only the links themselves.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from postloom.domain.graph import Edge


class EdgeJournal(Protocol):
    def append(self, edge: Edge) -> None:
        """Record an edge as it is saved or superseded."""
        ...

    def read(self) -> Sequence[Edge]:
        """Every recorded edge, in order. Unreadable lines are skipped."""
        ...

    def rewrite(self, edges: Sequence[Edge]) -> None:
        """Atomically replace the journal, e.g. after erasing a node or a rebuild."""
        ...
