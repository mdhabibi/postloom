"""The picture shown when the website's link is shared (1200 x 630).

    uv run python scripts/demo/og_image.py

Drawn from HTML with the site's own fonts and the home screenshot, so it matches the page.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

SITE = Path(__file__).resolve().parents[2] / "site"
THREADS = ["#7c94ff", "#f0727a", "#f2c14e", "#5fc4d9", "#78c98a", "#b48cf0", "#e59b6a", "#ee7fb4"]

FONTS = f"{SITE.as_uri()}/fonts"
PAGE = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family: Geist; src: url("{FONTS}/Geist-Medium.woff2"); }}
@font-face {{ font-family: Serif; src: url("{FONTS}/SourceSerif4Variable-Roman.ttf.woff2");
  font-weight: 200 900; }}
@font-face {{ font-family: Serif; src: url("{FONTS}/SourceSerif4Variable-Italic.ttf.woff2");
  font-weight: 200 900; font-style: italic; }}
body {{ margin: 0; width: 1200px; height: 630px; background: #0b0e1a; color: #e9ebf5;
  font-family: Geist, sans-serif; overflow: hidden; position: relative; }}
.warp {{ position: absolute; inset: 0 auto 0 0; width: 14px; display: flex; }}
.warp i {{ flex: 1; }}
.text {{ position: absolute; left: 84px; top: 86px; width: 560px; }}
.brand {{ display: flex; align-items: center; gap: 14px; font-size: 30px; font-weight: 500; }}
.brand img {{ width: 40px; height: 40px; }}
h1 {{ font: 600 80px/1.02 Serif, serif; letter-spacing: -1.5px; margin: 56px 0 26px; }}
h1 em {{ color: #93a2ff; }}
p {{ font-size: 25px; line-height: 1.45; color: #b2b8d2; margin: 0; }}
.shot {{ position: absolute; left: 690px; top: 118px; width: 760px; border: 1px solid #262e4a;
  border-radius: 14px; overflow: hidden; box-shadow: 0 30px 80px -20px #000; }}
.shot img {{ display: block; width: 100%; }}
</style></head><body>
<div class="warp">{"".join(f'<i style="background:{c}"></i>' for c in THREADS[:4])}</div>
<div class="text">
  <div class="brand"><img src="{SITE.as_uri()}/img/icon.svg">postloom</div>
  <h1>Your LinkedIn, <em>remembered</em>.</h1>
  <p>Your articles, posts and every comment under them, in one private library on your
  computer.</p>
</div>
<div class="shot"><img src="{SITE.as_uri()}/img/home.png"></div>
</body></html>"""


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        # Loaded from a file, so the page may use the site's fonts and images.
        with tempfile.TemporaryDirectory() as folder:
            html = Path(folder) / "og.html"
            html.write_text(PAGE, encoding="utf-8")
            page.goto(html.as_uri())
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(300)
            page.screenshot(path=str(SITE / "img" / "og.png"))
        browser.close()


if __name__ == "__main__":
    main()
