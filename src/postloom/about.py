"""Who made postloom, under which license, and what it is built on.

Read from the installed package's metadata (pyproject.toml), so the app, the command line
and PyPI always say the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from postloom import __version__

REPOSITORY = "https://github.com/mdhabibi/postloom"
WEBSITE = "https://postloom-app.vercel.app/"
LICENSE_SUMMARY = (
    "postloom is fair source. You can read, run, change and share the code for anything "
    "except offering a competing commercial product or service; using it for your own "
    "work, including your business, is allowed. Each release becomes Apache-2.0 two years "
    "after it is published. The postloom name and logo aren't covered by the license."
)


@dataclass(frozen=True, slots=True)
class Credit:
    name: str
    what: str
    license: str
    url: str


CREDITS: tuple[Credit, ...] = (
    Credit(
        "Geist",
        "interface font, by Vercel",
        "SIL Open Font License 1.1",
        "https://github.com/vercel/geist-font",
    ),
    Credit(
        "Source Serif 4",
        "reading font, by Adobe",
        "SIL Open Font License 1.1",
        "https://github.com/adobe-fonts/source-serif",
    ),
    Credit(
        "bge-small-en-v1.5",
        "search by meaning in English, by BAAI",
        "MIT",
        "https://huggingface.co/BAAI/bge-small-en-v1.5",
    ),
    Credit(
        "paraphrase-multilingual-MiniLM-L12-v2",
        "search by meaning in 50+ languages",
        "Apache-2.0",
        "https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ),
    Credit(
        "ms-marco-MiniLM-L-6-v2",
        "decides whether your library holds an answer",
        "Apache-2.0",
        "https://huggingface.co/cross-encoder/ms-marco-MiniLM-L-6-v2",
    ),
    Credit(
        "FastEmbed",
        "runs those models on your computer, by Qdrant",
        "Apache-2.0",
        "https://github.com/qdrant/fastembed",
    ),
    Credit(
        "Starlette and Uvicorn", "the local web server", "BSD-3-Clause", "https://www.starlette.io"
    ),
    Credit("Pydantic", "checks what models and forms send", "MIT", "https://docs.pydantic.dev"),
    Credit("PyYAML", "reads and writes note properties", "MIT", "https://pyyaml.org"),
    Credit("SQLite", "the search index", "Public domain", "https://sqlite.org"),
)


@dataclass(frozen=True, slots=True)
class About:
    name: str
    version: str
    description: str
    author: str
    license: str
    license_summary: str
    license_text: str
    source: str
    """The code on GitHub."""
    website: str
    issues: str
    changelog: str
    credits: tuple[Credit, ...]


def about() -> About:
    try:
        dist = metadata.distribution("postloom")
        meta = dist.metadata
        urls = dict(u.split(", ", 1) for u in meta.get_all("Project-URL") or [])
        text = _license_text(dist)
        return About(
            name="postloom",
            version=__version__,
            description=meta["Summary"] or "",
            author=meta["Author"] or "Dr. Mahdi Habibi",
            license=meta["License-Expression"] or "FSL-1.1-ALv2",
            license_summary=LICENSE_SUMMARY,
            license_text=text,
            source=urls.get("Source", REPOSITORY),
            website=urls.get("Homepage", WEBSITE),
            issues=urls.get("Issues", f"{REPOSITORY}/issues"),
            changelog=urls.get("Changelog", f"{REPOSITORY}/blob/main/CHANGELOG.md"),
            credits=CREDITS,
        )
    except metadata.PackageNotFoundError:  # running from a source tree without installing
        return About(
            "postloom",
            __version__,
            "",
            "Dr. Mahdi Habibi",
            "FSL-1.1-ALv2",
            LICENSE_SUMMARY,
            _source_license(),
            REPOSITORY,
            WEBSITE,
            f"{REPOSITORY}/issues",
            f"{REPOSITORY}/blob/main/CHANGELOG.md",
            CREDITS,
        )


def _license_text(dist: metadata.Distribution) -> str:
    for name in ("licenses/LICENSE.md", "LICENSE.md"):
        text = dist.read_text(name)
        if text:
            return text
    return _source_license()


def _source_license() -> str:
    path = Path(__file__).resolve().parents[2] / "LICENSE.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""
