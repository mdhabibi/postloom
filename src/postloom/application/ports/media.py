"""Ports for images and videos: where their files are kept, and a model that can look at an
image and say what it shows."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class MediaStore(Protocol):
    """Media files in the vault, under ``media/<folder>/``. Paths are vault-relative."""

    def save(self, folder: str, filename: str, data: Iterable[bytes], *, limit: int) -> str:
        """Write the file (renamed if the name is taken) and return its path. Raises
        ``MediaTooLargeError`` past ``limit`` bytes, leaving nothing behind."""
        ...

    def read(self, path: str) -> bytes: ...

    def locate(self, path: str) -> Path:
        """The file on disk, for serving it; raises if the path leaves the media folder."""
        ...

    def trash(self, path: str) -> None:
        """Move the file to the vault's trash (never delete it)."""
        ...


@dataclass(frozen=True, slots=True)
class ImageDescription:
    description: str
    """What the image shows, then any text written in it, word for word."""
    model: str


class ImageDescriber(Protocol):
    def describe(self, image: bytes, mime: str, context: str) -> ImageDescription:
        """``context`` is the post or article the image belongs to, so the description
        uses its vocabulary (a "latency chart", not "a line graph")."""
        ...
