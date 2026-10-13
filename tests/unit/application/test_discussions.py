from dataclasses import replace
from pathlib import Path

import pytest

from postloom.adapters.storage.database import SqliteDatabase
from postloom.adapters.storage.search import SqliteSearchIndex
from postloom.adapters.storage.sqlite import SqliteGraphRepository
from postloom.adapters.vault.markdown_vault import MarkdownVault
from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.errors import ApplicationError
from postloom.application.ports.thread_parser import ParsedMessage, ParsedThread
from postloom.application.use_cases import (
    AskQuestion,
    BrowseContent,
    DraftMessage,
    IndexArticle,
    IngestArticle,
    IngestArticleCommand,
    PreviewComments,
    SaveComments,
    SeedTopics,
)
from postloom.domain.discussion import OWNER
from postloom.domain.graph import EdgeKind, NodeId
from tests.fakes import (
    FakeChat,
    FakeEmbedder,
    FakeExtractor,
    FakeThreadParser,
    FixedClock,
    fixture_text,
    part3_extraction,
)

PASTED = fixture_text("comments", "caching_thread.txt")


class World:
    def __init__(self, tmp_path: Path) -> None:
        database = SqliteDatabase()
        self.repository = SqliteGraphRepository(database)
        self.index = SqliteSearchIndex(database)
        self.vault = MarkdownVault(tmp_path / "vault")
        self.clock = FixedClock()
        self.parser = FakeThreadParser()
        SeedTopics(self.repository, self.vault).execute(DEFAULT_TOPICS)
        ingest = IngestArticle(
            FakeExtractor(part3_extraction()), self.repository, self.vault, self.clock
        )
        self.article = ingest.execute(IngestArticleCommand("article", "Read part 3")).article
        self.preview = PreviewComments(self.parser, self.repository)
        self.save = SaveComments(self.repository, self.vault, self.clock)

    def drafts(self, owner: str | None = "Alex Author") -> list[DraftMessage]:
        return list(self.preview.execute(self.article.id, PASTED, owner).messages)

    def save_all(self) -> list[DraftMessage]:
        drafts = self.drafts()
        self.save.execute(self.article.id, drafts)
        return drafts

    @property
    def post(self) -> NodeId:
        return NodeId(f"post:{self.article.slug}")


# -- preview ------------------------------------------------------------------------
def test_preview_infers_the_conversation_chain(tmp_path: Path) -> None:
    drafts = World(tmp_path).drafts()
    assert [(d.author_name, d.thread, d.reply_to) for d in drafts] == [
        ("Jane Example", None, None),
        ("Alex Author", 0, 0),  # @Jane Example
        ("Jane Example", 0, 1),  # back-and-forth: answers Alex
        ("Alex Author", 0, 2),
        ("John Sample", None, None),  # new top-level comment
    ]
    assert [d.is_own for d in drafts] == [False, True, False, True, False]
    assert not any(d.already_saved or d.known_person for d in drafts)


def test_preview_passes_the_post_and_owner_to_the_parser(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.drafts(owner="Alex Author")
    pasted, post_text, owner = world.parser.calls[0]
    assert pasted == PASTED and post_text == "Read part 3" and owner == "Alex Author"


def test_owner_is_recognised_by_name_even_without_the_author_badge(tmp_path: Path) -> None:
    world = World(tmp_path)
    messages = world.parser.result.messages
    unmarked = [m.model_copy(update={"is_post_author": False}) for m in messages]
    world.parser.result = ParsedThread(messages=tuple(unmarked))
    assert [d.is_own for d in world.drafts(owner="alex author")] == [
        False,
        True,
        False,
        True,
        False,
    ]


def test_impossible_structure_from_the_model_is_repaired_with_a_warning(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.parser.result = ParsedThread(
        messages=(
            ParsedMessage(author_name="Jane", text="first", thread=3),  # points forward
            ParsedMessage(author_name="Alex", text="reply", thread=0, reply_to=9),
        )
    )
    preview = world.preview.execute(world.article.id, PASTED, None)
    assert [(d.thread, d.reply_to) for d in preview.messages] == [(None, None), (0, 0)]
    assert len(preview.warnings) == 2


def test_preview_needs_text_and_a_post(tmp_path: Path) -> None:
    world = World(tmp_path)
    with pytest.raises(ApplicationError, match="Paste the comments"):
        world.preview.execute(world.article.id, "  ", None)
    with pytest.raises(ApplicationError, match="Unknown article"):
        world.preview.execute(NodeId("article:nope"), PASTED, None)


# -- save ---------------------------------------------------------------------------
def test_saving_creates_people_comments_and_conversation_links(tmp_path: Path) -> None:
    world = World(tmp_path)
    drafts = world.drafts()
    result = world.save.execute(world.article.id, drafts)

    assert (result.added, result.already_saved, result.new_people) == (5, 0, 2)
    comments = list(world.repository.comments_on(world.post))
    jane_q, my_a, jane_q2, my_a2, john = comments
    assert my_a.author == OWNER and my_a.reply_to == jane_q.id and my_a.thread == jane_q.id
    assert jane_q2.reply_to == my_a.id and my_a2.reply_to == jane_q2.id
    assert john.thread is None and john.reply_to is None

    kinds = {e.kind for e in world.repository.edges_from(jane_q2.id)}
    assert kinds == {EdgeKind.COMMENTED_ON, EdgeKind.REPLIED_TO}
    jane = world.repository.get_person(jane_q.author)
    assert jane is not None and jane.headline == "Senior ML Engineer at Acme Analytics"
    assert jane.is_provisional


def test_pasting_again_adds_only_new_messages_to_the_existing_chain(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.save_all()
    more = (
        *world.parser.result.messages,
        ParsedMessage(author_name="Jane Example", text="Makes sense, thanks!", thread=0),
    )
    world.parser.result = ParsedThread(messages=more)

    drafts = world.drafts()
    assert [d.already_saved for d in drafts] == [True] * 5 + [False]
    result = world.save.execute(world.article.id, drafts)

    assert (result.added, result.already_saved, result.new_people) == (1, 5, 0)
    (thanks,) = result.comments
    previous = world.repository.comments_on(world.post)[3]  # my weekly-retune answer
    assert thanks.reply_to == previous.id
    assert thanks.position == 5


def test_profile_urls_give_people_a_stable_identity(tmp_path: Path) -> None:
    world = World(tmp_path)
    drafts = world.drafts()
    drafts[0] = replace(drafts[0], profile_url="https://www.linkedin.com/in/jane-example/")
    world.save.execute(world.article.id, drafts)

    comments = world.repository.comments_on(world.post)
    jane_ids = {c.author for c in comments if c.author_name == "Jane Example"}
    assert jane_ids == {NodeId("person:jane-example")}
    # Next time, the preview recognises her and fills in the link.
    again = world.drafts()
    assert again[2].known_person
    assert again[2].profile_url == "https://www.linkedin.com/in/jane-example"


def test_invalid_profile_url_is_rejected_before_saving(tmp_path: Path) -> None:
    world = World(tmp_path)
    drafts = world.drafts()
    drafts[0] = replace(drafts[0], profile_url="https://example.com/jane")
    with pytest.raises(ApplicationError, match="linkedin"):
        world.save.execute(world.article.id, drafts)
    assert world.repository.comments_on(world.post) == []


@pytest.mark.parametrize(
    ("index", "changes", "message"),
    [
        (1, {"reply_to": None}, "must answer an earlier message"),
        (1, {"thread": 3}, "invalid thread"),
        (0, {"reply_to": 1}, "top-level but answers"),
        (4, {"thread": 0, "reply_to": 4}, "must answer an earlier message"),
        (0, {"text": "  "}, "needs an author and some text"),
    ],
)
def test_review_edits_that_break_the_structure_are_refused(
    tmp_path: Path, index: int, changes: dict[str, object], message: str
) -> None:
    world = World(tmp_path)
    drafts = world.drafts()
    drafts[index] = replace(drafts[index], **changes)  # type: ignore[arg-type]
    with pytest.raises(ApplicationError, match=message):
        world.save.execute(world.article.id, drafts)


def test_replies_cannot_cross_threads(tmp_path: Path) -> None:
    world = World(tmp_path)
    drafts = world.drafts()
    extra = DraftMessage(author_name="Alex Author", text="x", is_own=True, thread=4, reply_to=2)
    with pytest.raises(ApplicationError, match="different thread"):
        world.save.execute(world.article.id, [*drafts, extra])


def test_saving_writes_an_obsidian_discussion_note(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.save_all()
    note = (tmp_path / "vault" / "discussions" / f"{world.article.slug}.md").read_text("utf-8")
    assert "people:\n- '[[Jane Example]]'\n- '[[John Sample]]'" in note
    assert "## Thread started by Jane Example" in note
    assert "> **[[Jane Example]]** (Senior ML Engineer at Acme Analytics, 4h)" in note
    assert ">> **You** (3h)" in note
    assert ">>> **[[Jane Example]]**" in note


# -- reading ------------------------------------------------------------------------
def test_article_detail_shows_threads_as_conversations(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.save_all()
    detail = BrowseContent(world.repository).get_article(world.article.id)
    assert detail is not None
    rows = [(c.author_name, c.depth, c.reply_to_name, c.is_own) for c in detail.discussion]
    assert rows == [
        ("Jane Example", 0, None, False),
        ("Alex Author", 1, "Jane Example", True),
        ("Jane Example", 2, "Alex Author", False),
        ("Alex Author", 3, "Jane Example", True),
        ("John Sample", 0, None, False),
    ]


def test_chat_about_an_article_sees_its_discussion(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.save_all()
    IndexArticle(world.repository, world.index, FakeEmbedder()).execute(world.article.id)
    chat = FakeChat()
    AskQuestion(chat, world.index, world.repository, FakeEmbedder(), 0.0).execute(
        "Does the post have comments?", article_id=world.article.id
    )
    prompt = chat.last_prompt
    assert "| Comment by Jane Example\nHow do you choose" in prompt
    assert "| Your reply (answering Jane Example)\n@Jane Example I start" in prompt
    assert "| Comment by John Sample\nGreat series." in prompt
