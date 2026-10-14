from pathlib import Path

import pytest

from postloom.adapters.storage.database import SqliteDatabase
from postloom.adapters.storage.sqlite import SqliteGraphRepository
from postloom.adapters.vault.markdown_vault import MarkdownVault
from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.errors import ApplicationError
from postloom.application.use_cases import (
    IngestArticle,
    IngestArticleCommand,
    PeopleDirectory,
    PreviewComments,
    SaveComments,
    SeedTopics,
    UpdatePerson,
)
from postloom.domain.graph import EdgeKind, NodeId
from postloom.domain.people import Person, ProfileUrl
from tests.fakes import (
    FakeExtractor,
    FakeThreadParser,
    FixedClock,
    fixture_text,
    part3_extraction,
)

JANE = NodeId("person:~jane-example")
JOHN = NodeId("person:~john-sample")


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.repository = SqliteGraphRepository(SqliteDatabase())
        self.vault_dir = tmp_path / "vault"
        self.vault = MarkdownVault(self.vault_dir)
        self.clock = FixedClock()
        SeedTopics(self.repository, self.vault).execute(DEFAULT_TOPICS)
        ingest = IngestArticle(
            FakeExtractor(part3_extraction()), self.repository, self.vault, self.clock
        )
        self.article = ingest.execute(IngestArticleCommand("article", "Read part 3")).article
        pasted = fixture_text("comments", "caching_thread.txt")
        preview = PreviewComments(FakeThreadParser(), self.repository)
        drafts = preview.execute(self.article.id, pasted, "Alex Author").messages
        SaveComments(self.repository, self.vault, self.clock).execute(self.article.id, drafts)
        self.people = PeopleDirectory(self.repository)
        self.update = UpdatePerson(self.repository, self.vault, self.clock)


def test_people_are_listed_by_how_much_they_engage(tmp_path: Path) -> None:
    listed = World(tmp_path).people.list_people()
    assert [(p.name, p.messages, p.articles) for p in listed] == [
        ("Jane Example", 2, 1),
        ("John Sample", 1, 1),
    ]
    assert listed[0].headline == "Senior ML Engineer at Acme Analytics"
    assert listed[0].profile_url is None


def test_person_page_shows_whole_conversations_including_your_replies(tmp_path: Path) -> None:
    detail = World(tmp_path).people.get_person(JANE)
    assert detail is not None
    (conversation,) = detail.conversations
    assert conversation.article_title.startswith("Measuring What Matters")
    rows = [(m.author_name, m.is_own, m.depth) for m in conversation.messages]
    assert rows == [
        ("Jane Example", False, 0),
        ("Alex Author", True, 1),
        ("Jane Example", False, 2),
        ("Alex Author", True, 3),
    ]  # John's separate thread is not part of Jane's conversation


def test_unknown_person_is_none(tmp_path: Path) -> None:
    assert World(tmp_path).people.get_person(NodeId("person:nobody")) is None


def test_saving_comments_writes_person_notes_to_the_vault(tmp_path: Path) -> None:
    world = World(tmp_path)
    note = (world.vault_dir / "people" / "Jane Example.md").read_text("utf-8")
    assert "headline: Senior ML Engineer at Acme Analytics" in note
    assert "articles:\n- '[[articles/" in note


def test_adding_a_profile_link_merges_the_provisional_person(tmp_path: Path) -> None:
    world = World(tmp_path)
    new_id = world.update.execute(JANE, profile_url="https://www.linkedin.com/in/jane-example/")

    assert new_id == NodeId("person:jane-example")
    assert world.repository.get_person(JANE) is None
    merged = world.repository.get_person(new_id)
    assert merged is not None and merged.headline == "Senior ML Engineer at Acme Analytics"

    comments = world.repository.comments_on(NodeId(f"post:{world.article.slug}"))
    assert {c.author for c in comments if c.author_name == "Jane Example"} == {new_id}
    # Authorship moved, and the old links are kept as history rather than deleted.
    assert {e.target for e in world.repository.edges_from(new_id)} == {
        c.id for c in comments if c.author_name == "Jane Example"
    }
    old = world.repository.edges_from(JANE, include_history=True)
    assert old and all(e.superseded_at is not None for e in old)
    assert world.people.list_people()[0].profile_url == "https://www.linkedin.com/in/jane-example"
    assert (world.vault_dir / "people" / "Jane Example.md").exists()


def test_merging_into_someone_already_known_combines_their_records(tmp_path: Path) -> None:
    world = World(tmp_path)
    profile = ProfileUrl.parse("linkedin.com/in/jane-example")
    existing = Person("Jane Example", profile, notes="Met at PyCon")
    world.repository.save_person(existing.observe("Lead at Beta", world.clock.now()))
    world.update.execute(JANE, profile_url="linkedin.com/in/jane-example")

    merged = world.repository.get_person(NodeId("person:jane-example"))
    assert merged is not None
    assert merged.notes == "Met at PyCon"
    assert {o.headline for o in merged.observations} >= {"Lead at Beta"}


def test_notes_and_tags_are_saved(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.update.execute(JOHN, notes="  Wants a part on invalidation.  ", tags=["reader", " "])
    john = world.repository.get_person(JOHN)
    assert john is not None
    assert (john.notes, john.tags) == ("Wants a part on invalidation.", ("reader",))
    note = (world.vault_dir / "people" / "John Sample.md").read_text("utf-8")
    assert "## Notes\n\nWants a part on invalidation." in note


def test_bad_profile_links_and_unknown_people_are_errors(tmp_path: Path) -> None:
    world = World(tmp_path)
    with pytest.raises(ApplicationError, match="linkedin"):
        world.update.execute(JANE, profile_url="https://example.com/jane")
    with pytest.raises(ApplicationError, match="Unknown person"):
        world.update.execute(NodeId("person:nobody"), notes="x")


def test_reply_links_survive_a_merge(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.update.execute(JANE, profile_url="linkedin.com/in/jane-example")
    comments = world.repository.comments_on(NodeId(f"post:{world.article.slug}"))
    replies = [
        e
        for c in comments
        for e in world.repository.edges_from(c.id)
        if e.kind is EdgeKind.REPLIED_TO
    ]
    assert len(replies) == 3
    assert comments[2].reply_to == comments[1].id
