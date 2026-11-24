"""Images and videos in the vault, under ``media/<item>/``.

They sit next to the notes so the vault stays the whole library: copy the folder and the
pictures come along, and Obsidian shows them. Nothing here is ever deleted; a removed file
goes to the vault's trash like a removed note.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

from postloom.adapters.vault.notes import DATA_DIR, TRASH_DIR
from postloom.application.errors import MediaTooLargeError
from postloom.domain.media import MEDIA_FOLDER, check_media_path, safe_filename
from postloom.domain.text import slugify


class VaultMediaStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, folder: str, filename: str, data: Iterable[bytes], *, limit: int) -> str:
        name = safe_filename(filename)
        directory = self.root / MEDIA_FOLDER / (slugify(folder, max_length=120) or "files")
        directory.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=directory, prefix=".upload-")
        size = 0
        try:
            with os.fdopen(handle, "wb") as out:
                for chunk in data:
                    size += len(chunk)
                    if size > limit:
                        raise MediaTooLargeError(
                            f"{filename} is larger than {limit // 1_000_000} MB."
                        )
                    out.write(chunk)
            target = _free_name(directory / name)
            Path(temporary).replace(target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        return target.relative_to(self.root).as_posix()

    def read(self, path: str) -> bytes:
        return self.locate(path).read_bytes()

    def locate(self, path: str) -> Path:
        check_media_path(path)
        media = (self.root / MEDIA_FOLDER).resolve()
        found = (self.root / path).resolve()
        if found.parent.parent != media:
            raise ValueError(f"Not a media file in the vault: {path!r}")
        return found

    def trash(self, path: str) -> None:
        source = self.locate(path)
        if not source.exists():
            return
        target = self.root / DATA_DIR / TRASH_DIR / time.strftime("%Y%m%d-%H%M%S") / path
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(_free_name(target))
        with contextlib.suppress(OSError):
            source.parent.rmdir()  # only when it was the item's last file


def _free_name(path: Path) -> Path:
    """``chart.png``, else ``chart-2.png``, ``chart-3.png``..."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    n = 2
    while (candidate := path.with_name(f"{stem}-{n}{suffix}")).exists():
        n += 1
    return candidate
