from dataclasses import replace
from pathlib import Path

import pytest

from postloom.application.defaults import DEFAULT_TOPICS
from postloom.bootstrap import Container, Settings, build_container
from postloom.interfaces.cli.main import main
from tests.fakes import FakeExtractor, fixture_text, part3_extraction


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
    return build_container(settings, extractor=FakeExtractor(part3_extraction()))


def no_key_container(settings: Settings) -> Container:
    return build_container(replace(settings, gemini_api_key=None))


def write_inputs(tmp_path: Path) -> tuple[str, str]:
    article = tmp_path / "article.txt"
    post = tmp_path / "post.txt"
    article.write_text(fixture_text("semantic_caching_part3", "article.txt"), encoding="utf-8")
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
    assert "GEMINI_API_KEY" in capsys.readouterr().err


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
    settings = Settings(home=tmp_path, gemini_api_key="secret-123")
    assert "secret-123" not in repr(settings)
