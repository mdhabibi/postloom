import os
import stat
import sys
from pathlib import Path

import pytest

from postloom.bootstrap import DEFAULT_MIN_SIMILARITY, Settings
from postloom.config import config_path, read_config, update_config

KEY_ENVS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*KEY_ENVS, "POSTLOOM_CHAT_MODEL", "POSTLOOM_MIN_SIMILARITY"):
        monkeypatch.delenv(name, raising=False)


def test_saved_key_is_used_when_no_environment_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_env(monkeypatch)
    update_config(tmp_path, gemini_api_key="saved-key", chat_model="gemini-x")
    settings = Settings.load(tmp_path)
    assert settings.gemini_api_key == "saved-key"
    assert settings.api_key_source == "config"
    assert settings.chat_model == "gemini-x"
    assert settings.min_similarity == DEFAULT_MIN_SIMILARITY


def test_environment_wins_over_saved_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_env(monkeypatch)
    update_config(tmp_path, gemini_api_key="saved-key")
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    settings = Settings.load(tmp_path)
    assert (settings.gemini_api_key, settings.api_key_source) == ("env-key", "environment")


def test_missing_key_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_env(monkeypatch)
    settings = Settings.load(tmp_path)
    assert (settings.gemini_api_key, settings.api_key_source) == (None, "missing")


def test_update_merges_and_none_removes(tmp_path: Path) -> None:
    update_config(tmp_path, gemini_api_key="k", chat_model="m")
    update_config(tmp_path, gemini_api_key=None)
    assert read_config(tmp_path) == {"chat_model": "m"}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_config_file_is_private(tmp_path: Path) -> None:
    update_config(tmp_path, gemini_api_key="secret")
    mode = stat.S_IMODE(os.stat(config_path(tmp_path)).st_mode)
    assert mode == 0o600


def test_corrupt_config_is_reported_clearly(tmp_path: Path) -> None:
    config_path(tmp_path).write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Could not read"):
        read_config(tmp_path)
