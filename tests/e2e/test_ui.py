"""The app in a real browser: every main screen and the flows that change data.

Starts postloom on a free port with a small library and fake models, and drives it with
Playwright. Needs a Chromium that matches the Playwright version, so it only runs when
asked:

    uv run playwright install chromium   # once
    RUN_BROWSER_TESTS=1 uv run pytest tests/e2e

Every test also fails on any error in the browser console, any missing file and any
server error.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from playwright.sync_api import (
    Browser,
    ConsoleMessage,
    Page,
    Response,
    expect,
    sync_playwright,
)

from postloom.bootstrap import Container, build_container
from postloom.interfaces.web.app import create_app
from postloom.settings import Settings
from tests.fakes import (
    FakeChat,
    FakeEmbedder,
    FakeExtractor,
    FakeThreadParser,
    part3_extraction,
)
from tests.home_support import library

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="set RUN_BROWSER_TESTS=1 to run the browser tests",
)

CACHING = "#/article/article%3Acaching-basics"
ANSWER = "Pick the threshold from your own data [1]. See [the guide](https://example.com/a[1]b)."
"""A citation in text, and one inside a link that must stay part of the link."""
JANE = "#/person/person%3Ajane-example"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        launched = playwright.chromium.launch()
        yield launched
        launched.close()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    library(tmp_path)
    return tmp_path


@pytest.fixture
def app_url(home: Path) -> Iterator[str]:
    def make(settings: Settings) -> Container:
        offline = replace(settings, provider=None, api_key=None, embeddings="off")
        return build_container(
            offline,
            extractor=FakeExtractor(part3_extraction()),
            embedder=FakeEmbedder(),
            chat=FakeChat(reply=ANSWER),
            thread_parser=FakeThreadParser(),
        )

    app = create_app(lambda: replace(Settings.load(home), min_similarity=0.0), make)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("postloom did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def page(browser: Browser, app_url: str) -> Iterator[Page]:
    context = browser.new_context(base_url=app_url, viewport={"width": 1360, "height": 900})
    opened = context.new_page()
    errors: list[str] = []

    def console(message: ConsoleMessage) -> None:
        # Failed requests are judged by the response listener below instead: an API
        # refusal (4xx) the page explains is expected; a missing file or a 5xx is not.
        if message.type == "error" and not message.text.startswith("Failed to load resource"):
            errors.append(message.text)

    def response(answer: Response) -> None:
        is_api = "/api/" in answer.url
        if answer.status >= 500 or (answer.status >= 400 and not is_api):
            errors.append(f"HTTP {answer.status} for {answer.url}")

    opened.on("console", console)
    opened.on("response", response)
    opened.on("pageerror", lambda error: errors.append(str(error)))
    opened.set_default_timeout(10_000)
    yield opened
    context.close()
    assert errors == [], f"errors in the browser console: {errors}"


def visit(page: Page, route: str) -> None:
    page.goto(f"/{route}")
    expect(page.locator("#main")).not_to_be_empty()


def note(home: Path, relative: str) -> Path:
    return home / "vault" / relative


def change(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


# -- every screen opens ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("route", "shows"),
    [
        ("#/", "Caching basics"),
        (CACHING, "Caching basics"),
        ("#/people", "Jane Example"),
        (JANE, "Jane Example"),
        ("#/graph", "Graph"),
        ("#/search?q=caching", "Caching basics"),
        ("#/settings", "Topics"),
    ],
)
def test_every_screen_opens_without_errors(page: Page, route: str, shows: str) -> None:
    visit(page, route)
    expect(page.locator("#main")).to_contain_text(shows)


def test_the_phone_layout_has_a_menu_and_no_sideways_scrolling(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    for route in ("#/", CACHING, JANE, "#/settings"):
        visit(page, route)
        overflow: Any = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0, f"{route} scrolls sideways by {overflow}px"
    page.click("#menu-toggle")
    expect(page.locator("#menu-toggle")).to_have_attribute("aria-expanded", "true")
    expect(page.locator("#article-list")).to_be_visible()


def test_the_theme_choice_is_remembered(page: Page) -> None:
    visit(page, "#/")
    before = page.evaluate("document.documentElement.dataset.theme || 'dark'")
    page.click("#theme-toggle")
    page.reload()
    expect(page.locator("#main")).not_to_be_empty()
    assert page.evaluate("document.documentElement.dataset.theme") != before


# -- asking ----------------------------------------------------------------------------
def test_a_question_is_answered_with_its_sources(page: Page) -> None:
    visit(page, "#/search?q=caching")
    page.fill(".chat textarea", "How do I pick the distance threshold?")
    page.click(".chat button[type=submit]")
    answer = page.locator(".message.assistant").last
    expect(answer).to_contain_text("Pick the threshold from your own data")
    expect(answer.locator(".sources")).to_contain_text("[1]")
    expect(answer.locator(".uncited")).to_have_count(0)
    expect(answer.locator("button.cite")).to_have_count(1)  # not inside the link
    expect(answer.locator("a")).to_have_attribute("href", "https://example.com/a[1]b")


# -- editing and deleting --------------------------------------------------------------
def test_an_articles_details_can_be_edited(page: Page) -> None:
    visit(page, CACHING)
    page.click(".article-actions > .button")
    page.fill("#edit_title", "Caching 101")
    page.fill("#edit_series", "Caching in practice")
    page.fill("#edit_part", "1")
    page.click(".chip:has-text('MLOps')")
    page.click(".chip:has-text('AI Agents')")
    page.click(".editor button[type=submit]")
    expect(page.locator("h1")).to_have_text("Caching 101")
    expect(page.locator(".byline")).to_contain_text("Caching in practice, part 1")
    expect(page.locator(".reader .tags")).to_contain_text("MLOps")
    expect(page.locator(".reader .tags")).not_to_contain_text("AI Agents")
    expect(page.locator("#article-list")).to_contain_text("Caching 101")
    assert "caching-basics" in page.url  # the identity didn't follow the title


def test_deleting_an_article_asks_first(page: Page, home: Path) -> None:
    visit(page, CACHING)
    page.click(".article-actions .confirm .button")
    expect(page.locator(".confirm-text")).to_contain_text("and 5 comments")
    page.click(".confirm-actions .button:has-text('Cancel')")
    expect(page.locator(".confirm-text")).to_have_count(0)

    page.click(".article-actions .confirm .button")
    page.click(".confirm-actions .button-danger")
    page.wait_for_url("**/#/")
    expect(page.locator("#article-list")).not_to_contain_text("Caching basics")
    assert not note(home, "articles/caching-basics.md").exists()


def test_topics_can_be_added_renamed_and_removed(page: Page) -> None:
    visit(page, "#/settings")
    page.fill("#new_topic", "Vector databases")
    page.click(".topic-add button[type=submit]")
    expect(page.locator("#thread-list")).to_contain_text("Vector databases")

    rag = page.locator(".topic-rows > li").filter(has=page.get_by_text("RAG", exact=True))
    rag.get_by_role("button", name="Edit").click()
    page.fill(".topic-form input[aria-label='Topic name']", "Retrieval")
    page.click(".topic-rows .topic-form button[type=submit]")
    expect(page.locator(".topic-rows")).to_contain_text("Retrieval")
    expect(page.locator("#thread-list")).not_to_contain_text("RAG")

    nlp = page.locator(".topic-rows > li").filter(has=page.get_by_text("NLP", exact=True))
    nlp.locator(".confirm .button").click()
    nlp.locator(".button-danger").click()
    expect(page.locator(".topic-rows")).not_to_contain_text("NLP")

    page.fill("#new_topic", "retrieval")
    page.click(".topic-add button[type=submit]")
    expect(page.locator(".settings-section .notice.error")).to_contain_text("already have")


def test_deleting_a_person_removes_them_everywhere(page: Page, home: Path) -> None:
    visit(page, JANE)
    page.click(".danger-zone .confirm .button")
    expect(page.locator(".danger-zone .confirm-text")).to_contain_text("2 messages")
    page.click(".danger-zone .button-danger")
    page.wait_for_url("**/#/people")
    expect(page.locator("#main")).not_to_contain_text("Jane Example")
    assert not note(home, "people/Jane Example.md").exists()


# -- the vault -------------------------------------------------------------------------
def test_a_note_edited_outside_is_announced_and_read(page: Page, home: Path) -> None:
    visit(page, "#/people")  # the app is running (edits made before it starts are read then)
    person = note(home, "people/Jane Example.md")
    change(person, "Met at PyCon.", "Met at EuroPython, edited in Obsidian.")
    visit(page, "#/")  # any navigation checks the vault again
    expect(page.locator(".banner")).to_contain_text("1 note was edited outside postloom")
    page.click(".banner .button")
    expect(page.locator(".banner")).to_have_count(0)
    visit(page, JANE)
    expect(page.locator("#person_notes")).to_have_value("Met at EuroPython, edited in Obsidian.")


def test_a_note_that_cant_be_read_is_named_until_it_is_fixed(page: Page, home: Path) -> None:
    visit(page, "#/settings")
    person = note(home, "people/Jane Example.md")
    change(person, "name: Jane Example", "name: [Jane")
    visit(page, "#/people")
    page.click(".banner .button")
    expect(page.locator(".banner.error")).to_contain_text("people/Jane Example.md")
    change(person, "name: [Jane", "name: Jane Example")
    page.click(".banner .button")
    expect(page.locator(".banner")).to_have_count(0)
