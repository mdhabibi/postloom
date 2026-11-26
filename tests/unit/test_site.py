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


def parsed() -> tuple[str, Links]:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    links = Links()
    links.feed(html)
    return html, links


def test_everything_the_page_loads_is_part_of_the_site() -> None:
    html, links = parsed()
    loads = links.loads + re.findall(r'url\("([^"]+)"\)', html)
    assert loads
    canonical = "https://postloom-app.vercel.app/"
    for path in loads:
        if path == canonical:
            continue
        assert not path.startswith(("http:", "https:", "//")), path
        assert (SITE / path).is_file(), path


def test_in_page_links_point_at_sections_that_exist() -> None:
    html, links = parsed()
    for href in links.links:
        if href.startswith("#"):
            assert f'id="{href[1:]}"' in html, href
        elif not href.startswith("https://"):
            assert (SITE / href).is_file(), href


def test_a_shared_link_shows_a_preview() -> None:
    html, _ = parsed()
    image = "https://postloom-app.vercel.app/img/og.png"
    assert f'<meta property="og:image" content="{image}">' in html
    assert (SITE / "img" / "og.png").is_file()
