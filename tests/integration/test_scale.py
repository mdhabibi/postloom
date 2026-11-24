"""A large library stays quick: every library screen is answered within a generous limit.

The library is fictional and built straight through the repository: articles, posts,
topics, series, people, comments and mentions in the proportions a busy creator reaches
after a few years. The limits are far above what a laptop needs (tens of milliseconds),
so only a return to per-item database work, which took whole seconds, fails them.
"""

from __future__ import annotations

import random
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from postloom.adapters.storage.cached import CachedRepository
from postloom.application.ports.repository import GraphRepository
from postloom.bootstrap import Container, Settings, build_container
from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.discussion import Comment
from postloom.domain.entities import Category, Entity
from postloom.domain.graph import Edge, EdgeKind, NodeId
from postloom.domain.people import Person
from postloom.domain.provenance import Grade, Origin, Provenance
from postloom.interfaces.web.app import create_app
from tests.asgi import AsgiClient
from tests.fakes import FixedClock

ARTICLES, POSTS, PEOPLE, COMMENTS, TOPICS, ENTITIES, MENTIONS = 150, 80, 400, 1500, 30, 300, 900
LIMIT_SECONDS = 1.5
WORDS = [
    "agent",
    "cache",
    "retrieval",
    "vector",
    "model",
    "training",
    "latency",
    "evaluation",
    "pipeline",
    "graph",
]


def build(container: Container) -> None:
    rng = random.Random(7)
    repo = container.repository
    now = container.clock.now()
    asserted = Provenance(Origin.TAXONOMY, Grade.ASSERTED, "llm:fake", now)
    fact = Provenance(Origin.STRUCTURAL, Grade.VERIFIED, "parser", now)
    confirmed = Provenance(Origin.MANUAL, Grade.VERIFIED, "user", now, "Thanks to them.")
    topics = [Topic(f"Topic {i} {rng.choice(WORDS).title()}") for i in range(TOPICS)]
    for topic in topics:
        repo.save_topic(topic)
    series = Series("A long series")
    repo.save_series(series)
    items: list[tuple[NodeId, NodeId]] = []  # (item, the post its comments are on)
    for i in range(ARTICLES):
        article = Article(
            title=f"Article {i}: {' '.join(rng.choices(WORDS, k=4))}",
            body_markdown=" ".join(rng.choices(WORDS, k=200)),
            summary=" ".join(rng.choices(WORDS, k=15)),
            published_on=date(2024, 1, 1) + timedelta(days=i),
            key=f"article-{i}",
            series=series if i % 10 == 0 else None,
            series_part=i // 10 + 1 if i % 10 == 0 else None,
        )
        repo.save_article(article)
        post = Post(key=f"article-{i}-post", text=f"New article {i}")
        repo.save_post(post)
        repo.save_edge(Edge(post.id, article.id, EdgeKind.ANNOUNCES, fact))
        if article.series:
            repo.save_edge(Edge(article.id, series.id, EdgeKind.PART_OF, asserted))
        items.append((article.id, post.id))
    for i in range(POSTS):
        post = Post(key=f"post-{i}", text=f"Stand-alone post {i}\n\n{' '.join(WORDS)}")
        repo.save_post(post)
        items.append((post.id, post.id))
    for item, _ in items:
        for topic in rng.sample(topics, 2):
            repo.save_edge(Edge(item, topic.id, EdgeKind.BELONGS_TO, asserted))
    people = [Person(f"Sample Person {i}") for i in range(PEOPLE)]
    for person in people:
        repo.save_person(person)
    for i in range(COMMENTS):
        _, post = rng.choice(items)
        who = rng.choice(people)
        comment = Comment(post, who.id, who.name, f"{' '.join(rng.choices(WORDS, k=12))} {i}", i)
        repo.save_comment(comment)
        repo.save_edge(Edge(who.id, comment.id, EdgeKind.AUTHORED, fact))
        repo.save_edge(Edge(comment.id, post, EdgeKind.COMMENTED_ON, fact))
    entities = [
        Entity(f"entity-{i}", f"Entity {i}", rng.choice(list(Category))) for i in range(ENTITIES)
    ]
    for entity in entities:
        repo.save_entity(entity)
    for _ in range(MENTIONS):
        item, _ = rng.choice(items)
        target = rng.choice(entities).id if rng.random() < 0.8 else rng.choice(people).id
        repo.save_edge(Edge(item, target, EdgeKind.MENTIONS, confirmed))


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[AsgiClient]:
    home = tmp_path_factory.mktemp("large")

    def make(settings: Settings) -> Container:
        offline = replace(settings, provider=None, api_key=None, embeddings="off")
        return build_container(offline, clock=FixedClock())

    with make(Settings.load(home)) as container:
        build(container)
    yield AsgiClient(create_app(lambda: Settings.load(home), make))


def timed(client: AsgiClient, path: str) -> tuple[float, Any]:
    start = time.perf_counter()
    response = client.get(path)
    assert response.status == 200, response.text
    return time.perf_counter() - start, response.json


@pytest.mark.parametrize(
    "path",
    ["/api/articles", "/api/overview", "/api/people", "/api/entities", "/api/graph"],
)
def test_every_library_screen_is_quick(client: AsgiClient, path: str) -> None:
    timed(client, path)  # the first screen loads the snapshot the others reuse
    seconds, _ = timed(client, path)
    assert seconds < LIMIT_SECONDS, f"{path} took {seconds:.2f}s"


def test_a_busy_person_and_article_are_quick(client: AsgiClient) -> None:
    _, listing = timed(client, "/api/people")
    busiest = listing["people"][0]["id"]
    seconds, person = timed(client, f"/api/person?id={busiest}")
    assert person["messages"] > 0
    assert seconds < LIMIT_SECONDS
    seconds, _ = timed(client, "/api/article?id=article:article-0")
    assert seconds < LIMIT_SECONDS


def test_the_answers_cover_the_whole_library(client: AsgiClient) -> None:
    _, articles = timed(client, "/api/articles")
    _, people = timed(client, "/api/people")
    _, graph = timed(client, "/api/graph")
    assert len(articles["articles"]) == ARTICLES + POSTS
    assert len(people["people"]) == PEOPLE
    dated = [n for n in graph["nodes"] if n["kind"] == "article"]
    assert len(dated) == ARTICLES and all(n["date"] for n in dated)


def test_a_change_is_seen_at_once(client: AsgiClient) -> None:
    _, before = timed(client, "/api/status")
    added = client.post("/api/topics", json_body={"name": "Brand new topic"})
    assert added.status == 200, added.text
    _, after = timed(client, "/api/status")
    assert "Brand new topic" in after["topics"]
    assert after["library_version"] != before["library_version"]


class Counting:
    """Counts the questions a screen asks the database."""

    def __init__(self, inner: GraphRepository) -> None:
        self.inner = inner
        self.calls = 0

    def __getattr__(self, name: str) -> Any:
        method = getattr(self.inner, name)

        def counted(*args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            return method(*args, **kwargs)

        return counted


def test_a_screen_asks_the_database_a_bounded_number_of_questions(tmp_path: Path) -> None:
    """Not one question per article, person or comment: a few bulk ones (and the comments
    of each post, one indexed query each)."""
    settings = replace(Settings.load(tmp_path), provider=None, api_key=None, embeddings="off")
    with build_container(settings, clock=FixedClock()) as container:
        build(container)
        counting = Counting(container.repository)
        cached = CachedRepository(cast(GraphRepository, counting))
        screens = replace(container, repository=cached)
        bound = ARTICLES + POSTS + 25
        for name, show in [
            ("library", lambda: screens.browse().list_articles()),
            ("home", lambda: screens.overview().execute()),
            ("people", lambda: screens.people().list_people()),
            ("mentions", lambda: screens.entities().summaries()),
            ("graph", lambda: screens.graph().execute()),
        ]:
            cached._drop()  # a fresh snapshot for each screen  # pyright: ignore[reportPrivateUsage]
            counting.calls = 0
            with cached.reading():
                show()
            assert counting.calls <= bound, f"{name} asked {counting.calls} questions"
