"""Screenshots of postloom on the fictional library, for the website and the README.

    uv run python scripts/demo/screenshots.py <output folder>

Builds the library (scripts/demo/library.py) in a temporary folder, serves it with the
test fakes standing in for models, and photographs each screen at twice the pixel density.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import uvicorn
from playwright.sync_api import Page, sync_playwright
from scripts.demo.library import CHART_DESCRIPTION, build

from postloom.bootstrap import Container, build_container
from postloom.interfaces.web.app import create_app
from postloom.settings import Settings
from tests.fakes import (
    FakeChat,
    FakeEmbedder,
    FakeExtractor,
    FakeImageDescriber,
    FakeThreadParser,
    part3_extraction,
)

PORT = 8831
BASE = f"http://127.0.0.1:{PORT}/"

ANSWER = (
    "Two people asked about the cache threshold. Lena Okafor asked how you pick the "
    "similarity threshold, since that is where her team gets burned [1]; you answered that "
    "you chose it from a labelled sample of 500 question pairs, and she went on to thank "
    "you for Part 2 [2]. Samir Haddad asked whether billing questions should get a stricter "
    "threshold than how-to questions [2]. You haven't answered Samir yet."
)
DRAFT = (
    "Good question, Samir. Yes: we now use a stricter threshold for billing and account "
    "questions, where a wrong cached answer costs more, and the general one for how-to "
    "questions. It moved the false-hit rate for billing from 1 in 150 to under 1 in 400."
)

CHART = """<html><body style="margin:0;background:#fff;color:#1d2233;
font:15px system-ui,sans-serif">
<div style="padding:22px 26px;width:548px">
<div style="font-weight:600;margin-bottom:14px">p99 latency (ms), support assistant</div>
<div style="display:flex;align-items:center;gap:12px;margin:8px 0">
<span style="width:118px">No cache</span>
<div style="background:#d9645c;height:30px;width:372px"></div>
<b>1240</b></div>
<div style="display:flex;align-items:center;gap:12px;margin:8px 0">
<span style="width:118px">Semantic cache</span>
<div style="background:#4f9a6c;height:30px;width:93px"></div>
<b>310</b></div></div></body></html>"""


def serve(home: Path) -> uvicorn.Server:
    def make(settings: Settings) -> Container:
        offline = replace(settings, provider=None, api_key=None, embeddings="off")
        return build_container(
            offline,
            extractor=FakeExtractor(part3_extraction()),
            embedder=FakeEmbedder(),
            chat=FakeChat(ANSWER),
            reply_chat=FakeChat(DRAFT),
            thread_parser=FakeThreadParser(),
            image_describer=FakeImageDescriber(CHART_DESCRIPTION),
        )

    settings = lambda: replace(Settings.load(home), min_similarity=0.0)  # noqa: E731
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings, make), host="127.0.0.1", port=PORT, log_level="error")
    )
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server


def shoot(page: Page, out: Path, name: str, **clip: Any) -> None:
    page.wait_for_timeout(400)
    page.screenshot(path=str(out / f"{name}.png"), **clip)


def article(page: Page, title: str) -> None:
    page.goto(f"{BASE}#/library")
    page.get_by_role("link", name=title).first.click()
    page.wait_for_selector(".reader, .post-page, article")


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp()) / "Postloom"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        chart = browser.new_page(viewport={"width": 600, "height": 160}, device_scale_factor=2)
        chart.set_content(CHART)
        build(home, chart.screenshot())
        server = serve(home)

        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page.goto(BASE)
        page.wait_for_selector(".dashboard")
        # With a model connected there is no "connect a model" notice; the fakes stand in.
        page.evaluate("document.querySelectorAll('.dashboard .notice').forEach(n => n.remove())")
        shoot(page, out, "home")

        page.goto(f"{BASE}#/add")
        page.fill(
            "#article_text",
            "Choosing a cache threshold without guessing\n\nStart from a "
            "false-hit budget\nDecide how many wrong cached answers you can live with, say "
            "1 in 200, before looking at any similarity score...",
        )
        page.fill(
            "#post_text",
            "Part 2 of the series is out: choosing a semantic cache "
            "threshold without guessing. #LLM #MLOps",
        )
        page.locator("form").first.screenshot(path=str(out / "add.png"))

        page.goto(f"{BASE}#/library")
        page.get_by_role("link", name="Three things I learned speaking").first.click()
        review = page.locator(".mentions-section .review, [aria-label^='Found in this']").first
        review.wait_for()
        review.screenshot(path=str(out / "review.png"))

        page.goto(f"{BASE}#/graph")
        page.wait_for_selector("svg.graph")
        page.fill("input[aria-label='Focus on']", "Lena Okafor (Person)")
        page.keyboard.press("Enter")
        page.wait_for_selector(".graph-node.focus")
        page.wait_for_timeout(600)
        page.locator(".graph-stage").screenshot(path=str(out / "graph.png"))

        page.goto(f"{BASE}#/people")
        page.get_by_role("link", name="Lena Okafor").first.click()
        page.wait_for_selector(".person-page, .page")
        shoot(page, out, "person")

        article(page, "Choosing a cache threshold without guessing")
        samir = page.locator(".comment", has_text="Samir Haddad").first
        samir.get_by_role("button", name="Draft reply").click()
        page.wait_for_selector(".reply-draft textarea, .reply-draft .draft")
        page.wait_for_timeout(500)
        samir.screenshot(path=str(out / "reply.png"))

        page.goto(f"{BASE}#/search?q=what%20did%20people%20ask%20about%20the%20cache%20threshold")
        page.wait_for_selector(".chat")
        page.locator(".ask-form input, .ask-form textarea").first.fill(
            "What did people ask about the cache threshold?"
        )
        page.locator(".chat .ask-form button[type=submit]").click()
        page.wait_for_selector(".chat .message.assistant:not(.pending)")
        page.locator(".chat").screenshot(path=str(out / "chat.png"))

        page.goto(f"{BASE}#/search?q=how%20much%20faster%20is%20the%20cache")
        page.wait_for_selector(".result-media")
        page.locator(".result").first.screenshot(path=str(out / "media-search.png"))

        browser.close()
        server.should_exit = True


if __name__ == "__main__":
    main(Path(sys.argv[1]))
