"""The index mirrors the vault: rebuilt when lost, updated when notes are edited."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.use_cases import IngestArticleCommand
from postloom.domain.content import Topic
from postloom.domain.graph import EdgeKind, NodeId
from postloom.domain.provenance import Grade, Origin
from tests.home_support import (
    AGENTS,
    CACHING,
    RETRIEVAL,
    body_of,
    edit,
    library,
    lose_index,
    note,
    open_home,
    related,
    state,
)


# -- rebuild ---------------------------------------------------------------------------
def test_a_lost_index_is_rebuilt_exactly_from_the_vault(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c:
        assert c.vault_report is None  # nothing to do: index and vault agree
        before = state(c)
    assert len(before["articles"]) == 3 and len(before["comments"]) == 5
    assert any(e.superseded_at is not None for e in before["edges"])  # there is history

    lose_index(tmp_path)
    with open_home(tmp_path) as c:
        report = c.vault_report
        assert report is not None and (report.applied, report.reason) == (True, "rebuilt")
        assert (report.articles, report.comments, report.people) == (3, 5, 2)
        assert report.problems == () and report.trashed == ()
        assert state(c) == before
        found = c.search().execute("caching0 caching1")
        assert [r.article_id for r in found.results] == [CACHING]  # search works again

    with open_home(tmp_path) as c:
        assert c.vault_report is None  # and the rebuild left nothing half-done


def test_decisions_survive_a_rebuild(tmp_path: Path) -> None:
    library(tmp_path)
    lose_index(tmp_path)
    with open_home(tmp_path) as c:
        assert related(c, CACHING, AGENTS).grade is Grade.VERIFIED
        assert related(c, CACHING, RETRIEVAL).grade is Grade.REJECTED  # stays dismissed
        assert related(c, CACHING, RETRIEVAL).producer == "user"
        topics = {t.name for t in c.browse().get_article(AGENTS).summary.topics}  # type: ignore[union-attr]
        assert topics == {"AI Agents"}
        jane = c.repository.get_person(NodeId("person:jane-example"))
        assert jane is not None and jane.notes == "Met at PyCon."
        assert c.suggest_links().execute().added == 0  # nothing dismissed comes back


def test_rebuilding_twice_changes_nothing_and_the_journal_does_not_grow(tmp_path: Path) -> None:
    library(tmp_path)
    journal = tmp_path / "vault" / ".postloom" / "edges.jsonl"
    with open_home(tmp_path) as c:
        first = c.sync_vault().execute()
        lines = journal.read_text(encoding="utf-8").count("\n")
        before = state(c)
        notes = {p: p.read_bytes() for p in (tmp_path / "vault").rglob("*.md")}
        second = c.sync_vault().execute()
        assert first.applied and second.applied
        assert state(c) == before
        assert journal.read_text(encoding="utf-8").count("\n") == lines == len(before["edges"])
        assert {p: p.read_bytes() for p in (tmp_path / "vault").rglob("*.md")} == notes


# -- edits made in Obsidian --------------------------------------------------------------
def test_edited_notes_update_the_index_on_the_next_start(tmp_path: Path) -> None:
    library(tmp_path)
    edit(note(tmp_path, "articles", "caching-basics"), "An introduction to", "A short guide to")
    edit(
        note(tmp_path, "articles", "caching-basics"), "title: Caching basics", "title: Caching 101"
    )
    edit(note(tmp_path, "people", "Jane Example"), "Met at PyCon.", "Met at EuroPython.")
    edit(note(tmp_path, "topics", "RAG"), "# RAG\n", "# RAG\n\nMy own definition.\n")

    with open_home(tmp_path) as c:
        report = c.vault_report
        assert report is not None and (report.reason, report.changed) == ("updated", 3)
        article = c.repository.get_article(CACHING)
        assert article is not None and article.title == "Caching 101"  # same id, new title
        assert article.body_markdown.startswith("A short guide to")
        jane = c.repository.get_person(NodeId("person:jane-example"))
        assert jane is not None and jane.notes == "Met at EuroPython."
        rag = next(t for t in c.repository.list_topics() if t.name == "RAG")
        assert rag.description.startswith("My own definition.")
        assert c.search().execute("short guide").results[0].title == "Caching 101"
        # Notes that mention the article by title were brought up to date as well.
        assert "Caching 101" in note(tmp_path, "discussions", "caching-basics").read_text("utf-8")
        assert "Caching 101" in note(tmp_path, "articles", "agents-in-production").read_text(
            "utf-8"
        )
        assert not c.vault.changes()


def test_topics_changed_in_a_note_become_the_authors_decisions(tmp_path: Path) -> None:
    library(tmp_path)
    article = note(tmp_path, "articles", "caching-basics")
    edit(article, "- '[[RAG]]'\n", "- '[[Kubernetes]]'\n")
    with open_home(tmp_path) as c:
        edges = {
            e.target: e.provenance
            for e in c.repository.edges_from(CACHING)
            if e.kind is EdgeKind.BELONGS_TO
        }
        rag, kubernetes = Topic("RAG").id, Topic("Kubernetes").id
        assert (edges[rag].grade, edges[rag].producer) == (Grade.REJECTED, "vault")
        assert (edges[kubernetes].grade, edges[kubernetes].origin) == (
            Grade.VERIFIED,
            Origin.MANUAL,
        )
        assert Topic("Kubernetes") in c.repository.list_topics()
        assert note(tmp_path, "topics", "Kubernetes").exists()  # the new topic got a note
    # A later re-ingest must not bring the rejected topic back.
    with open_home(tmp_path, title="Caching basics", body_markdown=body_of("Caching basics")) as c:
        result = c.ingest_article().execute(IngestArticleCommand(body_of("Caching basics"), "p"))
        assert "RAG" not in {t.name for t in result.topics}
        assert "[[RAG]]" not in article.read_text(encoding="utf-8")


def test_related_links_can_be_added_and_removed_in_notes(tmp_path: Path) -> None:
    library(tmp_path)
    retrieval = note(tmp_path, "articles", "evaluating-retrieval")
    edit(retrieval, "post:", "related:\n- '[[articles/agents-in-production]]'\npost:")
    edit(
        note(tmp_path, "articles", "agents-in-production"),
        "related:\n- '[[articles/caching-basics|Caching basics]]'\n",
        "",
    )
    with open_home(tmp_path) as c:
        assert related(c, RETRIEVAL, AGENTS).grade is Grade.VERIFIED  # added in one note
        assert related(c, CACHING, AGENTS).grade is Grade.REJECTED  # removed from an edited one
        # Both notes of each pair now agree with the decision.
        assert "evaluating-retrieval" in note(
            tmp_path, "articles", "agents-in-production"
        ).read_text("utf-8")
        assert "agents-in-production" not in note(tmp_path, "articles", "caching-basics").read_text(
            "utf-8"
        )


def test_comments_edited_or_removed_in_a_note(tmp_path: Path) -> None:
    library(tmp_path)
    discussion = note(tmp_path, "discussions", "caching-basics")
    edit(discussion, "> Great series.", "> Great series!!")
    with open_home(tmp_path) as c:
        (post,) = [p for p in c.repository.list_posts() if p.key == "caching-basics"]
        comments = c.repository.comments_on(post.id)
        assert len(comments) == 5
        john = next(m for m in comments if m.author_name == "John Sample")
        assert john.text.startswith("Great series!!")
        authored = [e for e in c.repository.edges_to(john.id) if e.kind is EdgeKind.AUTHORED]
        assert len(authored) == 1 and authored[0].is_current
        assert c.overview().execute().messages == 5


def test_deleting_an_article_note_removes_the_article_and_trashes_its_other_notes(
    tmp_path: Path,
) -> None:
    library(tmp_path)
    note(tmp_path, "articles", "caching-basics").unlink()
    with open_home(tmp_path) as c:
        report = c.vault_report
        assert report is not None and report.applied
        assert c.repository.get_article(CACHING) is None
        assert set(report.trashed) == {"posts/caching-basics.md", "discussions/caching-basics.md"}
        assert len(list((tmp_path / "vault" / ".postloom" / "trash").rglob("*.md"))) == 2
        assert c.search().execute("caching0").results == ()
        assert c.overview().execute().messages == 0
        assert len(c.repository.list_people()) == 2  # people are kept, with their notes


# -- protection ------------------------------------------------------------------------
def test_an_unreadable_note_blocks_the_sync_and_changes_nothing(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c:
        before = state(c)
    article = note(tmp_path, "articles", "caching-basics")
    edit(article, "title: Caching basics", "title: [Caching basics")
    edit(note(tmp_path, "people", "Jane Example"), "Met at PyCon.", "Met at EuroPython.")

    with open_home(tmp_path) as c:
        report = c.vault_report
        assert report is not None and (report.applied, report.reason) == (False, "blocked")
        assert [p.path for p in report.problems] == ["articles/caching-basics.md"]
        assert state(c) == before  # not even the readable edit was applied
        assert c.vault.changes().count == 2
        assert "title: [Caching basics" in article.read_text(encoding="utf-8")  # left alone

    edit(article, "title: [Caching basics", "title: Caching basics, fixed")
    with open_home(tmp_path) as c:
        assert c.vault_report is not None and c.vault_report.applied
        fixed = c.repository.get_article(CACHING)
        assert fixed is not None and fixed.title == "Caching basics, fixed"


def test_with_no_index_readable_notes_are_restored_and_broken_ones_left_alone(
    tmp_path: Path,
) -> None:
    library(tmp_path)
    broken = note(tmp_path, "articles", "caching-basics")
    edit(broken, "title: Caching basics", "title: [Caching basics")
    lose_index(tmp_path)
    with open_home(tmp_path) as c:
        report = c.vault_report
        assert report is not None and (report.applied, report.reason) == (True, "rebuilt")
        assert report.articles == 2 and len(report.problems) == 1
        assert broken.exists() and report.trashed != ()  # its post and discussion moved aside
        assert "articles/caching-basics.md" not in report.trashed


def test_an_emptied_vault_is_restored_from_the_index_not_mirrored(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c:
        before = state(c)
    for path in (tmp_path / "vault").rglob("*.md"):
        path.unlink()
    with open_home(tmp_path) as c:
        report = c.vault_report
        assert report is not None and report.reason == "restored"
        assert state(c) == before
        assert note(tmp_path, "articles", "caching-basics").exists()
        assert note(tmp_path, "people", "Jane Example").exists()


def test_a_vault_from_an_older_postloom_is_upgraded_from_its_index(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c:
        for article in c.repository.list_articles():
            c.repository.save_article(replace(article, key=""))  # as saved before keys existed
        ids = {a.id for a in c.repository.list_articles()}
        edges = sorted(c.repository.all_edges(), key=repr)
    for file in (tmp_path / "vault" / ".postloom").iterdir():
        file.unlink()  # no format marker and no journal: how format 1 looked
    old = note(tmp_path, "discussions", "caching-basics")
    old.write_text(
        "---\nid: discussion:caching-basics\ntype: discussion\ncomments: 5\n---\n\nold\n", "utf-8"
    )

    with open_home(tmp_path) as c:
        report = c.vault_report
        assert report is not None and report.reason == "upgraded"
        assert {a.id for a in c.repository.list_articles()} == ids  # identities are kept
        assert all(a.key for a in c.repository.list_articles())  # and pinned from now on
        assert sorted(c.repository.all_edges(), key=repr) == edges
        assert "%%{" in old.read_text(encoding="utf-8")  # rewritten in the readable format
        assert c.vault.format == 2
        assert c.search().execute("love a part on invalidation").results  # comments indexed
        upgraded = state(c)
    lose_index(tmp_path)
    with open_home(tmp_path) as c:  # and from now on it can be rebuilt, exactly
        assert state(c) == upgraded


def test_the_users_own_notes_survive_everything(tmp_path: Path) -> None:
    library(tmp_path)
    mine = tmp_path / "vault" / "articles" / "My draft.md"
    mine.write_text("# Draft\n\nNot postloom's.\n", encoding="utf-8")
    elsewhere = tmp_path / "vault" / "Journal" / "today.md"
    elsewhere.parent.mkdir()
    elsewhere.write_text(
        "---\ntype: article\nid: article:fake\n---\n\nOutside postloom's folders.\n", "utf-8"
    )
    lose_index(tmp_path)
    with open_home(tmp_path) as c:
        assert len(c.repository.list_articles()) == 3
        assert c.vault_report is not None and c.vault_report.problems == ()
    assert mine.read_text(encoding="utf-8") == "# Draft\n\nNot postloom's.\n"
    assert elsewhere.exists()


def test_a_lost_journal_is_rewritten_from_the_index(tmp_path: Path) -> None:
    library(tmp_path)
    journal = tmp_path / "vault" / ".postloom" / "edges.jsonl"
    with open_home(tmp_path) as c:
        before = state(c)
    journal.unlink()
    edit(note(tmp_path, "people", "Jane Example"), "Met at PyCon.", "Met at EuroPython.")
    with open_home(tmp_path) as c:
        assert c.vault_report is not None and c.vault_report.applied
        assert state(c)["edges"] == before["edges"]
    assert journal.read_text(encoding="utf-8").count("\n") == len(before["edges"])


def test_a_new_home_needs_no_sync(tmp_path: Path) -> None:
    with open_home(tmp_path) as c:
        assert c.vault_report is None
        c.seed_topics().execute(DEFAULT_TOPICS)
        assert c.vault.format == 2
    with open_home(tmp_path) as c:
        assert c.vault_report is None and len(c.repository.list_topics()) == len(DEFAULT_TOPICS)


@pytest.mark.parametrize("folder", ["articles", "posts", "people", "topics", "discussions"])
def test_every_kind_of_note_is_restored(tmp_path: Path, folder: str) -> None:
    library(tmp_path)
    count = len(list((tmp_path / "vault" / folder).glob("*.md")))
    lose_index(tmp_path)
    with open_home(tmp_path):
        pass
    assert len(list((tmp_path / "vault" / folder).glob("*.md"))) == count > 0
