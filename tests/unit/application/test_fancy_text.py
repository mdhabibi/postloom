"""Posts written with fancy-text converters are found, matched and read like any other."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from postloom.adapters.storage.database import SqliteDatabase
from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.use_cases import IngestPostCommand
from tests import fancy
from tests.fakes import FakeChat, FakePostClassifier
from tests.home_support import open_home

BODY = (
    "{project} is our TimeNet Hackathon 2026 project. We fine-tuned {model} with LoRA "
    "to locate the T wave peak. {tags} #ECG"
)


def post_text(style: fancy.Style) -> str:
    title = style("Can a time-series language model tell you where the T wave peaks?")
    body = BODY.format(project=style("BeatLens"), model=style("OpenTSLM-SP"), tags=style("#XAI"))
    return f"{title}\n\n{body}"


def add(home: Path, text: str, classifier: FakePostClassifier | None = None) -> str:
    with open_home(home, post_classifier=classifier or FakePostClassifier()) as c:
        c.seed_topics().execute(DEFAULT_TOPICS, only_when_empty=True)
        result = c.ingest_post().execute(IngestPostCommand(text))
        c.index_article().execute(result.post.id)
        return result.post.id


def test_words_in_any_fancy_style_are_found_by_search(tmp_path: Path) -> None:
    styles = [fancy.bold, fancy.sans_bold, fancy.italic, fancy.monospace, fancy.small_caps]
    for number, style in enumerate(styles):
        home = tmp_path / str(number)
        post = add(home, post_text(style))
        with open_home(home) as c:
            for query in ["BeatLens", "OpenTSLM", "T wave peaks", fancy.bold("BeatLens")]:
                found = c.search().execute(query).results
                assert found and found[0].article_id == post, (style.__name__, query)


def test_the_text_is_kept_exactly_as_written(tmp_path: Path) -> None:
    text = post_text(fancy.bold)
    post = add(tmp_path, text)
    with open_home(tmp_path) as c:
        saved = c.repository.get_post(post)  # type: ignore[arg-type]
        assert saved is not None and saved.text == text
        assert saved.hashtags == ("XAI", "ECG")


def test_the_same_post_from_another_converter_is_recognised(tmp_path: Path) -> None:
    first = add(tmp_path, post_text(fancy.bold))
    with open_home(tmp_path) as c:
        again = c.ingest_post().execute(IngestPostCommand(post_text(fancy.sans_bold)))
    assert again.is_update and again.post.id == first


def test_the_model_reads_ordinary_letters(tmp_path: Path) -> None:
    from postloom.adapters.llm.prompts import post_topics_prompt

    assert "BeatLens is our TimeNet" in post_topics_prompt(post_text(fancy.bold))
    post = add(tmp_path, post_text(fancy.bold))
    chat = FakeChat(reply="It locates T wave peaks [1].")
    with open_home(tmp_path, chat=chat) as c:
        c.ask_question().execute("What does BeatLens do?", article_id=post)  # type: ignore[arg-type]
    assert "BeatLens is our TimeNet Hackathon 2026 project" in chat.last_prompt


def test_an_existing_index_is_rebuilt_for_fancy_letters(tmp_path: Path) -> None:
    post = add(tmp_path, post_text(fancy.bold))
    database = tmp_path / "index.db"
    with sqlite3.connect(database) as raw:  # as an older postloom left it
        raw.execute("DELETE FROM chunks_fts")
        raw.execute(
            "INSERT INTO chunks_fts (rowid, title, heading, text) "
            "SELECT id, title, heading, text FROM chunks"
        )
        raw.execute("PRAGMA user_version = 5")
    SqliteDatabase(database).close()  # opening upgrades it
    with open_home(tmp_path) as c:
        assert c.search().execute("BeatLens").results[0].article_id == post
