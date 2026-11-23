"""Shortcuts and starting postloom without a terminal."""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

import pytest

from postloom.interfaces.desktop.shortcuts import LOG_FILE, Shortcuts, last_lines, log_to_file

PYTHON = Path("/opt/tools/post loom/bin/python")
HOME = Path("/data/My Postloom's $folder")


OTHER_SYSTEMS = pytest.mark.skipif(
    sys.platform == "win32", reason="macOS and Linux paths and file modes"
)


@OTHER_SYSTEMS
def test_the_mac_app_runs_postloom_open_for_the_data_folder(tmp_path: Path) -> None:
    shortcuts = Shortcuts("Darwin", tmp_path, PYTHON)
    [app] = shortcuts.create(HOME)
    assert app == tmp_path / "Applications" / "Postloom.app"
    with (app / "Contents" / "Info.plist").open("rb") as file:
        info = plistlib.load(file)
    assert info["CFBundleExecutable"] == "Postloom" and info["CFBundleIconFile"] == "postloom.icns"
    script = app / "Contents" / "MacOS" / "Postloom"
    assert script.stat().st_mode & 0o111
    assert script.read_text() == (
        "#!/bin/sh\nexec '/opt/tools/post loom/bin/python' '-m' 'postloom' '--home' "
        "'/data/My Postloom'\\''s $folder' 'open'\n"
    )
    assert (app / "Contents" / "Resources" / "postloom.icns").stat().st_size > 10_000
    assert shortcuts.create(HOME) == [app]  # running the installer again refreshes it
    assert shortcuts.remove() == [app] and not app.exists()
    assert shortcuts.remove() == []


@OTHER_SYSTEMS
def test_the_linux_menu_entry_quotes_its_command(tmp_path: Path) -> None:
    shortcuts = Shortcuts("Linux", tmp_path, PYTHON)
    [entry] = shortcuts.create(Path("/data/100% $mine"))
    text = entry.read_text()
    assert 'Exec="/opt/tools/post loom/bin/python" "-m" "postloom" "--home" ' in text
    assert '"/data/100%% \\$mine" "open"' in text
    icon = tmp_path / ".local/share/icons/hicolor/512x512/apps/postloom.png"
    assert f"Icon={icon}" in text and "Terminal=false" in text and icon.is_file()
    assert set(shortcuts.remove()) == {entry, icon}


@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows PowerShell")
def test_windows_shortcuts_go_to_the_start_menu_and_desktop() -> None:  # pragma: no cover
    shortcuts = Shortcuts.here()
    links = shortcuts.create(Path.home() / "Postloom-test")
    try:
        assert len(links) == 2 and all(link.name == "Postloom.lnk" for link in links)
        assert all(link.is_file() for link in links)
    finally:
        assert set(shortcuts.remove()) == set(links)


def test_background_output_goes_to_a_log_that_starts_again_when_large(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("postloom.interfaces.desktop.shortcuts.LOG_LIMIT", 10)
    (tmp_path / LOG_FILE).write_text("old line that is long\n", encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    log = log_to_file(tmp_path)
    print("started")
    sys.stdout.flush()
    assert last_lines(log) == "started"
    assert (tmp_path / (LOG_FILE + ".1")).read_text() == "old line that is long\n"
    sys.stdout.close()


def test_the_suggested_model_fits_the_memory() -> None:
    from postloom.interfaces.desktop.ollama import memory_gb, recommended

    assert recommended(None) == "qwen3.5:4b"
    assert recommended(8) == "qwen3.5:4b"
    assert recommended(16) == "qwen3.5:9b"
    assert recommended(64) == "qwen3.5:27b"
    found = memory_gb()
    assert found is None or found > 0.5


def test_on_a_mac_the_browser_is_opened_with_open(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from postloom.interfaces.desktop import shortcuts

    ran: list[list[str]] = []

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        ran.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", run)
    assert shortcuts.open_in_browser("http://127.0.0.1:8767/")
    assert ran == [["open", "http://127.0.0.1:8767/"]]
