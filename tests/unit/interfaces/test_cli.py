from pathlib import Path

import pytest

from postloom.application.defaults import DEFAULT_TOPICS
from postloom.interfaces.cli.main import main


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
