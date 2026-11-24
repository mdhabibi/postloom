"""The GraphRepository contract. Every storage adapter must pass all of these.

To add an adapter, append its factory to FACTORIES; nothing else changes.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime

import pytest

from postloom.adapters.storage.memory import InMemoryGraphRepository
from postloom.adapters.storage.sqlite import SqliteGraphRepository
from postloom.application.ports.repository import GraphContents, GraphRepository
from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.discussion import OWNER, Comment
from postloom.domain.entities import Category, Entity
from postloom.domain.graph import Edge, EdgeKind, NodeId
from postloom.domain.people import Person, ProfileUrl
from postloom.domain.provenance import Grade, Origin, Provenance

pytestmark = pytest.mark.contract

FACTORIES: dict[str, Callable[[], GraphRepository]] = {
    "memory": InMemoryGraphRepository,
    "sqlite": SqliteGraphRepository,
}
adapters = pytest.mark.parametrize("make", FACTORIES.values(), ids=FACTORIES.keys())

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2026, 2, 1, tzinfo=UTC)
RAG = Topic("RAG")
ARTICLE = Article(
    title="Part 3",
    body_markdown="## Metrics\n\nHit rate: précision 👇",
    summary="Measuring caches.",
    url="https://www.linkedin.com/pulse/part-3",
    published_on=date(2026, 10, 12),
    series=Series("Caching"),
    series_part=3,
    hashtags=("RAG", "LLM"),
    entities=("LangGraph",),
)
POST = Post(
    key=ARTICLE.slug,
    text="Read part 3",
    published_on=date(2026, 10, 12),
    hashtags=("RAG",),
    links=("https://lnkd.in/euyuNU9y",),
    banner_path="assets/part3.png",
)


LAB = Entity(
    "example-lab",
    "Example Lab",
    Category.ORGANISATION,
    url="https://example.org",
    aliases=("ExLab",),
)


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
    assert repo.get_post(Post(key="missing", text="x").id) is None


@adapters
def test_articles_are_listed_in_first_save_order(make: Callable[[], GraphRepository]) -> None:
    repo = make()
    repo.save_article(Article(title="First", body_markdown="a"))
    repo.save_article(Article(title="Second", body_markdown="b"))
    repo.save_article(Article(title="First", body_markdown="edited"))
    assert [a.body_markdown for a in repo.list_articles()] == ["edited", "b"]


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
def test_edges_round_trip_every_field(make: Callable[[], GraphRepository]) -> None:
    repo = make()
    provenance = Provenance(Origin.SEMANTIC, Grade.ASSERTED, "embedding:x", T0, "cos=0.91")
    other = Article(title="Part 2", body_markdown="Body")
    edge = Edge(ARTICLE.id, other.id, EdgeKind.RELATED_TO, provenance, weight=0.91)
    repo.save_edge(edge)
    assert list(repo.edges_from(ARTICLE.id)) == [edge]


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


# -- discussions --------------------------------------------------------------------
@adapters
def test_comments_round_trip_in_pasted_order(make: Callable[[], GraphRepository]) -> None:
    repo = make()
    jane = NodeId("person:~jane-example")
    top = Comment(POST.id, jane, "Jane Example", "Question?", 0, posted_label="4h")
    reply = Comment(POST.id, OWNER, "Alex Author", "Answer.", 1, thread=top.id, reply_to=top.id)
    other = Comment(NodeId("post:other"), OWNER, "Alex Author", "Elsewhere", 0)
    for comment in (reply, other, top):
        repo.save_comment(comment)

    assert list(repo.comments_on(POST.id)) == [top, reply]
    assert repo.get_comment(reply.id) == reply
    assert repo.get_comment(NodeId("comment:none")) is None


@adapters
def test_people_round_trip_with_headline_history(make: Callable[[], GraphRepository]) -> None:
    repo = make()
    jane = Person("Jane Example", ProfileUrl.parse("linkedin.com/in/jane-example"))
    jane = jane.observe("Engineer at Acme", T0).observe("Lead at Beta", T1)
    provisional = Person("John Sample", notes="Met at PyCon", tags=("speaker",))
    repo.save_person(jane)
    repo.save_person(provisional)

    assert repo.get_person(jane.id) == jane
    assert repo.get_person(provisional.id) == provisional
    assert {p.name for p in repo.list_people()} == {"Jane Example", "John Sample"}


# -- whole-graph operations ---------------------------------------------------------
def filled(repo: GraphRepository) -> GraphRepository:
    """A small graph with a live edge, a rejected edge and history."""
    jane = Person("Jane Example", ProfileUrl.parse("linkedin.com/in/jane-example"))
    comment = Comment(POST.id, jane.id, "Jane Example", "Question?", 0)
    structural = Provenance(Origin.STRUCTURAL, Grade.VERIFIED, "parser", T0)
    repo.save_topic(RAG)
    repo.save_series(Series("Caching"))
    repo.save_article(ARTICLE)
    repo.save_article(Article(title="Part 2", body_markdown="Body", key="part-2"))
    repo.save_post(POST)
    repo.save_person(jane)
    repo.save_comment(comment)
    repo.save_edge(belongs())
    repo.supersede_edge(belongs().supersede(T1))
    repo.save_edge(belongs(Grade.VERIFIED))
    repo.save_edge(Edge(POST.id, ARTICLE.id, EdgeKind.ANNOUNCES, structural))
    repo.save_edge(Edge(jane.id, comment.id, EdgeKind.AUTHORED, structural))
    repo.save_edge(Edge(comment.id, POST.id, EdgeKind.COMMENTED_ON, structural))
    repo.save_entity(LAB)
    confirmed = Provenance(Origin.MANUAL, Grade.VERIFIED, "user", T0, "Thanks to Example Lab")
    repo.save_edge(Edge(POST.id, LAB.id, EdgeKind.MENTIONS, confirmed))
    repo.save_edge(Edge(POST.id, jane.id, EdgeKind.MENTIONS, confirmed))
    return repo


def snapshot(repo: GraphRepository) -> GraphContents:
    posts = tuple(repo.list_posts())
    return GraphContents(
        topics=tuple(repo.list_topics()),
        series=(Series("Caching"),),
        articles=tuple(repo.list_articles()),
        posts=posts,
        comments=tuple(c for p in posts for c in repo.comments_on(p.id)),
        people=tuple(repo.list_people()),
        entities=tuple(repo.list_entities()),
        edges=tuple(repo.all_edges()),
    )


@adapters
def test_posts_are_listed(make: Callable[[], GraphRepository]) -> None:
    repo = make()
    repo.save_post(POST)
    assert list(repo.list_posts()) == [POST]


@adapters
def test_all_edges_includes_history_and_rejections(make: Callable[[], GraphRepository]) -> None:
    repo = filled(make())
    edges = list(repo.all_edges())
    assert len(edges) == 7
    assert sum(1 for e in edges if e.superseded_at is not None) == 1
    assert [e.superseded_at for e in edges if e.kind is EdgeKind.BELONGS_TO] == [T1, None]


@adapters
def test_deleting_a_node_erases_its_edges_and_their_history(
    make: Callable[[], GraphRepository],
) -> None:
    repo = filled(make())
    repo.erase_nodes([ARTICLE.id])
    assert repo.get_article(ARTICLE.id) is None
    assert list(repo.edges_from(ARTICLE.id, include_history=True)) == []
    assert all(ARTICLE.id not in (e.source, e.target) for e in repo.all_edges())
    assert len(repo.list_articles()) == 1  # other nodes are untouched
    assert len(repo.all_edges()) == 4  # the comment and mention edges


@adapters
def test_replacing_a_graph_with_its_own_contents_changes_nothing(
    make: Callable[[], GraphRepository],
) -> None:
    repo = filled(make())
    before = snapshot(repo)
    repo.replace_graph(before)
    assert snapshot(repo) == before
    (live,) = repo.edges_from(ARTICLE.id)
    assert live.provenance.grade is Grade.VERIFIED


@adapters
def test_replacing_a_graph_removes_what_is_not_in_it(make: Callable[[], GraphRepository]) -> None:
    source = filled(make())
    target = filled(make())
    target.save_article(Article(title="Stale", body_markdown="x"))
    target.save_topic(Topic("Stale topic"))
    target.replace_graph(snapshot(source))
    assert {a.title for a in target.list_articles()} == {"Part 3", "Part 2"}
    assert list(target.list_topics()) == [RAG]
    assert list(target.all_edges()) == list(source.all_edges())


@adapters
def test_articles_keep_their_key_when_retitled(make: Callable[[], GraphRepository]) -> None:
    repo = make()
    first = Article(title="Old title", body_markdown="Body", key="old-title")
    repo.save_article(first)
    repo.save_article(Article(title="A better title", body_markdown="Body", key="old-title"))
    (stored,) = repo.list_articles()
    assert (stored.id, stored.title) == (first.id, "A better title")


@adapters
def test_removing_a_node_keeps_the_history_of_its_edges(
    make: Callable[[], GraphRepository],
) -> None:
    repo = filled(make())
    repo.remove_node(RAG.id)
    assert list(repo.list_topics()) == []
    assert len(repo.edges_to(RAG.id, include_history=True)) == 2


@adapters
def test_entities_round_trip_and_keep_their_id_when_renamed(
    make: Callable[[], GraphRepository],
) -> None:
    repo = make()
    repo.save_entity(LAB)
    assert repo.get_entity(LAB.id) == LAB
    renamed = LAB.renamed("Example Research Lab")
    repo.save_entity(renamed)
    assert renamed.id == LAB.id
    assert repo.list_entities() == [renamed]
    assert renamed.aliases == ("ExLab", "Example Lab")
    assert renamed.is_called("example   lab") and renamed.is_called("EXLAB")
