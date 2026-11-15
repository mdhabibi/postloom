"""A small, realistic library in a temporary home folder, on real storage with fake models.

Three articles; comments and people on the first; one link accepted and one dismissed;
topics and a series set by the author; notes on a person.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.use_cases import Decision, IngestArticleCommand
from postloom.bootstrap import Container, build_container
from postloom.domain.graph import EdgeKind, NodeId
from postloom.domain.provenance import Provenance
from postloom.settings import Settings
from tests.fakes import (
    FakeChat,
    FakeEmbedder,
    FakeExtractor,
    FakeThreadParser,
    FixedClock,
    part3_extraction,
)

JANE = NodeId("person:jane-example")
JOHN = NodeId("person:~john-sample")
TITLES = ("Caching basics", "Agents in production", "Evaluating retrieval")
CACHING, AGENTS, RETRIEVAL = (NodeId(f"article:{t.lower().replace(' ', '-')}") for t in TITLES)


def body_of(title: str) -> str:
    words = " ".join(f"{title.split()[0].lower()}{i}" for i in range(80))
    return f"An introduction to {title}.\n\n## Details\n\n{words}"


def open_home(
    home: Path,
    clock: FixedClock | None = None,
    *,
    chat: FakeChat | None = None,
    min_similarity: float | None = None,
    **extraction: Any,
) -> Container:
    return build_container(
        Settings(home=home, min_similarity=min_similarity),
        extractor=FakeExtractor(part3_extraction(**extraction)),
        embedder=FakeEmbedder(),
        chat=chat,
        thread_parser=FakeThreadParser(),
        clock=clock or FixedClock(),
    )


def library(home: Path) -> None:
    """Three articles; comments and people on the first; one link accepted, one dismissed;
    a topic taken away by the author; notes on a person."""
    clock = FixedClock()
    for title in TITLES:
        with open_home(
            home, clock, title=title, body_markdown=body_of(title), series_name=None
        ) as c:
            c.seed_topics().execute(DEFAULT_TOPICS)
            command = IngestArticleCommand(
                body_of(title), f"New article: {title} #RAG", published_on=None
            )
            article = c.ingest_article().execute(command).article
            c.index_article().execute(article.id)
            clock.advance(hours=1)
    with open_home(home, clock) as c:
        drafts = c.preview_comments().execute(CACHING, "pasted", "Alex Author").messages
        c.save_comments().execute(CACHING, drafts)
        clock.advance(hours=1)
        c.review_link().execute(CACHING, AGENTS, Decision.ACCEPT)
        c.review_link().execute(CACHING, RETRIEVAL, Decision.REJECT)
        c.update_article().execute(AGENTS, topics=["AI Agents"], series="Shipping agents")
        c.update_person().execute(
            NodeId("person:~jane-example"),
            profile_url="linkedin.com/in/jane-example",
            notes="Met at PyCon.",
            tags=["caching"],
        )


def state(c: Container) -> dict[str, Any]:
    repo = c.repository
    posts = list(repo.list_posts())
    return {
        "topics": {t.id: t for t in repo.list_topics()},
        "articles": {a.id: a for a in repo.list_articles()},
        "posts": {p.id: p for p in posts},
        "comments": {m.id: m for p in posts for m in repo.comments_on(p.id)},
        "people": {p.id: p for p in repo.list_people()},
        "edges": sorted(repo.all_edges(), key=repr),
    }


def related(c: Container, a: NodeId, b: NodeId) -> Provenance:
    """The standing of the link between two articles (stored once, smaller id first)."""
    first, second = sorted((a, b))
    return next(
        e.provenance
        for e in c.repository.edges_from(first)
        if e.kind is EdgeKind.RELATED_TO and e.target == second
    )


def lose_index(home: Path) -> None:
    for file in home.glob("index.db*"):
        file.unlink()


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {path.name}:\n{text}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def note(home: Path, folder: str, name: str) -> Path:
    return home / "vault" / folder / f"{name}.md"
