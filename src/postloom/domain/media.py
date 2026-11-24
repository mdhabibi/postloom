"""Images and videos that belong to an article or a post.

The files themselves live in the vault, under ``media/<item key>/``. What makes them
findable is text: the caption the user writes, what a model saw in an image (including
any text written in it), and a video's subtitles. That text is indexed with the item, so
searching "the slide with the latency chart" finds the post it was in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import PurePosixPath

from postloom.domain.errors import DomainError
from postloom.domain.text import slugify

MEDIA_FOLDER = "media"


class MediaKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


IMAGE_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
VIDEO_TYPES: dict[str, str] = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}
SUBTITLE_TYPES: dict[str, str] = {".vtt": "text/vtt", ".srt": "application/x-subrip"}
"""Subtitles belong to a video; their text makes what is said in it searchable."""


class InvalidMediaError(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class Media:
    file: str
    """Path inside the vault, e.g. ``media/caching-basics/latency-chart.png``."""
    kind: MediaKind
    caption: str = ""
    """The user's own words: alt text, what it shows, why it's there."""
    description: str = ""
    """What a model saw in the image, including any text written in it."""
    described_by: str | None = None
    """The model that wrote ``description``; None when the user did, or nobody."""
    subtitles: str | None = None
    """A video's subtitle file inside the vault (.vtt or .srt)."""
    transcript: str = ""
    """The subtitles' text. Read from the subtitle file, never stored on its own."""

    def __post_init__(self) -> None:
        check_media_path(self.file)
        if self.subtitles is not None:
            check_media_path(self.subtitles)

    @property
    def name(self) -> str:
        return PurePosixPath(self.file).name

    @property
    def mime(self) -> str:
        return media_type(self.name) or "application/octet-stream"

    def label(self) -> str:
        """A short name for lists and search results."""
        first = self.caption.strip().splitlines()[0] if self.caption.strip() else ""
        return first[:80] or self.name

    def text(self) -> str:
        """Everything that makes this findable, as one passage."""
        parts = [self.caption.strip(), self.description.strip(), self.transcript.strip()]
        return "\n\n".join(p for p in parts if p)

    def with_caption(self, caption: str) -> Media:
        return replace(self, caption=caption.strip())

    def described(self, description: str, model: str | None) -> Media:
        return replace(self, description=description.strip(), described_by=model)


def kind_of(filename: str) -> MediaKind | None:
    suffix = PurePosixPath(filename.lower()).suffix
    if suffix in IMAGE_TYPES:
        return MediaKind.IMAGE
    if suffix in VIDEO_TYPES:
        return MediaKind.VIDEO
    return None


def is_subtitles(filename: str) -> bool:
    return PurePosixPath(filename.lower()).suffix in SUBTITLE_TYPES


def media_type(filename: str) -> str | None:
    suffix = PurePosixPath(filename.lower()).suffix
    return IMAGE_TYPES.get(suffix) or VIDEO_TYPES.get(suffix) or SUBTITLE_TYPES.get(suffix)


def safe_filename(filename: str) -> str:
    """``My Slide (final).PNG`` -> ``my-slide-final.png``: no folders, nothing odd."""
    path = PurePosixPath(filename.replace("\\", "/").split("/")[-1])
    suffix = path.suffix.lower()
    if suffix not in IMAGE_TYPES and suffix not in VIDEO_TYPES and suffix not in SUBTITLE_TYPES:
        raise InvalidMediaError(
            f"postloom keeps images ({', '.join(IMAGE_TYPES)}), videos "
            f"({', '.join(VIDEO_TYPES)}) and subtitles ({', '.join(SUBTITLE_TYPES)}); "
            f"{filename!r} is none of these."
        )
    stem = slugify(path.stem, max_length=60) or "file"
    return f"{stem}{suffix}"


def check_media_path(path: str) -> None:
    """Media paths are ``media/<folder>/<file>``, never anywhere else in the vault."""
    parts = PurePosixPath(path).parts
    if (
        len(parts) != 3
        or parts[0] != MEDIA_FOLDER
        or any(p in ("", ".", "..") or p.startswith(".") for p in parts[1:])
        or "\\" in path
    ):
        raise InvalidMediaError(f"Not a media file in the vault: {path!r}")


def subtitle_text(raw: str) -> str:
    """The words of a .vtt or .srt file, without numbers, timings or styling."""
    lines: list[str] = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.strip().lstrip("﻿")
        if not line or line == "WEBVTT" or line.startswith(("WEBVTT ", "NOTE", "STYLE", "REGION")):
            continue
        if line.isdigit() or "-->" in line:
            continue
        line = _TAGS.sub("", line).strip()
        if line and (not lines or lines[-1] != line):  # captions often repeat a line
            lines.append(line)
    return " ".join(lines)


_TAGS = re.compile(r"<[^>]+>|\{\\[^}]*\}")
