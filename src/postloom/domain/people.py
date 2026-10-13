"""People who interact with the user's content."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from urllib.parse import unquote, urlsplit

from postloom.domain.errors import InvalidProfileUrlError
from postloom.domain.graph import NodeId, NodeKind, node_id
from postloom.domain.text import slugify

_VALID_SLUG = re.compile(r"^[\w-]{3,100}$", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ProfileUrl:
    """A normalized LinkedIn member profile URL.

    Every spelling of the same profile (``http://de.linkedin.com/in/Jane-Doe/?trk=x``,
    ``linkedin.com/in/jane-doe``) normalizes to the same slug, which is what makes a
    person's identity stable across pastes.
    """

    slug: str

    @classmethod
    def parse(cls, raw: str) -> ProfileUrl:
        text = raw.strip()
        if not text:
            raise InvalidProfileUrlError("empty profile URL")
        if "://" not in text:
            text = "https://" + text
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
        if host != "linkedin.com" and not host.endswith(".linkedin.com"):
            raise InvalidProfileUrlError(f"not a linkedin.com URL: {raw!r}")
        segments = [s for s in parts.path.split("/") if s]
        if len(segments) < 2 or segments[0].lower() != "in":
            raise InvalidProfileUrlError(f"not a member profile URL (/in/<name>): {raw!r}")
        slug = unquote(segments[1]).lower()
        if not _VALID_SLUG.match(slug):
            raise InvalidProfileUrlError(f"invalid profile name in URL: {raw!r}")
        return cls(slug=slug)

    @property
    def url(self) -> str:
        return f"https://www.linkedin.com/in/{self.slug}"

    def __str__(self) -> str:
        return self.url


@dataclass(frozen=True, slots=True)
class ProfileObservation:
    """What a person's profile said at a point in time.

    Headlines and companies change; old observations are superseded, never deleted,
    so you can see that someone commented as "Engineer at X" and later as "Lead at Y".
    """

    headline: str
    observed_at: datetime
    superseded_at: datetime | None = None

    @property
    def is_current(self) -> bool:
        return self.superseded_at is None


@dataclass(frozen=True, slots=True)
class Person:
    """Someone who commented on or reacted to the user's content."""

    name: str
    profile: ProfileUrl | None = None
    observations: tuple[ProfileObservation, ...] = ()
    notes: str = ""
    tags: tuple[str, ...] = ()

    @property
    def id(self) -> NodeId:
        """Identity is the profile slug when known, else a name-based provisional id.

        Provisional ids (``person:~jane-doe``) are flagged with ``~`` so the UI can ask
        the user to add the profile URL and merge duplicates.
        """
        if self.profile is not None:
            return node_id(NodeKind.PERSON, self.profile.slug)
        return node_id(NodeKind.PERSON, "~" + slugify(self.name))

    @property
    def is_provisional(self) -> bool:
        return self.profile is None

    @property
    def headline(self) -> str | None:
        current = [o for o in self.observations if o.is_current]
        return current[-1].headline if current else None

    def observe(self, headline: str, at: datetime) -> Person:
        """Record the headline seen now; supersede the previous one if it changed."""
        headline = headline.strip()
        if not headline or headline == self.headline:
            return self
        updated = tuple(
            replace(o, superseded_at=at) if o.is_current else o for o in self.observations
        )
        return replace(self, observations=(*updated, ProfileObservation(headline, at)))

    def with_profile(self, profile: ProfileUrl) -> Person:
        return replace(self, profile=profile)
