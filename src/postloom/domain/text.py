"""Deterministic text helpers.

Anything that can be parsed reliably with rules lives here instead of being asked of an LLM:
it's free, instant, and gives the same answer every time.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from urllib.parse import urlsplit

from postloom.domain.errors import InvalidUrlError

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
    """Turn arbitrary text into a lowercase, hyphen-separated slug, for ids and file names.

    Latin text is folded to ASCII ("Núñez" -> "nunez"). Letters and digits of other
    scripts are kept, so names in Persian, Arabic, Chinese, Cyrillic or Hindi get ids of
    their own instead of all becoming "untitled". For anything Latin the result is exactly
    what earlier versions produced, because people, topics and series are identified by
    their slugs and those must not change.

    Long slugs are shortened and suffixed with a hash of the full slug, so two long
    titles that differ only at the end ("... - Part 1" / "... - Part 3") never collide.

    >>> slugify("Measuring What Matters: Part 3!")
    'measuring-what-matters-part-3'
    >>> slugify("علی رضایی")
    'علی-رضایی'
    """
    kept: list[str] = []
    in_foreign_word = False
    for char in unicodedata.normalize("NFC", text):
        folded = unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode("ascii")
        if folded:
            kept.append(folded.lower())
            in_foreign_word = False
        elif _is_foreign_letter(char) or (in_foreign_word and _is_mark(char)):
            kept.append(char.casefold())
            in_foreign_word = True
        else:
            in_foreign_word = False  # dropped without a trace, as before (ß, ø, ¡...)
    slug = _ASCII_SEPARATORS.sub("-", "".join(kept)).strip("-")
    if len(slug) > max_length:
        digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:_HASH_LENGTH]
        keep = max(max_length - _HASH_LENGTH - 1, 1)
        slug = f"{slug[:keep].rstrip('-')}-{digest}"
    if slug in _WINDOWS_DEVICE_NAMES:
        slug = f"{slug}-0"  # Windows can't create a file called con.md, nul.md...
    return slug or "untitled"


_ASCII_SEPARATORS = re.compile(r"[\x00-\x2f\x3a-\x60\x7b-\x7f]+")
"""ASCII characters other than lowercase letters and digits: where words meet."""
_WINDOWS_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(10)} | {f"lpt{i}" for i in range(10)}
)
_LATIN_RANGES = (
    (0x0000, 0x036F),
    (0x1D00, 0x1EFF),
    (0x2C60, 0x2C7F),
    (0xA720, 0xA7FF),
    (0xAB30, 0xAB6F),
)
"""Latin, IPA, spacing modifiers and combining marks, and Latin extensions: folded to
ASCII or dropped, as earlier versions did."""


def _is_foreign_letter(char: str) -> bool:
    """A letter or digit of a script other than Latin, which ASCII folding would erase."""
    code = ord(char)
    if any(low <= code <= high for low, high in _LATIN_RANGES):
        return False
    if unicodedata.category(char)[0] not in "LN":
        return False
    return not unicodedata.name(char, "").startswith(("LATIN", "MODIFIER"))


def _is_mark(char: str) -> bool:
    """A vowel sign or other mark that is part of a word (Hindi, Thai, Arabic...)."""
    return unicodedata.category(char) in ("Mn", "Mc") and ord(char) > 0x036F


def canonical_url(url: str) -> str:
    """A URL reduced to what identifies the page: no scheme, ``www.``, query or fragment.

    >>> canonical_url("https://www.linkedin.com/pulse/my-article-abc/?trackingId=x#top")
    'linkedin.com/pulse/my-article-abc'
    """
    text = url.strip()
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    host = (parts.hostname or "").lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}"


def web_url(raw: str | None) -> str | None:
    """A link as postloom stores it: ``https://`` added when missing; None when empty.

    Only web addresses are accepted. A stored link is shown as a clickable "View on
    LinkedIn", so a ``javascript:`` or ``file:`` address must never get in.

    >>> web_url("linkedin.com/pulse/x")
    'https://linkedin.com/pulse/x'
    """
    text = (raw or "").strip()
    if not text:
        return None
    if "://" not in text and not text.lower().startswith(("javascript:", "data:", "file:")):
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise InvalidUrlError(f"That isn't a web link: {raw!r}")
    return text


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


_WORD = re.compile(r"[^\W_]+")
SHINGLE_WORDS = 4


def shingles(text: str, size: int = SHINGLE_WORDS) -> frozenset[str]:
    """Every run of ``size`` consecutive words, ignoring case, punctuation and Markdown."""
    words = _WORD.findall(plain_text(text).casefold())
    if len(words) <= size:
        return frozenset({" ".join(words)}) if words else frozenset()
    return frozenset(" ".join(words[i : i + size]) for i in range(len(words) - size + 1))


def containment(first: str, second: str) -> float:
    """How much of the shorter text also appears in the other, from 0 to 1.

    Two versions of one article score high even when one gained a section or was pasted
    with LinkedIn's page chrome around it; two different articles score near 0. Word
    sequences rather than single words, so shared vocabulary alone doesn't count.
    """
    a, b = shingles(first), shingles(second)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


STOPWORDS = frozenset(
    """a about after all also am an and any anybody anyone are as ask asked asking at be
    because been before being both but by can could describe did do does doing done each
    explain find for from get give got had has have having he her here him his how i if in
    into is it its just know like many may me mention mentioned more most much my no not
    now of on one only or other our out over said say says she should show so some
    somebody someone such talk talked tell than that the their them then there these they
    think this those thought to told too under up us use used using very was we were what
    when where which while who whom why will with would you your yours""".split()  # noqa: SIM905 - a word list reads better as prose
)
"""Words too common to tell one passage from another (including the verbs questions are
phrased with), for judging keyword matches."""


_UNSPACED = re.compile(
    "[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u0e00-\u0e7f\u0e80-\u0eff"
    "\u1000-\u109f\u1780-\u17ff]+"
)
"""Runs of Chinese, Japanese, Thai, Lao, Burmese or Khmer: scripts written without spaces
between words, where a "word" found by spaces is really a whole phrase."""


def unspaced_pieces(text: str) -> list[str]:
    """Overlapping two-character pieces of the runs of unspaced scripts in ``text``: the
    usual way to match words in those languages without a dictionary."""
    pieces: list[str] = []
    for run in _UNSPACED.findall(text):
        pieces += [run] if len(run) == 1 else [run[i : i + 2] for i in range(len(run) - 1)]
    return list(dict.fromkeys(pieces))


def significant_terms(query: str) -> list[str]:
    """The words of a question that carry its meaning: no stopwords, no 1-2 letter words
    (unless the question has nothing else). Text in unspaced scripts (Chinese, Japanese,
    Thai...) contributes its two-character pieces instead."""
    spaced = _UNSPACED.sub(" ", query.casefold())
    words = list(dict.fromkeys(_WORD.findall(spaced)))
    kept = [w for w in words if w not in STOPWORDS and len(w) > 2]
    terms = kept or [w for w in words if w not in STOPWORDS] or words
    pieces = unspaced_pieces(query)
    meaningful = [p for p in pieces if not _function_piece(p)]
    return terms + (meaningful or pieces)


_FUNCTION_CHARACTERS = frozenset(
    "是的了吗呢吧啊么什怎如何哪谁在有和与或我你他她它们这那个些也都就还又很"
)
"""Chinese characters that mostly build questions and grammar ("what is", "how", "my")."""


def _function_piece(piece: str) -> bool:
    """A two-character piece that is grammar rather than subject: it contains a common
    Chinese function character, or is all hiragana (Japanese particles and endings)."""
    if any(c in _FUNCTION_CHARACTERS for c in piece):
        return True
    return all("\u3040" <= c <= "\u309f" for c in piece)


def term_coverage(terms: Sequence[str], text: str) -> float:
    """The share of ``terms`` that appear in ``text``: as whole words, or for pieces of an
    unspaced script, anywhere in it."""
    if not terms:
        return 0.0
    folded = text.casefold()
    present = set(_WORD.findall(folded))
    found = sum(1 for t in terms if (t in folded if _UNSPACED.match(t) else t in present))
    return found / len(terms)


def mentions(text: str, phrase: str) -> bool:
    """True when ``phrase`` appears in ``text`` as whole words, ignoring case."""
    wanted = " ".join(_WORD.findall(phrase.casefold()))
    if not wanted:
        return False
    return f" {wanted} " in f" {' '.join(_WORD.findall(text.casefold()))} "


def looks_english(text: str) -> bool:
    """A cheap guess, good enough to warn about an English-only search model: mostly Latin
    letters, and English's small words ("the", "and", "of"...) are common."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True
    latin = sum(1 for c in letters if c.isascii() or unicodedata.name(c, "").startswith("LATIN"))
    if latin / len(letters) < 0.6:
        return False
    words = _WORD.findall(plain_text(text).casefold())
    return not words or sum(1 for w in words if w in STOPWORDS) / len(words) >= 0.12


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
