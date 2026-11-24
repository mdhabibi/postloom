"""Screens read from a snapshot; it must never show something that has since changed."""

from pathlib import Path

from postloom.adapters.storage.cached import CachedRepository
from postloom.adapters.storage.database import SqliteDatabase
from postloom.adapters.storage.sqlite import SqliteGraphRepository
from postloom.domain.content import Topic


def test_a_write_by_another_process_is_seen(tmp_path: Path) -> None:
    path = tmp_path / "index.db"
    mine, theirs = SqliteDatabase(path), SqliteDatabase(path)
    repo = CachedRepository(SqliteGraphRepository(mine), changed=mine.data_version)
    with repo.reading():
        assert list(repo.list_topics()) == []
    version = repo.version

    SqliteGraphRepository(theirs).save_topic(Topic("RAG"))  # e.g. the command line

    assert repo.version != version
    with repo.reading():
        assert [t.name for t in repo.list_topics()] == ["RAG"]
    mine.close()
    theirs.close()


def test_the_snapshot_is_kept_between_screens_until_a_write() -> None:
    inner = SqliteGraphRepository()
    repo = CachedRepository(inner)
    with repo.reading():
        repo.list_topics()
    inner.save_topic(Topic("Behind its back"))  # not through the wrapper: not seen
    with repo.reading():
        assert list(repo.list_topics()) == []
    repo.save_topic(Topic("RAG"))
    with repo.reading():
        assert {t.name for t in repo.list_topics()} == {"RAG", "Behind its back"}


def test_outside_a_screen_reads_go_straight_through() -> None:
    inner = SqliteGraphRepository()
    repo = CachedRepository(inner)
    with repo.reading():
        repo.list_topics()
    inner.save_topic(Topic("RAG"))
    assert [t.name for t in repo.list_topics()] == ["RAG"]
