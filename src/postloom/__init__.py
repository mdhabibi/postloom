"""postloom: a local-first knowledge graph of your LinkedIn writing and the people it reaches."""

import json
from importlib.metadata import PackageNotFoundError, distribution, version
from typing import cast

try:
    __version__ = version("postloom")
except PackageNotFoundError:  # running from a source checkout without installing
    __version__ = "0.0.0+unknown"


def how_to_run(args: str) -> str:
    """How to run a postloom command here, for messages: ``postloom start`` when it is
    installed (``uvx``, ``uv tool``, ``pipx``), ``uv run postloom start`` in a source
    checkout, where ``postloom`` alone isn't on the PATH."""
    return f"uv run postloom {args}" if _from_source() else f"postloom {args}"


def _from_source() -> bool:
    try:
        raw = distribution("postloom").read_text("direct_url.json")
    except PackageNotFoundError:
        return True
    if not raw:
        return False
    try:
        info: object = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(info, dict):
        return False
    dir_info: object = cast(dict[str, object], info).get("dir_info")
    return isinstance(dir_info, dict) and cast(dict[str, object], dir_info).get("editable") is True


__all__ = ["__version__", "how_to_run"]
