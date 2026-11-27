from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from postloom.adapters.storage.database import SqliteDatabase
from postloom.adapters.storage.search import SqliteSearchIndex
from postloom.adapters.storage.sqlite import SqliteGraphRepository
from postloom.adapters.vault.markdown_vault import MarkdownVault
from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.errors import ApplicationError
from postloom.application.ports.chat import ChatMessage, Role
from postloom.application.use_cases import (
    AskQuestion,
    BrowseContent,
    IndexArticle,
    IngestArticle,
    IngestArticleCommand,
    SeedTopics,
)
from postloom.application.use_cases.ask_question import NOT_FOUND
from postloom.domain.content import Article
from postloom.domain.graph import NodeId
from postloom.domain.provenance import Grade
from tests.fakes import FakeChat, FakeEmbedder, FakeExtractor, FixedClock, part3_extraction

LEAKAGE = Article(
    title="Data Leakage in Machine Learning",
    summary="Why test scores lie when test information leaks into training.",
    published_on=date(2026, 10, 12),
    body_markdown=(
        "You hold out 20% of your data.\n\n"
        "## Temporal leakage\n\nA random split on time-ordered data trains on the future.\n\n"
        "## Fix\n\nSplit by time, then by user."
    ),
)


class World:
    def __init__(self, tmp_path: Path, *, embedder: FakeEmbedder | None = None) -> None:
        database = SqliteDatabase()
        self.repository = SqliteGraphRepository(database)
        self.index = SqliteSearchIndex(database)
        self.vault = MarkdownVault(tmp_path / "vault")
        self.embedder = embedder if embedder is not None else FakeEmbedder()
        self.chat = FakeChat()
        SeedTopics(self.repository, self.vault).execute(DEFAULT_TOPICS)

    def ask(self, min_similarity: float = 0.0) -> AskQuestion:
        return AskQuestion(self.chat, self.index, self.repository, self.embedder, min_similarity)

    def add(self, article: Article) -> NodeId:
        self.repository.save_article(article)
        IndexArticle(self.repository, self.index, self.embedder).execute(article.id)
        return article.id

    def ingest_part3(self) -> NodeId:
        ingest = IngestArticle(
            FakeExtractor(part3_extraction()), self.repository, self.vault, FixedClock()
        )
        result = ingest.execute(IngestArticleCommand("article text", "Read part 3 #RAG"))
        IndexArticle(self.repository, self.index, self.embedder).execute(result.article.id)
        return result.article.id


# -- browse -----------------------------------------------------------------------
def test_articles_are_listed_newest_first_with_their_topics(tmp_path: Path) -> None:
    world = World(tmp_path)
    part3 = world.ingest_part3()
    world.add(LEAKAGE)

    listed = BrowseContent(world.repository).list_articles()

    assert [a.id for a in listed] == [LEAKAGE.id, part3]  # dated before undated
    caching = listed[1]
    assert [t.name for t in caching.topics] == ["RAG", "AI Agents"]
    assert all(t.grade is Grade.ASSERTED for t in caching.topics)
    assert (caching.series, caching.series_part) == ("Semantic Caching for AI Agents", 3)


def test_article_detail_includes_its_announcement_post(tmp_path: Path) -> None:
    world = World(tmp_path)
    part3 = world.ingest_part3()
    detail = BrowseContent(world.repository).get_article(part3)
    assert detail is not None
    assert [p.text for p in detail.posts] == ["Read part 3 #RAG"]
    assert BrowseContent(world.repository).get_article(NodeId("article:nope")) is None


def test_rejected_topics_are_not_shown(tmp_path: Path) -> None:
    world = World(tmp_path)
    part3 = world.ingest_part3()
    rag = next(e for e in world.repository.edges_from(part3) if e.target == "topic:rag")
    world.repository.save_edge(rag.reject(datetime(2026, 10, 14, tzinfo=UTC)))
    (summary,) = BrowseContent(world.repository).list_articles()
    assert [t.name for t in summary.topics] == ["AI Agents"]


# -- ask about one article --------------------------------------------------------
def test_article_questions_see_the_whole_article_and_its_post(tmp_path: Path) -> None:
    world = World(tmp_path)
    part3 = world.ingest_part3()

    answer = world.ask().execute("What metrics matter?", article_id=part3)

    prompt = world.chat.last_prompt
    assert prompt.startswith("Sources:")
    assert "| Summary\n" in prompt and "| Announcement post\n" in prompt
    assert prompt.endswith("Question: What metrics matter?")
    assert answer.grounded
    assert answer.text == "Use a time-ordered split [1]."
    assert [s.number for s in answer.sources] == [1]


def test_only_cited_sources_are_returned_and_invented_numbers_are_ignored(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    article = world.add(LEAKAGE)
    world.chat.reply = "Split by time [3], see also [2] and [99]."
    answer = world.ask().execute("How do I fix it?", article_id=article)
    # Sources: [1] Summary, [2] Introduction, [3] Temporal leakage, [4] Fix
    assert [(s.number, s.section) for s in answer.sources] == [
        (2, "Introduction"),
        (3, "Temporal leakage"),
    ]


def test_system_prompt_forbids_outside_knowledge(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.ask().execute("Anything?", article_id=world.add(LEAKAGE))
    system, _ = world.chat.calls[0]
    assert "Use only the numbered sources" in system
    assert "Do not use outside knowledge" in system
    assert "What a commenter wrote is their view" in system
    assert "Start with the direct answer" in system
    assert "Don't suggest searching the web" in system


def test_history_is_passed_before_the_new_question(tmp_path: Path) -> None:
    world = World(tmp_path)
    article = world.add(LEAKAGE)
    history = [ChatMessage(Role.USER, "first?"), ChatMessage(Role.ASSISTANT, "answer [1]")]
    world.ask().execute("and then?", article_id=article, history=history)
    _, messages = world.chat.calls[0]
    assert [m.text for m in messages[:2]] == ["first?", "answer [1]"]
    assert messages[-1].text.endswith("Question: and then?")


def test_unknown_article_and_empty_question_are_errors(tmp_path: Path) -> None:
    world = World(tmp_path)
    with pytest.raises(ApplicationError, match="Unknown article"):
        world.ask().execute("q", article_id=NodeId("article:nope"))
    with pytest.raises(ApplicationError, match="Ask a question"):
        world.ask().execute("   ")


# -- ask across the library ---------------------------------------------------------
def test_library_questions_use_relevant_passages(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add(LEAKAGE)
    answer = world.ask(min_similarity=0.0).execute("random split on time ordered data")
    assert answer.grounded
    assert "Temporal leakage" in world.chat.last_prompt


def test_sources_are_what_the_model_would_see_without_asking_it(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add(LEAKAGE)
    ask = world.ask(min_similarity=0.0)
    sources = ask.sources("random split on time ordered data")
    assert any("Temporal leakage" in s.section for s in sources)
    assert world.chat.calls == []
    ask.execute("random split on time ordered data")
    assert all(s.text in world.chat.last_prompt for s in sources)


def test_nothing_relevant_means_not_found_without_calling_the_model(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add(LEAKAGE)
    answer = world.ask(min_similarity=0.99).execute("best pasta recipe")
    assert answer == answer.__class__(NOT_FOUND, (), grounded=False)
    assert world.chat.calls == []
