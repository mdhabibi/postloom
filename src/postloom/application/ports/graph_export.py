"""Writing the whole graph in a format other tools read (RDF, Cypher, GraphML...)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from postloom.application.ports.repository import GraphContents


@dataclass(frozen=True, slots=True)
class ExportOptions:
    text: bool = True
    """Include what was written: article bodies, post texts, comments, person notes. Without
    it the export keeps the structure, names, titles and dates."""
    history: bool = False
    """``GraphContents.edges`` holds superseded and rejected edges too; formats mark them as
    not current. Without history they are left out before the format sees them."""


class GraphFormat(Protocol):
    @property
    def name(self) -> str:
        """Short id used on the command line and in the API, e.g. ``"turtle"``."""
        ...

    @property
    def title(self) -> str:
        """What people call it, e.g. ``"RDF (Turtle)"``."""
        ...

    @property
    def extension(self) -> str:
        """File extension without the dot."""
        ...

    @property
    def media_type(self) -> str: ...

    def write(self, graph: GraphContents, options: ExportOptions) -> bytes: ...
