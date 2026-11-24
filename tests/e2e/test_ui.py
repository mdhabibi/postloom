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

from postloom.application.ports.extraction import FoundMention, FoundMentions
from postloom.bootstrap import Container, build_container
from postloom.interfaces.web.app import create_app
from postloom.settings import Settings
from tests.fakes import (
    FakeChat,
    FakeEmbedder,
    FakeExtractor,
    FakeImageDescriber,
    FakeMentionFinder,
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


MENTIONS = FoundMentions(
    mentions=(
        FoundMention(name="Robin Sample", category="person"),
        FoundMention(name="Example Labs", category="organisation"),
        FoundMention(name="Example Hackathon 2026", category="event"),
        FoundMention(name="Invented Org", category="organisation"),  # not in the text
    ),
    new_topics=("Time Series",),
)
POST_TEXT = (
    "Hot take\n\nWe built it at Example Hackathon 2026 with Robin Sample. "
    "Thanks to Example Labs! Code: https://github.com/example/wavelens #ECG"
)


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
            mention_finder=FakeMentionFinder(MENTIONS),
            image_describer=FakeImageDescriber(),
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
        ("#/add", "Add an article"),
        ("#/add/post", "Add a post"),
    ],
)
def test_every_screen_opens_without_errors(page: Page, route: str, shows: str) -> None:
    visit(page, route)
    expect(page.locator("#main")).to_contain_text(shows)


def test_the_phone_layout_has_a_menu_and_no_sideways_scrolling(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    for route in ("#/", CACHING, JANE, "#/settings", "#/library", "#/people", "#/graph"):
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


# -- the main daily flow: pasting a comment section --------------------------------------
def test_a_post_is_added_discussed_edited_and_deleted(page: Page, home: Path) -> None:
    visit(page, "#/")
    page.click(".main-nav a[data-route=add]")
    page.get_by_role("link", name="Post", exact=True).click()
    page.fill("#text", "Hot take\n\nCaching beats bigger models for repeated questions.\n\n#RAG")
    page.get_by_role("button", name="Add post").click()
    expect(page.locator("#add-result")).to_contain_text('Added "Hot take"')
    page.get_by_role("link", name="Open the post").click()

    expect(page.locator(".reader h1")).to_have_text("Hot take")
    expect(page.locator(".reader .eyebrow")).to_have_text("Post")
    text = page.locator(".post-text")
    expect(text).to_contain_text("Caching beats bigger models")
    expect(text).not_to_contain_text("Hot take")  # the title isn't shown twice
    expect(page.locator(".related")).to_have_count(0)
    expect(page.locator("#article-list")).to_contain_text("Post")
    assert note(home, "posts/hot-take.md").is_file()

    page.get_by_role("button", name="Add comments").click()
    page.fill("#comments-paste", "Jane Example\nHow do you choose the distance threshold?")
    page.get_by_role("button", name="Read comments").click()
    page.get_by_role("button", name="Save comments").click()
    expect(page.locator(".comment-text")).to_have_count(5)

    page.click(".article-actions > .button")
    page.click(".chip:has-text('MLOps')")
    page.click(".editor button[type=submit]")
    expect(page.locator(".reader .tags")).to_contain_text("MLOps")

    page.click(".article-actions .confirm .button")
    expect(page.locator(".confirm-text")).to_contain_text("Delete this post and 5 comments")
    page.click(".confirm-actions .button-danger")
    page.wait_for_url("**/#/")
    expect(page.locator("#article-list")).not_to_contain_text("Hot take")
    assert not note(home, "posts/hot-take.md").exists()


def test_a_pasted_comment_section_is_reviewed_and_saved_once(page: Page) -> None:
    agents = "#/article/article%3Aagents-in-production"
    visit(page, agents)
    page.get_by_role("button", name="Add comments").click()
    page.fill("#comments-paste", "Jane Example\nHow do you choose the distance threshold?\n...")
    page.get_by_role("button", name="Read comments").click()
    items = page.locator(".review-item")
    expect(items).to_have_count(5)
    page.get_by_role("button", name="Save comments").click()
    expect(page.locator(".comment-text")).to_have_count(5)
    expect(page.locator("#main")).to_contain_text("How do you choose the distance threshold")

    # Pasting the same section again recognises every message and adds nothing.
    page.get_by_role("button", name="Add more comments").click()
    page.fill("#comments-paste", "the same section again")
    page.get_by_role("button", name="Read comments").click()
    expect(page.locator(".saved-badge")).to_have_count(5)
    page.get_by_role("button", name="Save comments").click()
    expect(page.locator(".toast")).to_contain_text("Nothing new to save")
    expect(page.locator(".comment-text")).to_have_count(5)


def test_right_to_left_text_reads_right_to_left(page: Page) -> None:
    visit(page, CACHING)
    page.click(".article-actions > .button")
    page.fill("#edit_summary", "چگونه یک حافظه نهان معنایی را بسنجیم.")
    page.click(".editor button[type=submit]")
    summary = page.locator(".summary")
    expect(summary).to_contain_text("حافظه نهان")
    assert summary.evaluate("node => getComputedStyle(node).direction") == "rtl"
    assert (
        page.locator(".prose p").first.evaluate("node => getComputedStyle(node).direction") == "ltr"
    )


def test_a_local_model_is_downloaded_and_chosen_without_a_terminal(
    page: Page, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from postloom.interfaces.desktop import ollama
    from postloom.settings import read_config
    from tests.fake_ollama import fake_ollama

    monkeypatch.setattr(ollama, "memory_gb", lambda: 8.0)
    with fake_ollama([]) as url:
        visit(page, "#/settings")
        page.locator(".provider-card", has_text="Ollama").click()
        page.fill("#ollama-url", url)
        page.locator("#ollama-url").press("Tab")  # leaving the field fires "change"
        small = page.locator(".model-choices li", has_text="qwen3.5:4b")
        expect(small).to_contain_text("Fits this computer")
        small.get_by_role("button", name="Download").click()
        small.get_by_role("button", name="Use this model").click()
        expect(page.locator(".toast")).to_contain_text("Ollama (on this computer) saved")
    config = read_config(home)
    assert config["provider"] == "ollama"
    assert set(config["models"]["ollama"].values()) == {"qwen3.5:4b"}


def test_found_mentions_are_reviewed_then_shown_and_edited(page: Page, home: Path) -> None:
    visit(page, "#/add/post")
    page.fill("#text", POST_TEXT)
    page.get_by_role("button", name="Add post").click()
    expect(page.locator("#add-result")).to_contain_text("Found 5 things to review")
    page.get_by_role("link", name="Open the post").click()

    review = page.locator(".review")
    expect(review).to_contain_text("Found in this post")
    expect(review).not_to_contain_text("Invented Org")
    expect(review.locator(".review-group h4")).to_have_text(
        ["People", "Organisations", "Events", "Links", "Topics"]
    )
    event = review.locator(".review-row", has=page.locator("input[value='Example Hackathon 2026']"))
    event.get_by_role("checkbox").uncheck()  # not wanted
    lab = review.locator(".review-row", has=page.locator("input[value='Example Labs']"))
    lab.get_by_role("textbox").fill("Example Research Labs")
    review.get_by_role("checkbox", name="Add the topic Time Series").check()
    review.get_by_role("button", name="Add 4 to your graph").click()

    mentions = page.locator(".mentions")
    expect(mentions.locator(".mention-chips a")).to_have_text(
        ["Robin Sample", "Example Research Labs", "github.com/example/wavelens"]
    )
    expect(page.locator(".review")).to_have_count(0)
    expect(page.locator(".reader .tags")).to_contain_text("Time Series")
    assert note(home, "mentions/example-research-labs.md").is_file()

    mentions.get_by_role("link", name="Example Research Labs").click()
    expect(page.locator("h1")).to_have_text("Example Research Labs")
    expect(page.locator(".eyebrow")).to_have_text("Organisation")
    page.fill("#entity_name", "Example Labs")
    page.get_by_role("button", name="Save").click()
    expect(page.locator(".hint").first).to_contain_text("Also known as: Example Research Labs")

    visit(page, "#/mentions")
    expect(page.locator(".mention-group h2")).to_have_text(["Organisations (1)", "Links (1)"])
    visit(page, "#/graph")
    expect(page.locator(".node-entity")).to_have_count(2)


# -- a large library stays tidy --------------------------------------------------------
def test_the_library_page_searches_filters_and_remembers(page: Page) -> None:
    visit(page, "#/library")
    rows = page.locator(".library-page .article-row")
    expect(rows).to_have_count(3)
    page.get_by_role("searchbox", name="Search titles and summaries").fill("agents")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Agents in production")
    assert "query=agents" in page.url  # Back and reload keep the search

    page.get_by_role("searchbox").fill("")
    expect(rows).to_have_count(3)
    page.get_by_label("Kind").select_option("post")
    expect(page.locator(".library-page")).to_contain_text("Nothing matches")
    page.get_by_label("Kind").select_option("")
    page.get_by_label("Sort").select_option("title")
    expect(rows.locator("h3")).to_have_text(TITLES_BY_NAME)

    visit(page, "#/")
    expect(page.locator(".main-nav a[data-route='library']")).to_be_visible()


TITLES_BY_NAME = ["Agents in production", "Caching basics", "Evaluating retrieval"]


def test_people_can_be_searched_and_narrowed(page: Page) -> None:
    visit(page, "#/people")
    people = page.locator(".people-list .person-row")
    total = people.count()
    assert total >= 2
    page.get_by_role("searchbox", name="Search names and headlines").fill("jane")
    expect(people).to_have_count(1)
    expect(people.first).to_contain_text("Jane Example")
    page.get_by_role("searchbox").fill("")
    page.get_by_label("Show").select_option("nolink")
    expect(page.locator(".people-list .badge").first).to_have_text("no profile link")


def test_a_graph_node_opens_a_card_and_can_be_focused(page: Page) -> None:
    visit(page, "#/graph")
    expect(page.locator(".graph-note")).to_contain_text("Showing all")
    page.locator(".graph-node[data-id='article:caching-basics']").click()
    card = page.locator(".graph-card")
    expect(card).to_contain_text("Caching basics")
    expect(card.get_by_role("link", name="Open")).to_have_attribute("href", CACHING)

    card.get_by_role("button", name="Focus here").click()
    expect(page.locator(".graph-node.focus")).to_have_attribute("data-id", "article:caching-basics")
    expect(page.locator(".graph-note")).to_contain_text("Caching basics and all")
    assert "focus=article%3Acaching-basics" in page.url

    page.reload()  # the focus is part of the address
    expect(page.locator(".graph-node.focus")).to_have_count(1)
    page.get_by_role("button", name="Clear focus").click()
    expect(page.locator(".graph-node.focus")).to_have_count(0)
    expect(page.locator(".graph-card")).to_be_hidden()


def test_forms_say_what_to_paste_and_text_can_be_made_larger(page: Page) -> None:
    visit(page, "#/add")
    article = page.get_by_role("textbox", name="The article", exact=True)
    expect(article).to_have_attribute("aria-describedby", "article_text-hint")
    expect(page.locator("#article_text-hint")).to_contain_text("open the article")
    expect(page.get_by_role("textbox", name="The post that shared it")).to_be_visible()
    expect(page.locator(".details-group legend")).to_contain_text("Details")

    size = "getComputedStyle(document.documentElement).fontSize"
    assert page.evaluate(size) == "16px"
    page.get_by_role("button", name="Larger text size").click()
    assert page.evaluate(size) == "20px"
    page.reload()  # the choice is remembered
    expect(page.get_by_role("button", name="Larger text size")).to_have_attribute(
        "aria-pressed", "true"
    )
    page.get_by_role("button", name="Standard text size").click()
    assert page.evaluate(size) == "16px"


def test_about_shows_the_author_license_and_source(page: Page) -> None:
    visit(page, "#/")
    page.get_by_role("link", name="About postloom").click()
    expect(page.locator("h1")).to_have_text("postloom")
    expect(page.get_by_role("link", name="Mahdi Habibi")).to_have_attribute(
        "href", "https://github.com/mdhabibi"
    )
    expect(page.get_by_role("link", name="github.com/mdhabibi/postloom")).to_be_visible()
    page.get_by_text("Read the full license").click()
    expect(page.locator(".license-text")).to_contain_text("Functional Source License")
    expect(page.locator(".credits")).to_contain_text("Geist")


# -- images and videos --------------------------------------------------------------
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00"
    b"\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05"
    b"\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_an_image_is_added_described_captioned_and_found(page: Page, home: Path) -> None:
    visit(page, CACHING)
    section = page.locator(".media-section")
    expect(section.get_by_text("Describe new images with AI")).to_be_visible()
    section.locator("#media-files").set_input_files(
        files=[{"name": "Latency chart.png", "mimeType": "image/png", "buffer": PNG}]
    )
    card = section.locator(".media-card")
    expect(card).to_have_count(1)
    expect(card.locator("img")).to_have_attribute("src", "/media/caching-basics/latency-chart.png")
    expect(card.locator(".media-seen summary")).to_contain_text("What AI saw (fake-vision)")
    assert (home / "vault/media/caching-basics/latency-chart.png").read_bytes() == PNG

    card.get_by_role("textbox").fill("p99 latency before and after the semantic cache")
    card.get_by_role("button", name="Save").click()
    expect(page.locator(".toast")).to_contain_text("Saved")

    visit(page, "#/search?q=semantic%20cache%20latency")
    expect(page.locator(".passage .where").first).to_contain_text("Image: p99 latency")
    expect(page.locator(".result-media")).to_have_count(1)

    visit(page, CACHING)
    page.locator(".media-card").get_by_role("button", name="Remove").click()
    expect(page.locator(".media-card")).to_have_count(0)
    assert not (home / "vault/media/caching-basics/latency-chart.png").exists()


def test_a_post_can_be_added_with_its_image(page: Page, home: Path) -> None:
    visit(page, "#/add/post")
    page.fill("#text", "Our architecture, in one picture\n\n#RAG")
    page.locator("#media_files").set_input_files(
        files=[{"name": "architecture.png", "mimeType": "image/png", "buffer": PNG}]
    )
    page.get_by_role("button", name="Add post").click()
    expect(page.locator("#add-result")).to_contain_text("1 image or video added and described")
    assert list((home / "vault/media").rglob("architecture.png"))
