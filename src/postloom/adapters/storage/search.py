"""SQLite SearchIndex: FTS5 for keywords, brute-force cosine similarity for vectors.

Why brute force: a creator's archive is thousands of chunks, not millions. Comparing a
query against 5,000 768-dimension vectors takes ~0.1 s in pure Python, with no native
extension to install. Vectors are cached in memory per vector space and the cache is
dropped on every write. If an archive ever outgrows this, a sqlite-vec or ANN adapter
can implement the same port.
"""

from __future__ import annotations

import array
import heapq
import operator
import re
import sqlite3
import sys
from collections.abc import Collection, Sequence
from itertools import zip_longest
from pathlib import Path

from postloom.adapters.storage.database import MEMORY, SqliteDatabase
from postloom.application.ports.embeddings import Vector
from postloom.application.ports.search_index import ChunkHit, IndexedChunk
from postloom.domain.graph import NodeId
from postloom.domain.text import plain_letters, unspaced_pieces

_TOKEN = re.compile(r"\w+", re.UNICODE)
_MAX_QUERY_TOKENS = 32


class SqliteSearchIndex:
    def __init__(self, database: SqliteDatabase | Path | str = MEMORY) -> None:
        self._owns_database = not isinstance(database, SqliteDatabase)
        self._database = (
            database if isinstance(database, SqliteDatabase) else SqliteDatabase(database)
        )
        self._vectors: dict[str, list[tuple[int, array.array[float]]]] = {}

    def close(self) -> None:
        if self._owns_database:
            self._database.close()

    # -- writes -----------------------------------------------------------------
    def replace_chunks(self, node: NodeId, chunks: Sequence[IndexedChunk]) -> None:
        with self._database.transaction() as db:
            self._delete(db, node)
            for item in chunks:
                chunk = item.chunk
                cursor = db.execute(
                    "INSERT INTO chunks (node, idx, title, heading, text, content_hash, "
                    "vector_space, vector) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        node,
                        chunk.index,
                        chunk.title,
                        chunk.heading,
                        chunk.text,
                        chunk.content_hash,
                        item.vector_space if item.vector is not None else None,
                        _pack(item.vector) if item.vector is not None else None,
                    ),
                )
                db.execute(
                    "INSERT INTO chunks_fts (rowid, title, heading, text) VALUES (?, ?, ?, ?)",
                    (
                        cursor.lastrowid,
                        plain_letters(chunk.title),
                        plain_letters(chunk.heading),
                        plain_letters(chunk.text),
                    ),
                )
            self._vectors.clear()

    def remove(self, node: NodeId) -> None:
        with self._database.transaction() as db:
            self._delete(db, node)
            self._vectors.clear()

    @staticmethod
    def _delete(db: sqlite3.Connection, node: NodeId) -> None:
        db.execute(
            "DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE node = ?)",
            (node,),
        )
        db.execute("DELETE FROM chunks WHERE node = ?", (node,))

    # -- reads ------------------------------------------------------------------
    def cached_vectors(self, space: str, hashes: Collection[str]) -> dict[str, Vector]:
        found: dict[str, Vector] = {}
        wanted = list(set(hashes))
        for start in range(0, len(wanted), 500):  # stay under SQLite's variable limit
            batch = wanted[start : start + 500]
            marks = ", ".join("?" * len(batch))
            rows = self._database.query(
                "SELECT content_hash, vector FROM chunks WHERE vector_space = ? "
                f"AND vector IS NOT NULL AND content_hash IN ({marks})",
                (space, *batch),
            )
            for row in rows:
                found[row["content_hash"]] = _unpack(row["vector"]).tolist()
        return found

    def chunks_of(self, node: NodeId) -> Sequence[ChunkHit]:
        rows = self._database.query(
            "SELECT id, node, idx, title, heading, text FROM chunks WHERE node = ? ORDER BY idx",
            (node,),
        )
        return [_hit(row, 0.0) for row in rows]

    def vectors_by_node(self, space: str) -> dict[NodeId, list[Vector]]:
        rows = self._database.query(
            "SELECT node, vector FROM chunks WHERE vector_space = ? AND vector IS NOT NULL "
            "ORDER BY node, idx",
            (space,),
        )
        grouped: dict[NodeId, list[Vector]] = {}
        for row in rows:
            grouped.setdefault(NodeId(row["node"]), []).append(_unpack(row["vector"]).tolist())
        return grouped

    def vector_spaces(self) -> dict[str, int]:
        rows = self._database.query(
            "SELECT vector_space, count(*) AS n FROM chunks "
            "WHERE vector IS NOT NULL GROUP BY vector_space"
        )
        return {str(row["vector_space"]): int(row["n"]) for row in rows}

    def keyword_search(self, query: str, limit: int) -> Sequence[ChunkHit]:
        query = plain_letters(query)
        hits: list[ChunkHit] = []
        expression = _fts_query(query)
        if expression:
            rows = self._database.query(
                "SELECT c.id, c.node, c.idx, c.title, c.heading, c.text, "
                "bm25(chunks_fts, 2.0, 1.5, 1.0) AS rank "
                "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
                "WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (expression, limit),
            )
            # bm25() is "lower is better" and negative; flip it so higher is better.
            hits = [_hit(row, -float(row["rank"])) for row in rows]
        pieces = unspaced_pieces(query)[:_MAX_QUERY_TOKENS]
        if pieces:
            hits = _merge(hits, self._piece_search(pieces, limit), limit)
        return hits

    def _piece_search(self, pieces: list[str], limit: int) -> list[ChunkHit]:
        """Chinese, Japanese, Thai...: the full-text index splits words on spaces, which
        these scripts don't use, so match two-character pieces as substrings instead.
        Scored by how many of the query's pieces a chunk contains."""
        score = " + ".join(
            "(instr(title, ?) > 0) * 2 + (instr(heading, ?) > 0) + (instr(text, ?) > 0)"
            for _ in pieces
        )
        args: list[object] = [p for piece in pieces for p in (piece, piece, piece)]
        rows = self._database.query(
            f"SELECT id, node, idx, title, heading, text, ({score}) AS found FROM chunks "
            "WHERE found > 0 ORDER BY found DESC, id LIMIT ?",
            (*args, limit),
        )
        return [_hit(row, float(row["found"])) for row in rows]

    def vector_search(self, vector: Vector, space: str, limit: int) -> Sequence[ChunkHit]:
        candidates = self._load_vectors(space)
        if not candidates:
            return []
        query = array.array("f", vector)
        scored = heapq.nlargest(
            limit,
            ((sum(map(operator.mul, query, stored)), chunk_id) for chunk_id, stored in candidates),
        )
        if not scored:
            return []
        ids = [chunk_id for _, chunk_id in scored]
        marks = ", ".join("?" * len(ids))
        rows = {
            row["id"]: row
            for row in self._database.query(
                f"SELECT id, node, idx, title, heading, text FROM chunks WHERE id IN ({marks})",
                tuple(ids),
            )
        }
        return [_hit(rows[chunk_id], score) for score, chunk_id in scored if chunk_id in rows]

    def _load_vectors(self, space: str) -> list[tuple[int, array.array[float]]]:
        cached = self._vectors.get(space)
        if cached is None:
            rows = self._database.query(
                "SELECT id, vector FROM chunks WHERE vector_space = ? AND vector IS NOT NULL",
                (space,),
            )
            cached = [(int(row["id"]), _unpack(row["vector"])) for row in rows]
            self._vectors[space] = cached
        return cached


def _hit(row: sqlite3.Row, score: float) -> ChunkHit:
    return ChunkHit(
        node=NodeId(row["node"]),
        index=int(row["idx"]),
        heading=row["heading"],
        text=row["text"],
        title=row["title"],
        score=score,
    )


def _merge(first: list[ChunkHit], second: list[ChunkHit], limit: int) -> list[ChunkHit]:
    """Both result lists, without repeats, alternating so neither crowds out the other."""
    merged: dict[tuple[NodeId, int], ChunkHit] = {}
    for pair in zip_longest(first, second):
        for hit in pair:
            if hit is not None:
                merged.setdefault((hit.node, hit.index), hit)
    return list(merged.values())[:limit]


def _fts_query(query: str) -> str:
    """Turn free text into a safe FTS5 expression: any of the words, each quoted.

    Quoting stops user input like ``AND``, ``-`` or ``"`` from being parsed as FTS syntax.
    BM25 still ranks chunks containing more (and rarer) words higher.
    """
    tokens = list(dict.fromkeys(t.lower() for t in _TOKEN.findall(query)))[:_MAX_QUERY_TOKENS]
    return " OR ".join(f'"{token}"' for token in tokens)


def _pack(vector: Vector) -> bytes:
    data = array.array("f", vector)
    if sys.byteorder != "little":  # pragma: no cover - big-endian machines are rare
        data.byteswap()
    return data.tobytes()


def _unpack(blob: bytes) -> array.array[float]:
    data = array.array("f")
    data.frombytes(blob)
    if sys.byteorder != "little":  # pragma: no cover
        data.byteswap()
    return data
