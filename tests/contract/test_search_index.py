"""The SearchIndex contract. Every retrieval index adapter must pass all of these."""

from collections.abc import Callable

import pytest

from postloom.adapters.storage.search import SqliteSearchIndex
from postloom.application.ports.search_index import IndexedChunk, SearchIndex
from postloom.domain.chunking import Chunk
from postloom.domain.graph import NodeId

pytestmark = pytest.mark.contract

FACTORIES: dict[str, Callable[[], SearchIndex]] = {"sqlite": SqliteSearchIndex}
adapters = pytest.mark.parametrize("make", FACTORIES.values(), ids=FACTORIES.keys())

LEAKAGE = NodeId("article:leakage")
CACHING = NodeId("article:caching")
SPACE = "test@3"


def chunk(node: NodeId, index: int, heading: str, text: str, title: str = "T") -> Chunk:
    return Chunk(node, index, heading, text, title)


def indexed(c: Chunk, vector: list[float] | None) -> IndexedChunk:
    return IndexedChunk(c, vector, SPACE if vector is not None else None)


def populated(make: Callable[[], SearchIndex]) -> SearchIndex:
    index = make()
    index.replace_chunks(
        LEAKAGE,
        [
            indexed(chunk(LEAKAGE, 0, "", "Duplicates across splits inflate scores."), [1, 0, 0]),
            indexed(chunk(LEAKAGE, 1, "Fix", "Split by time and by user."), [0.6, 0.8, 0]),
        ],
    )
    index.replace_chunks(
        CACHING,
        [indexed(chunk(CACHING, 0, "Metrics", "Cache hit rate and precision."), [0, 0, 1])],
    )
    return index


@adapters
def test_keyword_search_ranks_matching_chunks(make: Callable[[], SearchIndex]) -> None:
    hits = populated(make).keyword_search("duplicate scores", 10)
    assert [(h.node, h.index) for h in hits][:1] == [(LEAKAGE, 0)]
    assert all(h.score > 0 for h in hits)


@adapters
def test_keyword_search_stems_and_ignores_case(make: Callable[[], SearchIndex]) -> None:
    hits = populated(make).keyword_search("SPLITTING", 10)
    assert {h.node for h in hits} == {LEAKAGE}


@adapters
def test_keyword_search_is_safe_against_query_syntax(make: Callable[[], SearchIndex]) -> None:
    index = populated(make)
    for nasty in ['"', "AND OR NOT", "cache*", "-precision", "(hit", "NEAR(x y)", ""]:
        index.keyword_search(nasty, 10)  # must not raise


@adapters
def test_vector_search_orders_by_cosine_similarity(make: Callable[[], SearchIndex]) -> None:
    hits = populated(make).vector_search([1.0, 0.0, 0.0], SPACE, 2)
    assert [(h.node, h.index) for h in hits] == [(LEAKAGE, 0), (LEAKAGE, 1)]
    assert hits[0].score == pytest.approx(1.0)
    assert hits[1].score == pytest.approx(0.6)


@adapters
def test_vector_search_never_mixes_vector_spaces(make: Callable[[], SearchIndex]) -> None:
    assert populated(make).vector_search([1.0, 0.0, 0.0], "other-model@3", 5) == []


@adapters
def test_replacing_chunks_drops_the_old_ones(make: Callable[[], SearchIndex]) -> None:
    index = populated(make)
    index.replace_chunks(LEAKAGE, [indexed(chunk(LEAKAGE, 0, "", "Brand new text."), [1, 0, 0])])
    assert index.keyword_search("duplicates", 10) == []
    assert [h.text for h in index.vector_search([1.0, 0.0, 0.0], SPACE, 5)][:1] == [
        "Brand new text."
    ]


@adapters
def test_remove_deletes_a_node_from_both_searches(make: Callable[[], SearchIndex]) -> None:
    index = populated(make)
    index.remove(LEAKAGE)
    assert {h.node for h in index.keyword_search("scores split cache", 10)} == {CACHING}
    assert {h.node for h in index.vector_search([1.0, 0.0, 0.0], SPACE, 10)} == {CACHING}


@adapters
def test_cached_vectors_are_found_by_content_hash(make: Callable[[], SearchIndex]) -> None:
    index = populated(make)
    known = chunk(LEAKAGE, 0, "", "Duplicates across splits inflate scores.")
    unknown = chunk(LEAKAGE, 0, "", "Never indexed.")
    found = index.cached_vectors(SPACE, [known.content_hash, unknown.content_hash])
    assert list(found) == [known.content_hash]
    assert found[known.content_hash] == pytest.approx([1.0, 0.0, 0.0])
    assert index.cached_vectors("other@3", [known.content_hash]) == {}


@adapters
def test_chunks_without_vectors_are_keyword_searchable_only(
    make: Callable[[], SearchIndex],
) -> None:
    index = make()
    index.replace_chunks(LEAKAGE, [indexed(chunk(LEAKAGE, 0, "", "Leakage basics"), None)])
    assert len(index.keyword_search("leakage", 5)) == 1
    assert index.vector_search([1.0, 0.0, 0.0], SPACE, 5) == []


@adapters
def test_chunks_of_returns_a_nodes_chunks_in_order(make: Callable[[], SearchIndex]) -> None:
    chunks = populated(make).chunks_of(LEAKAGE)
    assert [(c.index, c.heading) for c in chunks] == [(0, ""), (1, "Fix")]
    assert populated(make).chunks_of(NodeId("article:none")) == []


@adapters
def test_vectors_by_node_groups_one_vector_space(make: Callable[[], SearchIndex]) -> None:
    index = populated(make)
    index.replace_chunks(
        NodeId("article:other-space"),
        [IndexedChunk(chunk(NodeId("article:other-space"), 0, "", "x"), [1, 1, 1], "other@3")],
    )
    grouped = index.vectors_by_node(SPACE)
    assert set(grouped) == {LEAKAGE, CACHING}
    assert [x for v in grouped[LEAKAGE] for x in v] == pytest.approx([1, 0, 0, 0.6, 0.8, 0])
    assert index.vectors_by_node("missing@3") == {}


@adapters
def test_vector_spaces_count_chunks_with_vectors(make: Callable[[], SearchIndex]) -> None:
    index = populated(make)
    index.replace_chunks(
        NodeId("article:plain"), [indexed(chunk(NodeId("article:plain"), 0, "", "x"), None)]
    )
    assert index.vector_spaces() == {SPACE: 3}


@adapters
def test_keyword_search_works_in_every_script(make: Callable[[], SearchIndex]) -> None:
    index = make()
    texts = {
        "fa": "حافظه نهان معنایی پاسخ مدل زبانی را دوباره استفاده می‌کند",
        "ru": "Семантический кэш повторно использует ответы модели",
        "zh": "语义缓存可以重复使用大语言模型的答案",
        "ja": "セマンティックキャッシュは大規模言語モデルの回答を再利用します",
    }
    for key, text in texts.items():
        node = NodeId(f"article:{key}")
        index.replace_chunks(node, [indexed(chunk(node, 0, "", text), None)])
    for query, expected in [
        ("حافظه", "fa"),
        ("КЭШ", "ru"),
        ("语义缓存", "zh"),  # written without spaces between words
        ("キャッシュ", "ja"),
    ]:
        hits = index.keyword_search(query, 5)
        assert [h.node for h in hits][:1] == [NodeId(f"article:{expected}")], query
    assert index.keyword_search("量子计算", 5) == []  # pieces that appear nowhere
