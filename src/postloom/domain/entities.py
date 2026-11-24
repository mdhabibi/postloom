"""Things your writing mentions: organisations, places, events, projects, datasets, methods
and links. (People are ``Person`` nodes, the same ones who comment, so a person you thank
and a person who replies can be one.)

An entity enters the graph only when the user confirms it. Its id comes from a ``key``
that never changes, so renaming it or changing its category keeps every connection; old
names are kept as aliases, which is how a later mention of an old name finds it again.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from postloom.domain.content import check_key
from postloom.domain.errors import DomainError
from postloom.domain.graph import NodeId, NodeKind, node_id
from postloom.domain.text import plain_letters


class Category(StrEnum):
    ORGANISATION = "organisation"
    """Company, university, institute, lab, team, group, community."""
    PLACE = "place"
    EVENT = "event"
    """Conference, hackathon, meetup, course, competition."""
    PROJECT = "project"
    """Project, product, model, tool or library with a name."""
    DATASET = "dataset"
    METHOD = "method"
    """Technique, algorithm, method or field."""
    LINK = "link"
    OTHER = "other"


CATEGORY_NAMES: dict[Category, str] = {
    Category.ORGANISATION: "Organisation",
    Category.PLACE: "Place",
    Category.EVENT: "Event",
    Category.PROJECT: "Project or product",
    Category.DATASET: "Dataset",
    Category.METHOD: "Method or technique",
    Category.LINK: "Link",
    Category.OTHER: "Other",
}

PERSON = "person"
"""The category name people are found under; they are stored as ``Person`` nodes."""


class InvalidEntityError(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class Entity:
    key: str
    name: str
    category: Category
    url: str | None = None
    aliases: tuple[str, ...] = ()
    """Earlier names and other spellings, matched like the name."""

    def __post_init__(self) -> None:
        check_key(self.key, "Entity")
        if not self.name.strip():
            raise InvalidEntityError("An entity needs a name.")

    @property
    def id(self) -> NodeId:
        return node_id(NodeKind.ENTITY, self.key)

    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)

    def is_called(self, name: str) -> bool:
        wanted = same_name(name)
        return any(same_name(n) == wanted for n in self.names())

    def renamed(self, name: str) -> Entity:
        name = " ".join(name.split())
        if same_name(name) == same_name(self.name):
            return replace(self, name=name)
        kept = tuple(a for a in self.aliases if same_name(a) != same_name(name))
        return replace(self, name=name, aliases=_unique((*kept, self.name)))

    def absorbing(self, other: Entity) -> Entity:
        """This entity after ``other`` was merged into it: all its names are kept."""
        names = [n for n in other.names() if same_name(n) != same_name(self.name)]
        return replace(self, aliases=_unique((*self.aliases, *names)), url=self.url or other.url)


def same_name(name: str) -> str:
    """How names are compared: case, spacing and fancy letters don't matter."""
    return " ".join(plain_letters(name).casefold().split())


def _unique(names: tuple[str, ...]) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    for name in names:
        seen.setdefault(same_name(name), name)
    return tuple(seen.values())
