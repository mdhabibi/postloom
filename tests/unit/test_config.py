import stat
import sys
from pathlib import Path

import pytest

from postloom.config import config_path, read_config, update_config
from postloom.settings import Settings, save_settings


def test_nothing_configured_means_no_provider(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    assert (settings.provider, settings.configured) == (None, False)
    assert settings.embeddings == "local"


def test_saved_provider_key_and_models_are_used(tmp_path: Path) -> None:
    save_settings(tmp_path, provider="anthropic", api_key="sk", models={"chat": "claude-x"})
    settings = Settings.load(tmp_path)
    assert (settings.provider, settings.api_key, settings.api_key_source) == (
        "anthropic",
        "sk",
        "config",
    )
    assert settings.model("chat") == "claude-x"
    assert settings.model("reply") == "claude-sonnet-5-5"  # provider default
    assert settings.configured


def test_environment_wins_over_saved_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_settings(tmp_path, provider="gemini", api_key="saved")
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    monkeypatch.setenv("POSTLOOM_CHAT_MODEL", "gemini-env")
    settings = Settings.load(tmp_path)
    assert (settings.api_key, settings.api_key_source) == ("env-key", "environment")
    assert settings.model("chat") == "gemini-env"
    assert {"api_key", "model:chat"} <= settings.locked


def test_a_provider_is_picked_from_its_environment_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    settings = Settings.load(tmp_path)
    assert (settings.provider, settings.api_key_source) == ("openrouter", "environment")


def test_postloom_provider_and_key_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POSTLOOM_PROVIDER", "custom")
    monkeypatch.setenv("POSTLOOM_API_KEY", "k")
    monkeypatch.setenv("POSTLOOM_BASE_URL", "https://api.groq.example/v1")
    settings = Settings.load(tmp_path)
    assert (settings.provider, settings.api_key, settings.base_url) == (
        "custom",
        "k",
        "https://api.groq.example/v1",
    )
    assert not settings.configured  # custom servers need explicit models
    with pytest.raises(ValueError, match="environment variable"):
        save_settings(tmp_path, provider="gemini")


def test_ollama_needs_no_key_but_needs_models(tmp_path: Path) -> None:
    save_settings(tmp_path, provider="ollama")
    settings = Settings.load(tmp_path)
    assert (settings.api_key_source, settings.base_url) == ("not-needed", "http://localhost:11434")
    assert not settings.configured
    models = {"extraction": "qwen", "comments": "qwen", "chat": "qwen", "reply": "qwen"}
    save_settings(tmp_path, models=models)
    assert Settings.load(tmp_path).configured


def test_legacy_gemini_config_keeps_provider_embeddings(tmp_path: Path) -> None:
    update_config(tmp_path, gemini_api_key="old", embedding_model="gemini-embedding-2")
    settings = Settings.load(tmp_path)
    assert (settings.provider, settings.api_key, settings.embeddings) == (
        "gemini",
        "old",
        "provider",
    )
    assert settings.embedding_space == "gemini-embedding-2@768"
    assert settings.cutoffs.search == 0.66


def test_anthropic_always_embeds_locally(tmp_path: Path) -> None:
    save_settings(tmp_path, provider="anthropic", api_key="k", embeddings="provider")
    settings = Settings.load(tmp_path)
    assert not settings.uses_provider_embeddings
    assert settings.embedding_space == "local:BAAI/bge-small-en-v1.5"


def test_explicit_cutoffs_win_over_calibrated_ones(tmp_path: Path) -> None:
    update_config(tmp_path, min_similarity=0.5, related_similarity=0.9)
    cutoffs = Settings.load(tmp_path).cutoffs
    assert (cutoffs.search, cutoffs.related) == (0.5, 0.9)


def test_prices_and_budget_are_read(tmp_path: Path) -> None:
    update_config(tmp_path, prices={"m": [1, 2.5], "broken": "x"}, monthly_budget_usd=3)
    settings = Settings.load(tmp_path)
    assert settings.monthly_budget_usd == 3.0
    assert set(settings.prices) == {"m"}
    assert (settings.prices["m"].input, settings.prices["m"].output) == (1.0, 2.5)


def test_invalid_numbers_are_reported(tmp_path: Path) -> None:
    update_config(tmp_path, monthly_budget_usd="lots")
    with pytest.raises(ValueError, match="Expected a number"):
        Settings.load(tmp_path)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"provider": "nope"}, "Unknown provider"),
        ({"api_key": "k"}, "Choose a provider"),
        ({"embeddings": "cloud"}, "Unknown embeddings mode"),
        ({"monthly_budget_usd": -1.0}, "negative"),
        ({"ollama_context": 1000}, "at least 8192"),
    ],
)
def test_invalid_changes_are_refused(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        save_settings(tmp_path, **changes)  # type: ignore[arg-type]


def test_unknown_model_tasks_are_refused(tmp_path: Path) -> None:
    save_settings(tmp_path, provider="gemini")
    with pytest.raises(ValueError, match="Unknown model task"):
        save_settings(tmp_path, models={"poetry": "x"})


def test_clearing_a_model_falls_back_to_the_default(tmp_path: Path) -> None:
    save_settings(tmp_path, provider="gemini", models={"chat": "custom"})
    save_settings(tmp_path, models={"chat": None})
    assert Settings.load(tmp_path).model("chat") == "gemini-3.8-flash"
    assert "models" not in read_config(tmp_path)


def test_settings_never_print_the_key(tmp_path: Path) -> None:
    assert "secret-1" not in repr(Settings(home=tmp_path, provider="gemini", api_key="secret-1"))


def test_update_merges_and_none_removes(tmp_path: Path) -> None:
    update_config(tmp_path, owner_name="k", chat_model="m")
    update_config(tmp_path, owner_name=None)
    assert read_config(tmp_path) == {"chat_model": "m"}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_config_file_is_private(tmp_path: Path) -> None:
    save_settings(tmp_path, provider="gemini", api_key="secret")
    mode = stat.S_IMODE(config_path(tmp_path).stat().st_mode)
    assert mode == 0o600


def test_corrupt_config_is_reported_clearly(tmp_path: Path) -> None:
    config_path(tmp_path).write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Could not read"):
        read_config(tmp_path)
