"""The single SQLite file behind postloom's index: connection, locking and migrations.

Every SQLite adapter (graph repository, search index) shares one ``SqliteDatabase`` so
they live in the same file and their writes can never interleave inconsistently.

- Schema changes are numbered migrations tracked with ``PRAGMA user_version``; a new
  version of postloom upgrades an existing ``index.db`` on first open.
- One connection guarded by a re-entrant lock, so web-server threads can share it.
- File databases use WAL, so reads never block on a write.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from postloom.domain.text import plain_letters

MEMORY = ":memory:"

MIGRATIONS: tuple[str, ...] = (
    # 1: graph nodes and edges
    """
    CREATE TABLE nodes (
        id          TEXT PRIMARY KEY,
        kind        TEXT NOT NULL,
        data        TEXT NOT NULL
    );
    CREATE INDEX nodes_by_kind ON nodes(kind);

    CREATE TABLE edges (
        seq           INTEGER PRIMARY KEY AUTOINCREMENT,
        source        TEXT NOT NULL,
        target        TEXT NOT NULL,
        kind          TEXT NOT NULL,
        origin        TEXT NOT NULL,
        grade         TEXT NOT NULL,
        producer      TEXT NOT NULL,
        recorded_at   TEXT NOT NULL,
        evidence      TEXT,
        weight        REAL,
        superseded_at TEXT
    );
    CREATE UNIQUE INDEX edges_one_live_per_key
        ON edges(source, target, kind) WHERE superseded_at IS NULL;
    CREATE INDEX edges_by_source ON edges(source);
    CREATE INDEX edges_by_target ON edges(target);
    """,
    # 2: retrieval chunks with full-text search and stored embeddings
    """
    CREATE TABLE chunks (
        id            INTEGER PRIMARY KEY,
        node          TEXT NOT NULL,
        idx           INTEGER NOT NULL,
        title         TEXT NOT NULL,
        heading       TEXT NOT NULL,
        text          TEXT NOT NULL,
        content_hash  TEXT NOT NULL,
        vector_space  TEXT,
        vector        BLOB,
        UNIQUE (node, idx)
    );
    CREATE INDEX chunks_by_hash ON chunks(content_hash, vector_space);

    CREATE VIRTUAL TABLE chunks_fts USING fts5(
        title, heading, text,
        tokenize = 'porter unicode61 remove_diacritics 2'
    );
    """,
    # 3: find a post's comments without scanning every node
    """
    CREATE INDEX nodes_comments_by_post
        ON nodes(json_extract(data, '$.post')) WHERE kind = 'comment';
    """,
    # 4: model usage per month, provider, model and task (the usage page and the budget)
    """
    CREATE TABLE usage (
        month          TEXT NOT NULL,
        provider       TEXT NOT NULL,
        model          TEXT NOT NULL,
        task           TEXT NOT NULL,
        calls          INTEGER NOT NULL DEFAULT 0,
        input_tokens   INTEGER NOT NULL DEFAULT 0,
        output_tokens  INTEGER NOT NULL DEFAULT 0,
        cost_usd       REAL NOT NULL DEFAULT 0,
        unpriced_calls INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (month, provider, model, task)
    );
    """,
    # 5: how each vault note looked when it was last written or read, to notice edits
    """
    CREATE TABLE notes (
        path     TEXT PRIMARY KEY,
        mtime_ns INTEGER NOT NULL,
        size     INTEGER NOT NULL
    );
    """,
    # 6: index words written in fancy look-alike letters as ordinary words.
    """
    DELETE FROM chunks_fts;
    INSERT INTO chunks_fts (rowid, title, heading, text)
        SELECT id, plain_letters(title), plain_letters(heading), plain_letters(text)
        FROM chunks;
    """,
)


class SqliteDatabase:
    def __init__(self, path: Path | str = MEMORY) -> None:
        self.is_memory = str(path) == MEMORY
        if not self.is_memory:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.create_function("plain_letters", 1, plain_letters, deterministic=True)
        self.connection.execute("PRAGMA foreign_keys = ON")
        if not self.is_memory:
            self.connection.execute("PRAGMA journal_mode = WAL")
            self.connection.execute("PRAGMA synchronous = NORMAL")
        self._migrate()

    @property
    def schema_version(self) -> int:
        row = self.connection.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def close(self) -> None:
        with self.lock:
            self.connection.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Serialize a write: BEGIN IMMEDIATE ... COMMIT, rolled back on any error."""
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self.connection
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise
            self.connection.execute("COMMIT")

    def query(self, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.connection.execute(sql, params).fetchall()

    def _migrate(self) -> None:
        with self.transaction() as db:
            current = self.schema_version
            for version, script in enumerate(MIGRATIONS, start=1):
                if version > current:
                    for statement in _split_sql(script):
                        db.execute(statement)
                    db.execute(f"PRAGMA user_version = {version}")


def _split_sql(script: str) -> list[str]:
    """Split a migration into statements (our migrations never contain ';' in literals)."""
    return [s.strip() for s in script.split(";") if s.strip()]
