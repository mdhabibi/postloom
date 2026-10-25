"""Wiring decisions in the composition root."""

from pathlib import Path

import pytest

from postloom import bootstrap
from postloom.adapters.llm.embeddings import RemoteEmbeddings
from postloom.adapters.llm.local_embeddings import LocalEmbeddings
from postloom.bootstrap import build_container
from postloom.settings import Settings
from tests.fakes import FakeBackend


def embedder_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, installed: bool, **settings: object
) -> object:
    monkeypatch.setattr(bootstrap, "local_embeddings_installed", lambda: installed)
    config = Settings(home=tmp_path, api_key="k", **settings)  # type: ignore[arg-type]
    with build_container(config, backend=FakeBackend(provider=config.provider or "")) as c:
        return c.embedder


def test_local_embeddings_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    embedder = embedder_for(tmp_path, monkeypatch, installed=True, provider="anthropic")
    assert isinstance(embedder, LocalEmbeddings)


def test_without_local_embeddings_the_providers_are_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    embedder = embedder_for(tmp_path, monkeypatch, installed=False, provider="gemini")
    assert isinstance(embedder, RemoteEmbeddings)
    assert embedder.name == "gemini-embedding-2@768"


def test_without_local_or_provider_embeddings_search_uses_keywords(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert embedder_for(tmp_path, monkeypatch, installed=False, provider="anthropic") is None


def test_embeddings_can_be_turned_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    embedder = embedder_for(
        tmp_path, monkeypatch, installed=True, provider="gemini", embeddings="off"
    )
    assert embedder is None


def test_cutoffs_follow_the_embedder_in_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bootstrap, "local_embeddings_installed", lambda: False)
    settings = Settings(home=tmp_path, provider="gemini", api_key="k")  # configured for local
    with build_container(settings, backend=FakeBackend(provider="gemini")) as container:
        assert container.min_similarity == 0.66  # Gemini's calibration, not the local model's
