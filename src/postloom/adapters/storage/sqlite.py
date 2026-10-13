"""SQLite GraphRepository: the default index, one file, standard library only.

Design notes:
- Nodes live in one table keyed by their stable id, with the entity as JSON. Adding a
  node kind needs no migration; columns are added only when we need to query by them.
- Edges keep history in the same table: at most one *live* row per (source, target,
  kind), enforced by a partial unique index; superseded rows are never deleted.
- Schema changes are numbered migrations tracked with ``PRAGMA user_version``.
- One connection guarded by a lock, so the web server's worker threads can share it.
- File databases use WAL so reads never block on a write.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from postloom.adapters.storage import codec
from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.graph import Edge, EdgeKind, NodeId, NodeKind
from postloom.domain.provenance import Grade, Origin, Provenance

MEMORY = ":memory:"

MIGRATIONS: tuple[str, ...] = (
    # 1: nodes and edges
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
)

_EDGE_COLUMNS = (
    "source, target, kind, origin, grade, producer, recorded_at, evidence, weight, superseded_at"
)


class SqliteGraphRepository:
    def __init__(self, path: Path | str = MEMORY) -> None:
        if str(path) != MEMORY:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        if str(path) != MEMORY:
            self._db.execute("PRAGMA journal_mode = WAL")
            self._db.execute("PRAGMA synchronous = NORMAL")
        self._migrate()

    # -- lifecycle --------------------------------------------------------------
    @property
    def schema_version(self) -> int:
        row = self._db.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _migrate(self) -> None:
        with self._transaction():
            current = self.schema_version
            for version, script in enumerate(MIGRATIONS, start=1):
                if version > current:
                    for statement in _split_sql(script):
                        self._db.execute(statement)
                    self._db.execute(f"PRAGMA user_version = {version}")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    # -- nodes ------------------------------------------------------------------
    def _put(self, node_id: NodeId, kind: NodeKind, data: codec.Json) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT INTO nodes (id, kind, data) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                (node_id, kind.value, codec.dumps(data)),
            )

    def _get(self, node_id: NodeId) -> codec.Json | None:
        with self._lock:
            row = self._db.execute("SELECT data FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return codec.loads(row["data"]) if row else None

    def _all(self, kind: NodeKind) -> list[codec.Json]:
        with self._lock:
            rows = self._db.execute(
                "SELECT data FROM nodes WHERE kind = ? ORDER BY rowid", (kind.value,)
            ).fetchall()
        return [codec.loads(r["data"]) for r in rows]

    def list_topics(self) -> Sequence[Topic]:
        return [codec.topic_from_json(d) for d in self._all(NodeKind.TOPIC)]

    def save_topic(self, topic: Topic) -> None:
        self._put(topic.id, NodeKind.TOPIC, codec.topic_to_json(topic))

    def get_article(self, article_id: NodeId) -> Article | None:
        data = self._get(article_id)
        return codec.article_from_json(data) if data else None

    def save_article(self, article: Article) -> None:
        self._put(article.id, NodeKind.ARTICLE, codec.article_to_json(article))

    def list_articles(self) -> Sequence[Article]:
        return [codec.article_from_json(d) for d in self._all(NodeKind.ARTICLE)]

    def get_post(self, post_id: NodeId) -> Post | None:
        data = self._get(post_id)
        return codec.post_from_json(data) if data else None

    def save_post(self, post: Post) -> None:
        self._put(post.id, NodeKind.POST, codec.post_to_json(post))

    def save_series(self, series: Series) -> None:
        self._put(series.id, NodeKind.SERIES, codec.series_to_json(series))

    # -- edges ------------------------------------------------------------------
    def save_edge(self, edge: Edge) -> None:
        if edge.superseded_at is not None:
            raise ValueError("save_edge takes a live edge; use supersede_edge to retire one")
        self._replace_live(edge)

    def supersede_edge(self, edge: Edge) -> None:
        if edge.superseded_at is None:
            raise ValueError("supersede_edge takes the superseded version of an edge")
        self._replace_live(edge)

    def _replace_live(self, edge: Edge) -> None:
        """Remove the live row for the edge's key, then insert ``edge`` (live or history)."""
        p = edge.provenance
        with self._transaction() as db:
            db.execute(
                "DELETE FROM edges WHERE source = ? AND target = ? AND kind = ? "
                "AND superseded_at IS NULL",
                (edge.source, edge.target, edge.kind.value),
            )
            db.execute(
                f"INSERT INTO edges ({_EDGE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    edge.source,
                    edge.target,
                    edge.kind.value,
                    p.origin.value,
                    p.grade.value,
                    p.producer,
                    p.recorded_at.isoformat(),
                    p.evidence,
                    edge.weight,
                    edge.superseded_at.isoformat() if edge.superseded_at else None,
                ),
            )

    def edges_from(self, node: NodeId, *, include_history: bool = False) -> Sequence[Edge]:
        return self._edges("source", node, include_history)

    def edges_to(self, node: NodeId, *, include_history: bool = False) -> Sequence[Edge]:
        return self._edges("target", node, include_history)

    def _edges(self, column: str, node: NodeId, include_history: bool) -> list[Edge]:
        live_only = "" if include_history else " AND superseded_at IS NULL"
        query = f"SELECT {_EDGE_COLUMNS} FROM edges WHERE {column} = ?{live_only} ORDER BY seq"
        with self._lock:
            rows = self._db.execute(query, (node,)).fetchall()
        return [_edge_from_row(r) for r in rows]


def _edge_from_row(row: sqlite3.Row) -> Edge:
    superseded: str | None = row["superseded_at"]
    return Edge(
        source=NodeId(row["source"]),
        target=NodeId(row["target"]),
        kind=EdgeKind(row["kind"]),
        provenance=Provenance(
            origin=Origin(row["origin"]),
            grade=Grade(row["grade"]),
            producer=row["producer"],
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
            evidence=row["evidence"],
        ),
        weight=row["weight"],
        superseded_at=datetime.fromisoformat(superseded) if superseded else None,
    )


def _split_sql(script: str) -> list[str]:
    """Split a migration into statements (our migrations never contain ';' in literals)."""
    return [s.strip() for s in script.split(";") if s.strip()]
