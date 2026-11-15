"""NoteStamps in the index database: how each vault note looked at the last sync.

Kept in the index, not in the vault, on purpose: a new or restored index has no stamps,
so every note counts as changed and the index is rebuilt from the vault.
"""

from __future__ import annotations

from collections.abc import Mapping

from postloom.adapters.storage.database import SqliteDatabase
from postloom.application.ports.vault import Stamp


class SqliteNoteStamps:
    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def all(self) -> dict[str, Stamp]:
        rows = self._database.query("SELECT path, mtime_ns, size FROM notes")
        return {str(r["path"]): (int(r["mtime_ns"]), int(r["size"])) for r in rows}

    def put(self, path: str, stamp: Stamp) -> None:
        with self._database.transaction() as db:
            db.execute(
                "INSERT INTO notes (path, mtime_ns, size) VALUES (?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET mtime_ns = excluded.mtime_ns, "
                "size = excluded.size",
                (path, *stamp),
            )

    def remove(self, path: str) -> None:
        with self._database.transaction() as db:
            db.execute("DELETE FROM notes WHERE path = ?", (path,))

    def replace_all(self, stamps: Mapping[str, Stamp]) -> None:
        with self._database.transaction() as db:
            db.execute("DELETE FROM notes")
            db.executemany(
                "INSERT INTO notes (path, mtime_ns, size) VALUES (?, ?, ?)",
                [(path, *stamp) for path, stamp in stamps.items()],
            )
