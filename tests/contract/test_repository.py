"""The GraphRepository contract. Every storage adapter must pass all of these.

To add an adapter, append its factory to FACTORIES; nothing else changes.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from postloom.adapters.storage.memory import InMemoryGraphRepository
from postloom.application.ports.repository import GraphRepository
from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.graph import Edge, EdgeKind
from postloom.domain.provenance import Grade, Origin, Provenance

pytestmark = pytest.mark.contract

FACTORIES: dict[str, Callable[[], GraphRepository]] = {
    "memory": InMemoryGraphRepository,
}
adapters = pytest.mark.parametrize("make", FACTORIES.values(), ids=FACTORIES.keys())

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2026, 2, 1, tzinfo=UTC)
RAG = Topic("RAG")
ARTICLE = Article(title="Part 3", body_markdown="Body", series=Series("Caching"), series_part=3)
POST = Post(key=ARTICLE.slug, text="Read part 3", links=("https://lnkd.in/euyuNU9y",))


def belongs(grade: Grade = Grade.ASSERTED) -> Edge:
    return Edge(
        ARTICLE.id, RAG.id, EdgeKind.BELONGS_TO, Provenance(Origin.TAXONOMY, grade, "llm", T0)
    )


@adapters
def test_topics_round_trip(make: Callable[[], GraphRepository]) -> None:
    repo = make()
    repo.save_topic(RAG)
    repo.save_topic(RAG)
    assert list(repo.list_topics()) == [RAG]


@adapters
def test_content_round_trips_unchanged(make: Callable[[], GraphRepository]) -> None:
    repo = make()
    repo.save_series(Series("Caching"))
    repo.save_article(ARTICLE)
    repo.save_post(POST)
    assert repo.get_article(ARTICLE.id) == ARTICLE
    assert repo.get_post(POST.id) == POST
    assert repo.get_article(Article(title="Missing", body_markdown="x").id) is None


@adapters
def test_saving_an_edge_twice_keeps_one_live_edge(make: Callable[[], GraphRepository]) -> None:
    repo = make()
    repo.save_edge(belongs())
    repo.save_edge(belongs().verify(T1))
    edges = list(repo.edges_from(ARTICLE.id))
    assert len(edges) == 1
    assert edges[0].provenance.grade is Grade.VERIFIED
    assert list(repo.edges_to(RAG.id)) == edges


@adapters
def test_superseded_edges_move_to_history(make: Callable[[], GraphRepository]) -> None:
    repo = make()
    repo.save_edge(belongs())
    repo.supersede_edge(belongs().supersede(T1))
    assert list(repo.edges_from(ARTICLE.id)) == []
    history = list(repo.edges_from(ARTICLE.id, include_history=True))
    assert [e.superseded_at for e in history] == [T1]


@adapters
def test_rejected_edges_stay_visible_so_decisions_are_respected(
    make: Callable[[], GraphRepository],
) -> None:
    repo = make()
    repo.save_edge(belongs().reject(T1))
    (edge,) = repo.edges_from(ARTICLE.id)
    assert edge.provenance.grade is Grade.REJECTED
    assert not edge.is_current


@adapters
def test_save_edge_refuses_superseded_edges(make: Callable[[], GraphRepository]) -> None:
    repo = make()
    with pytest.raises(ValueError):
        repo.save_edge(belongs().supersede(T1))
