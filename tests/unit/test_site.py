"""The website in site/ is complete and makes no third-party requests, like the app."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "site"


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.loads: list[str] = []  # fetched by the browser on load
        self.links: list[str] = []  # followed only when clicked

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if tag in ("img", "script", "source") and found.get("src"):
            self.loads.append(str(found["src"]))
        if tag == "link" and found.get("href"):
            self.loads.append(str(found["href"]))
        if tag == "a" and found.get("href"):
            self.links.append(str(found["href"]))


PAGES = sorted(SITE.glob("*.html"))


def parsed(page: Path = SITE / "index.html") -> tuple[str, Links]:
    html = page.read_text(encoding="utf-8")
    links = Links()
    links.feed(html)
    return html, links


def test_the_site_has_its_pages() -> None:
    assert [p.name for p in PAGES] == ["index.html", "tour.html"]


def test_everything_a_page_loads_is_part_of_the_site() -> None:
    for page in PAGES:
        html, links = parsed(page)
        loads = links.loads + re.findall(r'url\("([^"]+)"\)', html)
        assert loads, page.name
        for path in loads:
            if path.startswith("https://postloom-app.vercel.app/"):
                continue  # its own canonical address
            assert not path.startswith(("http:", "https:", "//")), (page.name, path)
            assert (SITE / path).is_file(), (page.name, path)


def test_links_between_pages_and_sections_work() -> None:
    for page in PAGES:
        _, links = parsed(page)
        for href in links.links:
            if href.startswith(("https://", "mailto:")):
                continue
            target, _, section = href.partition("#")
            # "#x" is this page, "./" the site's home page, "tour.html" another page.
            name = page.name if target == "" else target.removeprefix("./") or "index.html"
            path = SITE / name
            assert path.is_file(), (page.name, href)
            if section:
                assert f'id="{section}"' in path.read_text(encoding="utf-8"), (page.name, href)


def test_a_shared_link_shows_a_preview() -> None:
    html, _ = parsed()
    image = "https://postloom-app.vercel.app/img/og.png"
    assert f'<meta property="og:image" content="{image}">' in html
    assert (SITE / "img" / "og.png").is_file()
