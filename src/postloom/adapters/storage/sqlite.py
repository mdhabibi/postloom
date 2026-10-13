"""SQLite GraphRepository: the default graph index, standard library only.

- Nodes live in one table keyed by their stable id, with the entity as JSON. Adding a
  node kind needs no migration; columns are added only when we need to query by them.
- Edges keep history in the same table: at most one *live* row per (source, target,
  kind), enforced by a partial unique index; superseded rows are never deleted.
- Connection, locking and migrations live in ``database.SqliteDatabase``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from postloom.adapters.storage import codec
from postloom.adapters.storage.database import MEMORY, MIGRATIONS, SqliteDatabase
from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.graph import Edge, EdgeKind, NodeId, NodeKind
from postloom.domain.provenance import Grade, Origin, Provenance

__all__ = ["MIGRATIONS", "SqliteGraphRepository"]

_EDGE_COLUMNS = (
    "source, target, kind, origin, grade, producer, recorded_at, evidence, weight, superseded_at"
)


class SqliteGraphRepository:
    def __init__(self, database: SqliteDatabase | Path | str = MEMORY) -> None:
        self._owns_database = not isinstance(database, SqliteDatabase)
        self._database = (
            database if isinstance(database, SqliteDatabase) else SqliteDatabase(database)
        )
        self._db = self._database.connection
        self._lock = self._database.lock
        self._transaction = self._database.transaction

    # -- lifecycle --------------------------------------------------------------
    @property
    def schema_version(self) -> int:
        return self._database.schema_version

    def close(self) -> None:
        """Close the database if this repository opened it."""
        if self._owns_database:
            self._database.close()

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
