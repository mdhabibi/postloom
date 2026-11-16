"""Posts that don't announce an article: added, recognised, discussed, kept in the vault."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.errors import ApplicationError, ProviderError
from postloom.application.ports.extraction import PostTopics
from postloom.application.use_cases import IngestArticleCommand, IngestPost, IngestPostCommand
from postloom.domain.content import Post
from postloom.domain.graph import EdgeKind, NodeId
from postloom.domain.provenance import Grade
from tests.fakes import FakeChat, FakePostClassifier
from tests.home_support import CACHING, body_of, edit, library, lose_index, open_home, state

TEXT = (
    "Why I stopped tuning chunk sizes\n\n"
    "Small chunks lose context; big ones dilute it. Measure retrieval recall instead.\n\n"
    "#RAG #LLM"
)
LINK = "https://www.linkedin.com/posts/alex-author_rag-activity-1"
POST = NodeId("post:why-i-stopped-tuning-chunk-sizes")


def add(home: Path, text: str = TEXT, **kwargs: object) -> Post:
    with open_home(home) as c:
        c.seed_topics().execute(DEFAULT_TOPICS, only_when_empty=True)
        result = c.ingest_post().execute(IngestPostCommand(text, **kwargs))  # type: ignore[arg-type]
        c.index_article().execute(result.post.id)
        return result.post


def topic_names(home: Path, item: NodeId) -> set[str]:
    with open_home(home) as c:
        detail = c.browse().get_article(item)
        assert detail is not None
        return {t.name for t in detail.summary.topics}


# -- adding ------------------------------------------------------------------------------
def test_a_post_is_saved_with_a_title_topics_and_a_note(tmp_path: Path) -> None:
    classifier = FakePostClassifier()
    with open_home(tmp_path, post_classifier=classifier) as c:
        c.seed_topics().execute(DEFAULT_TOPICS)
        result = c.ingest_post().execute(IngestPostCommand(TEXT, url=LINK))
        listed = c.browse().list_articles()
    assert result.post.id == POST and not result.is_update
    assert result.post.title == "Why I stopped tuning chunk sizes"
    assert result.post.hashtags == ("RAG", "LLM")
    assert [t.name for t in result.topics] == ["RAG"]
    assert classifier.requests == [TEXT]
    assert [(i.id, i.kind) for i in listed] == [(POST, "post")]
    note = result.note_path.read_text(encoding="utf-8")
    assert result.note_path == tmp_path / "vault" / "posts" / "why-i-stopped-tuning-chunk-sizes.md"
    assert "announces" not in note and "RAG" in note and LINK in note


def test_adding_the_same_post_again_updates_it(tmp_path: Path) -> None:
    first = add(tmp_path)
    again = add(tmp_path, TEXT + "\n\nEdit: thanks for the comments!", url=LINK)
    with open_home(tmp_path) as c:
        assert [p.id for p in c.repository.list_posts()] == [first.id]
        assert again.id == first.id and again.url == LINK
        moved = c.ingest_post().execute(IngestPostCommand("A different hook\n\n" + TEXT, url=LINK))
    assert moved.is_update and moved.post.id == first.id  # recognised by its link


def test_a_link_already_used_by_a_different_post_is_refused(tmp_path: Path) -> None:
    add(tmp_path, url=LINK)
    with open_home(tmp_path) as c, pytest.raises(ApplicationError, match="already belongs"):
        c.ingest_post().execute(IngestPostCommand("Something else entirely today", url=LINK))


def test_an_article_announcement_is_not_added_twice_as_a_post(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c, pytest.raises(ApplicationError, match="announces the article"):
        c.ingest_post().execute(IngestPostCommand("New article: Caching basics #RAG"))


def test_two_posts_with_the_same_first_line_get_different_keys(tmp_path: Path) -> None:
    first = add(tmp_path, "Hot take\n\nCaching beats bigger models for repeated questions.")
    second = add(tmp_path, "Hot take\n\nEvaluation sets should be versioned like code.")
    assert first.id != second.id and first.title == second.title == "Hot take"


def test_without_a_model_a_post_is_saved_without_topics(tmp_path: Path) -> None:
    with open_home(tmp_path) as c:
        c.seed_topics().execute(DEFAULT_TOPICS)
        use_case = IngestPost(None, c.repository, c.vault, c.clock)
        result = use_case.execute(IngestPostCommand(TEXT))
    assert result.topics == () and "No model is connected" in result.warnings[0]


def test_a_failing_model_still_saves_the_post(tmp_path: Path) -> None:
    class Failing(FakePostClassifier):
        def classify(self, post_text: str, allowed_topics: tuple[str, ...]) -> PostTopics:
            raise ProviderError("quota exceeded")

    with open_home(tmp_path, post_classifier=Failing()) as c:
        c.seed_topics().execute(DEFAULT_TOPICS)
        result = c.ingest_post().execute(IngestPostCommand(TEXT))
        assert c.repository.get_post(POST) is not None
    assert result.topics == () and "quota exceeded" in result.warnings[0]


# -- curating ----------------------------------------------------------------------------
def test_topics_link_and_date_can_be_corrected(tmp_path: Path) -> None:
    add(tmp_path)
    with open_home(tmp_path) as c:
        post = c.update_post().execute(
            POST, topics=["AI Agents"], url=LINK, published_on=date(2026, 3, 1)
        )
        edges = [e for e in c.repository.edges_from(POST) if e.kind is EdgeKind.BELONGS_TO]
        with pytest.raises(ApplicationError, match="Unknown topic"):
            c.update_post().execute(POST, topics=["Knitting"])
    assert (post.url, post.published_on) == (LINK, date(2026, 3, 1))
    current = [e for e in edges if e.is_current]
    assert [e.provenance.grade for e in current] == [Grade.VERIFIED]
    assert any(not e.is_current for e in edges)  # the model's choice is superseded, not lost
    assert topic_names(tmp_path, POST) == {"AI Agents"}


def test_deleting_a_post_erases_it_and_its_comments_but_keeps_people(tmp_path: Path) -> None:
    add(tmp_path)
    with open_home(tmp_path) as c:
        drafts = c.preview_comments().execute(POST, "pasted", "Alex Author").messages
        c.save_comments().execute(POST, drafts)
        c.delete_post().execute(POST)
        assert c.repository.get_post(POST) is None
        assert any(p.name == "Jane Example" for p in c.repository.list_people())
        assert c.search().execute("chunk sizes recall").results == ()
    vault = tmp_path / "vault"
    assert not (vault / "posts" / "why-i-stopped-tuning-chunk-sizes.md").exists()
    assert not (vault / "discussions" / "why-i-stopped-tuning-chunk-sizes.md").exists()
    assert "Why I stopped" not in (vault / "people" / "Jane Example.md").read_text("utf-8")


# -- comments, search and chat -----------------------------------------------------------
def test_comments_on_a_post_are_saved_and_counted(tmp_path: Path) -> None:
    add(tmp_path)
    with open_home(tmp_path) as c:
        drafts = c.preview_comments().execute(POST, "pasted", "Alex Author").messages
        saved = c.save_comments().execute(POST, drafts)
        detail = c.browse().get_article(POST)
        overview = c.overview().execute()
        person = next(p for p in c.people().list_people() if p.name == "Jane Example")
        conversations = c.people().get_person(person.id).conversations  # type: ignore[union-attr]
    assert saved.added == 5 and detail is not None and len(detail.discussion) == 5
    assert (overview.articles, overview.posts, overview.messages) == (0, 1, 5)
    assert {w.article_id for w in overview.waiting} == {POST}
    assert {conv.article_id for conv in conversations} == {POST}
    discussion = tmp_path / "vault" / "discussions" / "why-i-stopped-tuning-chunk-sizes.md"
    text = discussion.read_text("utf-8")
    assert "# Discussion: Why I stopped tuning chunk sizes" in text and "article:" not in text
    jane = (tmp_path / "vault" / "people" / "Jane Example.md").read_text("utf-8")
    assert "posts/why-i-stopped-tuning-chunk-sizes" in jane


def test_posts_are_found_by_search(tmp_path: Path) -> None:
    library(tmp_path)
    add(tmp_path)
    with open_home(tmp_path) as c:
        found = c.search().execute("tuning chunk sizes")
    assert found.results[0].article_id == POST
    assert found.results[0].title == "Why I stopped tuning chunk sizes"


def test_chat_about_one_post_uses_its_text_and_comments(tmp_path: Path) -> None:
    add(tmp_path)
    chat = FakeChat(reply="Measure recall instead [1].")
    with open_home(tmp_path, chat=chat) as c:
        drafts = c.preview_comments().execute(POST, "pasted", "Alex Author").messages
        c.save_comments().execute(POST, drafts)
        answer = c.ask_question().execute("What should I measure?", article_id=POST)
    assert answer.grounded
    assert answer.sources[0].section == "The post" and "Measure retrieval recall" in (
        answer.sources[0].text
    )
    assert "How do you choose the distance threshold" in chat.last_prompt


def test_the_library_overview_counts_posts(tmp_path: Path) -> None:
    library(tmp_path)
    add(tmp_path)
    chat = FakeChat(reply="Three articles and one post [1].")
    with open_home(tmp_path, chat=chat) as c:
        answer = c.ask_question().execute("How many things have I written in my library?")
    overview = next(s for s in answer.sources if s.kind == "library")
    assert overview.text.startswith("The library has 3 articles, 1 posts")
    assert 'post "Why I stopped tuning chunk sizes"' in overview.text


def test_the_graph_shows_posts(tmp_path: Path) -> None:
    add(tmp_path)
    with open_home(tmp_path) as c:
        graph = c.graph().execute()
    node = next(n for n in graph.nodes if n.id == POST)
    assert node.kind == "post"
    assert any(link.source == POST and link.kind == "belongs_to" for link in graph.links)


# -- the vault ---------------------------------------------------------------------------
def test_posts_and_their_comments_survive_a_lost_index(tmp_path: Path) -> None:
    library(tmp_path)
    add(tmp_path, url=LINK)
    with open_home(tmp_path) as c:
        drafts = c.preview_comments().execute(POST, "pasted", "Alex Author").messages
        c.save_comments().execute(POST, drafts)
        c.update_post().execute(POST, topics=["AI Agents", "RAG"])
        before = state(c)
    lose_index(tmp_path)
    with open_home(tmp_path) as c:
        report = c.vault_report
        assert report is not None and report.reason == "rebuilt"
        assert (report.articles, report.posts, report.comments) == (3, 1, 10)
        assert state(c) == before
        assert c.search().execute("tuning chunk sizes").results[0].article_id == POST


def test_topics_edited_in_a_post_note_are_read_back(tmp_path: Path) -> None:
    add(tmp_path)
    path = tmp_path / "vault" / "posts" / "why-i-stopped-tuning-chunk-sizes.md"
    with open_home(tmp_path):
        pass  # the first start after adding records the note as postloom's
    edit(path, "- '[[RAG]]'", "- '[[AI Agents]]'")
    with open_home(tmp_path) as c:
        assert c.vault_report is not None
    assert topic_names(tmp_path, POST) == {"AI Agents"}


def test_an_article_added_after_a_post_keeps_both(tmp_path: Path) -> None:
    add(tmp_path)
    with open_home(tmp_path, title="Caching basics", body_markdown=body_of("Caching basics")) as c:
        c.ingest_article().execute(IngestArticleCommand(body_of("Caching basics"), "New #RAG"))
        kinds = {i.id: i.kind for i in c.browse().list_articles()}
    assert kinds == {POST: "post", CACHING: "article"}
