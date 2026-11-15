"""Fixing, deleting and organising the library, and which article an ingest means."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from postloom.application.errors import ApplicationError
from postloom.application.use_cases import IngestArticleCommand
from postloom.bootstrap import Container
from postloom.domain.content import Series, Topic
from postloom.domain.graph import EdgeKind, NodeId
from postloom.domain.provenance import Grade
from tests.home_support import (
    AGENTS,
    CACHING,
    JANE,
    JOHN,
    RETRIEVAL,
    body_of,
    library,
    lose_index,
    note,
    open_home,
    related,
    state,
)


def vault_text(home: Path) -> str:
    """Everything postloom keeps in the vault, notes and journal alike."""
    files = [p for p in (home / "vault").rglob("*") if p.is_file() and "trash" not in p.parts]
    return "\n".join(p.read_text(encoding="utf-8") for p in files)


def articles_in(c: Container, topic: str) -> set[NodeId]:
    found: set[NodeId] = set()
    for article in c.repository.list_articles():
        detail = c.browse().get_article(article.id)
        if detail is not None and topic in {t.name for t in detail.summary.topics}:
            found.add(article.id)
    return found


# -- which article is this? --------------------------------------------------------------
def test_the_same_text_with_a_reworded_title_updates_the_article(tmp_path: Path) -> None:
    library(tmp_path)
    text = body_of("Caching basics") + "\n\n## Added later\n\nA new closing section."
    with open_home(tmp_path, title="Caching, the basics (updated)", body_markdown=text) as c:
        result = c.ingest_article().execute(IngestArticleCommand(text, "Updated post"))
        assert result.is_update and result.article.id == CACHING
        assert result.article.title == "Caching, the basics (updated)"
        assert any("new version" in w for w in result.warnings)
        assert len(c.repository.list_articles()) == 3
        assert len(c.browse().get_article(CACHING).discussion) == 5  # type: ignore[union-attr]
        assert "(updated)" in note(tmp_path, "discussions", "caching-basics").read_text("utf-8")


def test_a_different_article_with_the_same_title_is_kept_separately(tmp_path: Path) -> None:
    library(tmp_path)
    text = "Something else entirely. " + " ".join(f"other{i}" for i in range(80))
    with open_home(tmp_path, title="Caching basics", body_markdown=text) as c:
        result = c.ingest_article().execute(IngestArticleCommand(text, "Another post"))
        assert not result.is_update
        assert result.article.id == NodeId("article:caching-basics-2")
        assert any("same title" in w for w in result.warnings)
        original = c.repository.get_article(CACHING)
        assert original is not None and original.body_markdown == body_of("Caching basics")
        assert len(c.repository.list_articles()) == 4
        assert note(tmp_path, "articles", "caching-basics-2").exists()


def test_the_link_identifies_an_article_and_survives_a_re_ingest(tmp_path: Path) -> None:
    library(tmp_path)
    url = "https://www.linkedin.com/pulse/caching-basics-abc123/"
    with open_home(tmp_path) as c:
        c.update_article().execute(CACHING, url=url, published_on=date(2026, 10, 1))
    text = body_of("Caching basics")
    with open_home(tmp_path, title="A brand new title", body_markdown=text) as c:
        again = c.ingest_article().execute(
            IngestArticleCommand(text, "p", article_url="linkedin.com/pulse/caching-basics-abc123")
        )
        assert again.article.id == CACHING and again.is_update
        plain = c.ingest_article().execute(IngestArticleCommand(text, "p"))
        assert plain.article.url == "linkedin.com/pulse/caching-basics-abc123"  # not wiped
        assert plain.article.published_on == date(2026, 10, 1)


def test_a_link_that_belongs_to_another_article_is_refused_before_paying(tmp_path: Path) -> None:
    library(tmp_path)
    url = "https://www.linkedin.com/pulse/caching-basics-abc123"
    with open_home(tmp_path) as c:
        c.update_article().execute(CACHING, url=url)
    text = "Unrelated text. " + " ".join(f"zzz{i}" for i in range(80))
    with open_home(tmp_path, title="Unrelated", body_markdown=text) as c:
        with pytest.raises(ApplicationError, match='already belongs to "Caching basics"'):
            c.ingest_article().execute(IngestArticleCommand(text, "p", article_url=url))
        assert c.extractor.requests == []  # type: ignore[union-attr]  # the model was not called


# -- editing an article ----------------------------------------------------------------
def test_retitling_keeps_the_article_its_comments_and_its_links(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c:
        updated = c.update_article().execute(CACHING, title="Caching 101", summary="Short.")
        assert updated.id == CACHING
        detail = c.browse().get_article(CACHING)
        assert detail is not None and len(detail.discussion) == 5
        assert related(c, CACHING, AGENTS).grade is Grade.VERIFIED
        assert c.search().execute("Caching 101").results[0].title == "Caching 101"
    assert note(tmp_path, "articles", "caching-basics").exists()  # the file keeps its name
    text = vault_text(tmp_path)
    assert "Caching 101" in text and "|Caching basics]]" not in text
    lose_index(tmp_path)
    with open_home(tmp_path) as c:
        article = c.repository.get_article(CACHING)
        assert article is not None and article.title == "Caching 101"


def test_saving_topics_makes_them_the_authors_and_rejects_the_rest(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c:
        c.update_article().execute(CACHING, topics=["MLOps", "rag"])
        topics = {t.name: t.grade for t in c.browse().get_article(CACHING).summary.topics}  # type: ignore[union-attr]
        assert topics == {"MLOps": Grade.VERIFIED, "RAG": Grade.VERIFIED}
        rejected = [
            e
            for e in c.repository.edges_from(CACHING)
            if e.kind is EdgeKind.BELONGS_TO and e.provenance.grade is Grade.REJECTED
        ]
        assert [e.target for e in rejected] == [Topic("AI Agents").id]
        with pytest.raises(ApplicationError, match="Unknown topic: Quantum"):
            c.update_article().execute(CACHING, topics=["Quantum"])


def test_series_date_and_link_can_be_set_and_cleared(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c:
        update = c.update_article()
        article = update.execute(
            CACHING, series="Caching in practice", series_part=2, published_on=date(2026, 9, 1)
        )
        assert (article.series, article.series_part) == (Series("Caching in practice"), 2)
        graph = c.graph().execute()
        assert "Caching in practice" in {n.label for n in graph.nodes if n.kind == "series"}
        cleared = update.execute(CACHING, series=None, published_on=None)
        assert (cleared.series, cleared.series_part, cleared.published_on) == (None, None, None)
        assert not [e for e in c.repository.edges_from(CACHING) if e.kind is EdgeKind.PART_OF]
        with pytest.raises(ApplicationError, match="needs a title"):
            update.execute(CACHING, title="   ")


# -- deleting --------------------------------------------------------------------------
def test_deleting_an_article_erases_it_everywhere(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c:
        c.delete_article().execute(CACHING)
        assert c.repository.get_article(CACHING) is None
        assert len(c.repository.list_articles()) == 2
        assert c.overview().execute().messages == 0
        assert c.search().execute("caching0").results == ()
        assert all(CACHING not in (e.source, e.target) for e in c.repository.all_edges())
        assert len(c.repository.list_people()) == 2  # people stay
        jane = c.people().get_person(JANE)
        assert jane is not None and jane.summary.messages == 0
        with pytest.raises(ApplicationError):
            c.delete_article().execute(CACHING)
    text = vault_text(tmp_path)
    assert "caching-basics" not in text and "Caching basics" not in text
    assert not list((tmp_path / "vault").rglob("caching-basics.md"))
    lose_index(tmp_path)
    with open_home(tmp_path) as c:  # and it does not come back
        assert {a.id for a in c.repository.list_articles()} == {AGENTS, RETRIEVAL}


def test_deleting_a_person_erases_them_and_keeps_the_conversation_readable(
    tmp_path: Path,
) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c:
        deleted = c.delete_person().execute(JANE)
        assert (deleted.name, deleted.comments) == ("Jane Example", 2)
        assert c.repository.get_person(JANE) is None
        rows = [
            (m.author_name, m.depth)
            for m in c.browse().get_article(CACHING).discussion  # type: ignore[union-attr]
        ]
        # Your two replies to her remain, as their own thread; John's thread is untouched.
        assert rows == [("Alex Author", 0), ("Alex Author", 1), ("John Sample", 0)]
        assert all(JANE not in (e.source, e.target) for e in c.repository.all_edges())
        assert c.overview().execute().people == 1
        with pytest.raises(ApplicationError):
            c.delete_person().execute(JANE)
        before = state(c)
    text = vault_text(tmp_path)
    assert "jane-example" not in text and "Senior ML Engineer" not in text
    assert "threshold in practice" not in text  # her words are gone from every note
    assert not note(tmp_path, "people", "Jane Example").exists()
    lose_index(tmp_path)
    with open_home(tmp_path) as c:
        assert state(c) == before


def test_deleting_the_only_commenter_removes_the_discussion_note(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c:
        c.delete_person().execute(JANE)
        c.delete_person().execute(JOHN)
        detail = c.browse().get_article(CACHING)
        assert detail is not None and [m.is_own for m in detail.discussion] == [True, True]
        assert c.repository.list_people() == []


# -- topics ----------------------------------------------------------------------------
def test_topics_can_be_added_described_and_removed(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c:
        topics = c.topics()
        added = topics.add("  Vector   databases ", "Storage for embeddings.")
        assert added == Topic("Vector databases", "Storage for embeddings.")
        assert note(tmp_path, "topics", "Vector databases").exists()
        with pytest.raises(ApplicationError, match="already have"):
            topics.add("vector databases")
        with pytest.raises(ApplicationError, match="needs a name"):
            topics.add("  ")
        described = topics.update(added.id, description="Where vectors live.")
        assert described.description == "Where vectors live."

        topics.delete(Topic("RAG").id)
        assert "RAG" not in {t.name for t in c.repository.list_topics()}
        assert not note(tmp_path, "topics", "RAG").exists()
        assert "[[RAG]]" not in vault_text(tmp_path)
        summary = c.browse().get_article(CACHING).summary  # type: ignore[union-attr]
        assert "RAG" not in {t.name for t in summary.topics}
        history = c.repository.edges_to(Topic("RAG").id, include_history=True)
        assert history and all(e.superseded_at is not None for e in history)  # history kept


def test_renaming_a_topic_moves_its_articles(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c:
        before = articles_in(c, "RAG")
        assert before
        renamed = c.topics().update(Topic("RAG").id, name="Retrieval")
        assert articles_in(c, "Retrieval") == before and renamed.name == "Retrieval"
        assert renamed.description.startswith("Retrieval-augmented")  # the description moves
        assert not note(tmp_path, "topics", "RAG").exists()
        assert "[[RAG]]" not in vault_text(tmp_path) and "[[Retrieval]]" in vault_text(tmp_path)
        saved = state(c)
    lose_index(tmp_path)
    with open_home(tmp_path) as c:
        assert state(c) == saved


def test_renaming_a_topic_to_an_existing_one_merges_them(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c:
        merged = c.topics().update(Topic("AI Agents").id, name="rag")
        assert merged.name == "RAG"  # the existing topic keeps its name and description
        names = [t.name for t in c.repository.list_topics()]
        assert "AI Agents" not in names and names.count("RAG") == 1
        topics = [t.name for t in c.browse().get_article(AGENTS).summary.topics]  # type: ignore[union-attr]
        assert topics == ["RAG"]


def test_changing_only_the_capitals_of_a_topic_keeps_its_links(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c:
        c.topics().update(Topic("MLOps").id, name="MLops")
        assert "MLops" in {t.name for t in c.repository.list_topics()}
        assert [p.name for p in (tmp_path / "vault" / "topics").glob("ML*.md")] == ["MLops.md"]
