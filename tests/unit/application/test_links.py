from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml

from postloom.adapters.storage.database import SqliteDatabase
from postloom.adapters.storage.search import SqliteSearchIndex
from postloom.adapters.storage.sqlite import SqliteGraphRepository
from postloom.adapters.vault.markdown_vault import MarkdownVault
from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.errors import ApplicationError
from postloom.application.ports.embeddings import DocumentText, Vector
from postloom.application.ports.search_index import IndexedChunk
from postloom.application.use_cases import (
    BrowseContent,
    Decision,
    GraphOverview,
    IngestArticle,
    IngestArticleCommand,
    PreviewComments,
    ReviewLink,
    SaveComments,
    SeedTopics,
    SuggestLinks,
)
from postloom.domain.chunking import Chunk
from postloom.domain.content import Article
from postloom.domain.graph import EdgeKind, NodeId
from postloom.domain.provenance import Grade, Origin
from tests.fakes import FakeExtractor, FakeThreadParser, FixedClock, fixture_text, part3_extraction

SPACE = "test@3"


class Embedder:
    @property
    def name(self) -> str:
        return SPACE

    def embed_documents(self, documents: Sequence[DocumentText]) -> list[Vector]:
        raise AssertionError("suggestions reuse stored vectors")

    def embed_query(self, query: str) -> Vector:
        raise AssertionError("suggestions reuse stored vectors")


class World:
    def __init__(self, tmp_path: Path, max_per_article: int = 3) -> None:
        database = SqliteDatabase()
        self.repository = SqliteGraphRepository(database)
        self.index = SqliteSearchIndex(database)
        self.vault_dir = tmp_path / "vault"
        self.vault = MarkdownVault(self.vault_dir)
        self.clock = FixedClock()
        SeedTopics(self.repository, self.vault).execute(DEFAULT_TOPICS)
        self.a = self.add("Leakage A", [1, 0, 0])
        self.b = self.add("Leakage B", [0.9, 0.1, 0])
        self.c = self.add("Unrelated C", [0, 0, 1])
        self.suggest = SuggestLinks(
            self.repository, self.index, Embedder(), self.clock, 0.8, max_per_article
        )
        self.review = ReviewLink(self.repository, self.vault, self.clock)

    def add(self, title: str, vector: Vector) -> Article:
        extraction = part3_extraction(title=title)
        ingest = IngestArticle(FakeExtractor(extraction), self.repository, self.vault, self.clock)
        article = ingest.execute(IngestArticleCommand("article", f"Read {title}")).article
        self.embed(article, vector)
        return article

    def embed(self, article: Article, vector: Vector) -> None:
        chunk = Chunk(article.id, 0, "", "text", article.title)
        self.index.replace_chunks(article.id, [IndexedChunk(chunk, vector, SPACE)])

    def related(self, article: Article) -> list[tuple[str, Grade]]:
        detail = BrowseContent(self.repository).get_article(article.id)
        assert detail is not None
        return [(link.title, link.grade) for link in detail.related]

    def note_related(self, article: Article) -> list[str]:
        text = (self.vault_dir / "articles" / f"{article.slug}.md").read_text(encoding="utf-8")
        return yaml.safe_load(text.split("---")[1]).get("related", [])


def test_similar_articles_get_a_suggested_link(tmp_path: Path) -> None:
    world = World(tmp_path)
    result = world.suggest.execute()
    assert (result.added, result.updated, result.retired) == (1, 0, 0)
    assert result.pairs[0].similarity == pytest.approx(0.994, abs=1e-3)
    assert len(result.pairs) == 3  # every pair is reported, for calibration
    assert world.related(world.a) == [("Leakage B", Grade.ASSERTED)]
    assert world.related(world.b) == [("Leakage A", Grade.ASSERTED)]
    assert world.related(world.c) == []
    edges = world.repository.edges_from(min(world.a.id, world.b.id))
    (edge,) = [e for e in edges if e.kind is EdgeKind.RELATED_TO]
    assert edge.provenance.origin is Origin.SEMANTIC
    assert edge.provenance.evidence == "meaning similarity 0.994"


def test_suggesting_again_changes_nothing(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.suggest.execute()
    again = world.suggest.execute()
    assert (again.added, again.updated, again.retired) == (0, 0, 0)


def test_suggestions_are_not_written_to_the_vault_until_accepted(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.suggest.execute()
    assert world.note_related(world.a) == []
    world.review.execute(world.a.id, world.b.id, Decision.ACCEPT)
    assert world.note_related(world.a) == ["[[articles/leakage-b|Leakage B]]"]
    assert world.note_related(world.b) == ["[[articles/leakage-a|Leakage A]]"]
    assert world.related(world.a) == [("Leakage B", Grade.VERIFIED)]


def test_accepted_links_survive_a_re_ingest(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.review.execute(world.a.id, world.b.id, Decision.ACCEPT)
    world.add("Leakage A", [1, 0, 0])
    assert world.note_related(world.a) == ["[[articles/leakage-b|Leakage B]]"]
    assert world.related(world.a) == [("Leakage B", Grade.VERIFIED)]


def test_dismissed_links_are_hidden_and_never_suggested_again(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.suggest.execute()
    world.review.execute(world.b.id, world.a.id, Decision.REJECT)  # either direction
    assert world.related(world.a) == []
    again = world.suggest.execute()
    assert again.added == 0
    assert world.related(world.a) == []


def test_a_suggestion_that_no_longer_holds_is_retired_with_history(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.suggest.execute()
    world.embed(world.b, [0, 1, 0])  # B was rewritten and is no longer similar
    result = world.suggest.execute()
    assert result.retired == 1
    assert world.related(world.a) == []
    key = min(world.a.id, world.b.id)
    history = world.repository.edges_from(key, include_history=True)
    assert [e.superseded_at is not None for e in history if e.kind is EdgeKind.RELATED_TO] == [True]


def test_accepted_links_are_kept_even_when_no_longer_similar(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.suggest.execute()
    world.review.execute(world.a.id, world.b.id, Decision.ACCEPT)
    world.embed(world.b, [0, 1, 0])
    assert world.suggest.execute().retired == 0
    assert world.related(world.a) == [("Leakage B", Grade.VERIFIED)]


def test_articles_can_be_linked_by_hand(tmp_path: Path) -> None:
    world = World(tmp_path)
    link = world.review.execute(world.c.id, world.a.id, Decision.ACCEPT)
    assert (link.title, link.grade, link.origin) == ("Leakage A", Grade.VERIFIED, Origin.MANUAL)
    assert world.related(world.c) == [("Leakage A", Grade.VERIFIED)]


def test_each_article_keeps_only_its_closest_suggestions(tmp_path: Path) -> None:
    world = World(tmp_path, max_per_article=1)
    world.add("Leakage D", [0.95, 0.05, 0])
    world.suggest.execute()
    assert len(world.related(world.a)) == 1


def test_without_embeddings_nothing_is_compared(tmp_path: Path) -> None:
    world = World(tmp_path)
    plain = SuggestLinks(world.repository, world.index, None, world.clock, 0.8)
    assert not plain.execute().semantic


@pytest.mark.parametrize(
    ("first", "second", "message"),
    [
        ("article:leakage-a", "article:leakage-a", "itself"),
        ("article:leakage-a", "article:nope", "Unknown article"),
        ("article:leakage-a", "topic:rag", "Not an article"),
    ],
)
def test_invalid_reviews_are_refused(tmp_path: Path, first: str, second: str, message: str) -> None:
    world = World(tmp_path)
    with pytest.raises(ApplicationError, match=message):
        world.review.execute(NodeId(first), NodeId(second), Decision.ACCEPT)


def test_graph_overview_folds_comments_into_people(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.suggest.execute()
    pasted = fixture_text("comments", "caching_thread.txt")
    drafts = PreviewComments(FakeThreadParser(), world.repository).execute(
        world.a.id, pasted, "Alex Author"
    )
    SaveComments(world.repository, world.vault, world.clock).execute(world.a.id, drafts.messages)

    graph = GraphOverview(world.repository).execute()
    kinds = {n.id: n.kind for n in graph.nodes}
    assert sorted(n.label for n in graph.nodes if n.kind == "person") == [
        "Jane Example",
        "John Sample",
    ]
    assert sum(1 for n in graph.nodes if n.kind == "article") == 3
    assert all(n.weight > 0 for n in graph.nodes if n.kind == "topic")  # unused topics hidden
    discussed = {(link.source, link.weight) for link in graph.links if link.kind == "discussed"}
    assert discussed == {(NodeId("person:~jane-example"), 2), (NodeId("person:~john-sample"), 1)}
    related = [link for link in graph.links if link.kind == "related_to"]
    assert [(link.grade, kinds[link.source], kinds[link.target]) for link in related] == [
        (Grade.ASSERTED, "article", "article")
    ]
    assert all(link.source in kinds and link.target in kinds for link in graph.links)
