"""How questions about the whole library choose their passages: fused search, a cap per
article or post, more sources for broad questions, periods, and the "not found" gate."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from postloom.application.use_cases import IngestPostCommand
from postloom.application.use_cases.ask_question import BROAD_SOURCES, NOT_FOUND, PER_ITEM
from tests.fakes import FakeChat, FakeReranker, FixedClock
from tests.home_support import CACHING, library, open_home

LOOSE = 0.0
"""A similarity cutoff everything passes, so the rule under test decides."""
TODAY = FixedClock()


def posts(home: Path, texts: list[tuple[str, date]]) -> None:
    with open_home(home) as c:
        for text, day in texts:
            post = c.ingest_post().execute(IngestPostCommand(text, published_on=day)).post
            c.index_article().execute(post.id)


def test_the_reranker_says_not_found_without_calling_the_model(tmp_path: Path) -> None:
    library(tmp_path)
    chat = FakeChat()
    reranker = FakeReranker(relevant=("nothing like this",))
    with open_home(tmp_path, chat=chat, min_similarity=LOOSE, reranker=reranker) as c:
        answer = c.ask_question().execute("caching41 threshold")
    assert (answer.text, answer.grounded) == (NOT_FOUND, False)
    assert reranker.read and chat.calls == []


def test_when_the_reranker_finds_an_answer_the_passages_go_to_the_model(tmp_path: Path) -> None:
    library(tmp_path)
    chat = FakeChat(reply="Like this [1].")
    reranker = FakeReranker(relevant=("caching41",))
    with open_home(tmp_path, chat=chat, min_similarity=LOOSE, reranker=reranker) as c:
        answer = c.ask_question().execute("caching41 threshold")
    assert answer.grounded and answer.sources[0].article_id == CACHING


def test_a_reranker_that_cannot_run_falls_back_to_the_cutoff(tmp_path: Path) -> None:
    library(tmp_path)
    chat = FakeChat(reply="Like this [1].")
    with open_home(
        tmp_path, chat=chat, min_similarity=LOOSE, reranker=FakeReranker(broken=True)
    ) as c:
        answer = c.ask_question().execute("caching41 threshold")
    assert answer.grounded


def test_one_article_gives_at_most_two_passages(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path, chat=FakeChat(), min_similarity=LOOSE) as c:
        sources = c.ask_question().sources("caching threshold section")
    per_item: dict[str | None, int] = {}
    for s in sources:
        if s.kind in ("article", "post", "comments"):
            per_item[s.article_id] = per_item.get(s.article_id, 0) + 1
    assert per_item and max(per_item.values()) <= PER_ITEM


def test_a_broad_question_gets_more_sources_one_per_item(tmp_path: Path) -> None:
    places = [
        "Lisbon", "Oslo", "Lagos", "Lima", "Quito", "Hanoi", "Dakar", "Perth", "Riga", "Sofia",
        "Accra", "Bogota", "Cairo", "Delhi", "Essen", "Fukuoka", "Graz", "Haifa", "Izmir", "Jaipur",
    ]  # fmt: skip
    posts(
        tmp_path,
        [
            (
                f"Vector search tuning in {place}: recall went up after we changed {n} things.",
                date(2026, 3, 1 + n),
            )
            for n, place in enumerate(places)
        ],
    )
    with open_home(tmp_path, chat=FakeChat(), min_similarity=LOOSE) as c:
        ask = c.ask_question()
        narrow = ask.sources("vector search tuning recall")
        broad = ask.sources("What have people said about vector search tuning?")
    passages = [s for s in broad if s.kind != "library"]
    assert len([s for s in narrow if s.kind != "library"]) == 8
    assert len(passages) == BROAD_SOURCES
    assert len({s.article_id for s in passages}) == BROAD_SOURCES


def test_a_question_about_a_period_is_answered_from_what_was_published_then(
    tmp_path: Path,
) -> None:
    posts(
        tmp_path,
        [
            ("Caching lesson one: flush on template change.", date(2026, 3, 4)),
            ("Caching lesson two: expire prices after 72 hours.", date(2026, 3, 20)),
            ("Caching lesson three: key on the plan tier.", date(2026, 5, 2)),
        ],
    )
    with open_home(tmp_path, chat=FakeChat(), min_similarity=LOOSE) as c:
        sources = c.ask_question().sources("What did I write about caching in March 2026?")
    texts = " ".join(s.text for s in sources if s.kind == "post")
    assert "lesson one" in texts and "lesson two" in texts
    assert "lesson three" not in texts
