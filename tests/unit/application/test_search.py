from collections.abc import Sequence

import pytest

from postloom.adapters.storage.database import SqliteDatabase
from postloom.adapters.storage.search import SqliteSearchIndex
from postloom.adapters.storage.sqlite import SqliteGraphRepository
from postloom.application.errors import ApplicationError, ProviderUnavailableError
from postloom.application.ports.embeddings import DocumentText, Vector
from postloom.application.use_cases import IndexArticle, Method, ReindexAll, SearchContent
from postloom.domain.content import Article
from postloom.domain.graph import NodeId
from tests.fakes import FakeEmbedder

LEAKAGE = Article(
    title="Data Leakage in Machine Learning",
    summary="Why test scores lie when information leaks from test into training.",
    body_markdown=(
        "You hold out 20% of your data and the test score looks excellent.\n\n"
        "## Duplicates across splits\n\n"
        "The same example in train and test makes the model memorize instead of generalize.\n\n"
        "## Temporal leakage\n\n"
        "A random split on time-ordered data lets the model train on the future."
    ),
)
CACHING = Article(
    title="Semantic Caching for AI Agents",
    body_markdown=(
        "## Metrics\n\nTrack cache hit rate, precision and recall of cached answers.\n\n"
        "## LangGraph workflow\n\nDecompose the query and check the cache per sub-query."
    ),
)


class World:
    def __init__(self, embedder: FakeEmbedder | None = None) -> None:
        database = SqliteDatabase()
        self.repository = SqliteGraphRepository(database)
        self.index = SqliteSearchIndex(database)
        self.embedder = embedder
        for article in (LEAKAGE, CACHING):
            self.repository.save_article(article)
        self.index_article = IndexArticle(self.repository, self.index, embedder)
        self.search = SearchContent(self.index, self.repository, embedder)

    def index_all(self) -> None:
        ReindexAll(self.repository, self.index_article).execute()


# -- indexing ---------------------------------------------------------------------
def test_indexing_embeds_the_summary_and_every_section() -> None:
    world = World(FakeEmbedder())
    result = world.index_article.execute(LEAKAGE.id)
    assert (result.chunks, result.embedded, result.reused, result.semantic) == (4, 4, 0, True)


def test_reindexing_unchanged_content_embeds_nothing() -> None:
    embedder = FakeEmbedder()
    world = World(embedder)
    world.index_article.execute(LEAKAGE.id)
    again = world.index_article.execute(LEAKAGE.id)
    assert (again.embedded, again.reused) == (0, 4)
    assert embedder.documents_embedded == 4


def test_editing_one_section_re_embeds_only_that_section() -> None:
    world = World(FakeEmbedder())
    world.index_article.execute(LEAKAGE.id)
    edited = Article(
        title=LEAKAGE.title,
        summary=LEAKAGE.summary,
        body_markdown=LEAKAGE.body_markdown.replace("on the future.", "on the future!"),
    )
    world.repository.save_article(edited)
    result = world.index_article.execute(LEAKAGE.id)
    assert (result.embedded, result.reused) == (1, 3)


def test_without_an_embedder_articles_are_keyword_searchable() -> None:
    world = World(embedder=None)
    assert not world.index_article.execute(LEAKAGE.id).semantic
    found = world.search.execute("temporal leakage")
    assert found.methods == {Method.KEYWORD}
    assert [r.article_id for r in found.results] == [LEAKAGE.id]


def test_indexing_an_unknown_article_fails_clearly() -> None:
    with pytest.raises(ApplicationError, match="Unknown article"):
        World(FakeEmbedder()).index_article.execute(NodeId("article:nope"))


def test_reindex_all_reports_totals() -> None:
    world = World(FakeEmbedder())
    result = ReindexAll(world.repository, world.index_article).execute()
    assert (result.articles, result.chunks, result.embedded) == (2, 6, 6)


# -- searching --------------------------------------------------------------------
def test_hybrid_search_groups_passages_by_article() -> None:
    world = World(FakeEmbedder())
    world.index_all()

    found = world.search.execute("duplicates in train and test")

    assert found.methods == {Method.KEYWORD, Method.SEMANTIC}
    best = found.results[0]
    assert best.article_id == LEAKAGE.id
    assert best.title == LEAKAGE.title
    assert best.passages[0].heading == "Duplicates across splits"
    assert best.passages[0].matched_by == {Method.KEYWORD, Method.SEMANTIC}
    assert len({r.article_id for r in found.results}) == len(found.results)


def test_semantic_search_finds_passages_without_shared_keywords() -> None:
    """Simulates meaning-based recall: the keyword index has no match for the query."""

    class SynonymEmbedder(FakeEmbedder):
        def embed_query(self, query: str) -> Vector:
            return super().embed_query("cache hit rate precision recall")

    world = World(SynonymEmbedder())
    world.index_all()
    found = world.search.execute("how good are my stored responses")
    assert found.results[0].article_id == CACHING.id
    assert found.results[0].passages[0].matched_by == {Method.SEMANTIC}


def test_provider_failure_falls_back_to_keyword_search() -> None:
    class BrokenQueries(FakeEmbedder):
        def embed_query(self, query: str) -> Vector:
            raise ProviderUnavailableError("offline")

    embedder = BrokenQueries()
    world = World(embedder)
    world.index_all()
    found = world.search.execute("temporal leakage")
    assert found.methods == {Method.KEYWORD}
    assert found.results[0].article_id == LEAKAGE.id
    assert any("offline" in w for w in found.warnings)


def test_limit_and_empty_queries() -> None:
    world = World(FakeEmbedder())
    world.index_all()
    assert len(world.search.execute("cache leakage test", limit=1).results) == 1
    assert world.search.execute("   ").results == ()


def test_documents_carry_their_title_for_embedding() -> None:
    seen: list[DocumentText] = []

    class Recording(FakeEmbedder):
        def embed_documents(self, documents: Sequence[DocumentText]) -> list[Vector]:
            seen.extend(documents)
            return super().embed_documents(documents)

    World(Recording()).index_article.execute(CACHING.id)
    assert {d.title for d in seen} == {CACHING.title}
    assert seen[0].text.startswith("Metrics\n\n")


def test_semantic_matches_below_the_cutoff_are_dropped() -> None:
    """Nearest-neighbour search always returns *something*; the cutoff removes noise."""
    world = World(FakeEmbedder())
    world.index_all()
    strict = SearchContent(world.index, world.repository, world.embedder, min_similarity=0.99)
    found = strict.execute("quantum gardening recipes")
    assert found.results == ()


def test_passages_explain_their_scores() -> None:
    world = World(FakeEmbedder())
    world.index_all()
    passage = world.search.execute("temporal leakage").results[0].passages[0]
    assert passage.keyword_score is not None and passage.keyword_score > 0
    assert passage.similarity is not None and 0 < passage.similarity <= 1.0001
