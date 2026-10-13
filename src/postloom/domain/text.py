"""Deterministic text helpers.

Anything that can be parsed reliably with rules lives here instead of being asked of an LLM:
it's free, instant, and gives the same answer every time.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

_HASH_LENGTH = 8
# A hashtag may follow a word character because pasted LinkedIn text often loses the
# whitespace between a link and the first hashtag ("...lnkd.in/abc#RAG").
_HASHTAG = re.compile(r"(?<![#&])#([A-Za-z][\w]{1,99})")
# '#' is excluded so a glued hashtag is not swallowed into the URL as a fragment.
_URL = re.compile(r"https?://[^\s<>\"')\]#]+")
# LinkedIn short links are lnkd.in/<8 chars>; anything after that was glued on by copy-paste.
_LNKD_IN = re.compile(r"^(https?://lnkd\.in/[A-Za-z0-9_-]{8})")
_SERIES_PART = re.compile(r"\bpart\s*[-:#]?\s*(\d{1,3})\b", re.IGNORECASE)
_TRAILING_PUNCT = ".,;:!?"


def slugify(text: str, max_length: int = 80) -> str:
    """Turn arbitrary text into a lowercase, ASCII, hyphen-separated slug.

    Long slugs are shortened and suffixed with a hash of the full slug, so two long
    titles that differ only at the end ("... - Part 1" / "... - Part 3") never collide.

    >>> slugify("Measuring What Matters: Part 3!")
    'measuring-what-matters-part-3'
    """
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if len(slug) > max_length:
        digest = hashlib.sha1(slug.encode("ascii")).hexdigest()[:_HASH_LENGTH]
        keep = max(max_length - _HASH_LENGTH - 1, 1)
        slug = f"{slug[:keep].rstrip('-')}-{digest}"
    return slug or "untitled"


def extract_hashtags(text: str) -> list[str]:
    """Return hashtags in order of first appearance, without '#' and without duplicates.

    Matching is case-insensitive for de-duplication; the first spelling seen is kept.
    """
    seen: dict[str, str] = {}
    for match in _HASHTAG.finditer(text):
        tag = match.group(1)
        seen.setdefault(tag.lower(), tag)
    return list(seen.values())


def extract_urls(text: str) -> list[str]:
    """Return http(s) URLs in order of first appearance, without duplicates.

    Copy-pasted LinkedIn text often glues a URL to the following word
    (``https://lnkd.in/euyuNU9yPart``). LinkedIn short links have a fixed 8-character
    code, so those are repaired; other URLs cannot be repaired reliably and should be
    treated as hints rather than verified links.
    """
    urls: list[str] = []
    for match in _URL.finditer(text):
        url = match.group(0).rstrip(_TRAILING_PUNCT)
        short = _LNKD_IN.match(url)
        if short:
            url = short.group(1)
        if url not in urls:
            urls.append(url)
    return urls


def content_size(text: str) -> int:
    """Count letters and digits, ignoring hashtags, URLs, whitespace and Markdown syntax.

    Used to check that a model restoring an article's formatting didn't drop content.
    Counting characters rather than words is robust to copy-paste gluing words together.
    """
    without_links = _URL.sub(" ", text)
    without_tags = _HASHTAG.sub(" ", without_links)
    return sum(1 for ch in without_tags if ch.isalnum())


_MD_FENCE_LINE = re.compile(r"^\s*(```|~~~).*$", re.MULTILINE)
_MD_LINE_PREFIX = re.compile(r"^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)", re.MULTILINE)
_MD_EMPHASIS = re.compile(r"(\*\*|__|\*|`)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")


def plain_text(markdown: str) -> str:
    """Markdown reduced to readable plain text, for snippets and previews."""
    text = _MD_FENCE_LINE.sub("", markdown)
    text = _MD_LINE_PREFIX.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    return _MD_EMPHASIS.sub("", text)


def excerpt(text: str, query: str, width: int = 280) -> str:
    """A plain-text window of ``text`` around the first query word, on word boundaries."""
    flat = " ".join(plain_text(text).split())
    if len(flat) <= width:
        return flat
    lowered = flat.lower()
    positions = [
        lowered.find(word) for word in re.findall(r"\w{3,}", query.lower()) if word in lowered
    ]
    centre = min(positions) if positions else 0
    start = max(0, min(centre - width // 3, len(flat) - width))
    end = start + width
    if start > 0:
        start = flat.find(" ", start) + 1 or start
    if end < len(flat):
        end = flat.rfind(" ", start, end) if flat.rfind(" ", start, end) > start else end
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(flat) else ""
    return f"{prefix}{flat[start:end].strip()}{suffix}"


def detect_series_part(title: str) -> int | None:
    """Detect a 'Part N' marker in a title and return N, or None."""
    match = _SERIES_PART.search(title)
    return int(match.group(1)) if match else None
