"""Messages name the command the way it works where postloom is running."""

import json
from importlib.metadata import PackageNotFoundError

import pytest

import postloom


class Dist:
    def __init__(self, direct_url: object | None) -> None:
        self._text = None if direct_url is None else json.dumps(direct_url)

    def read_text(self, name: str) -> str | None:
        return self._text


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        (None, "postloom start"),  # from PyPI: uvx, uv tool, pipx
        ({"url": "file:///x.whl", "archive_info": {}}, "postloom start"),  # a wheel file
        ({"url": "file:///src", "dir_info": {"editable": True}}, "uv run postloom start"),
    ],
)
def test_the_command_matches_how_postloom_was_installed(
    monkeypatch: pytest.MonkeyPatch, installed: object | None, expected: str
) -> None:
    def found(name: str) -> Dist:
        return Dist(installed)

    monkeypatch.setattr(postloom, "distribution", found)
    assert postloom.how_to_run("start") == expected


def test_a_source_checkout_that_was_never_installed_uses_uv_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> object:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(postloom, "distribution", missing)
    assert postloom.how_to_run("sync") == "uv run postloom sync"
