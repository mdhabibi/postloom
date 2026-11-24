"""ManageMedia: the images and videos of an article or a stand-alone post.

A file is copied into the vault next to the notes, listed in the item's note with its
caption and description, and its words are indexed with the item, so search and chat find
"the slide with the latency chart". A model describes an image only when asked (it costs
a call); the user's own caption always works, with or without a model.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace

from postloom.application.errors import (
    ApplicationError,
    BudgetExceededError,
    NotConfiguredError,
    ProviderError,
)
from postloom.application.ports.media import ImageDescriber, MediaStore
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.vault import Vault
from postloom.application.use_cases.relations import Item, get_item, write_item_note
from postloom.domain.content import Article, Post
from postloom.domain.graph import NodeId
from postloom.domain.media import (
    InvalidMediaError,
    Media,
    MediaKind,
    is_subtitles,
    kind_of,
    safe_filename,
    subtitle_text,
)

LIMITS = {MediaKind.IMAGE: 25_000_000, MediaKind.VIDEO: 1_000_000_000}
"""Bytes. LinkedIn takes images up to a few MB and videos up to 5 GB; most are far smaller."""
SUBTITLES_LIMIT = 2_000_000

_LOCK = threading.Lock()
"""Uploads for one item can arrive together; each reads the item's list and writes it back."""


class ManageMedia:
    def __init__(
        self,
        repository: GraphRepository,
        vault: Vault,
        store: MediaStore,
        reindex: Callable[[NodeId], object],
        describer: ImageDescriber | None,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._store = store
        self._reindex = reindex
        self._describer = describer

    def add(
        self, item_id: NodeId, filename: str, data: Iterable[bytes], caption: str = ""
    ) -> Media:
        kind = kind_of(filename)
        if kind is None:
            if is_subtitles(filename):
                raise InvalidMediaError(
                    "Subtitles belong to a video: add the video first, then its subtitles."
                )
            safe_filename(filename)  # says which files are accepted
            raise InvalidMediaError(f"{filename!r} isn't an image or a video.")
        item = self._item(item_id)
        path = self._store.save(_folder(item), filename, data, limit=LIMITS[kind])
        media = Media(path, kind, caption=caption.strip())
        with _LOCK:
            item = self._item(item_id)
            self._save(item, (*item.media, media))
        return media

    def add_subtitles(
        self, item_id: NodeId, video: str, filename: str, data: Iterable[bytes]
    ) -> Media:
        if not is_subtitles(filename):
            raise InvalidMediaError("Subtitles are .vtt or .srt files.")
        item = self._item(item_id)
        current = _find(item, video)
        if current.kind is not MediaKind.VIDEO:
            raise InvalidMediaError("Only videos have subtitles.")
        path = self._store.save(_folder(item), filename, data, limit=SUBTITLES_LIMIT)
        try:
            transcript = subtitle_text(self._store.read(path).decode("utf-8-sig"))
        except UnicodeDecodeError as error:
            self._store.trash(path)
            raise InvalidMediaError("The subtitle file isn't plain text (UTF-8).") from error
        with _LOCK:
            item = self._item(item_id)
            old = _find(item, video)
            updated = replace(old, subtitles=path, transcript=transcript)
            self._save(item, _swap(item.media, old, updated))
        if old.subtitles and old.subtitles != path:
            self._store.trash(old.subtitles)
        return updated

    def update(self, item_id: NodeId, file: str, caption: str) -> Media:
        with _LOCK:
            item = self._item(item_id)
            old = _find(item, file)
            updated = old.with_caption(caption)
            self._save(item, _swap(item.media, old, updated))
        return updated

    def describe(self, item_id: NodeId, file: str) -> Media:
        """Ask the reading model what the image shows, and keep it with the image."""
        if self._describer is None:
            raise NotConfiguredError(
                "Describing images needs a model. Connect one in Settings, or write a caption."
            )
        item = self._item(item_id)
        image = _find(item, file)
        if image.kind is not MediaKind.IMAGE:
            raise InvalidMediaError("Only images can be described; give a video subtitles.")
        seen = self._describer.describe(self._store.read(image.file), image.mime, _context(item))
        with _LOCK:
            item = self._item(item_id)
            old = _find(item, file)
            updated = old.described(seen.description, seen.model)
            self._save(item, _swap(item.media, old, updated))
        return updated

    def remove(self, item_id: NodeId, file: str) -> Media:
        """Take it off the item; the file goes to the vault's trash."""
        with _LOCK:
            item = self._item(item_id)
            old = _find(item, file)
            self._save(item, tuple(m for m in item.media if m.file != file))
        self._store.trash(old.file)
        if old.subtitles:
            self._store.trash(old.subtitles)
        return old

    def move(self, item_id: NodeId, file: str, position: int) -> tuple[Media, ...]:
        with _LOCK:
            item = self._item(item_id)
            moving = _find(item, file)
            rest = [m for m in item.media if m.file != file]
            rest.insert(max(0, min(position, len(rest))), moving)
            self._save(item, tuple(rest))
        return tuple(rest)

    # -------------------------------------------------------------------------------
    def _item(self, item_id: NodeId) -> Item:
        item = get_item(self._repository, item_id)
        if item is None:
            raise ApplicationError(f"Unknown article or post: {item_id}")
        return item

    def _save(self, item: Item, media: Sequence[Media]) -> None:
        updated = replace(item, media=tuple(media))
        if isinstance(updated, Article):
            self._repository.save_article(updated)
        else:
            self._repository.save_post(updated)
        write_item_note(self._repository, self._vault, updated.id)
        # Saved and findable by keywords even if embedding fails; a reindex catches up.
        with contextlib.suppress(ProviderError, BudgetExceededError):
            self._reindex(updated.id)


def _folder(item: Item) -> str:
    return item.slug if isinstance(item, Article) else item.key


def _find(item: Item, file: str) -> Media:
    for media in item.media:
        if media.file == file:
            return media
    raise ApplicationError(f"{file} isn't one of this {_what(item)}'s images or videos.")


def _swap(media: Sequence[Media], old: Media, new: Media) -> tuple[Media, ...]:
    return tuple(new if m.file == old.file else m for m in media)


def _what(item: Item) -> str:
    return "post" if isinstance(item, Post) else "article"


def _context(item: Item) -> str:
    if isinstance(item, Article):
        return f"{item.title}\n\n{item.summary}\n\n{item.body_markdown[:1500]}"
    return item.text
