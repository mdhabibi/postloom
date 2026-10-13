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


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("postloom ")
