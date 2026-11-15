"""Note files: frontmatter, wikilinks, safe file names and atomic writes."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, cast

import yaml

FOLDERS = ("articles", "posts", "topics", "people", "discussions")
"""Where postloom keeps its notes. Anything else in the vault belongs to the user."""
TYPES = frozenset({"article", "post", "topic", "person", "discussion"})
DATA_DIR = ".postloom"
"""Hidden from Obsidian: the edge journal, the format marker and the trash."""

Meta = dict[str, Any]

_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f#^\[\]]')
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)
_MAX_NAME = 120
_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


class NoteError(ValueError):
    """A note that looks like postloom's but can't be read."""


def safe_name(name: str, fallback: str) -> str:
    """A file name that works on every platform and inside an Obsidian ``[[link]]``.

    Windows refuses names that end in a dot or a space, and device names like ``CON``.
    """
    cleaned = " ".join(_UNSAFE_FILENAME.sub("-", name).split())
    cleaned = cleaned[:_MAX_NAME].strip(" .")
    if cleaned.casefold() in _WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned or fallback


def wikilink(target: str, alias: str | None = None) -> str:
    if not alias or alias == target:
        return f"[[{target}]]"
    shown = alias.replace("|", "-").replace("[", "(").replace("]", ")")
    return f"[[{target}|{shown}]]"


def link_target(value: object) -> str | None:
    """``"[[posts/x|Announcement post]]"`` -> ``"posts/x"``; None if it isn't a link."""
    if not isinstance(value, str):
        return None
    match = _WIKILINK.fullmatch(value.strip())
    return match.group(1).strip() if match else None


def render_note(meta: Meta, body: str) -> str:
    clean = {k: v for k, v in meta.items() if v not in (None, [], "")}
    front = yaml.safe_dump(clean, sort_keys=False, allow_unicode=True, width=1000)
    return f"---\n{front}---\n\n{body.rstrip()}\n"


def split_note(text: str) -> tuple[Meta, str] | None:
    """Frontmatter and body. None for a file without frontmatter (not postloom's)."""
    lines = text.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines[0].strip() != "---":
        return None
    end = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if end is None:
        raise NoteError("the properties block at the top never closes (missing `---`)")
    try:
        loaded: object = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as error:
        raise NoteError(f"the properties at the top aren't valid YAML ({_brief(error)})") from error
    if loaded is None:
        return {}, "\n".join(lines[end + 1 :])
    if not isinstance(loaded, dict):
        return None
    meta = {str(k): v for k, v in cast(dict[object, Any], loaded).items()}
    return meta, "\n".join(lines[end + 1 :])


def _brief(error: yaml.YAMLError) -> str:
    mark = getattr(error, "problem_mark", None)
    problem = getattr(error, "problem", None) or "syntax error"
    return f"{problem}, line {mark.line + 2}" if mark is not None else str(problem)


def body_after_heading(body: str) -> str:
    """The note's text without the ``# Title`` line postloom puts first."""
    text = body.strip("\n")
    first, _, rest = text.partition("\n")
    if first.startswith("# "):
        return rest.strip("\n").rstrip()
    return text.rstrip()


def atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + rename so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
