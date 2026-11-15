from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.ports.extraction import ExtractedContent
from postloom.bootstrap import Container, Settings, build_container
from postloom.interfaces.cli.main import main
from postloom.settings import save_settings
from tests.fakes import (
    FakeBackend,
    FakeEmbedder,
    FakeExtractor,
    fixture_text,
    part3_extraction,
)


def test_init_creates_a_vault_with_the_default_topics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--home", str(tmp_path), "init"]) == 0

    notes = sorted(p.stem for p in (tmp_path / "vault" / "topics").glob("*.md"))
    assert notes == sorted(t.name for t in DEFAULT_TOPICS)
    assert "Vault ready" in capsys.readouterr().out


def test_init_persists_so_a_second_run_creates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--home", str(tmp_path), "init"])
    main(["--home", str(tmp_path), "init"])
    assert (tmp_path / "index.db").exists()
    assert "(0 topics created)" in capsys.readouterr().out.splitlines()[-2]


def test_home_can_come_after_the_command(tmp_path: Path) -> None:
    assert main(["init", "--home", str(tmp_path / "after")]) == 0
    assert (tmp_path / "after" / "vault" / "topics" / "RAG.md").exists()


def test_home_before_the_command_is_not_lost(tmp_path: Path) -> None:
    assert main(["--home", str(tmp_path / "before"), "init"]) == 0
    assert (tmp_path / "before" / "vault" / "topics" / "RAG.md").exists()


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("postloom ")


# -- ingest ---------------------------------------------------------------------
def fake_container(settings: Settings) -> Container:
    # No real key, even if the developer running the tests has one exported.
    # The fake embedder's similarities aren't calibrated like Gemini's, so no cutoff.
    return build_container(
        offline(settings, min_similarity=0.0),
        extractor=FakeExtractor(part3_extraction()),
        embedder=FakeEmbedder(),
    )


def no_key_container(settings: Settings) -> Container:
    return build_container(offline(settings))


def offline(settings: Settings, **changes: Any) -> Settings:
    """No provider and no local model downloads, whatever the test machine has."""
    return replace(settings, provider=None, api_key=None, embeddings="off", **changes)


def write_inputs(tmp_path: Path, article_text: str | None = None) -> tuple[str, str]:
    article = tmp_path / "article.txt"
    post = tmp_path / "post.txt"
    text = article_text or fixture_text("semantic_caching_part3", "article.txt")
    article.write_text(text, encoding="utf-8")
    post.write_text(fixture_text("semantic_caching_part3", "post.txt"), encoding="utf-8")
    return str(article), str(post)


def test_ingest_adds_the_article_and_reports_what_it_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = str(tmp_path / "home")
    main(["--home", home, "init"], make_container=fake_container)
    article, post = write_inputs(tmp_path)

    code = main(
        ["--home", home, "ingest", article, post, "--date", "2026-10-12"],
        make_container=fake_container,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert 'Added: "Measuring What Matters' in out
    assert "Topics:   RAG, AI Agents" in out
    assert "Series:   Semantic Caching for AI Agents, part 3" in out
    assert "https://lnkd.in/euyuNU9y" in out
    assert list((tmp_path / "home" / "vault" / "articles").glob("*.md"))


def test_ingesting_twice_reports_an_update(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = str(tmp_path / "home")
    main(["--home", home, "init"], make_container=fake_container)
    article, post = write_inputs(tmp_path)
    main(["--home", home, "ingest", article, post], make_container=fake_container)
    main(["--home", home, "ingest", article, post], make_container=fake_container)
    assert 'Updated: "Measuring What Matters' in capsys.readouterr().out


def test_ingest_without_api_key_explains_how_to_add_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = str(tmp_path / "home")
    main(["--home", home, "init"], make_container=no_key_container)
    article, post = write_inputs(tmp_path)

    code = main(["--home", home, "ingest", article, post], make_container=no_key_container)

    assert code == 1
    assert "choose a provider" in capsys.readouterr().err


def test_ingest_with_a_missing_file_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["--home", str(tmp_path), "ingest", str(tmp_path / "nope.txt"), str(tmp_path / "x")],
        make_container=fake_container,
    )
    assert code == 1
    assert "File not found" in capsys.readouterr().err


def test_settings_never_print_the_api_key(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path, provider="gemini", api_key="secret-123")
    assert "secret-123" not in repr(settings)


# -- search -----------------------------------------------------------------------
def ingested_home(tmp_path: Path) -> str:
    home = str(tmp_path / "home")
    main(["--home", home, "init"], make_container=fake_container)
    article, post = write_inputs(tmp_path)
    main(["--home", home, "ingest", article, post], make_container=fake_container)
    return home


def test_ingest_also_indexes_the_article_for_search(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ingested_home(tmp_path)
    assert "Search:   " in capsys.readouterr().out


def test_search_shows_matching_articles_and_passages(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = ingested_home(tmp_path)
    capsys.readouterr()

    code = main(["--home", home, "search", "cache", "hit", "rate"], make_container=fake_container)

    out = capsys.readouterr().out
    assert code == 0
    assert '1 article for "cache hit rate" (keyword + semantic):' in out
    assert "1. Measuring What Matters" in out
    assert "(keyword+semantic)" in out


def test_search_without_matches_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--home", str(tmp_path), "init"], make_container=fake_container)
    main(["--home", str(tmp_path), "search", "anything"], make_container=fake_container)
    assert 'No articles match "anything".' in capsys.readouterr().out


def test_reindex_reuses_existing_embeddings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = ingested_home(tmp_path)
    capsys.readouterr()
    main(["--home", home, "reindex"], make_container=fake_container)
    out = capsys.readouterr().out
    assert "Indexed 1 article, " in out
    assert "(0 embedded," in out


def test_search_explain_shows_scores(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home = ingested_home(tmp_path)
    capsys.readouterr()
    main(["--home", home, "search", "cache", "--explain"], make_container=fake_container)
    assert "scores: meaning similarity 0." in capsys.readouterr().out


def test_similarity_cutoffs_follow_the_embedding_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gemini = Settings(home=tmp_path, provider="gemini", api_key="k", embeddings="provider")
    assert (gemini.embedding_space, gemini.cutoffs.search) == ("gemini-embedding-2@768", 0.66)
    assert Settings(home=tmp_path).embedding_space == "local:BAAI/bge-small-en-v1.5"
    monkeypatch.setenv("POSTLOOM_MIN_SIMILARITY", "0.7")
    assert Settings.load(tmp_path).cutoffs.search == 0.7


# -- links ----------------------------------------------------------------------
def extracting(extraction: ExtractedContent) -> Callable[[Settings], Container]:
    def make(settings: Settings) -> Container:
        return build_container(
            offline(settings), extractor=FakeExtractor(extraction), embedder=FakeEmbedder()
        )

    return make


def test_links_explain_lists_every_compared_pair(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = ["--home", str(tmp_path)]
    for title in ("First article", "Second article"):
        body = f"{title}: " + " ".join(f"{title} word{i}" for i in range(60))
        make = extracting(part3_extraction(title=title, body_markdown=body))
        main([*home, "init"], make_container=make)
        main([*home, "ingest", *write_inputs(tmp_path, body)], make_container=make)
    capsys.readouterr()

    assert main([*home, "links", "--explain"], make_container=fake_container) == 0
    out = capsys.readouterr().out
    assert "First article  <->  Second article" in out
    assert "(cutoff 0." in out


def test_links_need_embeddings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--home", str(tmp_path), "init"], make_container=no_key_container)
    assert main(["--home", str(tmp_path), "links"], make_container=no_key_container) == 1
    assert "embeddings are off" in capsys.readouterr().out


def test_links_with_one_article_explain_why_nothing_was_compared(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = ["--home", str(tmp_path)]
    main([*home, "init"], make_container=fake_container)
    main([*home, "ingest", *write_inputs(tmp_path)], make_container=fake_container)
    capsys.readouterr()
    main([*home, "links"], make_container=fake_container)
    assert "1 article of 1 has embeddings" in capsys.readouterr().out


# -- sync and doctor --------------------------------------------------------------
def test_a_lost_index_is_rebuilt_and_announced_by_any_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = ["--home", str(tmp_path)]
    main([*home, "init"], make_container=fake_container)
    main([*home, "ingest", *write_inputs(tmp_path)], make_container=fake_container)
    for file in tmp_path.glob("index.db*"):
        file.unlink()
    capsys.readouterr()

    assert main([*home, "search", "semantic", "cache"], make_container=fake_container) == 0
    out = capsys.readouterr().out
    assert "Rebuilt the index from your vault: 1 article, 0 comments, 0 people." in out
    assert "Measuring What Matters" in out  # and the search itself works


def test_sync_reads_edited_notes_and_reports_unreadable_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = ["--home", str(tmp_path)]
    main([*home, "init"], make_container=fake_container)
    main([*home, "ingest", *write_inputs(tmp_path)], make_container=fake_container)
    capsys.readouterr()
    assert main([*home, "sync"], make_container=fake_container) == 0
    assert "Your vault and the index agree: 1 article" in capsys.readouterr().out

    (note,) = (tmp_path / "vault" / "articles").glob("*.md")
    original = note.read_text(encoding="utf-8")
    note.write_text(original.replace("summary: ", "summary: Edited. "), encoding="utf-8")
    assert main([*home, "sync"], make_container=fake_container) == 0
    assert "Read 1 edited note from your vault" in capsys.readouterr().out

    note.write_text(original.replace("title: ", "title: [broken "), encoding="utf-8")
    assert main([*home, "sync"], make_container=fake_container) == 1
    out = capsys.readouterr().out
    assert "can't be read" in out and f"articles/{note.name}" in out


def test_removed_default_topics_do_not_come_back(tmp_path: Path) -> None:
    home = ["--home", str(tmp_path)]
    main([*home, "init"], make_container=fake_container)
    with fake_container(Settings.load(tmp_path)) as container:
        rag = next(t for t in container.repository.list_topics() if t.name == "RAG")
        container.topics().delete(rag.id)
    main([*home, "init"], make_container=fake_container)
    with fake_container(Settings.load(tmp_path)) as container:
        assert "RAG" not in {t.name for t in container.repository.list_topics()}


def test_doctor_checks_every_model_with_a_real_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = FakeBackend(json_replies={"connection_test": {"ok": True}})

    models = {"extraction": "small", "comments": "small", "chat": "big", "reply": "big"}
    save_settings(tmp_path, provider="ollama", models=models)

    def make(settings: Settings) -> Container:
        return build_container(settings, backend=backend, embedder=FakeEmbedder())

    assert main(["--home", str(tmp_path), "doctor"], make_container=make) == 0
    out = capsys.readouterr().out
    assert "Everything works." in out
    assert "Extraction model: small (structured output)" in out
    assert "Reply model: big (text)" in out
    assert "every note is readable" in out
    assert backend.calls == [("json", "small"), ("text", "big")]  # each model once per kind


def test_doctor_reports_what_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--home", str(tmp_path), "doctor"], make_container=no_key_container) == 1
    out = capsys.readouterr().out
    assert "FAIL  Models:" in out and "1 of 3 checks failed" in out
    assert "off; search uses keywords only" in out
