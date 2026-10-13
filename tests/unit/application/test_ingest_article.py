from datetime import date
from pathlib import Path

import pytest

from postloom.adapters.storage.memory import InMemoryGraphRepository
from postloom.adapters.vault.markdown_vault import MarkdownVault
from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.errors import NoTopicsConfiguredError
from postloom.application.use_cases import IngestArticle, IngestArticleCommand, SeedTopics
from postloom.domain.content import Topic
from postloom.domain.graph import EdgeKind, NodeId, NodeKind, node_id
from postloom.domain.provenance import Grade, Origin
from postloom.domain.text import slugify
from tests.fakes import FakeExtractor, FixedClock, fixture_text, part3_extraction

ARTICLE_ID = node_id(NodeKind.ARTICLE, slugify(part3_extraction().title))


def command() -> IngestArticleCommand:
    return IngestArticleCommand(
        article_text=fixture_text("semantic_caching_part3", "article.txt"),
        post_text=fixture_text("semantic_caching_part3", "post.txt"),
        article_url="https://www.linkedin.com/pulse/measuring-what-matters-part-3",
        published_on=date(2026, 10, 12),
    )


class World:
    """A fully wired use case over in-memory and temp-dir adapters."""

    def __init__(self, tmp_path: Path, extractor: FakeExtractor | None = None) -> None:
        self.repository = InMemoryGraphRepository()
        self.vault = MarkdownVault(tmp_path / "vault")
        self.clock = FixedClock()
        self.extractor = extractor or FakeExtractor(part3_extraction())
        SeedTopics(self.repository, self.vault).execute(DEFAULT_TOPICS)
        self.ingest = IngestArticle(self.extractor, self.repository, self.vault, self.clock)

    def topic_grades(self, article_id: NodeId) -> dict[str, Grade]:
        return {
            e.target: e.provenance.grade
            for e in self.repository.edges_from(article_id)
            if e.kind is EdgeKind.BELONGS_TO
        }


def test_ingest_creates_article_post_topics_and_series(tmp_path: Path) -> None:
    world = World(tmp_path)
    result = world.ingest.execute(command())

    assert result.article.id == ARTICLE_ID
    assert result.article.series_part == 3
    assert result.article.series is not None
    assert result.article.entities == ("LangGraph", "Redis", "LLM-as-a-judge")
    assert [t.name for t in result.topics] == ["RAG", "AI Agents"]
    assert result.post.links == (
        "https://lnkd.in/euyuNU9y",
        "https://lnkd.in/e-fJ7GXi",
        "https://lnkd.in/erGaGnNp",
    )
    assert "LangGraph" in result.post.hashtags
    assert not result.is_update
    assert result.warnings == ()
    assert result.note_path.exists()


def test_extractor_only_sees_the_users_taxonomy(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.ingest.execute(command())
    request = world.extractor.requests[0]
    assert request.allowed_topics == tuple(t.name for t in DEFAULT_TOPICS)


def test_edge_provenance_separates_parsed_facts_from_model_claims(tmp_path: Path) -> None:
    world = World(tmp_path)
    result = world.ingest.execute(command())
    by_kind = {e.kind: e for e in result.edges}

    announces = by_kind[EdgeKind.ANNOUNCES]
    assert announces.provenance.origin is Origin.STRUCTURAL
    assert announces.provenance.grade is Grade.VERIFIED

    belongs = by_kind[EdgeKind.BELONGS_TO]
    assert belongs.provenance.grade is Grade.ASSERTED
    assert belongs.provenance.producer == "llm:fake"


def test_topics_outside_the_taxonomy_are_dropped_with_a_warning(tmp_path: Path) -> None:
    extractor = FakeExtractor(part3_extraction(topics=("RAG", "Quantum Basket Weaving")))
    result = World(tmp_path, extractor).ingest.execute(command())
    assert [t.name for t in result.topics] == ["RAG"]
    assert any("Quantum Basket Weaving" in w for w in result.warnings)


def test_topic_matching_is_case_insensitive(tmp_path: Path) -> None:
    extractor = FakeExtractor(part3_extraction(topics=("rag", " ai agents ")))
    result = World(tmp_path, extractor).ingest.execute(command())
    assert [t.name for t in result.topics] == ["RAG", "AI Agents"]


def test_ingest_without_topics_fails_with_an_actionable_error(tmp_path: Path) -> None:
    repository = InMemoryGraphRepository()
    ingest = IngestArticle(
        FakeExtractor(part3_extraction()),
        repository,
        MarkdownVault(tmp_path),
        FixedClock(),
    )
    with pytest.raises(NoTopicsConfiguredError):
        ingest.execute(command())


def test_reingest_replaces_stale_model_topics_but_keeps_history(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.ingest.execute(command())

    world.extractor.result = part3_extraction(topics=("RAG", "MLOps"))
    world.clock.advance(days=1)
    result = world.ingest.execute(command())

    assert result.is_update
    assert world.topic_grades(ARTICLE_ID) == {
        "topic:rag": Grade.ASSERTED,
        "topic:mlops": Grade.ASSERTED,
    }
    history = [
        e
        for e in world.repository.edges_from(ARTICLE_ID, include_history=True)
        if e.superseded_at is not None
    ]
    assert [e.target for e in history] == ["topic:ai-agents"]


def test_reingest_never_overrides_the_users_decisions(tmp_path: Path) -> None:
    world = World(tmp_path)
    first = world.ingest.execute(command())
    agents, rag = (
        next(e for e in first.edges if e.target == f"topic:{slug}") for slug in ("ai-agents", "rag")
    )
    world.repository.save_edge(agents.verify(world.clock.now()))
    world.repository.save_edge(rag.reject(world.clock.now()))

    # The model now omits the verified topic and re-proposes the rejected one.
    world.extractor.result = part3_extraction(topics=("RAG",))
    result = world.ingest.execute(command())

    assert world.topic_grades(ARTICLE_ID) == {
        "topic:ai-agents": Grade.VERIFIED,
        "topic:rag": Grade.REJECTED,
    }
    assert {e.target for e in result.edges if e.kind is EdgeKind.BELONGS_TO} == {
        "topic:ai-agents"
    }


def test_series_part_comes_from_the_title_when_present(tmp_path: Path) -> None:
    extractor = FakeExtractor(part3_extraction(series_part=7))
    result = World(tmp_path, extractor).ingest.execute(command())
    assert result.article.series_part == 3


def test_no_series_means_no_part_number(tmp_path: Path) -> None:
    extractor = FakeExtractor(part3_extraction(series_name=None, title="A standalone article"))
    result = World(tmp_path, extractor).ingest.execute(command())
    assert result.article.series is None
    assert result.article.series_part is None
    assert all(e.kind is not EdgeKind.PART_OF for e in result.edges)


def test_seed_topics_is_idempotent(tmp_path: Path) -> None:
    world = World(tmp_path)  # already seeded once
    created = SeedTopics(world.repository, world.vault).execute(
        [*DEFAULT_TOPICS, Topic("Reinforcement Learning")]
    )
    assert [t.name for t in created] == ["Reinforcement Learning"]
