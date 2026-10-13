"""SQLite behaviour beyond the shared contract: files, restarts, migrations."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from postloom.adapters.storage.database import SqliteDatabase
from postloom.adapters.storage.sqlite import MIGRATIONS, SqliteGraphRepository
from postloom.domain.content import Article, Topic
from postloom.domain.graph import Edge, EdgeKind
from postloom.domain.provenance import Grade, Origin, Provenance

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2026, 2, 1, tzinfo=UTC)
ARTICLE = Article(title="Part 3", body_markdown="Body")
RAG = Topic("RAG")


def edge() -> Edge:
    provenance = Provenance(Origin.TAXONOMY, Grade.ASSERTED, "llm", T0)
    return Edge(ARTICLE.id, RAG.id, EdgeKind.BELONGS_TO, provenance)


def test_data_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "index.db"
    repo = SqliteGraphRepository(path)
    repo.save_topic(RAG)
    repo.save_article(ARTICLE)
    repo.save_edge(edge())
    repo.supersede_edge(edge().supersede(T1))
    repo.close()

    reopened = SqliteGraphRepository(path)
    assert list(reopened.list_topics()) == [RAG]
    assert reopened.get_article(ARTICLE.id) == ARTICLE
    history = list(reopened.edges_from(ARTICLE.id, include_history=True))
    assert [e.superseded_at for e in history] == [T1]
    reopened.close()


def test_new_database_is_migrated_to_the_latest_schema(tmp_path: Path) -> None:
    repo = SqliteGraphRepository(tmp_path / "index.db")
    assert repo.schema_version == len(MIGRATIONS)
    repo.close()


def test_reopening_does_not_rerun_migrations(tmp_path: Path) -> None:
    path = tmp_path / "index.db"
    SqliteGraphRepository(path).close()
    repo = SqliteGraphRepository(path)  # would fail with "table nodes already exists"
    assert repo.schema_version == len(MIGRATIONS)
    repo.close()


def test_file_databases_use_wal(tmp_path: Path) -> None:
    path = tmp_path / "index.db"
    SqliteGraphRepository(path).close()
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_the_database_rejects_two_live_edges_for_one_key(tmp_path: Path) -> None:
    """The partial unique index is the last line of defence against duplicate links."""
    path = tmp_path / "index.db"
    repo = SqliteGraphRepository(path)
    repo.save_edge(edge())
    repo.close()

    with closing(sqlite3.connect(path)) as db:
        insert = (
            "INSERT INTO edges (source, target, kind, origin, grade, producer, recorded_at) "
            "VALUES (?, ?, 'belongs_to', 'taxonomy', 'asserted', 'llm', 'x')"
        )
        try:
            db.execute(insert, (ARTICLE.id, RAG.id))
        except sqlite3.IntegrityError:
            return
    raise AssertionError("duplicate live edge was accepted")


def test_a_version_1_database_is_upgraded_in_place(tmp_path: Path) -> None:
    """Users who ran an earlier postloom keep their data when the schema grows."""
    path = tmp_path / "index.db"
    with closing(sqlite3.connect(path)) as db:
        for statement in MIGRATIONS[0].split(";"):
            if statement.strip():
                db.execute(statement)
        db.execute(
            "INSERT INTO nodes (id, kind, data) VALUES (?, 'topic', ?)",
            (RAG.id, '{"name": "RAG", "description": ""}'),
        )
        db.execute("PRAGMA user_version = 1")
        db.commit()

    database = SqliteDatabase(path)
    assert database.schema_version == len(MIGRATIONS)
    assert list(SqliteGraphRepository(database).list_topics()) == [RAG]
    assert database.query("SELECT count(*) AS n FROM chunks")[0]["n"] == 0
    database.close()
