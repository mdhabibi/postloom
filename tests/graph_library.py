"""An invented library for the graph export tests.

Its texts carry everything that breaks naive writers: quotes of both kinds, backslashes,
new lines, a would-be Cypher injection, control characters and other scripts.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from postloom.application.ports.repository import GraphContents
from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.discussion import OWNER, Comment
from postloom.domain.entities import Category, Entity
from postloom.domain.graph import Edge, EdgeKind, NodeId
from postloom.domain.media import Media, MediaKind
from postloom.domain.people import Person, ProfileObservation, ProfileUrl
from postloom.domain.provenance import Grade, Origin, Provenance

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
NASTY = "She said \"don't\" \\ then '}) DETACH DELETE n //\nnew line\ttab \x07bell 日本語 🎉"


def prov(
    grade: Grade = Grade.VERIFIED,
    origin: Origin = Origin.STRUCTURAL,
    producer: str = "parser",
    evidence: str | None = None,
) -> Provenance:
    return Provenance(origin, grade, producer, T0, evidence)


def library() -> GraphContents:
    rag = Topic("RAG", "Retrieval-augmented generation")
    evals = Topic("Evaluation")
    series = Series("Caching in practice")
    chart = Media(
        "media/caching-one/chart.png", MediaKind.IMAGE, caption="Latency", description="A bar chart"
    )
    one = Article(
        "Caching, part one",
        f"# Caching\n\n{NASTY}",
        summary="Why cache",
        url="https://www.linkedin.com/pulse/caching-one",
        published_on=date(2026, 3, 4),
        series=series,
        series_part=1,
        hashtags=("caching", "llm"),
        key="caching-one",
        media=(chart,),
    )
    two = Article("Caching, part two", "Body two", key="caching-two", series=series, series_part=2)
    post = Post(
        "caching-one", f"Part one is out.\n\n{NASTY}", url="https://www.linkedin.com/feed/update/1"
    )
    alone = Post("a-thought", "Just a thought", links=("https://example.org/a b", "not a url"))
    jane = Person(
        "Jane Example",
        ProfileUrl("jane-example"),
        (ProfileObservation("Engineer at Example Labs", T0),),
        notes=NASTY,
        tags=("speaker",),
    )
    sam = Person("Sam Sample")  # provisional: no profile yet
    first = Comment(post.id, jane.id, "Jane Example", f"Great read. {NASTY}", 0, posted_label="2w")
    reply = Comment(post.id, OWNER, "Alex Author", "Thanks!", 1, first.id, first.id)
    third = Comment(post.id, sam.id, "Sam Sample", "+1", 2)
    lab = Entity(
        "example-labs", "Example Labs", Category.ORGANISATION, "https://example.org", ("ExLabs",)
    )

    def edge(
        s: NodeId,
        t: NodeId,
        kind: EdgeKind,
        p: Provenance | None = None,
        weight: float | None = None,
        superseded_at: datetime | None = None,
    ) -> Edge:
        return Edge(s, t, kind, p or prov(), weight, superseded_at)

    edges = (
        edge(
            one.id,
            rag.id,
            EdgeKind.BELONGS_TO,
            prov(Grade.ASSERTED, Origin.TAXONOMY, producer="llm:test"),
        ),
        edge(
            two.id,
            rag.id,
            EdgeKind.BELONGS_TO,
            prov(Grade.VERIFIED, Origin.MANUAL, producer="user"),
        ),
        edge(one.id, series.id, EdgeKind.PART_OF),
        edge(two.id, series.id, EdgeKind.PART_OF),
        edge(post.id, one.id, EdgeKind.ANNOUNCES),
        edge(alone.id, evals.id, EdgeKind.BELONGS_TO),
        edge(first.id, post.id, EdgeKind.COMMENTED_ON),
        edge(reply.id, post.id, EdgeKind.COMMENTED_ON),
        edge(third.id, post.id, EdgeKind.COMMENTED_ON),
        edge(reply.id, first.id, EdgeKind.REPLIED_TO),
        edge(jane.id, first.id, EdgeKind.AUTHORED),
        edge(OWNER, reply.id, EdgeKind.AUTHORED),
        edge(sam.id, third.id, EdgeKind.AUTHORED),
        edge(one.id, lab.id, EdgeKind.MENTIONS, prov(evidence=NASTY)),
        edge(one.id, jane.id, EdgeKind.MENTIONS),
        # An accepted suggestion: the asserted record was superseded by a verified one.
        edge(
            one.id,
            two.id,
            EdgeKind.RELATED_TO,
            prov(Grade.ASSERTED, Origin.SEMANTIC, producer="embeddings"),
            weight=0.91,
            superseded_at=T1,
        ),
        edge(
            one.id,
            two.id,
            EdgeKind.RELATED_TO,
            Provenance(Origin.SEMANTIC, Grade.VERIFIED, "user", T1),
            weight=0.91,
        ),
        # A dismissed suggestion.
        edge(
            two.id,
            evals.id,
            EdgeKind.BELONGS_TO,
            Provenance(Origin.TAXONOMY, Grade.REJECTED, "user", T1),
        ),
        # A link to an erased node stays in the history only.
        edge(alone.id, NodeId("article:erased"), EdgeKind.LINKS_TO, superseded_at=T1),
    )
    return GraphContents(
        topics=(rag, evals),
        series=(series,),
        articles=(one, two),
        posts=(post, alone),
        comments=(first, reply, third),
        people=(jane, sam),
        entities=(lab,),
        edges=edges,
    )
