"""Split an article into retrievable chunks along its Markdown structure.

Chunks follow the author's own sections (## / ###), so a search hit points at a
meaningful part of the article. Long sections are split between paragraphs; a fenced code
block is never cut in half. Each chunk has a content hash, which lets the index reuse an
embedding when a re-ingest leaves that part of the article unchanged.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from postloom.domain.graph import NodeId

DEFAULT_MAX_CHARS = 3000
_HEADING = re.compile(r"^(#{2,3})\s+(.*\S)\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True, slots=True)
class Chunk:
    node: NodeId
    index: int
    heading: str
    """Section heading the chunk belongs to ("" for the introduction)."""
    text: str
    title: str
    """Title of the article, kept so a chunk can be embedded and shown with context."""

    @property
    def content_hash(self) -> str:
        payload = "\x1f".join((self.title, self.heading, self.text))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def chunk_markdown(
    node: NodeId, title: str, markdown: str, max_chars: int = DEFAULT_MAX_CHARS
) -> list[Chunk]:
    sections = _sections(markdown)
    chunks: list[Chunk] = []
    for heading, body in sections:
        for piece in _split_long(body, max_chars):
            chunks.append(Chunk(node, len(chunks), heading, piece, title))
    return chunks


def _sections(markdown: str) -> list[tuple[str, str]]:
    """Group lines under their nearest ## or ### heading, ignoring headings inside code."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    in_code = False
    for line in markdown.splitlines():
        if _FENCE.match(line):
            in_code = not in_code
        heading = None if in_code else _HEADING.match(line)
        if heading:
            sections.append((heading.group(2).strip(), []))
        else:
            sections[-1][1].append(line)
    result: list[tuple[str, str]] = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        if body:
            result.append((heading, body))
    return result


def _split_long(body: str, max_chars: int) -> list[str]:
    if len(body) <= max_chars:
        return [body]
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for block in _blocks(body):
        if current and size + len(block) > max_chars:
            pieces.append("\n\n".join(current))
            current, size = [], 0
        current.append(block)
        size += len(block) + 2
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def _blocks(body: str) -> list[str]:
    """Paragraphs separated by blank lines, keeping each fenced code block whole."""
    blocks: list[str] = []
    current: list[str] = []
    in_code = False
    for line in body.splitlines():
        if _FENCE.match(line):
            in_code = not in_code
        if not line.strip() and not in_code:
            if current:
                blocks.append("\n".join(current))
                current = []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks
